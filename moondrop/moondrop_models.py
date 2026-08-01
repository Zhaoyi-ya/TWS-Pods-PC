"""
Moondrop（水月雨）TWS 家族识别 —— HyperEars Python 移植（仅水月雨）

Moondrop 私有控制通道是 **标准 GAIA 帧**（version 固定 4、vendor 0x001D），
**没有 vivo 那样的逐型号 wire Profile 差异**（无 ANC 档位、无手势变体），
所以这里只需要「家族识别 + 展示名」，不需要 Profile 选择。
"""

from __future__ import annotations

from typing import List, Optional


MOONDROP_KEYWORDS = ("moondrop", "水月雨")

# 已知水月雨 TWS（用于精确匹配展示名；不影响协议，version 均为 4）
_MODELS = [
    ("Moondrop Space Travel", set()),
    ("Moondrop Robin", set()),
    ("Moondrop Meteor", set()),
    ("Moondrop Music", set()),
    ("Moondrop SSR", set()),
    ("Moondrop CHU", set()),
]


def normalize(value: str) -> str:
    """小写 + 仅保留字母数字（与 Kotlin normalize 一致）。"""
    return "".join(c for c in value.lower() if c.isalnum())


def is_family_name(device_name: Optional[str]) -> bool:
    """名称是否落入 Moondrop 家族（用于初筛进入私有协议）。"""
    if not device_name:
        return False
    n = normalize(device_name)
    return any(kw in n for kw in MOONDROP_KEYWORDS)


def find_model(device_name: Optional[str]) -> Optional[str]:
    """按归一化名精确匹配具体型号，返回零售名或 None。"""
    if not device_name:
        return None
    n = normalize(device_name)
    for canonical, aliases in _MODELS:
        if n == normalize(canonical) or n in (normalize(a) for a in aliases):
            return canonical
    return None


def canonical_for(address: str, device_name: Optional[str]) -> str:
    """页面展示用：有型号名用型号名，否则用家族名，否则 unknown。"""
    if device_name:
        exact = find_model(device_name)
        if exact:
            return exact
        if is_family_name(device_name):
            return "Moondrop TWS（家族）"
    return "未知蓝牙设备"
