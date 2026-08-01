"""
Moondrop（水月雨）TWS 私有控制通道 —— HyperEars Python 移植（仅水月雨）

源：Pods-Protocol-Reverse-Engineering / handmade/MOONDROP-Protocol.txt（纯手工逆向，可信度高）

协议是 **标准 GAIA 帧**（与 vivo 同构，以 ``FF`` 开头），区别仅在厂商 ID 与命令号：
- SPP UUID 即标准 SPP：``00001101-0000-1000-8000-00805F9B34FB``
  （与华为相同；vivo 用的是私有 UUID ``00000837-...``）。
- 握手用 GAIA vendor（``0x000A``），其余设备命令用 Moondrop vendor ``0x001D``。
- 降噪模式编码有「查询/设置」两套（与 vivo 不同）：
    - 查询回包 payload[0]：0=关 1=开(降噪) 2=通透
    - 设置包 payload：      1=关 2=开(降噪) 4=通透
- 电量回包 payload 末 4 字节为 ``01 LL 02 RR``（仅左/右，无充电盒、无充电位）。

帧格式（Compact GAIA，与 Kotlin / vivo 一致）::

    FF [version] [flags] [payloadLen] [vendor_hi] [vendor_lo] [cmd_hi] [cmd_lo] [payload...]

- 本项目沿用 vivo 的 GAIA ``frame()`` / ``Decoder``（逐字节等价），仅替换常量。
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

# 厂商 / 命令常量（与 MOONDROP-Protocol.txt 逐字节对齐）
GAIA_VENDOR = 0x000A          # 握手用 GAIA 通用厂商
MOONDROP_VENDOR = 0x001D      # 设备私有命令厂商

HANDSHAKE = 0x0300
HANDSHAKE_RESPONSE = 0x8300
QUERY_NOISE_MODE = 0x1003
REPORT_NOISE_MODE = 0x1103
SET_NOISE_MODE = 0x1004
QUERY_BATTERY = 0x1A01
REPORT_BATTERY = 0x1B01

# 标准 SPP UUID（与华为一致；用作 RFCOMM 连接入口）
MOONDROP_SPP_UUID = "00001101-0000-1000-8000-00805F9B34FB"


class MoondropNoiseMode(IntEnum):
    """降噪状态域（与文档 关/开/通透 对齐）。

    注意：GAIA 线上的「查询回包」与「设置包」用的字节不同，
    见 ``query_byte`` / ``set_byte`` 映射。
    """

    ANC = 0
    OFF = 1
    TRANSPARENCY = 2


# query 回包 payload[0]：关=0 / 开=1 / 通透=2
_QUERY_BYTE = {
    MoondropNoiseMode.ANC: 0x01,
    MoondropNoiseMode.OFF: 0x00,
    MoondropNoiseMode.TRANSPARENCY: 0x02,
}
# set 包 payload：关=1 / 开=2 / 通透=4（类似位标志）
_SET_BYTE = {
    MoondropNoiseMode.ANC: 0x02,
    MoondropNoiseMode.OFF: 0x01,
    MoondropNoiseMode.TRANSPARENCY: 0x04,
}


def query_byte(mode: MoondropNoiseMode) -> int:
    return _QUERY_BYTE[mode]


def set_byte(mode: MoondropNoiseMode) -> int:
    return _SET_BYTE[mode]


def from_query_byte(b: int) -> Optional[MoondropNoiseMode]:
    return {0x00: MoondropNoiseMode.OFF, 0x01: MoondropNoiseMode.ANC,
            0x02: MoondropNoiseMode.TRANSPARENCY}.get(b & 0xFF)


def from_set_byte(b: int) -> Optional[MoondropNoiseMode]:
    return {0x01: MoondropNoiseMode.OFF, 0x02: MoondropNoiseMode.ANC,
            0x04: MoondropNoiseMode.TRANSPARENCY}.get(b & 0xFF)


def _u8(value: int) -> int:
    return value & 0xFF


def _xor(bytes_: bytes, count: int) -> int:
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
    """构造一帧（与 vivo GAIA frame 等价）。"""
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
    voff = header_size
    out[voff] = _u8((vendor >> 8) & 0xFF)
    out[voff + 1] = _u8(vendor & 0xFF)
    out[voff + 2] = _u8((command >> 8) & 0xFF)
    out[voff + 3] = _u8(command & 0xFF)
    out[voff + COMMAND_BYTES:] = payload
    if flags & FLAG_CHECKSUM:
        out.append(_u8(_xor(out, len(out))))
    return bytes(out)


class Decoder:
    """流式解码器：去前导噪声 / 拆包 / 粘包 / 可选异或校验（与 vivo 一致）。"""

    def __init__(self, initial_capacity: int = 256) -> None:
        self._bytes = bytearray(max(16, initial_capacity))
        self._size = 0

    def offer(self, chunk: bytes) -> List["Frame"]:
        self._append(chunk)
        frames: List["Frame"] = []
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
    mode: Optional[MoondropNoiseMode]
    acknowledged: bool
    version: int


@dataclass
class BatteryState:
    left_percent: Optional[int]
    right_percent: Optional[int]
    version: int


@dataclass
class HandshakeState:
    accepted: bool
    payload: bytes
    version: int


# ---- 编码器便捷函数（与文档逐字节对齐）----


def handshake() -> bytes:
    # 文档：ff 01 00 00 00 0a 03 00（version=1）
    return frame(version=1, vendor=GAIA_VENDOR, command=HANDSHAKE)


def query_noise_mode() -> bytes:
    # 文档：ff 04 00 00 00 1d 10 03
    return frame(version=4, vendor=MOONDROP_VENDOR, command=QUERY_NOISE_MODE)


def set_noise_mode(mode: MoondropNoiseMode) -> bytes:
    # 文档：ff 04 00 01 00 1d 10 04 [01/02/04]
    return frame(version=4, vendor=MOONDROP_VENDOR, command=SET_NOISE_MODE,
                 payload=bytes([set_byte(mode)]))


def query_battery() -> bytes:
    # 文档：ff 04 00 00 00 1d 1a 01
    return frame(version=4, vendor=MOONDROP_VENDOR, command=QUERY_BATTERY)


# ---- 解析器 ----


def parse_noise_state(frame: Frame) -> Optional[NoiseState]:
    if frame.vendor != MOONDROP_VENDOR or frame.command != REPORT_NOISE_MODE:
        return None
    if len(frame.payload) < 1:
        return None
    mode = from_query_byte(frame.payload[0])
    return NoiseState(
        mode=mode,
        acknowledged=True,
        version=frame.version,
    )


def parse_battery_state(frame: Frame) -> Optional[BatteryState]:
    if frame.vendor != MOONDROP_VENDOR or frame.command != REPORT_BATTERY:
        return None
    if len(frame.payload) < 4:
        return None
    # 末 4 字节：01 LL 02 RR（marker 0x01=左, 0x02=右）
    # 兼容「payload 可能还有前导字节、以这 4 字节收尾」的真实报文。
    tail = frame.payload[-4:]
    if tail[0] != 0x01 or tail[2] != 0x02:
        return None

    def pct(b: int) -> Optional[int]:
        v = b & 0xFF
        return v if 0 <= v <= 100 else None

    return BatteryState(
        left_percent=pct(tail[1]),
        right_percent=pct(tail[3]),
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
