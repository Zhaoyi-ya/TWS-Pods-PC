# TWS-Pods-PC

Windows 桌面端的 TWS 真无线耳机控制台：把各家私有的耳机控制通道（降噪 / 电量 / 手势）
搬到 PC 上。目前支持 **vivo、Huawei FreeBuds、Moondrop（水月雨）** 三个品牌。

每个品牌的控制协议都是手工逆向出来的（参考 `Pods-Protocol-Reverse-Engineering` 与各家
HyperOS / LSPosed 模块），这里用 **纯 Python、零第三方依赖** 在 Windows 上重新实现：
真实连接走 **`ctypes` 调 `ws2_32.dll` 的 Bluetooth Classic RFCOMM**（无 WinRT），已配对设备
枚举直接读 **注册表** `BTHPORT\Parameters\Devices`（免手动输入 MAC）。

---

## 支持的品牌

| 子目录 | 品牌 | 控制帧 | 连接入口 | 特点 |
|---|---|---|---|---|
| [`vivo/`](vivo/) | vivo / iQOO TWS | 标准 GAIA（`FF` 开头） | 私有 SPP UUID `00000837-d102-…` | 三套 wire Profile；电量含充电盒/充电位 |
| [`huawei/`](huawei/) | Huawei FreeBuds / HONOR | 华为自研 `0x5A` 私有帧 + CRC16/XMODEM | 标准 SPP UUID `00001101-…` | 电量走 HFP（`+HUAWEIBATTERY=`），SPP 上常无回包 |
| [`moondrop/`](moondrop/) | Moondrop 水月雨 | 标准 GAIA（vendor `0x001D`） | 标准 SPP UUID `00001101-…` | 降噪查询/设置用两套字节；设置无 ACK；电量仅左右耳 |

---

## 架构

三个子目录结构完全一致，彼此**不共享代码**（品牌间协议差异大，各跑各的最稳）：

```
<brand>/
├── <brand>_protocol.py   # 帧编解码 + 命令/解析器（与逆向文档逐字节对齐）
├── <brand>_models.py      # 型号识别 / 家族关键词
├── transport.py           # SimulatedTransport(离线演示) + WinSockRfcommTransport(真实 RFCOMM) + 注册表枚举
├── session.py             # 每地址会话状态机（识别→通道→协议→状态映射）
├── app.py                 # Tkinter 暗色看板
├── test_<brand>.py        # 单元测试（对齐逆向文档向量）
└── README.md              # 该品牌协议说明
```

> 想加新品牌（OPPO、小米…）？复制一个子目录、只改 `<brand>_protocol.py` 的帧/命令常量即可。

---

## 快速开始

任选一个品牌子目录：

```bash
cd vivo        # 或 huawei / moondrop
python app.py          # 启动看板
python test_vivo.py    # 跑测试（vivo 例；其余对应 test_huawei.py / test_moondrop.py）
```

- **离线演示**：看板点「连接模拟设备」即可看到完整管线（含电量/降噪模拟）。
- **真实连接**：先在 Windows 设置里配对耳机，看板点「列出已配对设备」，双击列表项走
  Windows 原生 RFCOMM 真实连接（免 winrt）。

---

## 环境与依赖

- **Windows**（Bluetooth Classic RFCOMM 仅 Windows 桌面端可用）。
- **Python 3.9+**，仅需标准库（`tkinter`、`ctypes`、`winreg`、`socket`）。
- **零第三方依赖**：不装 `winrt`、不装 `pybluez`（Linux 真机可选 pybluez，见各子目录 README）。
- Linux / Raspberry Pi：可用 `PyBluezRfcommTransport`（需 `pip install pybluez` + `libbluetooth-dev`）。

---

## 已知限制

- **真机 RFCOMM 握手尚未在本机逐一硬件验证**（vivo / Huawei / Moondrop 的真实连接待用户配对后实测；
  `connect()` 报 WSA 错误时可显式指定 `channel=` 兜底）。
- 华为电量走 HFP，SPP 上通常无回包 → 看板显示「电量未知」属预期。
- Moondrop / Huawei 的「设置」命令真机无 ACK（fire-and-forget），UI 做乐观更新，下次查询校正。
- 协议为手工逆向，新固件可能变更；以各子目录 README 与 `Pods-Protocol-Reverse-Engineering`
  原始记录为准。

---

## 许可证与致谢

本项目整体以 **GNU GPL-3.0-only** 发布（见 [`LICENSE`](LICENSE)）。上游 **HyperEars** 为
GPL-3.0-**only**（不含“或更高版本”选项），派生作品依法须以相同许可发布。

### 第三方来源与许可状态

下列逆向工程工作是本协议实现的参考来源；各自许可状态与本项目的使用方式如下：

- **OPPO Pods for Windows**（RFCOMM 连接方案 `ctypes` + 注册表枚举的参考原型）：
  <https://github.com/Zhaoyi-ya/OPPO-Pods-Win>
- **HyperEars**（vivo / iQOO TWS 协议来源）：**GNU GPL-3.0-only**，本仓库据此整体以 GPL-3.0-only 发布。
- **HuaweiPods**（HUAWEI FreeBuds 控制协议来源）：基于 **GPL-3.0** 开源。
- **Pods-Protocol-Reverse-Engineering**（Star-ZER0，手工逆向记录）：**未声明许可证，默认保留所有权利。**
  在获得作者明确授权、或作者为其成果增补许可证之前，本仓库**不包含该仓库的任何源码或文档文件**，
  仅将其**公开的协议事实**作为参考并予署名（协议规范属于事实，不受版权保护）；建议作者为其内容增补许可证以便社区合法复用。
- **1812z/OppoPods**、**moculll/ScrewVivoTWS**：协议研究参考，以原仓库许可为准；本仓库仅作事实性参考，未复制其源码。

### 本项目的贡献（实机抓包与验证结果）

在上述事实来源之外，本仓库补充了：

- **各品牌独立的 Python 实现**（`vivo/` `huawei/` `moondrop/`），零第三方依赖（纯 `ctypes` + 注册表 RFCOMM）。
- **逐字节验证**：每个子目录的 `test_*.py` 对照逆向文档的协议向量做字节级断言——
  vivo 13/13、huawei 18/18、moondrop 28/28 全部通过，帧编解码与文档逐字节一致。
- **模拟器往返**（SimulatedTransport）覆盖握手 / 查询 / 设置 / 电量全链路。
- **实机 RFCOMM 握手验证**：待用户在已配对真机上通过看板双击连接后补充
  （部分机型 `connect()` 可能需指定 `channel=` 兜底；目前本机注册表枚举已验证可用）。
