"""
Huawei / Honor 耳机识别与型号表 —— HyperEars Python 移植（仅华为）

源：HuaweiPods-main
- pods/DeviceCapabilities.kt（detectHuaweiDeviceRoute / normalizeDeviceName）
- pods/HuaweiL2capAncController.kt（仅 FreeBuds 3 被放行 supportsPrivateCommands）

PC 端用途：枚举已配对设备时，按设备名判定是否属于华为 / 荣耀 FreeBuds 家族，
并选定对应 wire Profile。参考项目仅在设备名命中 ``huaweifreebuds3`` /
``freebuds3`` 时放行私有命令，因此 VALIDATED 画像仅锁定 FreeBuds 3；
其余 FreeBuds / 荣耀型号走通用画像（0x5A 私有帧通常兼容，但未实机验证）。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional


# 名称归一化：小写 + 仅保留字母数字（与 Kotlin normalizeDeviceName 一致）
def normalize(value: Optional[str]) -> str:
    if not value:
        return ""
    return "".join(c for c in value.lower() if c.isalnum())


# 设备名白名单关键词（用于枚举时初筛华为 / 荣耀家族）
HUAWEI_KEYWORDS = ("huawei", "freebuds", "honor", "budse", "budsl", "earbuds")


# 零售型号表（含别名）。参考公开 FreeBuds / HONOR Earbuds 家族命名。
_MODELS: List[tuple] = [
    ("HUAWEI FreeBuds 3", {"FreeBuds 3", "huawei freebuds 3"}),
    ("HUAWEI FreeBuds 3i", set()),
    ("HUAWEI FreeBuds 4", set()),
    ("HUAWEI FreeBuds 4E", set()),
    ("HUAWEI FreeBuds 4i", set()),
    ("HUAWEI FreeBuds 5", set()),
    ("HUAWEI FreeBuds 5i", set()),
    ("HUAWEI FreeBuds 6", set()),
    ("HUAWEI FreeBuds Pro", set()),
    ("HUAWEI FreeBuds Pro 2", set()),
    ("HUAWEI FreeBuds Pro 3", set()),
    ("HUAWEI FreeBuds Pro 4", set()),
    ("HUAWEI FreeBuds SE", set()),
    ("HUAWEI FreeBuds SE 2", set()),
    ("HUAWEI FreeBuds Lipstick", set()),
    ("HUAWEI FreeBuds Lipstick 2", set()),
    ("HONOR Earbuds", set()),
    ("HONOR Earbuds 3 Pro", set()),
    ("HONOR Earbuds X Series", set()),
]

# 具体型号 -> 是否经过参考项目实机验证（仅 FreeBuds 3）
_VALIDATED_MODELS = {"HUAWEI FreeBuds 3"}


@dataclass
class HuaweiProfile:
    """字节级 wire profile。华为不做 GAIA，统一用 0x5A 私有帧。

    label 仅用于展示与日志；validated 标记是否经参考项目实机验证。
    """

    label: str
    validated: bool = False
    note: str = ""


# 实机验证画像（FreeBuds 3）
FREEBUDS3_VALIDATED = HuaweiProfile(
    label="FreeBuds 3（已验证）",
    validated=True,
    note="参考项目实机验证：0x2B 降噪帧可用",
)
# 家族通用画像（未逐型号实机验证，但 0x5A 私有帧通常兼容）
FAMILY_DEFAULT = HuaweiProfile(
    label="FreeBuds / 荣耀 通用（0x5A 私有帧）",
    validated=False,
    note="未逐型号实机验证；如命令无响应请改用 FreeBuds 3 验证路径",
)


def is_family_name(device_name: Optional[str]) -> bool:
    """名称是否落入华为 / 荣耀 FreeBuds 家族（用于枚举初筛）。"""
    if not device_name:
        return False
    n = normalize(device_name)
    return any(kw in n for kw in HUAWEI_KEYWORDS)


def find_model(device_name: Optional[str]) -> Optional[str]:
    """按归一化名精确匹配具体型号，返回零售名或 None。"""
    if not device_name:
        return None
    n = normalize(device_name)
    for canonical, aliases in _MODELS:
        if n == normalize(canonical) or n in (normalize(a) for a in aliases):
            return canonical
    return None


def select_profile(device_name: Optional[str]) -> HuaweiProfile:
    """选定具体型号；FreeBuds 3 用已验证画像，其余回退家族通用画像。"""
    name = find_model(device_name)
    if name in _VALIDATED_MODELS:
        return FREEBUDS3_VALIDATED
    return FAMILY_DEFAULT


def canonical_for(address: str, device_name: Optional[str]) -> str:
    """页面展示用：有型号名用型号名，否则用家族名，否则 unknown。"""
    if device_name:
        exact = find_model(device_name)
        if exact:
            return exact
        if is_family_name(device_name):
            return "HUAWEI / HONOR FreeBuds（家族）"
    return "未知蓝牙设备"
