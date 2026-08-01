"""
vivo 耳机识别与型号表 —— HyperEars Python 移植（仅 vivo）

源：
- integration/VivoRetailModelCatalog.kt
- integration/VivoEarbudAdapter.kt（matches / 前缀判定）
- protocol/vivo/VivoFastPairAdvertisement.kt（BLE 广播解析）

PC 端用途：通过 BLE 扫描（bleak）拿到设备名 / FastPair 广播，据此判定是否属于
vivo/iQOO TWS 家族、映射到具体型号，并选定对应 wire Profile。
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import List, Optional

from vivo_protocol import AIR3_PRO_CAPTURED, FAMILY_DEFAULT_V4, TWS_3E_V3, Profile

VIVO_TWS_PREFIX = "vivotws"
IQOO_TWS_PREFIX = "iqootws"


def normalize(value: str) -> str:
    """小写 + 仅保留字母数字（与 Kotlin normalize 一致）。"""
    return "".join(c for c in value.lower() if c.isalnum())


# 零售型号表（含别名）。与 Kotlin VivoRetailModelCatalog.models 对齐。
_MODELS = [
    ("vivo TWS Air3 Pro", set()),
    ("vivo TWS 3e", set()),
    ("vivo TWS Air2", {"vivo TWS Air200"}),
    ("vivo TWS 5e", set()),
    ("vivo TWS 3 Pro", set()),
    ("vivo TWS 3", set()),
    ("vivo TWS 2e", set()),
    ("vivo TWS 2", set()),
    ("vivo TWS 1", set()),
    ("vivo TWS A1 Pro", set()),
    ("vivo TWS A1", set()),
    ("vivo TWS Air Pro", set()),
    ("vivo TWS Air", set()),
    ("vivo TWS Neo", set()),
    ("vivo TWS X1", set()),
    ("vivo TWS", set()),
    ("iQOO TWS Air Pro", set()),
    ("iQOO TWS Air", set()),
    ("iQOO TWS 1", set()),
]

# 具体型号 -> Profile（与 Kotlin 各 Adapter 的 protocolProfile 对齐）
MODEL_PROFILES: dict[str, Profile] = {
    "vivo TWS Air3 Pro": AIR3_PRO_CAPTURED,
    "vivo TWS 3e": TWS_3E_V3,
}
DEFAULT_FAMILY_PROFILE = FAMILY_DEFAULT_V4


def is_family_name(device_name: Optional[str]) -> bool:
    """名称是否落入 vivo/iQOO TWS 家族（用于初筛进入私有协议）。"""
    if not device_name:
        return False
    n = normalize(device_name)
    return n.startswith(VIVO_TWS_PREFIX) or n.startswith(IQOO_TWS_PREFIX)


def find_model(device_name: Optional[str]) -> Optional[str]:
    """按归一化名精确匹配具体型号，返回零售名或 None。"""
    if not device_name:
        return None
    n = normalize(device_name)
    for canonical, aliases in _MODELS:
        if n == normalize(canonical) or n in (normalize(a) for a in aliases):
            return canonical
    return None


def select_profile(device_name: Optional[str]) -> Profile:
    """选定型号优先用具体 Profile，否则回退家族默认 v4。"""
    name = find_model(device_name)
    return MODEL_PROFILES.get(name, DEFAULT_FAMILY_PROFILE)


def canonical_for(address: str, device_name: Optional[str]) -> str:
    """页面展示用：有型号名用型号名，否则用家族名，否则 unknown。"""
    if device_name:
        exact = find_model(device_name)
        if exact:
            return exact
        if is_family_name(device_name):
            return "vivo / iQOO TWS（家族）"
    return "未知蓝牙设备"


# ---- FastPair BLE 广播解析（与 VivoFastPairAdvertisementParser 对齐）----


class Layout(str, Enum):
    V0 = "V0"
    V1 = "V1"
    V2 = "V2"
    ADVERTISE = "Advertise"


class ModelEncoding(str, Enum):
    BYTE = "BYTE"
    EXTENDED_LITTLE_ENDIAN = "EXTENDED_LITTLE_ENDIAN"


@dataclass
class VivoFastPairIdentity:
    uuid: int
    model_id: int
    layout: Layout
    advertisement_type: int
    ble_type: Optional[int]
    protocol_version: Optional[int]
    model_encoding: ModelEncoding
    packet_offset: int

    @property
    def uuid_label(self) -> str:
        if self.uuid == VivoFastPairAdvertisementParser.UUID_NEW:
            return "0x0837（新标记）"
        if self.uuid == VivoFastPairAdvertisementParser.UUID_LEGACY:
            return "0x8486（旧标记）"
        return f"0x{self.uuid:04X}"


# 内部家族/型号常量（与 VivoEarbudModelCatalog.labels 对齐）
MODEL_ID_LABELS = {
    1: "TWS1_BASE",
    2: "TWS1_BLACK / TWS1_TOP",
    16: "TWS_NEO_BASE",
    17: "TWS_NEO_BLUE",
    19: "TWS_NEO_TOP",
    28: "TWS2_BASE",
    29: "TWS2_BLUE",
    31: "TWS2_TOP",
    32: "TWS2E_BASE",
    33: "TWS2E_BLUE",
    35: "TWS2E_TOP",
    48: "DPD2135A",
    49: "DPD2135A_BLUE",
    60: "TWS3_BASE",
    72: "DPD2220_BASE",
    156: "DPD2430_BASE",
    176: "DPD2430F_VIVO_WHITE",
    177: "DPD2430F_VIVO_BLUE",
    180: "DPD2430F_IQOO_BLACK",
    184: "DPD2430F_JOVI_WHITE",
    185: "DPD2430F_JOVI_BLUE",
    192: "DPD2523_BASE",
    203: "DPD2523_TOP",
}


def model_id_label(model_id: int) -> Optional[str]:
    return MODEL_ID_LABELS.get(model_id)


class VivoFastPairAdvertisementParser:
    UUID_NEW = 0x0837
    UUID_LEGACY = 0x8486

    _AD_TYPE_SERVICE_UUID_16 = 0x03
    _AD_TYPE_MANUFACTURER = 0xFF
    _TWS_BLE_TYPE = 0x08
    _VERSION_V1 = 0x01
    _VERSION_V2 = 0x02
    _EXTENDED_MODEL_MARKER = 0xFF

    @staticmethod
    def parse(bytes_: bytes) -> Optional[VivoFastPairIdentity]:
        marker_index = VivoFastPairAdvertisementParser._find_marker(bytes_)
        if marker_index is None:
            return None
        packet_offset = marker_index - 1
        if packet_offset < 0:
            return None

        advertisement_type = _u8(bytes_, packet_offset + 1)
        uuid_low = _u8(bytes_, packet_offset + 2)
        uuid_high = _u8(bytes_, packet_offset + 3)
        if uuid_low is None or uuid_high is None:
            return None
        uuid = uuid_low | (uuid_high << 8)

        if advertisement_type == VivoFastPairAdvertisementParser._AD_TYPE_SERVICE_UUID_16:
            return VivoFastPairAdvertisementParser._parse_v0(bytes_, packet_offset, uuid)
        if advertisement_type == VivoFastPairAdvertisementParser._AD_TYPE_MANUFACTURER:
            return VivoFastPairAdvertisementParser._parse_manufacturer(bytes_, packet_offset, uuid)
        return None

    @staticmethod
    def _parse_v0(bytes_: bytes, packet_offset: int, uuid: int) -> Optional[VivoFastPairIdentity]:
        advertised_length = _u8(bytes_, packet_offset)
        if advertised_length is None or advertised_length < 21 or packet_offset + 21 >= len(bytes_):
            return None
        model_id = _u8(bytes_, packet_offset + 20)
        if model_id is None:
            return None
        return VivoFastPairIdentity(
            uuid=uuid,
            model_id=model_id,
            layout=Layout.V0,
            advertisement_type=VivoFastPairAdvertisementParser._AD_TYPE_SERVICE_UUID_16,
            ble_type=None,
            protocol_version=None,
            model_encoding=ModelEncoding.BYTE,
            packet_offset=packet_offset,
        )

    @staticmethod
    def _parse_manufacturer(bytes_: bytes, packet_offset: int, uuid: int) -> Optional[VivoFastPairIdentity]:
        ble_type = _u8(bytes_, packet_offset + 4)
        version = _u8(bytes_, packet_offset + 5)
        if ble_type is None or version is None:
            return None
        if ble_type != VivoFastPairAdvertisementParser._TWS_BLE_TYPE:
            return None
        if version not in (
            VivoFastPairAdvertisementParser._VERSION_V1,
            VivoFastPairAdvertisementParser._VERSION_V2,
        ):
            return None

        model_marker = _u8(bytes_, packet_offset + 17)
        if model_marker is None:
            return None
        extended = version == VivoFastPairAdvertisementParser._VERSION_V2 and model_marker == (
            VivoFastPairAdvertisementParser._EXTENDED_MODEL_MARKER
        )
        if extended:
            low = _u8(bytes_, packet_offset + 20)
            high = _u8(bytes_, packet_offset + 21)
            if low is None or high is None:
                return None
            model_id = low | (high << 8)
        else:
            model_id = model_marker

        if version == VivoFastPairAdvertisementParser._VERSION_V1:
            layout = Layout.V1
        elif _u8(bytes_, packet_offset + 38) == VivoFastPairAdvertisementParser._EXTENDED_MODEL_MARKER:
            layout = Layout.ADVERTISE
        else:
            layout = Layout.V2

        return VivoFastPairIdentity(
            uuid=uuid,
            model_id=model_id,
            layout=layout,
            advertisement_type=VivoFastPairAdvertisementParser._AD_TYPE_MANUFACTURER,
            ble_type=ble_type,
            protocol_version=version,
            model_encoding=(
                ModelEncoding.EXTENDED_LITTLE_ENDIAN if extended else ModelEncoding.BYTE
            ),
            packet_offset=packet_offset,
        )

    @staticmethod
    def _find_marker(bytes_: bytes) -> Optional[int]:
        # 与官方顺序一致：先新 UUID 后旧 UUID，先 service UUID 后 manufacturer
        patterns = [
            [VivoFastPairAdvertisementParser._AD_TYPE_SERVICE_UUID_16, 0x37, 0x08],
            [VivoFastPairAdvertisementParser._AD_TYPE_SERVICE_UUID_16, 0x86, 0x84],
            [VivoFastPairAdvertisementParser._AD_TYPE_MANUFACTURER, 0x37, 0x08],
            [VivoFastPairAdvertisementParser._AD_TYPE_MANUFACTURER, 0x86, 0x84],
        ]
        for pattern in patterns:
            idx = _index_of(bytes_, pattern)
            if idx >= 1:
                return idx
        return None


def _u8(bytes_: bytes, index: int) -> Optional[int]:
    if 0 <= index < len(bytes_):
        return bytes_[index] & 0xFF
    return None


def _index_of(bytes_: bytes, pattern: List[int]) -> int:
    if not pattern or len(bytes_) < len(pattern):
        return -1
    for start in range(0, len(bytes_) - len(pattern) + 1):
        if all(bytes_[start + o] & 0xFF == pattern[o] for o in range(len(pattern))):
            return start
    return -1
