# MoondropPods-Python（水月雨 TWS 控制 · HyperEars Python 移植）

把 [Pods-Protocol-Reverse-Engineering](https://github.com/) 逆向仓库里
`handmade/MOONDROP-Protocol.txt` 描述的水月雨（Moondrop）TWS 私有控制协议，
移植成 **纯 Python（仅标准库）** 的 Windows PC 客户端 —— 与同步移植的
`vivo` / `HuaweiPods-Python` 结构一致，只有协议层不同。

> 协议来源 `MOONDROP-Protocol.txt` 是纯手工逆向，**可信度高**，且本项目所有编解码
> 字节都经过单元测试与文档逐字节对齐验证。

---

## 协议要点（与 vivo / 华为的差异）

| 项 | 水月雨 (Moondrop) | vivo | 华为 FreeBuds |
|---|---|---|---|
| 帧格式 | **标准 GAIA**（`FF` 开头） | 标准 GAIA | 私有 `5A` 帧 + CRC16 |
| GAIA version | 固定 **4** | 3 / 4（逐型号） | — |
| 设备 vendor | `0x001D` | `0x001B` | — |
| 握手 vendor | `0x000A`（GAIA） | `0x000A` | — |
| SPP UUID | **标准 SPP** `00001101-...` | 私有 `00000837-...` | 标准 SPP |
| 降噪控制 | 三态：关 / 降噪 / 通透 | 多档 + 效果字节 | 开关 + 0~8 档 |
| 设置命令 ACK | **无**（fire-and-forget） | 有 ACK | 无（乐观更新） |
| 电量 | 仅左右耳（`01 LL 02 RR`） | 左/右/盒 + 充电位 | 走 HFP（`+HUAWEIBATTERY=`） |
| 手势 | 无 | 无 | 双击映射 |

**关键差异说明**
- **降噪模式编码有「查询 / 设置」两套字节**（vivo 没有这种分裂）：
  - 查询回包 `payload[0]`：`0=关` / `1=降噪` / `2=通透`
  - 设置包 `payload`：`1=关` / `2=降噪` / `4=通透`（类似位标志）
  - 见 `moondrop_protocol.py` 的 `query_byte` / `set_byte` 映射。
- **设置命令真机无 ACK**：GUI 侧做「乐观更新」（立即反映选择），下一次 query 校正真实状态。

---

## 文件结构

```
MoondropPods-Python/
├── moondrop_protocol.py   # GAIA 帧编解码 + 水月雨命令/解析器（与文档逐字节对齐）
├── moondrop_models.py     # 家族识别（关键词 "moondrop"/"水月雨"）
├── transport.py           # SimulatedTransport / WinSockRfcommTransport / 注册表枚举
├── session.py             # 每地址会话状态机（识别→通道→协议→状态映射）
├── app.py                 # Tkinter 暗色看板（电量 L/R + 降噪三态按钮）
├── test_moondrop.py      # 28 项单元测试，全部通过
└── README.md
```

---

## 运行

### 依赖
**零第三方依赖**。仅需 Windows + Python 3.8+（用标准库 `tkinter` / `ctypes` / `winreg`）。

### 离线演示（模拟设备）
```bash
python app.py
# 点「连接模拟设备」即可看到完整管线：握手→查询降噪→查询电量
```

### 真实连接（已配对的水月雨耳机）
1. 在 Windows **设置 → 蓝牙** 里先配对好耳机。
2. 在程序里点「列出已配对设备」——直接读系统注册表枚举，免手动输入 MAC、免 winrt。
3. 双击列表里的设备，即用 **Windows 原生 RFCOMM**（纯 ctypes 调 `ws2_32.dll`）连接。
4. 切换「降噪模式」三态按钮即下发控制帧；「刷新」重新查询电量/降噪。

> 真实 RFCOMM 通道已在 vivo / 华为移植中于本机验证可行（Winsock 隐式 SDP 解析通道）。

---

## 已知限制

- **设置命令无 ACK**：真机上点击降噪模式后，UI 是乐观更新；若设备未真正响应，
  下一次「刷新」会校正。
- **电量仅左右耳**：逆向文档未给出充电盒电量与充电位，故看板不显示。
- **无手势 / 无多档**：水月雨该协议仅三态降噪 + 左右电量，没有华为那种档位或双击手势。
- **Linux / macOS**：`WinSockRfcommTransport` 仅 Windows；如需在 Linux/Raspberry Pi 上用，
  可改用 `PyBluezRfcommTransport`（`pip install pybluez`），其余逻辑通用。
