# HyperEars PC · vivo TWS（Python 移植，仅 vivo）

把 [HyperEars](https://github.com/silverpoetry/HyperEars) 的 **vivo TWS 私有协议** 移植到电脑端。
OPPO 分支用户已自行完成，本仓库只做 **vivo**（含 iQOO TWS 家族）。

> ⚠️ 平台边界：原项目强依赖 root / LSPosed / HyperOS MiLink，**这部分在 PC 上无法复现**。
> vivo 的真实控制通道是 **Bluetooth Classic RFCOMM (SPP)**，UUID `00000837-d102-11e1-9b23-00025b00a5a5`。各平台现状：
> - **Windows**：真实 RFCOMM 客户端用 **纯 `ctypes` 调 `ws2_32.dll`（WinSock2 Bluetooth RFCOMM）**，
>   **不依赖任何第三方包、无需 WinRT**。枚举已配对设备直接读 **注册表**
>   `HKLM\SYSTEM\CurrentControlSet\Services\BTHPORT\Parameters\Devices`（子键即 MAC 地址）。
>   该方案参考用户既有的 OPPO-Pods-Win 原型（`oppopods_ctk.py`），已在本机验证可行。
>   本移植内置 `WinSockRfcommTransport`。
> - **Linux / Raspberry Pi**：可直接用 `PyBluezRfcommTransport`（`pip install pybluez`）。
>
> 因此本移植的策略是：
> - **协议编解码层** 100% 忠实还原（用原项目 Kotlin 测试向量 + 独立逆向文档逐条验证）；
> - **识别 / 枚举层** 直接读系统注册表拿到已配对蓝牙地址与型号名，免手动输入、免 winrt；
> - **控制通道** 默认用「模拟通道」让整条管线在任意 PC 上立即可跑可演示；
>   真实硬件走 `WinSockRfcommTransport`（Windows，纯标准库）或 `PyBluezRfcommTransport`（Linux）。

---

## 运行

```powershell
# 看板（Tkinter，仅标准库，开箱即跑）
python app.py

# 协议回归测试（对齐 Kotlin 测试向量）
python test_vivo.py
```

可选依赖（全部不装也能跑看板，**Windows 真实连接连标准库都不需要**）：

```powershell
pip install pybluez      # 仅 Linux / Raspberry Pi 上建立真实 RFCOMM 控制通道
```

> **Windows 真实连接零依赖**：`WinSockRfcommTransport` 只用 Python 标准库
> （`ctypes` + `winreg`），枚举已配对设备只读注册表，都不需要 `winrt` / `bleak` /
> `pybluez` 等任何第三方包。之前依赖 WinRT 的 `WinRfcommTransport` 已移除
> （那套 `winrt` 命名空间包在本机容易装坏、且 `import` 崩溃会拖垮整个 GUI）。

---

## 真实连接测试（GUI）

看板（`app.py`）同时支持「离线演示」与「真实硬件连接测」。**蓝牙地址与型号名直接从系统注册表读取，免手动输入、免第三方包**：

1. **连接模拟设备**：默认，离线即可演示完整管线（编码→发送→解码→看板）。
2. **列出已配对设备**：点此按钮，读注册表 `BTHPORT\Parameters\Devices` 枚举 Windows **已配对**的蓝牙设备，
   地址与型号名直接从系统拿，无需手敲 MAC。勾选「仅 vivo/iQOO」会按型号表过滤（取消可见全部）。
3. **双击列表项连接**：对选中的已配对设备，后台线程用 `WinSockRfcommTransport`（纯 `ctypes` + `ws2_32.dll`）
   建立真实 RFCOMM 通道并跑握手/查询；连接时 `port=0` + vivo SPP UUID 触发 **隐式 SDP** 自动解析通道。
4. 每张会话卡片支持「刷新」（重新查询电量/降噪）与「断开」；降噪三态按钮直接发 SET 命令并看回包。

> 真实连接前置条件（Windows）：耳机已在「设置 → 蓝牙」里 **配对**（RFCOMM 要求已配对）；本机已配对 vivo
> 设备会显示为 `vivo TWS 3e` 之类，双击即连。若 `connect()` 报 WSA 错误，多为 SDP 通道解析或设备不在范围内，
> 可在 `WinSockRfcommTransport(address=..., channel=N)` 指定固定通道重试。

---

## 架构映射（Kotlin 原项目 → Python）

| 原项目（Android/Kotlin） | 本移植（Python） | 说明 |
|---|---|---|
| `protocol/VivoTwsProtocol.kt` | `vivo_protocol.py` | GAIA 帧编解码、Decoder 流式分帧、电量/降噪/握手解析、三套 wire Profile |
| `integration/VivoRetailModelCatalog.kt` + `VivoEarbudAdapter.kt` | `vivo_models.py` | 型号名归一化、家族判定、零售型号表、FastPair 广播解析 |
| `EarbudConnectionManager` / `EarbudAdapter` / `EarbudProtocol` / `DeviceStateRegistry` | `session.py` | `EarbudSession` 状态机：识别→通道→协议→状态映射 |
| 蓝牙传输 / RFCOMM | `transport.py` | `SimulatedTransport`（默认演示）+ `WinSockRfcommTransport`（Windows 真机，纯 ctypes + ws2_32，零依赖）+ `PyBluezRfcommTransport`（Linux 真机） |
| `dashboard-ui-architecture.md` 看板 | `app.py` | Tkinter 深色看板：会话卡片 + 阶段 chip + 电量条 + 降噪三态 |

会话阶段芯片序列与上游一致：**识别 → 通道 → 协议 → 状态映射**（MiLink 发布在 PC 无对应物，
以「状态已就绪、可在看板展示」替代）。

---

## 协议要点（vivo TWS Air3 Pro / 家族）

GAIA 紧凑帧（`vivo_protocol.frame`）：

```
FF [version] [flags] [payloadLen] [vendor_hi] [vendor_lo] [cmd_hi] [cmd_lo] [payload...]
```

- 厂商 `0x001B`，GAIA 握手 `0x000A`；RFCOMM 入口 UUID `00000837-d102-11e1-9b23-00025b00a5a5`。
- 命令：握手 `0x0300/0x8300`、降噪查询/上报 `0x0230/0x8230`、降噪设置/确认 `0x0130/0x8130`、
  电量查询/上报 `0x0207/0x8207`。
- 电量响应载荷 `00 L R C flags`：`L/R/C` 为 0..100，`flags` 的 bit0/1/2 = 左/右/盒充电中。
- 降噪响应 `00 mode 04 00`：`mode` = 0 降噪 / 1 关闭 / 2 通透。
- 三套线参：`AIR3_PRO_CAPTURED`(v3, 设置 `mode 04 00`)、`FAMILY_DEFAULT_V4`(v4)、`TWS_3E_V3`(v3)。

---

## 后续可扩展

- 在 Windows 用 `WinRfcommTransport`（配对耳机 + `pip install winrt`）接真实 Air3 Pro，验证端到端控制。
- 在 Linux 主机用 `PyBluezRfcommTransport` 接真实 Air3 Pro，验证端到端控制。
- 把 `vivo_protocol.py` 的编解码作为共享核心，后续补 Bose / StarRing（它们走 BLE GATT，
  PC 上比 RFCOMM 更有机会直接控制）。
- 看板增加「主动上报」模拟与历史曲线。

## 参考材料（本机附带）

这些文件用于辅助理解，已逐一核对：

- **`Pods-Protocol-Reverse-Engineering-main/handmade/vivo-Protocol.txt`** ✅ 已采用
  独立逆向文档，逐字节印证本移植的 **`FAMILY_DEFAULT_V4` 家族默认 Profile**：
  握手 `ff040000000a0300`、查询响应 `00 mode 03 01`、设置包 `FF040003001b0130 [mode] 03 01`、
  电量 `00 LL RR MM CC` 且 `CC` 的 bit0/1/2 = 左/右/充电盒充电（含 03/05/06/07 组合）。
  相关向量已加入 `test_vivo.py::TestHandmadeVivoProtocol`。
- **`proxypin_export_2026-07-18.har`** ⚠️ 仅作旁证
  vivo TWS App 的网络抓包（`tws-info.vivo.com` 前端 + `ptsouweb.vivo.com.cn` 的
  protobuf API，包名 `com.vivo.vivotws`）。属于 HTTP/Protobuf 流量，**不是** RFCOMM 控制帧，
  故未直接用于编解码；仅证实 App 包名与功能端点。
- **`VivoPodsDevices.json`** ❌ 未采用
  内容为 vivo App 的**埋点/遥测事件 schema**（262 条 `A102|xxxxx` 事件、采集参数），
  不含耳机型号列表，也不含 RFCOMM 帧，与协议移植无关。

## 致谢与开源协议

本子项目随仓库整体以 **GNU GPL-3.0-only** 发布（完整文本见仓库根目录 [LICENSE](LICENSE)）；
`vivo/` 派生自 GPL-3.0-only 的上游 **HyperEars** 项目，故须以相同许可发布。

致谢以下逆向工程与开源工作（协议事实来源）：

- **HyperEars**（vivo / iQOO TWS 协议来源，GPL-3.0-only）
- **OPPO Pods for Windows**（`ctypes` + 注册表 RFCOMM 连接方案参考原型）：
  <https://github.com/Zhaoyi-ya/OPPO-Pods-Win>
- **1812z/OppoPods**、**moculll/ScrewVivoTWS**（协议研究参考）
- **Star-ZER0/Pods-Protocol-Reverse-Engineering**（手工逆向记录；未声明许可证，仅作事实参考）

各来源的许可状态、本项目自己的实机抓包与逐字节验证结果，详见仓库根 README「许可证与致谢」一节。
