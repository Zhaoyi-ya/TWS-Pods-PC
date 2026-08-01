"""
Moondrop（水月雨）蓝牙传输层 —— HyperEars Python 移植（仅水月雨）

Moondrop 的私有控制通道是 **Bluetooth Classic RFCOMM (SPP)**
（标准 SPP UUID ``00001101-0000-1000-8000-00805F9B34FB``，**不是 BLE**，也非 vivo 私有 UUID）。

连接与枚举方式（与 vivo / Huawei 一致，已在本机验证可行）：
- 真实 RFCOMM 客户端用 **纯 ctypes 调 ws2_32.dll**（WinSock2 Bluetooth RFCOMM），
  **不依赖任何第三方包**，无需 WinRT。
- 「已配对设备」枚举直接读 **Windows 注册表**
  ``HKLM\\SYSTEM\\CurrentControlSet\\Services\\BTHPORT\\Parameters\\Devices``
  （子键名即 MAC 地址），免手动输入、免 winrt。

- ``SimulatedTransport``：纯软件模拟设备，按 MOONDROP-Protocol.txt 的 GAIA 帧回包。
- ``WinSockRfcommTransport``：Windows 真实 RFCOMM 客户端（ctypes + ws2_32）。
"""

from __future__ import annotations

import ctypes
import threading
import time
import traceback
import uuid as _uuid
import winreg
from abc import ABC, abstractmethod
from typing import List, Optional, Tuple

from moondrop_protocol import (
    MOONDROP_SPP_UUID,
    MOONDROP_VENDOR,
    GAIA_VENDOR,
    HANDSHAKE,
    HANDSHAKE_RESPONSE,
    QUERY_NOISE_MODE,
    REPORT_NOISE_MODE,
    SET_NOISE_MODE,
    QUERY_BATTERY,
    REPORT_BATTERY,
    MoondropNoiseMode,
    Decoder,
    frame,
    query_byte,
    from_set_byte,
)
from moondrop_models import is_family_name


# =====================================================================
# 传输层抽象
# =====================================================================

class Transport(ABC):
    @abstractmethod
    def connect(self) -> None:
        ...

    @abstractmethod
    def send(self, data: bytes) -> None:
        ...

    @abstractmethod
    def recv(self, timeout: Optional[float] = None) -> bytes:
        ...

    @abstractmethod
    def close(self) -> None:
        ...

    @property
    def connected(self) -> bool:
        return False


class SimulatedTransport(Transport):
    """模拟一台 Moondrop TWS 设备，按真实协议帧回包（MOONDROP-Protocol.txt）。

    用于在无硬件 / Windows 上演示完整管线。状态在内存中维护，可被 set 命令改变。
    set 命令在真机上 **无 ACK**（fire-and-forget），这里同样不回包，仅更新内部状态；
    后续 query 会反映新状态（GUI 侧也会乐观更新）。
    """

    def __init__(
        self,
        address: str = "AA:BB:CC:00:11:22",
        device_name: Optional[str] = "Moondrop Space Travel",
        battery: Tuple[int, int] = (60, 58),
        noise: MoondropNoiseMode = MoondropNoiseMode.ANC,
    ) -> None:
        self.address = address
        self.device_name = device_name
        self._battery = list(battery)
        self._noise = noise
        self._connected = False
        self._pending: List[bytes] = []

    def connect(self) -> None:
        self._connected = True

    @property
    def connected(self) -> bool:
        return self._connected

    def send(self, data: bytes) -> None:
        self._pending = []
        for fr in Decoder().offer(data):
            resp = self._respond(fr)
            if resp:
                self._pending.append(resp)

    def _respond(self, fr) -> bytes:
        if fr.command == HANDSHAKE:
            # 文档握手回包：ff 04 00 04 00 0a 83 00 00 04 03 01
            return frame(
                version=4, vendor=GAIA_VENDOR, command=HANDSHAKE_RESPONSE,
                payload=bytes([0, 4, 3, 1]),
            )
        if fr.command == QUERY_NOISE_MODE:
            # 文档查询回包：ff 04 00 04 00 1d 11 03 [qb] 01 00 00
            qb = query_byte(self._noise)
            return frame(
                version=4, vendor=MOONDROP_VENDOR, command=REPORT_NOISE_MODE,
                payload=bytes([qb, 0x01, 0x00, 0x00]),
            )
        if fr.command == SET_NOISE_MODE:
            # 真机无 ACK：仅更新内部状态（乐观更新由 session 负责）
            if fr.payload:
                m = from_set_byte(fr.payload[0])
                if m is not None:
                    self._noise = m
            return b""
        if fr.command == QUERY_BATTERY:
            # 文档电量回包：ff 04 00 04 00 1d 1b 01 01 LL 02 RR
            l, r = self._battery
            return frame(
                version=4, vendor=MOONDROP_VENDOR, command=REPORT_BATTERY,
                payload=bytes([0x01, l & 0xFF, 0x02, r & 0xFF]),
            )
        return b""

    def recv(self, timeout: Optional[float] = None) -> bytes:
        if self._pending:
            return self._pending.pop(0)
        return b""

    def close(self) -> None:
        self._connected = False

    # 演示用：随机微调电量，模拟“主动上报”效果
    def tick(self) -> None:
        for i in range(2):
            v = self._battery[i] + (-1 if self._battery[i] > 20 else 1)
            self._battery[i] = max(5, min(100, v))


class PyBluezRfcommTransport(Transport):
    """真实 RFCOMM 客户端（pybluez）。

    ⚠️ Windows 上 Python 无法稳定建立 RFCOMM 客户端，建议在 Linux / Raspberry Pi 使用。
    依赖：``pip install pybluez``（Linux 需 ``sudo apt install libbluetooth-dev``）。
    """

    def __init__(
        self,
        address: str,
        device_name: Optional[str] = None,
        channel: Optional[int] = None,
        uuid: str = MOONDROP_SPP_UUID,
    ) -> None:
        self.address = address
        self.device_name = device_name
        self.channel = channel
        self.uuid = uuid
        self._sock = None
        self._connected = False

    def connect(self) -> None:
        try:
            import bluetooth  # type: ignore
        except ImportError as exc:  # pragma: no cover
            raise RuntimeError(
                "未安装 pybluez，无法建立真实 RFCOMM 通道。"
                "请 `pip install pybluez`（Linux 还需 libbluetooth-dev）。"
            ) from exc

        self._sock = bluetooth.BluetoothSocket(bluetooth.RFCOMM)
        if self.channel is None:
            self.channel = bluetooth.find_service(address=self.address, uuid=self.uuid)
            if not self.channel:
                raise RuntimeError(f"未找到 Moondrop RFCOMM 服务（UUID={self.uuid}）")
            if isinstance(self.channel, list):
                self.channel = self.channel[0]["port"]
        self._sock.connect((self.address, self.channel))
        self._sock.settimeout(3.0)
        self._connected = True

    @property
    def connected(self) -> bool:
        return self._connected

    def send(self, data: bytes) -> None:
        if self._sock is None:
            raise RuntimeError("通道未连接")
        self._sock.send(bytes(data))

    def recv(self, timeout: Optional[float] = None) -> bytes:
        if self._sock is None:
            return b""
        if timeout is not None:
            self._sock.settimeout(timeout)
        try:
            chunk = self._sock.recv(1024)
        except Exception:
            return b""
        return chunk if chunk else b""

    def close(self) -> None:
        if self._sock is not None:
            try:
                self._sock.close()
            except Exception:
                pass
        self._connected = False


# =====================================================================
# Windows 真实 RFCOMM —— 纯 ctypes 调 ws2_32.dll（无需任何第三方包）
# 参考 OPPO-Pods-Win 原型（已在本机验证）：AF_BTH + BTHPROTO_RFCOMM + SOCKADDR_BTH
# =====================================================================

AF_BTH = 32
SOCK_STREAM = 1
BTHPROTO_RFCOMM = 3
SIO_RFCOMM_CONNECT = 0x8004667E  # 与 OPPO 原型一致的连接完成 ioctl
WSAEWOULDBLOCK = 10035


class _GUID(ctypes.Structure):
    _fields_ = [
        ("Data1", ctypes.c_uint32),
        ("Data2", ctypes.c_uint16),
        ("Data3", ctypes.c_uint16),
        ("Data4", ctypes.c_uint8 * 8),
    ]


class _SOCKADDR_BTH(ctypes.Structure):
    _pack_ = 1
    _fields_ = [
        ("addressFamily", ctypes.c_ushort),
        ("btAddr", ctypes.c_ulonglong),
        ("serviceClassId", _GUID),
        ("port", ctypes.c_uint32),
    ]


_WS = ctypes.WinDLL("ws2_32.dll")
_WS.WSAStartup.argtypes = [ctypes.c_uint16, ctypes.c_void_p]
_WS.WSAStartup.restype = ctypes.c_int
_WS.WSACleanup.restype = ctypes.c_int
_WS.WSAGetLastError.restype = ctypes.c_int
_WS.socket.restype = ctypes.c_void_p
_WS.socket.argtypes = [ctypes.c_int, ctypes.c_int, ctypes.c_int]
_WS.closesocket.restype = ctypes.c_int
_WS.closesocket.argtypes = [ctypes.c_void_p]
_WWW = _WS.connect
_WWW.restype = ctypes.c_int
_WWW.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_int]
_WS.send.restype = ctypes.c_int
_WS.send.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_int, ctypes.c_int]
_WS.recv.restype = ctypes.c_int
_WS.recv.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_int, ctypes.c_int]
_WS.ioctlsocket.restype = ctypes.c_int
_WS.ioctlsocket.argtypes = [ctypes.c_void_p, ctypes.c_long, ctypes.c_void_p]

_WSA_STARTED = False


def _ensure_wsa() -> None:
    global _WSA_STARTED
    if not _WSA_STARTED:
        _WSA_STARTED = True
        _WS.WSAStartup(0x0202, (ctypes.c_ubyte * 400)())


def _uuid_to_guid(uuid_str: str) -> _GUID:
    """把 '00001101-...' 转成 Windows GUID 结构。"""
    b = _uuid.UUID(uuid_str).bytes  # RFC4122 大端字节序，与 Windows GUID 内存布局一致
    d4 = (ctypes.c_uint8 * 8)(*b[8:16])
    return _GUID(
        int.from_bytes(b[0:4], "big"),
        int.from_bytes(b[4:6], "big"),
        int.from_bytes(b[6:8], "big"),
        d4,
    )


class WinSockRfcommTransport(Transport):
    """Windows 真实 RFCOMM 客户端，纯 ctypes 调 ws2_32.dll（**无需 winrt**）。

    连接采用 Winsock 的隐式 SDP：``port=0`` 且 ``serviceClassId`` 设为标准 SPP UUID
    时，``connect()`` 会自动做 SDP 查询找到通道。若需指定固定通道，可传 ``channel=``。

    要求：耳机已在 Windows 系统里**配对**（设置 → 蓝牙 → 已配对）。
    控制帧通过标准 SPP UUID ``00001101-0000-1000-8000-00805F9B34FB`` 收发。
    """

    def __init__(
        self,
        address: str,
        device_name: Optional[str] = None,
        uuid: str = MOONDROP_SPP_UUID,
        channel: Optional[int] = None,
    ) -> None:
        self.address = address
        self.device_name = device_name
        self.uuid = uuid
        self.channel = channel
        self._sock = None
        self._lock = threading.Lock()
        self._connected = False

    @property
    def connected(self) -> bool:
        return self._connected

    def connect(self) -> None:
        _ensure_wsa()
        s = _WS.socket(AF_BTH, SOCK_STREAM, BTHPROTO_RFCOMM)
        if not s:
            raise RuntimeError("无法创建 Bluetooth socket（ws2_32）")
        addr_int = int(self.address.replace(":", ""), 16)
        sa = _SOCKADDR_BTH()
        sa.addressFamily = AF_BTH
        sa.btAddr = addr_int
        sa.serviceClassId = _uuid_to_guid(self.uuid)
        sa.port = self.channel or 0  # port=0 + serviceClassId → 隐式 SDP 查通道
        ret = _WS.connect(s, ctypes.byref(sa), ctypes.sizeof(sa))
        if ret != 0:
            err = _WS.WSAGetLastError()
            _WS.closesocket(s)
            raise RuntimeError(
                f"连接 {self.address} 失败（WSA 错误 {err}）。"
                "请确认耳机已配对且在范围内；若持续失败可能是 SDP 通道解析问题，可尝试指定 channel。"
            )
        m = ctypes.c_ulong(1)
        _WS.ioctlsocket(s, SIO_RFCOMM_CONNECT, ctypes.byref(m))
        self._sock = s
        self._connected = True

    def send(self, data: bytes) -> None:
        if self._sock is None:
            raise RuntimeError("通道未连接")
        with self._lock:
            _WS.send(self._sock, data, len(data), 0)

    def recv(self, timeout: Optional[float] = 1.0) -> bytes:
        if self._sock is None:
            return b""
        chunks: List[bytes] = []
        end = time.time() + (timeout or 0)
        while time.time() < end:
            buf = (ctypes.c_ubyte * 1024)()
            g = _WS.recv(self._sock, buf, 1024, 0)
            if g > 0:
                chunks.append(bytes(buf[:g]))
            elif g < 0 and _WS.WSAGetLastError() == WSAEWOULDBLOCK:
                time.sleep(0.02)
                continue
            else:
                break
        return b"".join(chunks)

    def close(self) -> None:
        self._connected = False
        if self._sock is not None:
            try:
                _WS.closesocket(self._sock)
            except Exception:
                pass
        self._sock = None


# =====================================================================
# 系统已配对蓝牙设备枚举（读注册表，免手动输入 MAC、免 winrt）
# =====================================================================

last_enum_error: Optional[str] = None

_BTH_DEVICES_KEY = r"SYSTEM\CurrentControlSet\Services\BTHPORT\Parameters\Devices"
# 注册表里设备名以「UTF-8 字节的十六进制字符串」存储（NUL 结尾），如
# '6d6f6f6e64726f702000' -> 'moondrop '.先试 Name，再试 LEName。
_NAME_VALUES = ("Name", "LEName")


def _decode_reg_name(raw) -> str:
    """注册表设备名可能是：
    - REG_BINARY：原始 UTF-8 字节，如 b'moondrop \\x00'
    - REG_SZ：有时存成「UTF-8 字节的十六进制字符串」，如 '6d6f6f6e...'
    两种都归一化为可读名字。
    """
    if isinstance(raw, bytes):
        s = raw.decode("utf-8", "replace")
    elif isinstance(raw, str):
        try:
            s = bytes.fromhex(raw).decode("utf-8", "replace")
        except Exception:
            s = raw
    else:
        return ""
    return s.rstrip("\x00").strip()


def list_paired_devices(
    keywords: Optional[Tuple[str, ...]] = None,
) -> List[Tuple[str, str]]:
    """枚举 Windows **已配对**蓝牙设备，返回 ``[(名称, MAC), ...]``。

    数据来自注册表 ``BTHPORT\\Parameters\\Devices``（子键名即 MAC，12 位十六进制）。
    蓝牙地址直接来自系统，无需手动输入，也不依赖 winrt。
    ``keywords`` 为大小写不敏感子串白名单；``None`` 返回全部。
    """
    global last_enum_error
    last_enum_error = None
    out: List[Tuple[str, str]] = []
    try:
        k = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, _BTH_DEVICES_KEY)
    except Exception as exc:  # pragma: no cover
        last_enum_error = f"{type(exc).__name__}: {exc}"
        print("[list_paired_devices] 注册表读取失败：\n" + traceback.format_exc(), file=__import__("sys").stderr)
        return []

    try:
        i = 0
        while True:
            try:
                sub = winreg.EnumKey(k, i)
            except OSError:
                break
            i += 1
            if len(sub) != 12:
                continue
            mac = ":".join(sub[j:j + 2] for j in range(0, 12, 2))
            name = ""
            try:
                dk = winreg.OpenKey(k, sub)
                try:
                    for valname in _NAME_VALUES:
                        try:
                            v, _ = winreg.QueryValueEx(dk, valname)
                        except FileNotFoundError:
                            continue
                        name = _decode_reg_name(v)
                        if name:
                            break
                finally:
                    winreg.CloseKey(dk)
            except Exception:
                pass

            if keywords:
                low = (name or "").lower()
                if not any(kw.lower() in low for kw in keywords):
                    continue
            out.append((name or mac, mac))
    finally:
        winreg.CloseKey(k)
    return out
