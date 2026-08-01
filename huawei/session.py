"""
Huawei FreeBuds 会话状态机 —— HyperEars Python 移植（仅华为）

对应 Kotlin 的 EarbudConnectionManager / EarbudAdapter / EarbudProtocol / DeviceStateRegistry。

与 vivo 的差异：
- 华为**电量**走 HFP AT 文本行（``+HUAWEIBATTERY=``），不是二进制 GAIA 帧；
  offer() 直接解析文本。
- 华为**降噪**是 set-only 私有帧（无查询回包），状态采用乐观更新。
- 每个蓝牙地址一个逻辑会话。
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import IntEnum
from typing import List, Optional

from huawei_models import canonical_for, select_profile
from huawei_protocol import (
    AncMode,
    BATTERY_QUERY,
    GESTURE_LEFT,
    GESTURE_RIGHT,
    HuaweiBatteryParser,
    anc_level,
    anc_off,
    anc_on,
    gesture_double_tap,
)


class Stage(IntEnum):
    """会话阶段（看板卡片左侧的 chip 序列）。"""

    IDENTIFIED = 0       # 识别：名称命中华为 / 荣耀家族
    CHANNEL = 1          # 通道：RFCOMM 已建立
    PROTOCOL = 2         # 协议：已查询
    PUBLISHED = 3        # 状态映射：电量 / 降噪已就绪
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
    kind: str  # "battery" | "unknown"
    payload: object


class EarbudSession:
    """每个蓝牙地址一个逻辑会话。"""

    def __init__(self, address: str, device_name: Optional[str] = None, profile=None) -> None:
        self.address = address
        self.device_name = device_name
        self.display_name = canonical_for(address, device_name)
        self.profile = profile or select_profile(device_name)
        self.stage = Stage.IDENTIFIED
        self.battery: Optional[HuaweiBatteryParser.BatteryState] = None
        self.anc_mode: Optional[AncMode] = None
        self.anc_level: Optional[int] = None
        self.gesture_left: Optional[int] = None
        self.gesture_right: Optional[int] = None

    # ---- 控制编码（对应 Kotlin HuaweiL2capAncController / HuaweiGestureController）----

    def initial_read_commands(self) -> List[bytes]:
        # 华为电量走 HFP AT；这里用 SPP 上的 AT 查询尽力获取（无响应时走模拟/手动）
        return [BATTERY_QUERY]

    def encode_refresh(self) -> List[bytes]:
        return self.initial_read_commands()

    def encode_set_anc(self, mode: AncMode) -> List[bytes]:
        return [anc_on() if mode == AncMode.ON else anc_off()]

    def encode_set_anc_level(self, level: int) -> List[bytes]:
        return [anc_level(level)]

    def encode_gesture(self, side: int, action: int) -> List[bytes]:
        return [gesture_double_tap(side, action)]

    # ---- 接收解码：返回事件列表（电量为文本 AT 行）----

    def offer(self, data: bytes) -> List[EarbudEvent]:
        text = None
        try:
            text = data.decode("utf-8", "replace")
        except Exception:
            pass
        if text:
            b = HuaweiBatteryParser.parse(text)
            if b is not None:
                self.battery = b
                self.stage = max(self.stage, Stage.PUBLISHED)
                return [EarbudEvent("battery", b)]
        return [EarbudEvent("unknown", data)]

    # ---- 乐观更新（华为降噪 / 手势为 set-only，无查询回包）----

    def apply_anc(self, mode: AncMode, level: Optional[int] = None) -> None:
        self.anc_mode = mode
        if level is not None:
            self.anc_level = max(0, min(8, int(level)))
        self.stage = max(self.stage, Stage.PUBLISHED)

    def apply_anc_level(self, level: int) -> None:
        self.anc_level = max(0, min(8, int(level)))
        self.stage = max(self.stage, Stage.PUBLISHED)

    def apply_gesture(self, side: int, action: int) -> None:
        if side == GESTURE_LEFT:
            self.gesture_left = action
        elif side == GESTURE_RIGHT:
            self.gesture_right = action

    def reset(self) -> None:
        self.battery = None

    def mask_address(self) -> str:
        """正式日志对地址脱敏：只保留厂商标识段。"""
        parts = self.address.split(":")
        if len(parts) == 6:
            return f"{parts[0]}:{parts[1]}:{parts[2]}:**:**:**"
        return self.address

    def summary(self) -> str:
        b = self.battery
        batt = (
            f"L{b.left_percent}% R{b.right_percent}% C{b.case_percent}%"
            if b
            else "电量未知（HFP 通道，SPP 上可能无响应）"
        )
        mode = self.anc_mode.name if self.anc_mode else "未设置"
        lvl = f"/档{self.anc_level}" if self.anc_level is not None else ""
        return f"{self.display_name} | {batt} | 降噪 {mode}{lvl}"
