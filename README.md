# TWS-Pods-PC

Windows 桌面端的 TWS 真无线耳机控制台：用**纯 Python、零第三方依赖**把各家私有耳机控制通道
（降噪 / 电量 / 手势）搬到 PC 上。目前支持 **vivo、Huawei FreeBuds、Moondrop（水月雨）**。

- **真实连接**：`ctypes` 直接调 `ws2_32.dll` 的 Bluetooth Classic RFCOMM（免 WinRT）。
- **设备枚举**：读注册表 `BTHPORT\Parameters\Devices`（免手输 MAC）。
- 离线可跑：内置模拟器，无需真机即可演示完整管线。

## 支持的品牌

| 子目录 | 品牌 | 控制帧 | 连接入口 | 要点 |
|---|---|---|---|---|
| `vivo/` | vivo / iQOO | 标准 GAIA | 私有 SPP UUID `00000837-…` | 三套 wire Profile；电量含充电盒 |
| `huawei/` | Huawei / HONOR | 华为 `0x5A` 私有帧 + CRC16 | 标准 SPP UUID `00001101-…` | 电量走 HFP；SPP 常无回包 |
| `moondrop/` | Moondrop 水月雨 | 标准 GAIA（vendor `0x001D`） | 标准 SPP UUID `00001101-…` | 降噪双字节；设置无 ACK |

## 目录结构

三个子目录结构一致、彼此**不共享代码**（品牌间协议差异大，各跑各的最稳）：

```
<brand>/
├── <brand>_protocol.py   # 帧编解码 + 命令/解析（逐字节对齐逆向文档）
├── <brand>_models.py     # 型号识别
├── transport.py           # 模拟 / 真实 RFCOMM / 注册表枚举
├── session.py             # 会话状态机
├── app.py                 # Tkinter 暗色看板
└── test_<brand>.py        # 单元测试
```

> 想加新品牌（OPPO、小米…）？复制一个子目录、只改 `<brand>_protocol.py` 的帧/命令常量即可。

## 快速开始

```bash
cd vivo            # 或 huawei / moondrop
python app.py      # 看板：点「列出已配对设备」→ 双击连接；「连接模拟设备」离线演示
python test_vivo.py  # 跑测试（其余对应 test_huawei.py / test_moondrop.py）
```

- **离线演示**：看板点「连接模拟设备」即可看到完整管线（含电量 / 降噪模拟）。
- **真实连接**：先在 Windows 设置里配对耳机，看板点「列出已配对设备」，双击列表项走
  Windows 原生 RFCOMM 真实连接。

## 环境与依赖

- **Windows**；**Python 3.9+**，仅需标准库（`tkinter`、`ctypes`、`winreg`、`socket`）。
- **零第三方依赖**：不装 `winrt`、不装 `pybluez`。
- Linux / Raspberry Pi：可用 `PyBluezRfcommTransport`（需 `pip install pybluez` + `libbluetooth-dev`）。

## 已知限制

- **真机 RFCOMM 握手尚未在本机逐一硬件验证**（vivo / Huawei / Moondrop 待配对后实测；
  `connect()` 报 WSA 错误时可显式指定 `channel=` 兜底）。
- 华为电量走 HFP，SPP 上通常无回包 → 看板显示「电量未知」属预期。
- 设置命令真机无 ACK（fire-and-forget），UI 做乐观更新，下次查询校正。

## 许可证与致谢

本项目以 **GNU GPL-3.0-only** 发布（见 [`LICENSE`](LICENSE)）。上游 **HyperEars** 为 GPL-3.0-only，
派生作品依法须以相同许可发布。

致谢以下逆向工程与开源项目（协议事实来源）：

- **HyperEars**（vivo / iQOO TWS 协议来源，GPL-3.0-only）
- **HuaweiPods**（HUAWEI FreeBuds 控制协议来源，GPL-3.0）
- **OPPO Pods for Windows**（`ctypes` + 注册表 RFCOMM 连接方案参考原型）：
  <https://github.com/Zhaoyi-ya/OPPO-Pods-Win>
- **Pods-Protocol-Reverse-Engineering**（Star-ZER0，手工逆向记录；未声明许可证，仅作事实参考）
- **1812z/OppoPods**、**moculll/ScrewVivoTWS**（协议研究参考）

**验证**：各子目录 `test_*.py` 对照逆向文档逐字节断言，vivo 13 / huawei 18 / moondrop 28 全部通过；
模拟器往返覆盖握手 / 查询 / 设置 / 电量全链路；真机 RFCOMM 握手待实测。
