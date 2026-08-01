"""
Huawei FreeBuds 私有控制通道 —— HyperEars Python 移植（仅华为）

源：HuaweiPods-main（Kotlin，FreeBuds for HyperOS / LSPosed 模块）
许可：与上游一致（见仓库 LICENSE，GPL-3.0-only）

控制通道是 **Bluetooth Classic RFCOMM (SPP)**，UUID 即标准 SPP：
    ``00001101-0000-1000-8000-00805F9B34FB``
（对应 Kotlin ``HuaweiL2capAncController.SPP_UUID``，用
``createRfcommSocketToServiceRecord`` 由系统做 SDP 解析通道 —— 与本项目
WinSockRfcommTransport 的 port=0 + serviceClassId 隐式 SDP 等价）。

帧格式（与 Kotlin ``HuaweiL2capAncController`` / ``HuaweiGestureController`` 逐字节对齐）::

    5A 00 06 00 [group] [command] [p1] [p2] [value] [crc_hi] [crc_lo]

- 固定前缀 ``5A 00 06 00``，其后 5 字节为命令体，末 2 字节为 **CRC16/XMODEM**。
- CRC16/XMODEM：poly=0x1021，init=0x0000，无反射、无最终 XOR（与 Kotlin ``crc16Xmodem`` 一致）。
- 命令分组（实机确认）：
  - 降噪 ANC：group=0x2B
      - 开关  command=0x04，p1=0x01 p2=0x01，value=0x01 开 / 0x00 关
      - 档位  command=0x08，p1=0x01 p2=0x01，value=0x00..0x08（0~8 共 9 档，
        与 Kotlin ``HUAWEI_ANC_LEVEL_LAST=8`` 对齐）
  - 双击手势：group=0x01，command=0x1F
      - p1=side（0x01 左 / 0x02 右），p2=0x01，value=action
      - action：0x00 语音助手 / 0x01 播放暂停 / 0x03 降噪 / 0x04 下一首 / 0xFF 无

⚠️ 电量说明：华为 FreeBuds 的**电量**走 **HFP AT 通道**（+HUAWEIBATTERY=），
不是上面的 SPP 私有帧。本移植在 SPP 通道上以 ``AT+HUAWEIBATTERY?`` 尽力查询
（Windows 上可能无响应），并在 SimulatedTransport 中模拟电量用于离线演示。
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import IntEnum
from typing import List, Optional

# 标准 SPP UUID（与 Kotlin SPP_UUID 一致）
HUAWEI_SPP_UUID = "00001101-0000-1000-8000-00805F9B34FB"

# 命令组 / 命令号
ANC_GROUP = 0x2B
ANC_CMD_TOGGLE = 0x04
ANC_CMD_LEVEL = 0x08
GESTURE_GROUP = 0x01
GESTURE_CMD = 0x1F

# 固定填充字节（实机帧中 ANC / 手势均为此）
P1_DEFAULT = 0x01
P2_DEFAULT = 0x01

# 降噪档位上限（0..8 共 9 档，与 Kotlin HUAWEI_ANC_LEVEL_LAST 对齐）
ANC_LEVEL_MAX = 8

# 手势侧
GESTURE_LEFT = 0x01
GESTURE_RIGHT = 0x02

# 帧起始与长度占位（前 4 字节固定）
FRAME_MAGIC = bytes([0x5A, 0x00, 0x06, 0x00])


class AncMode(IntEnum):
    """降噪开关状态（与 Kotlin ``setAncMode`` 映射对齐：1=关 2=开）。"""

    OFF = 1
    ON = 2


class GestureAction(IntEnum):
    """双击手势动作（与 Kotlin ``HuaweiGestureAction`` 对齐）。"""

    VOICE_ASSISTANT = 0x00
    PLAY_PAUSE = 0x01
    NOISE_CANCELLATION = 0x03
    PLAY_NEXT = 0x04
    NONE = 0xFF


# 电量查询（尽力而为的 SPP 通道 AT 查询）
BATTERY_QUERY = b"AT+HUAWEIBATTERY?\r\n"


def crc16_xmodem(data: bytes) -> int:
    """CRC16/XMODEM：poly=0x1021，init=0x0000，无反射、无最终异或。

    与 Kotlin ``HuaweiGestureController.crc16Xmodem`` 逐位对齐。
    """
    crc = 0
    for byte in data:
        crc ^= (byte << 8) & 0xFFFF
        for _ in range(8):
            if crc & 0x8000:
                crc = ((crc << 1) ^ 0x1021) & 0xFFFF
            else:
                crc = (crc << 1) & 0xFFFF
    return crc & 0xFFFF


def build_control_packet(
    group: int,
    command: int,
    p1: int,
    p2: int,
    value: int,
) -> bytes:
    """构造一帧：5A 00 06 00 [group] [cmd] [p1] [p2] [value] + CRC16/XMODEM。

    9 字节命令体 + 2 字节校验。
    """
    body = FRAME_MAGIC + bytes(
        [group & 0xFF, command & 0xFF, p1 & 0xFF, p2 & 0xFF, value & 0xFF]
    )
    crc = crc16_xmodem(body)
    return body + bytes([(crc >> 8) & 0xFF, crc & 0xFF])


# ---- ANC 便捷构造（与 Kotlin 预计算常量逐字节一致）----


def anc_on() -> bytes:
    return build_control_packet(ANC_GROUP, ANC_CMD_TOGGLE, P1_DEFAULT, P2_DEFAULT, 0x01)


def anc_off() -> bytes:
    return build_control_packet(ANC_GROUP, ANC_CMD_TOGGLE, P1_DEFAULT, P2_DEFAULT, 0x00)


def anc_level(level: int) -> bytes:
    safe = max(0, min(ANC_LEVEL_MAX, int(level)))
    return build_control_packet(ANC_GROUP, ANC_CMD_LEVEL, P1_DEFAULT, P2_DEFAULT, safe)


# 预生成 0..8 档（与 Kotlin ANC_LEVEL_PACKETS 对齐）
ANC_LEVEL_PACKETS: List[bytes] = [anc_level(i) for i in range(ANC_LEVEL_MAX + 1)]


def gesture_double_tap(side: int, action: int) -> bytes:
    """双击手势帧：group=0x01 cmd=0x1F，p1=side，p2=0x01，value=action。"""
    return build_control_packet(GESTURE_GROUP, GESTURE_CMD, side & 0xFF, P2_DEFAULT, action & 0xFF)


# ---- 电量解析（HFP AT +HUAWEIBATTERY=）----


@dataclass
class BatteryState:
    left_percent: Optional[int]
    right_percent: Optional[int]
    case_percent: Optional[int]
    left_charging: bool
    right_charging: bool
    case_charging: bool


_BATTERY_RE = re.compile(r"(?:AT)?\+?HUAWEIBATTERY\s*[=:]\s*([0-9,\s]+)", re.IGNORECASE)


class HuaweiBatteryParser:
    """解析 ``+HUAWEIBATTERY=...`` 文本（与 Kotlin ``HuaweiBatteryParser`` 对齐）。

    载荷格式：第一个数字为「对数 count」，其后是 count 对 (key, value)。
    键值：2=左耳电量 3=左耳充电 4=右耳电量 5=右耳充电 6=充电盒电量 7=充电盒充电。
    """

    BATTERY_LEFT = 2
    CHARGING_LEFT = 3
    BATTERY_RIGHT = 4
    CHARGING_RIGHT = 5
    BATTERY_CASE = 6
    CHARGING_CASE = 7

    @classmethod
    def parse(cls, text: Optional[str]) -> Optional[BatteryState]:
        if not text or not text.strip():
            return None
        payload = _BATTERY_RE.search(text)
        if not payload:
            return None
        body = payload.group(1)
        numbers = [int(x) for x in body.split(",") if x.strip().lstrip("-").isdigit()]
        if len(numbers) < 2:
            return None

        pair_values = cls._payload_values(numbers)
        if len(pair_values) < 2:
            return None

        values: dict = {}
        index = 0
        while index + 1 < len(pair_values):
            values[pair_values[index]] = pair_values[index + 1]
            index += 2

        battery = BatteryState(
            left_percent=cls._pod(values, cls.BATTERY_LEFT, cls.CHARGING_LEFT),
            right_percent=cls._pod(values, cls.BATTERY_RIGHT, cls.CHARGING_RIGHT),
            case_percent=cls._pod(values, cls.BATTERY_CASE, cls.CHARGING_CASE),
            left_charging=cls._charging(values, cls.CHARGING_LEFT),
            right_charging=cls._charging(values, cls.CHARGING_RIGHT),
            case_charging=cls._charging(values, cls.CHARGING_CASE),
        )
        if battery.left_percent is None and battery.right_percent is None and battery.case_percent is None:
            return None
        return battery

    @staticmethod
    def _payload_values(numbers: List[int]) -> List[int]:
        count = numbers[0]
        expected = count * 2
        if count > 0 and len(numbers) >= expected + 1:
            return numbers[1 : 1 + expected]
        return numbers

    @staticmethod
    def _pod(values: dict, battery_key: int, charging_key: int) -> Optional[int]:
        level = values.get(battery_key)
        if level is None or not (0 <= level <= 100):
            return None
        return level

    @staticmethod
    def _charging(values: dict, charging_key: int) -> bool:
        return (values.get(charging_key, 0) or 0) != 0


def hexlify(data: bytes, sep: str = " ") -> str:
    return sep.join(f"{b:02X}" for b in data)
