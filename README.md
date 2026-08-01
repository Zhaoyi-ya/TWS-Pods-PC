# TWS-Pods-PC（仅用来测试，并非最终版本）

Windows 桌面端的 TWS 真无线耳机控制台：用**纯 Python、零第三方依赖**把各家私有耳机控制通道
（降噪 / 电量 / 手势）搬到 PC 上。目前支持 **vivo、Huawei、Moondrop（水月雨）**。

- **真实连接**：`ctypes` 直接调 `ws2_32.dll` 的 Bluetooth Classic RFCOMM。
- **设备枚举**：读注册表 `BTHPORT\Parameters\Devices`。

## 支持的品牌

| 子目录 | 品牌 | 控制帧 | 连接入口 | 要点 |
|---|---|---|---|---|
| `vivo/` | vivo / iQOO | 标准 GAIA | 私有 SPP UUID `00000837-…` | 三套 wire Profile；电量含充电盒 |
| `huawei/` | Huawei / HONOR | 华为 `0x5A` 私有帧 + CRC16 | 标准 SPP UUID `00001101-…` | 电量走 HFP；SPP 常无回包 |
| `moondrop/` | Moondrop 水月雨 | 标准 GAIA（vendor `0x001D`） | 标准 SPP UUID `00001101-…` | 降噪双字节；设置无 ACK |

## 目录结构

三个子目录结构一致、彼此**不共享代码**：

```
<brand>/
├── <brand>_protocol.py   # 帧编解码 + 命令/解析（逐字节对齐逆向文档）
├── <brand>_models.py     # 型号识别
├── transport.py           # 模拟 / 真实 RFCOMM / 注册表枚举
├── session.py             # 会话状态机
├── app.py                 # Tkinter 暗色看板
└── test_<brand>.py        # 单元测试
```


## 快速开始

```bash
cd vivo            # 或 huawei / moondrop
python app.py      # 看板：点「列出已配对设备」→ 双击连接；「连接模拟设备」离线演示
python test_vivo.py  # 跑测试（其余对应 test_huawei.py / test_moondrop.py）
```

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

## 各品牌协议要点

### vivo / iQOO
- 控制帧：标准 GAIA（`FF` 开头）；连接用私有 SPP UUID `00000837-d102-11e1-9b23-00025b00a5a5`。
- 电量（左 / 右 / 充电盒）：`LL RR MM CC` 字节，`CC` 的 bit0/1/2 = 左 / 右 / 充电盒充电位。
- 已实测型号：**vivo TWS 3e**（本机注册表枚举命中）。

### Huawei FreeBuds / HONOR
- 控制帧：华为自研 `0x5A` 私有帧 + CRC16/XMODEM；降噪 `group=0x2B`、手势 `group=0x01`。
- 连接用标准 SPP UUID `00001101-…`；电量走 HFP（`+HUAWEIBATTERY=`），SPP 上常无回包。
- 已实测型号：**FreeBuds 3**（参考项目实机验证）。

### Moondrop 水月雨
- 控制帧：标准 GAIA（vendor `0x001D`）；连接用标准 SPP UUID `00001101-…`。
- 降噪双字节：查询 `0=关 / 1=降噪 / 2=通透`，设置 `1=关 / 2=降噪 / 4=通透`；设置无 ACK。
- 电量（仅左 / 右）：末 4 字节 `01 LL 02 RR`，无充电盒。

## 致谢

本项目参考了以下逆向工程与开源项目：

- **HyperEars** —— vivo / iQOO TWS 的私有协议与连接方式（GAIA 帧结构、命令号、三套 wire Profile、电量编码）
- **HuaweiPods** —— HUAWEI FreeBuds 控制协议（0x5A 私有帧 + CRC16/XMODEM、降噪/手势命令组）
- **Pods-Protocol-Reverse-Engineering**（Star-ZER0）—— Moondrop 手工逆向记录（GAIA 帧、降噪双字节映射、电量编码）

## License

GNU GPL-3.0-only
