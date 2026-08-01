"""
Moondrop（水月雨）耳机会话状态机 —— HyperEars Python 移植（仅水月雨）

把「识别 → 通道(RFCOMM) → 协议(握手/电量/降噪) → 状态映射」建模为会话阶段，
每个蓝牙地址一个逻辑会话。Moondrop 的协议比 vivo 简单：
- GAIA version 固定 4、vendor 0x001D（握手用 GAIA vendor 0x000A）。
- 仅 3 种降噪态（OFF / ANC / TRANSPARENCY），**设置命令无 ACK**（fire-and-forget），
  UI 侧做乐观更新。
- 电量仅左右耳（末 4 字节 01 LL 02 RR），无充电盒、无充电位。
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import IntEnum
from typing import List, Optional

from moondrop_protocol import (
    BatteryState,
    Decoder,
    HandshakeState,
    MoondropNoiseMode,
    NoiseState,
    QUERY_BATTERY,
    QUERY_NOISE_MODE,
    REPORT_BATTERY,
    REPORT_NOISE_MODE,
    SET_NOISE_MODE,
    HANDSHAKE,
    HANDSHAKE_RESPONSE,
    handshake,
    parse_battery_state,
    parse_handshake_state,
    parse_noise_state,
    query_battery,
    query_noise_mode,
    set_noise_mode,
    from_set_byte,
)
from moondrop_models import canonical_for


class Stage(IntEnum):
    """会话阶段（看板卡片左侧的 chip 序列）。"""

    IDENTIFIED = 0       # 识别：名称命中 Moondrop 家族
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

    def __init__(self, address: str, device_name: Optional[str] = None) -> None:
        self.address = address
        self.device_name = device_name
        self.display_name = canonical_for(address, device_name)
        self.stage = Stage.IDENTIFIED
        self.decoder = Decoder()
        self.battery: Optional[BatteryState] = None
        self.noise: Optional[NoiseState] = None
        self.handshake_ok: Optional[bool] = None

    # ---- 控制编码（对应逆向协议）----

    def initial_read_commands(self) -> List[bytes]:
        return [handshake(), query_noise_mode(), query_battery()]

    def encode_refresh(self) -> List[bytes]:
        return self.initial_read_commands()

    def encode_set_noise(self, mode: MoondropNoiseMode) -> List[bytes]:
        return [set_noise_mode(mode)]

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

    def apply_set_noise(self, mode: MoondropNoiseMode) -> None:
        """乐观更新：设置命令真机无 ACK，本地立即反映（next query 会校正）。"""
        self.noise = NoiseState(mode=mode, acknowledged=False, version=4)

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
            f"L{b.left_percent}% R{b.right_percent}%"
            if b
            else "电量未知"
        )
        mode = n.mode.name if n else "模式未知"
        return f"{self.display_name} | {batt} | {mode}"
