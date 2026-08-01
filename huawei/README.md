# HuaweiPods-Python · HyperEars PC（华为 FreeBuds 版）

把 [HuaweiPods-main](https://github.com/...)（Kotlin / FreeBuds for HyperOS）的华为私有控制协议
移植到 Windows 桌面 Python，提供与 **vivo 版**（`D:\System\Desktop\vivo`）对等的看板：

- **真实 RFCOMM 连接**：纯 `ctypes` 调 `ws2_32.dll`，**零第三方依赖、免 WinRT**。
- **已配对设备枚举**：读 Windows 注册表，**免手动输入 MAC、免 winrt**。
- **降噪开关 + 强度档位**、**双击手势映射**、**电量（尽力而为）**。

> 与 vivo 版并列存在：vivo 走 GAIA（`FF` 帧），华为走自研 `0x5A` 私有帧 + HFP 电量。
> 两者的传输层（`transport.py`）与枚举逻辑完全一致，仅协议层不同。

---

## 快速开始

```bat
cd D:\System\Desktop\HuaweiPods-Python
python app.py
```

- 「连接模拟设备」：离线演示完整管线（含电量模拟）。
- 「列出已配对设备」：从注册表读取已配对蓝牙，双击即用 Windows 原生 RFCOMM 连接。
- 先到 **Windows 设置 → 蓝牙 → 已配对** 把 FreeBuds 配对好。

运行测试：

```bat
python test_huawei.py
```

---

## 平台与依赖

- **Windows 真实连接：零依赖**。纯 ctypes + `ws2_32.dll`（WinSock2 Bluetooth RFCOMM）。
  不依赖 WinRT / pybluez / 任何第三方包。
- **Linux / 树莓派**：可用 `PyBluezRfcommTransport`（需 `pip install pybluez` +
  `sudo apt install libbluetooth-dev`），在 Linux 上建立真实 RFCOMM。
- **仅标准库**（tkinter）即可跑 GUI。

---

## 华为私有协议要点（与 Kotlin 源逐字节对齐）

### 连接
- 控制通道是 **Bluetooth Classic RFCOMM (SPP)**，UUID 即标准 SPP：
  `00001101-0000-1000-8000-00805F9B34FB`
- 连接采用 Winsock **隐式 SDP**：`port=0` + `serviceClassId = SPP UUID` 时，
  `connect()` 自动做 SDP 查询解析 RFCOMM 通道（与 Kotlin
  `createRfcommSocketToServiceRecord` 等价）。

### 控制帧格式（`HuaweiL2capAncController` / `HuaweiGestureController`）

```
5A 00 06 00 [group] [command] [p1] [p2] [value] [crc_hi] [crc_lo]
```

- 固定前缀 `5A 00 06 00`，其后 5 字节为命令体，末 2 字节为 **CRC16/XMODEM**
  （poly=0x1021，init=0x0000，无反射、无最终异或）。
- 命令组（实机确认）：
  - **降噪 ANC**：`group=0x2B`
    - 开关 `command=0x04`：`p1=0x01 p2=0x01`，`value=0x01` 开 / `0x00` 关
    - 档位 `command=0x08`：`p1=0x01 p2=0x01`，`value=0x00..0x08`（0~8 共 9 档）
  - **双击手势**：`group=0x01`，`command=0x1F`
    - `p1=side`（0x01 左 / 0x02 右），`p2=0x01`，`value=action`
    - action：`0x00` 语音助手 / `0x01` 播放暂停 / `0x03` 降噪 / `0x04` 下一首 / `0xFF` 无

参考 Kotlin 预计算常量（本移植 `build_control_packet` 动态生成，已逐字节验证）：

```
ANC 开 : 5A 00 06 00 2B 04 01 01 01 78 00
ANC 关 : 5A 00 06 00 2B 04 01 01 00 68 21
档位 0 : 5A 00 06 00 2B 08 01 01 00 27 13   ...  档位 8 : 5A 00 06 00 2B 08 01 01 08 A6 1B
```

### 电量（重要）

华为 FreeBuds 的**电量走 HFP AT 通道**（`+HUAWEIBATTERY=`），不是上面的 SPP 私有帧。

- 本移植在 SPP 通道上以 `AT+HUAWEIBATTERY?` **尽力查询**，并解析回包文本
  `+HUAWEIBATTERY: count, 2,L,3,cl, 4,R,5,cr, 6,C,7,cc`。
- 在 Windows 上，真机电量通常经系统 HFP 栈上报，**SPP 套接字可能不回包** ——
  此时看板显示「电量未知（HFP 通道）」，属预期行为。
- 离线演示用 `SimulatedTransport` 模拟电量回包。

---

## 型号支持

参考项目仅在设备名命中 `huaweifreebuds3` / `freebuds3` 时放行私有命令，因此：

- **实机验证**：`HUAWEI FreeBuds 3`（已验证 `0x2B` 降噪帧可用）。
- **家族通用**：其余 FreeBuds / HONOR Earbuds 走通用画像（`0x5A` 私有帧通常兼容，
  但未逐型号实机验证；如命令无响应请确认型号是否在验证路径内）。

---

## 文件结构

| 文件 | 作用 |
|------|------|
| `huawei_protocol.py` | 帧编解码、CRC16/XMODEM、ANC/手势构造、电量解析 |
| `huawei_models.py` | 型号识别表与 Profile 选择（FreeBuds 3 已验证） |
| `transport.py` | 传输层：`SimulatedTransport` / `WinSockRfcommTransport`（ctypes+ws2_32，零依赖）/ `PyBluezRfcommTransport`；注册表枚举 |
| `session.py` | 会话状态机（电量文本解析 + 降噪/手势乐观更新） |
| `app.py` | Tkinter 看板 GUI |
| `test_huawei.py` | 协议 / 解析 / 模型 / 端到端验证（18 项，全部通过） |

---

## 已知限制 / 后续

- 真机 RFCOMM 握手（隐式 SDP 通道解析）尚未在真实华为硬件上跑通，需用户在 GUI 双击设备验证；
  若 `connect()` 报 WSA 错误，可尝试在 `WinSockRfcommTransport` 指定固定 `channel=`。
- 电量在 Windows 上依赖 HFP，SPP 查询大概率为空；如需稳定电量，需接入系统蓝牙 HFP 栈（超出本移植范围）。
