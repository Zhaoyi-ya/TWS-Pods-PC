"""
vivo 耳机会话状态机 —— HyperEars Python 移植（仅 vivo）

对应 Kotlin 的 EarbudConnectionManager / EarbudAdapter / EarbudProtocol / DeviceStateRegistry。

PC 端把「识别 → 通道(RFCOMM) → 协议(握手/电量/降噪) → 状态映射」建模为会话阶段，
每个蓝牙地址一个逻辑会话。MiLink 发布阶段在 PC 上无对应物，这里用「状态映射」
（电量/降噪已就绪、可在看板展示）替代。
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import IntEnum
from typing import List, Optional, Tuple

from vivo_protocol import (
    ACK_NOISE_MODE,
    BatteryState,
    Decoder,
    HandshakeState,
    NoiseMode,
    NoiseState,
    QUERY_BATTERY,
    QUERY_NOISE_MODE,
    REPORT_BATTERY,
    REPORT_NOISE_MODE,
    SET_NOISE_MODE,
    HANDSHAKE,
    HANDSHAKE_RESPONSE,
    Profile,
    frame,
    handshake,
    parse_battery_state,
    parse_handshake_state,
    parse_noise_state,
    query_battery,
    query_noise_mode,
    set_noise_mode,
)
from vivo_models import canonical_for, select_profile


class Stage(IntEnum):
    """会话阶段（看板卡片左侧的 chip 序列）。"""

    IDENTIFIED = 0       # 识别：BLE/名称/FastPair 命中 vivo 家族
    CHANNEL = 1          # 通道：RFCOMM 已建立
    PROTOCOL = 2         # 协议：已握手 / 已查询
    PUBLISHED = 3        # 状态映射：电量与降噪已就绪
    DISCONNECTED = 4     # 断开


STAGE_LABELS = {
    Stage.IDENTIFIED: "识别",
    Stage.CHANNEL: "通道",
    Stage.PROTOCOL: "协议",
    Stage.PUBLISHED: "状态映射",
    Stage.DISCONNECTED: "断开",
}


@dataclass
class EarbudEvent:
    kind: str  # "handshake" | "battery" | "noise" | "unknown"
    payload: object


class EarbudSession:
    """每个蓝牙地址一个逻辑会话。"""

    def __init__(self, address: str, device_name: Optional[str] = None, profile: Optional[Profile] = None) -> None:
        self.address = address
        self.device_name = device_name
        self.display_name = canonical_for(address, device_name)
        self.profile = profile or select_profile(device_name)
        self.stage = Stage.IDENTIFIED
        self.decoder = Decoder()
        self.battery: Optional[BatteryState] = None
        self.noise: Optional[NoiseState] = None
        self.handshake_ok: Optional[bool] = None

    # ---- 控制编码（对应 Kotlin VivoEarbudProtocol）----

    def initial_read_commands(self) -> List[bytes]:
        return [handshake(), query_noise_mode(self.profile), query_battery()]

    def encode_refresh(self) -> List[bytes]:
        return self.initial_read_commands()

    def encode_set_noise(self, mode: NoiseMode) -> List[bytes]:
        return [set_noise_mode(mode, self.profile)]

    def encode_handshake(self) -> bytes:
        return handshake()

    # ---- 接收解码：返回事件列表 ----

    def offer(self, data: bytes) -> List[EarbudEvent]:
        events: List[EarbudEvent] = []
        for fr in self.decoder.offer(data):
            hs = parse_handshake_state(fr)
            if hs is not None:
                self.handshake_ok = hs.accepted
                self.stage = max(self.stage, Stage.PROTOCOL)
                events.append(EarbudEvent("handshake", hs.accepted))
                continue
            bs = parse_battery_state(fr)
            if bs is not None:
                self.battery = bs
                self.stage = max(self.stage, Stage.PUBLISHED)
                events.append(EarbudEvent("battery", bs))
                continue
            ns = parse_noise_state(fr)
            if ns is not None:
                self.noise = ns
                self.stage = max(self.stage, Stage.PUBLISHED)
                events.append(EarbudEvent("noise", ns))
                continue
            events.append(EarbudEvent("unknown", fr))
        return events

    def reset(self) -> None:
        self.decoder.reset()

    def mask_address(self) -> str:
        """正式日志对地址脱敏：只保留厂商标识段。"""
        parts = self.address.split(":")
        if len(parts) == 6:
            return f"{parts[0]}:{parts[1]}:{parts[2]}:**:**:**"
        return self.address

    def summary(self) -> str:
        b = self.battery
        n = self.noise
        batt = (
            f"L{b.left_percent}% R{b.right_percent}% C{b.case_percent}%"
            if b
            else "电量未知"
        )
        mode = n.mode.name if n else "模式未知"
        return f"{self.display_name} | {batt} | {mode}"
