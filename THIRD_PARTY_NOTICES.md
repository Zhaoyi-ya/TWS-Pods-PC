# 第三方声明 / Third-Party Notices

本仓库（**TWS-Pods-PC**）在以下第三方逆向工程工作的基础上实现，并包含本项目自己的实机抓包与验证结果。
各来源的许可（License）状态与具体要求如下；**本项目整体以 GNU GPL-3.0-only 发布**（见根目录 `LICENSE`）。

---

## 1. HyperEars（vivo / iQOO TWS 协议来源）
- 性质：Kotlin / Android 实现，本仓库 `vivo/` 子项目的协议框架来源。
- 许可：**GNU GPL-3.0-only**。
- 说明：因上游为 GPL-3.0-**only**（不含“或更高版本”选项），本仓库整体据此以 GPL-3.0-only 发布。

## 2. 1812z/OppoPods
- 性质：OPPO 耳机协议研究参考。
- 许可：以原仓库声明为准（请见其仓库 LICENSE）。本仓库仅作事实性参考，**未复制其源码**。

## 3. Star-ZER0/Pods-Protocol-Reverse-Engineering
- 性质：TWS 协议手工逆向记录（含 vivo / Moondrop 等 `handmade/*.txt`）。
- 许可：**原仓库未声明任何许可证（默认保留所有权利 / all rights reserved）。**
- 法律说明（重要）：
  - 在获得作者明确授权、或作者为其成果增补许可证之前，本仓库**不包含该仓库的任何源码或文档文件**；
    仅将其**公开的协议事实**作为参考并予署名（协议规范属于事实，不受版权保护）。
  - 若作者希望对其内容施加特定许可，或要求移除本引用，请联系本仓库维护者。
  - 建议：请该仓库作者为其成果增补许可证（如 GPL-3.0），以便社区合法复用。

## 4. moculll/ScrewVivoTWS
- 性质：vivo TWS 协议研究参考（如 TWS 3e 参考参数）。
- 许可：以原仓库声明为准。本仓库仅作事实性参考，**未复制其源码**。

## 5. HUAWEI pods（HuaweiPods / FreeBuds 控制协议）
- 性质：本仓库 `huawei/` 子项目的协议来源（FreeBuds for HyperOS / LSPosed 模块）。
- 许可：基于 **GPL-3.0** 开源。

---

## 本项目的贡献（实机抓包与验证结果）
本仓库在上述事实来源之外，补充了：

- **各品牌独立的 Python 实现**（`vivo/` `huawei/` `moondrop/`），零第三方依赖（纯 `ctypes` + 注册表 RFCOMM）。
- **逐字节验证**：每个子目录的 `test_*.py` 对照逆向文档的协议向量做字节级断言——
  vivo 13/13、huawei 18/18、moondrop 28/28 全部通过，验证帧编解码与文档逐字节一致。
- **模拟器往返**（SimulatedTransport）覆盖握手 / 查询 / 设置 / 电量全链路。
- **实机 RFCOMM 握手验证**：待用户在已配对真机上通过看板双击连接后补充
  （部分机型 `connect()` 可能需指定 `channel=` 兜底；目前本机注册表枚举已验证可用）。

> 如发现本声明有任何遗漏或需更正，请提交 issue 或 PR。
