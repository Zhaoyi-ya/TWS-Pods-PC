"""
vivo TWS (Air3 Pro / 家族) GAIA 帧编解码 —— HyperEars Python 移植（仅 vivo）

源：dev.hyperears.protocol.vivo.VivoTwsProtocol.kt
许可：GNU GPL-3.0-only（与上游一致）

帧格式（Compact GAIA，与 Kotlin 源码逐字节对齐）::

    FF [version] [flags] [payloadLen] [vendor_hi] [vendor_lo] [cmd_hi] [cmd_lo] [payload...] [(checksum)]

- ``flags`` 默认 0；``FLAG_CHECKSUM=0x01`` 时末尾附加 1 字节异或校验；
  ``FLAG_LENGTH_EXTENSION=0x02`` 时 ``payloadLen`` 扩为 2 字节、头部长度 5。
- vendor / command 均为**大端** 16 位。
- Kotlin ``frame()`` 只产出 ``flags=0`` 的紧凑帧（payload <= 254），解码器则完整支持
  校验与长度扩展，本移植保持一致。
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import IntEnum
from typing import List, Optional

PREAMBLE = 0xFF
FLAG_CHECKSUM = 0x01
FLAG_LENGTH_EXTENSION = 0x02
COMMAND_BYTES = 4
MAX_FRAME_BYTES = 65_544


class NoiseMode(IntEnum):
    """统一降噪状态域（与 Kotlin NoiseMode 对齐）。"""

    ANC = 0
    OFF = 1
    TRANSPARENCY = 2


# 命令 / 厂商常量
VIVO_VENDOR = 0x001B
GAIA_VENDOR = 0x000A

SET_NOISE_MODE = 0x0130
QUERY_NOISE_MODE = 0x0230
ACK_NOISE_MODE = 0x8130
REPORT_NOISE_MODE = 0x8230
QUERY_BATTERY = 0x0207
REPORT_BATTERY = 0x8207
HANDSHAKE = 0x0300
HANDSHAKE_RESPONSE = 0x8300

# vivo TWS 私有 RFCOMM 通道入口（与 Kotlin VivoEarbudAdapter.VIVO_GAIA_UUID 一致）
VIVO_GAIA_UUID = "00000837-d102-11e1-9b23-00025b00a5a5"


class Profile:
    """字节级 wire profile。只描述帧层面的差异，不含型号名/能力/传输策略。

    对应 Kotlin ``VivoTwsProtocol.Profile``。
    """

    def __init__(
        self,
        label: str,
        note: str,
        gaia_version: int,
        noise_query_payload: bytes,
        noise_set_suffix: bytes,
    ) -> None:
        self.label = label
        self.note = note
        self.gaia_version = gaia_version
        self.noise_query_payload = bytes(noise_query_payload)
        self.noise_set_suffix = bytes(noise_set_suffix)


# 实机抓包确认：Air3 Pro 用 GAIA v3，设置载荷 mode 04 00
AIR3_PRO_CAPTURED = Profile(
    label="Air3 Pro 抓包 v3",
    note="当前项目实机确认：设置载荷 mode 04 00",
    gaia_version=3,
    noise_query_payload=b"",
    noise_set_suffix=bytes([4, 0]),
)
# Star-ZER0 公共画像：家族默认 v4 兼容参数
FAMILY_DEFAULT_V4 = Profile(
    label="vivo 家族默认 v4",
    note="Star-ZER0 公共画像：具体型号未注明，作为家族默认兼容参数",
    gaia_version=4,
    noise_query_payload=bytes([0]),
    noise_set_suffix=bytes([3, 1]),
)
# ScrewVivoTWS：TWS 3e 参考 v3
TWS_3E_V3 = Profile(
    label="TWS 3e 参考 v3",
    note="ScrewVivoTWS：设置载荷 mode 03",
    gaia_version=3,
    noise_query_payload=b"",
    noise_set_suffix=bytes([3]),
)


@dataclass
class Frame:
    version: int
    flags: int
    vendor: int
    command: int
    payload: bytes
    raw: bytes


@dataclass
class NoiseState:
    mode: NoiseMode
    noise_effect: Optional[int]
    transparency_effect: Optional[int]
    acknowledged: bool
    version: int


@dataclass
class BatteryState:
    left_percent: Optional[int]
    right_percent: Optional[int]
    case_percent: Optional[int]
    left_charging: bool
    right_charging: bool
    case_charging: bool
    version: int


@dataclass
class HandshakeState:
    accepted: bool
    payload: bytes
    version: int


def _u8(value: int) -> int:
    return value & 0xFF


def _xor(bytes_: bytes, count: int) -> int:
    """Kotlin checksum：对 [0, count) 字节做异或。"""
    value = 0
    for i in range(count):
        value ^= bytes_[i] & 0xFF
    return value & 0xFF


def frame(
    version: int,
    vendor: int,
    command: int,
    payload: bytes = b"",
    flags: int = 0,
) -> bytes:
    """构造一帧。与 Kotlin ``VivoTwsProtocol.frame`` 对齐。"""
    if not (0 <= version <= 255):
        raise ValueError("version out of range")
    if not (0 <= vendor <= 0xFFFF):
        raise ValueError("vendor out of range")
    if not (0 <= command <= 0xFFFF):
        raise ValueError("command out of range")
    if len(payload) > 254:
        raise ValueError("Compact GAIA payload is limited to 254 bytes")

    extended = bool(flags & FLAG_LENGTH_EXTENSION)
    header_size = 5 if extended else 4
    out = bytearray(header_size + COMMAND_BYTES + len(payload))
    out[0] = PREAMBLE
    out[1] = _u8(version)
    out[2] = _u8(flags)
    if extended:
        out[3] = _u8((len(payload) >> 8) & 0xFF)
        out[4] = _u8(len(payload) & 0xFF)
    else:
        out[3] = _u8(len(payload))
    voff = header_size  # vendor 起始
    out[voff] = _u8((vendor >> 8) & 0xFF)
    out[voff + 1] = _u8(vendor & 0xFF)
    out[voff + 2] = _u8((command >> 8) & 0xFF)
    out[voff + 3] = _u8(command & 0xFF)
    out[voff + COMMAND_BYTES:] = payload
    if flags & FLAG_CHECKSUM:
        out.append(_u8(_xor(out, len(out))))
    return bytes(out)


class Decoder:
    """流式解码器：支持去前导噪声、拆包、粘包、可选异或校验。

    对应 Kotlin ``VivoTwsProtocol.Decoder``。
    """

    def __init__(self, initial_capacity: int = 256) -> None:
        self._bytes = bytearray(max(16, initial_capacity))
        self._size = 0

    def offer(self, chunk: bytes) -> List[Frame]:
        self._append(chunk)
        frames: List[Frame] = []
        while True:
            self._discard_noise()
            if self._size < 4:
                return frames

            flags = self._peek(2)
            extended = bool(flags & FLAG_LENGTH_EXTENSION)
            header_size = 5 if extended else 4
            if self._size < header_size:
                return frames

            payload_length = (
                (self._peek(3) << 8) | self._peek(4) if extended else self._peek(3)
            )
            checksum_bytes = 1 if (flags & FLAG_CHECKSUM) else 0
            total_length = header_size + COMMAND_BYTES + payload_length + checksum_bytes
            if total_length > MAX_FRAME_BYTES:
                self._discard(1)
                continue
            if self._size < total_length:
                return frames

            raw = self._take(total_length)
            if checksum_bytes == 1 and _xor(raw, len(raw) - 1) != raw[-1]:
                continue

            content_offset = header_size
            payload_offset = content_offset + COMMAND_BYTES
            frames.append(
                Frame(
                    version=raw[1],
                    flags=raw[2],
                    vendor=(raw[content_offset] << 8) | raw[content_offset + 1],
                    command=(raw[content_offset + 2] << 8) | raw[content_offset + 3],
                    payload=bytes(raw[payload_offset : payload_offset + payload_length]),
                    raw=bytes(raw),
                )
            )

    def reset(self) -> None:
        self._size = 0

    def _append(self, chunk: bytes) -> None:
        self._ensure_capacity(self._size + len(chunk))
        self._bytes[self._size : self._size + len(chunk)] = chunk
        self._size += len(chunk)

    def _discard_noise(self) -> None:
        count = 0
        while count < self._size and self._bytes[count] != PREAMBLE:
            count += 1
        if count > 0:
            self._discard(count)

    def _peek(self, index: int) -> int:
        return self._bytes[index] & 0xFF

    def _take(self, count: int) -> bytearray:
        chunk = self._bytes[:count]
        self._discard(count)
        return chunk

    def _discard(self, count: int) -> None:
        if count >= self._size:
            self._size = 0
            return
        self._bytes[: self._size - count] = self._bytes[count : self._size]
        self._size -= count

    def _ensure_capacity(self, required: int) -> None:
        if required <= len(self._bytes):
            return
        capacity = len(self._bytes)
        while capacity < required:
            capacity *= 2
        self._bytes = bytearray(self._bytes) + bytearray(capacity - len(self._bytes))


# ---- 编码器便捷函数（对应 Kotlin 顶层函数）----


def handshake() -> bytes:
    return frame(version=4, vendor=GAIA_VENDOR, command=HANDSHAKE)


def query_noise_mode(profile: Profile) -> bytes:
    return frame(
        version=profile.gaia_version,
        vendor=VIVO_VENDOR,
        command=QUERY_NOISE_MODE,
        payload=profile.noise_query_payload,
    )


def set_noise_mode(mode: NoiseMode, profile: Profile) -> bytes:
    return frame(
        version=profile.gaia_version,
        vendor=VIVO_VENDOR,
        command=SET_NOISE_MODE,
        payload=bytes([mode]) + profile.noise_set_suffix,
    )


def query_battery() -> bytes:
    return frame(version=4, vendor=VIVO_VENDOR, command=QUERY_BATTERY)


# ---- 解析器（对应 Kotlin parseXxx）----


def parse_noise_state(frame: Frame) -> Optional[NoiseState]:
    if frame.vendor != VIVO_VENDOR:
        return None
    if frame.command not in (ACK_NOISE_MODE, REPORT_NOISE_MODE):
        return None
    if len(frame.payload) < 2 or frame.payload[0] != 0:
        return None
    try:
        mode = NoiseMode(frame.payload[1])
    except ValueError:
        return None
    return NoiseState(
        mode=mode,
        noise_effect=frame.payload[2] if len(frame.payload) > 2 else None,
        transparency_effect=frame.payload[3] if len(frame.payload) > 3 else None,
        acknowledged=frame.command == ACK_NOISE_MODE,
        version=frame.version,
    )


def parse_battery_state(frame: Frame) -> Optional[BatteryState]:
    if frame.vendor != VIVO_VENDOR or frame.command != REPORT_BATTERY:
        return None
    if len(frame.payload) < 5 or frame.payload[0] != 0:
        return None
    charging = frame.payload[4]

    def pct(b: int) -> Optional[int]:
        v = b & 0xFF
        return v if 0 <= v <= 100 else None

    return BatteryState(
        left_percent=pct(frame.payload[1]),
        right_percent=pct(frame.payload[2]),
        case_percent=pct(frame.payload[3]),
        left_charging=bool(charging & 0x01),
        right_charging=bool(charging & 0x02),
        case_charging=bool(charging & 0x04),
        version=frame.version,
    )


def parse_handshake_state(frame: Frame) -> Optional[HandshakeState]:
    if frame.vendor != GAIA_VENDOR or frame.command != HANDSHAKE_RESPONSE:
        return None
    return HandshakeState(
        accepted=(frame.payload[0] == 0) if frame.payload else False,
        payload=frame.payload,
        version=frame.version,
    )


def hexlify(data: bytes, sep: str = " ") -> str:
    return sep.join(f"{b:02X}" for b in data)
