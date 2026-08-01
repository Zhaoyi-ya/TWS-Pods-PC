"""
HyperEars PC 看板（仅 Moondrop 水月雨）——Tkinter 实现

信息架构与 vivo / Huawei 版一致：设备会话列表 + 每设备卡片（识别/通道/协议/状态映射）
+ 顶部运行时卡片。

连接能力：
- 「连接模拟设备」：SimulatedTransport，离线即可演示完整管线（含电量/降噪模拟）。
- 「真实连接（RFCOMM）」：WinSockRfcommTransport，纯 ctypes 调 ws2_32.dll（零依赖、免 winrt）。
- 「列出已配对设备」：读注册表枚举已配对蓝牙，双击即用 Windows 原生 RFCOMM 连接。

功能（参考 MOONDROP-Protocol.txt）：
- 降噪模式三态：关 / 降噪(ANC) / 通透(Transparency)。
  注意：Moondrop 的「设置」命令**真机无 ACK**（fire-and-forget），UI 乐观更新，
  下一次 query 会校正真实状态。
- 电量：仅左右耳（末 4 字节 01 LL 02 RR），无充电盒、无充电位指示。

依赖：仅标准库（tkinter）。
"""

from __future__ import annotations

import threading
import tkinter as tk
from tkinter import ttk
from typing import Dict, List, Optional, Tuple

from session import EarbudSession, Stage, STAGE_LABELS
from transport import SimulatedTransport, WinSockRfcommTransport, list_paired_devices
from moondrop_models import is_family_name
from moondrop_protocol import MoondropNoiseMode


MOONDROP_KEYWORDS = ("moondrop", "水月雨")

NOISE_LABELS = {
    MoondropNoiseMode.OFF: "关",
    MoondropNoiseMode.ANC: "降噪",
    MoondropNoiseMode.TRANSPARENCY: "通透",
}
NOISE_ORDER = (MoondropNoiseMode.OFF, MoondropNoiseMode.ANC, MoondropNoiseMode.TRANSPARENCY)


# ---- 深色主题配色（与 IDE 深色主题一致）----
BG = "#1b1b1b"
PANEL = "#242424"
PANEL2 = "#2d2d2d"
FG = "#e6e6e6"
MUTED = "#9a9a9a"
ACCENT = "#4f9dff"
GREEN = "#3fb950"
RED = "#f85149"
PURPLE = "#bc8cff"
CHIP_DONE = "#2ea043"
CHIP_TODO = "#3a3a3a"


STAGE_ORDER = [Stage.IDENTIFIED, Stage.CHANNEL, Stage.PROTOCOL, Stage.PUBLISHED]
STAGE_COLOR = {
    Stage.IDENTIFIED: MUTED,
    Stage.CHANNEL: ACCENT,
    Stage.PROTOCOL: PURPLE,
    Stage.PUBLISHED: GREEN,
    Stage.DISCONNECTED: RED,
}


def _mask(addr: str) -> str:
    parts = addr.split(":")
    if len(parts) == 6:
        return f"{parts[0]}:{parts[1]}:{parts[2]}:**:**:**"
    return addr


class SessionCard(ttk.Frame):
    def __init__(self, master, app, session: EarbudSession, transport, kind: str, **kw):
        super().__init__(master, **kw)
        self.app = app
        self.session = session
        self.transport = transport
        self.kind = kind
        self._build()
        self.refresh()

    def _build(self):
        self.configure(style="Card.TFrame")
        head = ttk.Frame(self, style="Card.TFrame")
        head.pack(fill="x", padx=10, pady=(8, 4))
        ttk.Label(head, text=self.session.display_name, style="Title.TLabel").pack(side="left")
        ttk.Label(head, text=_mask(self.session.address), style="Muted.TLabel").pack(side="right")

        sub = ttk.Frame(self, style="Card.TFrame")
        sub.pack(fill="x", padx=10, pady=(0, 4))
        ttk.Label(sub, text=f"通道：{self.kind}", style="Muted.TLabel").pack(side="left")
        ttk.Button(sub, text="刷新", width=6, command=lambda: self.app.on_refresh(self.session)).pack(side="right", padx=(0, 6))
        ttk.Button(sub, text="断开", width=6, command=lambda: self.app.on_disconnect(self.session)).pack(side="right")

        chips = ttk.Frame(self, style="Card.TFrame")
        chips.pack(fill="x", padx=10, pady=(0, 6))
        self._chip_labels = {}
        for st in STAGE_ORDER:
            lbl = tk.Label(chips, text=STAGE_LABELS[st], font=("Segoe UI", 9), bg=CHIP_TODO, fg=FG, padx=8, pady=2)
            lbl.pack(side="left", padx=(0, 6))
            self._chip_labels[st] = lbl

        # ---- 电量（仅左右耳）----
        batt = ttk.Frame(self, style="Card.TFrame")
        batt.pack(fill="x", padx=10, pady=(0, 6))
        self._bars = {}
        for key, label in (("L", "左耳"), ("R", "右耳")):
            row = ttk.Frame(batt, style="Card.TFrame")
            row.pack(fill="x", pady=2)
            ttk.Label(row, text=label, width=6, style="Muted.TLabel").pack(side="left")
            bar = ttk.Progressbar(row, orient="horizontal", length=240, maximum=100, mode="determinate")
            bar.pack(side="left", padx=(0, 6))
            val = ttk.Label(row, text="—", width=14, style="Muted.TLabel")
            val.pack(side="left")
            self._bars[key] = (bar, val)

        # ---- 降噪模式（三态）----
        ctrl = ttk.Frame(self, style="Card.TFrame")
        ctrl.pack(fill="x", padx=10, pady=(4, 8))
        ttk.Label(ctrl, text="降噪模式", style="Muted.TLabel").pack(side="left", padx=(0, 6))
        self._noise_btns = {}
        for mode in NOISE_ORDER:
            btn = ttk.Button(ctrl, text=NOISE_LABELS[mode], width=7,
                             command=lambda m=mode: self.app.on_set_noise(self.session, m))
            btn.pack(side="left", padx=(0, 6))
            self._noise_btns[mode] = btn

    def refresh(self):
        st = self.session.stage
        for s in STAGE_ORDER:
            lbl = self._chip_labels[s]
            lbl.configure(bg=STAGE_COLOR[s] if (st >= s and st != Stage.DISCONNECTED) else CHIP_TODO)

        b = self.session.battery
        mapping = [
            ("L", b.left_percent if b else None),
            ("R", b.right_percent if b else None),
        ]
        for key, pct in mapping:
            bar, val = self._bars[key]
            if pct is None:
                bar["value"] = 0
                val.configure(text="不可用", foreground=MUTED)
            else:
                bar["value"] = pct
                val.configure(text=f"{pct}%", foreground=FG)

        active = self.session.noise.mode if self.session.noise else None
        for mode, btn in self._noise_btns.items():
            try:
                btn.configure(style="ActiveMode.TButton" if mode == active else "TButton")
            except tk.TclError:
                pass


class HyperEarsApp:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title("HyperEars PC · Moondrop 水月雨")
        self.root.geometry("600x640")
        self.style = ttk.Style()
        self.style.theme_use("clam")
        self._configure_style()

        self.sessions: Dict[str, Tuple[EarbudSession, object, str]] = {}
        self.devices: List[Tuple[str, str]] = []

        self._build_ui()
        self.set_status(
            "就绪。「连接模拟设备」离线演示；「列出已配对设备」从系统读取已配对蓝牙地址（免手动输入），"
            "双击即可通过 Windows 原生 RFCOMM 真实连接（免 winrt）。"
        )

    def _configure_style(self):
        s = self.style
        s.configure("TFrame", background=BG)
        s.configure("Card.TFrame", background=PANEL, relief="flat")
        s.configure("TLabel", background=BG, foreground=FG)
        s.configure("Title.TLabel", background=PANEL, foreground=FG, font=("Segoe UI", 11, "bold"))
        s.configure("Muted.TLabel", background=PANEL, foreground=MUTED, font=("Segoe UI", 9))
        s.configure("TButton", background=PANEL2, foreground=FG, font=("Segoe UI", 9))
        s.configure("ActiveMode.TButton", background=ACCENT, foreground="#06121f", font=("Segoe UI", 9, "bold"))
        s.configure("TProgressbar", background=ACCENT, troughcolor=PANEL2)

    def _build_ui(self):
        top = ttk.Frame(self.root, style="TFrame")
        top.pack(fill="x", padx=10, pady=8)
        self.runtime = tk.Label(top, text="传输：模拟通道（默认）", bg=PANEL, fg=FG, font=("Segoe UI", 10), padx=10, pady=6, anchor="w")
        self.runtime.pack(fill="x")

        bar = ttk.Frame(self.root, style="TFrame")
        bar.pack(fill="x", padx=10, pady=(0, 6))
        ttk.Button(bar, text="列出已配对设备", command=self.on_enumerate).pack(side="left", padx=(0, 6))
        self.moondrop_only = tk.BooleanVar(value=True)
        ttk.Checkbutton(bar, text="仅水月雨", variable=self.moondrop_only).pack(side="left", padx=(0, 6))
        ttk.Button(bar, text="连接模拟设备", command=self.on_connect_sim).pack(side="left", padx=(0, 6))
        ttk.Button(bar, text="断开全部", command=self.on_disconnect_all).pack(side="left")

        self.listbox = tk.Listbox(self.root, bg=PANEL, fg=FG, height=5, font=("Segoe UI", 9))
        self.listbox.pack(fill="x", padx=10, pady=(0, 4))
        self.listbox.bind("<Double-1>", self.on_connect_listed)

        canvas = tk.Canvas(self.root, bg=BG, highlightthickness=0)
        scroll = ttk.Scrollbar(self.root, orient="vertical", command=canvas.yview)
        self.cards = ttk.Frame(canvas, style="TFrame")
        self.cards.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.create_window((0, 0), window=self.cards, anchor="nw")
        canvas.configure(yscrollcommand=scroll.set)
        canvas.pack(side="left", fill="both", expand=True, padx=10, pady=(0, 6))
        scroll.pack(side="right", fill="y", pady=(0, 6))

        self.status = tk.Label(self.root, text="", bg=PANEL2, fg=MUTED, anchor="w", font=("Segoe UI", 9), padx=10, pady=4)
        self.status.pack(fill="x", side="bottom")

    # ---- actions ----

    def set_status(self, msg: str):
        self.status.configure(text=msg)

    def _register(self, session: EarbudSession, transport, kind: str):
        if session.address in self.sessions:
            return
        card = SessionCard(self.cards, self, session, transport, kind, style="Card.TFrame")
        card.pack(fill="x", pady=(0, 8))
        self.sessions[session.address] = (session, transport, kind)
        self._refresh_runtime()

    def on_connect_sim(self):
        addr, name = "AA:BB:CC:00:11:22", "Moondrop Space Travel"
        session = EarbudSession(addr, name)
        transport = SimulatedTransport(address=addr, device_name=name)
        transport.connect()
        session.stage = Stage.CHANNEL
        self._run_initial(session, transport)
        self._register(session, transport, "模拟通道")
        self.set_status("已连接模拟设备（Moondrop Space Travel）。可切降噪三态，或「刷新」重新查询电量。")

    def _connect_real_bg(self, addr: str, name: Optional[str]):
        self.set_status(f"正在通过 Windows 原生 RFCOMM 连接 {addr} …")
        threading.Thread(target=self._do_real_connect, args=(addr, name), daemon=True).start()

    def _do_real_connect(self, addr: str, name: Optional[str]):
        transport = WinSockRfcommTransport(address=addr, device_name=name)
        try:
            transport.connect()
        except Exception as exc:  # pragma: no cover
            self.root.after(0, lambda: self.set_status(f"真实连接失败：{exc}"))
            return
        session = EarbudSession(addr, name)
        session.stage = Stage.CHANNEL
        self._run_initial(session, transport)
        self.root.after(0, self._register, session, transport, "真实连接")

    def on_connect_listed(self, event=None):
        sel = self.listbox.curselection()
        if not sel or sel[0] >= len(self.devices):
            return
        name, mac = self.devices[sel[0]]
        self._connect_real_bg(mac, name)

    def _run_initial(self, session: EarbudSession, transport):
        for cmd in session.initial_read_commands():
            transport.send(cmd)
            resp = transport.recv()
            if resp:
                session.offer(resp)

    def on_refresh(self, session: EarbudSession):
        _, transport, _ = self.sessions.get(session.address, (None, None, None))
        if transport is None:
            return
        self._run_initial(session, transport)
        for widget in self.cards.winfo_children():
            if isinstance(widget, SessionCard) and widget.session is session:
                widget.refresh()
        self.set_status(f"已刷新：{session.display_name}（电量/降噪真机会在 query 后校正）")

    def on_set_noise(self, session: EarbudSession, mode: MoondropNoiseMode):
        _, transport, _ = self.sessions.get(session.address, (None, None, None))
        if transport is None:
            return
        for cmd in session.encode_set_noise(mode):
            transport.send(cmd)
            transport.recv()  # 真机无 ACK，recv 通常返回空，忽略即可
        session.apply_set_noise(mode)  # 乐观更新
        for widget in self.cards.winfo_children():
            if isinstance(widget, SessionCard) and widget.session is session:
                widget.refresh()
        self.set_status(f"已发送：{session.display_name} → 降噪模式「{NOISE_LABELS[mode]}」（真机无 ACK，乐观更新）")

    def on_disconnect(self, session: EarbudSession):
        _, transport, _ = self.sessions.get(session.address, (None, None, None))
        if transport is not None:
            transport.close()
        session.stage = Stage.DISCONNECTED
        for widget in self.cards.winfo_children():
            if isinstance(widget, SessionCard) and widget.session is session:
                widget.refresh()
                widget.destroy()
        self.sessions.pop(session.address, None)
        self._refresh_runtime()
        self.set_status(f"已断开：{session.display_name}")

    def on_disconnect_all(self):
        for addr, (session, transport, _) in list(self.sessions.items()):
            transport.close()
            session.stage = Stage.DISCONNECTED
            for widget in self.cards.winfo_children():
                if isinstance(widget, SessionCard) and widget.session is session:
                    widget.destroy()
        self.sessions.clear()
        self._refresh_runtime()
        self.set_status("已断开全部会话。")

    def on_enumerate(self):
        self.set_status("正在从系统注册表读取已配对蓝牙设备…")
        self.listbox.delete(0, tk.END)
        threading.Thread(target=self._enum_thread, daemon=True).start()

    def _enum_thread(self):
        all_found = list_paired_devices()
        if self.moondrop_only.get():
            found = [(n, m) for n, m in all_found if is_family_name(n)]
        else:
            found = all_found
        note = ""
        if self.moondrop_only.get() and not found and all_found:
            found = all_found
            note = "（型号名未命中的水月雨关键词，已显示全部已配对设备）"
        self.devices = found
        self.root.after(0, self._update_device_list, found, note)

    def _update_device_list(self, found: List[Tuple[str, str]], note: str = ""):
        self.listbox.delete(0, tk.END)
        if not found:
            hint = (
                "未发现任何已配对设备。"
                + ("（取消「仅水月雨」可看全部；或先在 Windows 设置里配对耳机）"
                   if self.moondrop_only.get() else "（先在 Windows 设置里配对耳机）")
            )
            self.listbox.insert(tk.END, hint)
            self.set_status("枚举完成：未找到已配对的蓝牙设备。仍可用「连接模拟设备」。")
            return
        for name, mac in found:
            self.listbox.insert(tk.END, f"{name}  ·  {mac}")
        msg = f"枚举完成：发现 {len(found)} 台已配对设备。双击用 Windows 原生 RFCOMM 连接。"
        if note:
            msg += note
        self.set_status(msg)

    def _refresh_runtime(self):
        n = len(self.sessions)
        real = sum(1 for _, _, k in self.sessions.values() if k != "模拟通道")
        self.runtime.configure(text=f"活动会话：{n}（真实连接：{real}）")


def main():
    root = tk.Tk()
    HyperEarsApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
