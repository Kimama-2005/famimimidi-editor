"""音色の A/B 比較の画面(最小限。中身は compare.py)。

A / B を鳴らすときは、その音色を「読み込んで送る」と同じ方法で全項目を送ってからフレーズを鳴らす。
"""
import tkinter as tk
from tkinter import messagebox, ttk

from .audition import PHRASES
from .compare import diff

PHRASE_MS = {name: max(s + d for s, d, _ in ev) for name, ev in PHRASES}


class ABWindow(tk.Toplevel):
    def __init__(self, app):
        super().__init__(app.root)
        self.app = app
        self.title("音色を比べる(A/B)")
        self.geometry("720x560")
        self.patches = app.library.lib.patches
        self._jobs = []
        f = ttk.Frame(self, padding=10)
        f.pack(fill="both", expand=True)

        top = ttk.Frame(f)
        top.pack(fill="x")
        names = [f"{p.name}(ch{p.channel})" for p in self.patches]
        self.combo = {}
        for row, key in enumerate("AB"):
            ttk.Label(top, text=key, font=("", 14, "bold"), foreground="#c00" if key == "A" else "#06c").grid(
                row=row, column=0, padx=(0, 6))
            c = ttk.Combobox(top, values=names, state="readonly", width=46)
            c.grid(row=row, column=1, sticky="w", pady=2)
            c.bind("<<ComboboxSelected>>", lambda e: self.refresh())
            ttk.Button(top, text=f"♪ {key} を鳴らす", command=lambda k=key: self.play(k)).grid(row=row, column=2, padx=6)
            self.combo[key] = c
        sel = app.library.selected()
        if sel in self.patches:
            self.combo["A"].current(self.patches.index(sel))

        opt = ttk.Frame(f)
        opt.pack(fill="x", pady=8)
        ttk.Label(opt, text="フレーズ").pack(side="left")
        self.phrase = ttk.Combobox(opt, values=[n for n, _ in PHRASES], state="readonly", width=20)
        self.phrase.set(PHRASES[0][0])
        self.phrase.pack(side="left", padx=4)
        ttk.Button(opt, text="A → B → A → B と交互に鳴らす", command=self.alternate).pack(side="left", padx=8)
        ttk.Button(opt, text="止める", command=self.stop).pack(side="left")
        self.now = ttk.Label(opt, font=("", 12, "bold"))
        self.now.pack(side="left", padx=10)

        ttk.Label(f, text="違う設定(上ほど音への影響が大きい。灰色 = どちらの音色でも効いていないので、音は変わらない)",
                  foreground="#555").pack(anchor="w")
        self.tree = ttk.Treeview(f, columns=("name", "a", "b"), show="headings")
        for c, t, w in [("name", "設定", 260), ("a", "A", 150), ("b", "B", 150)]:
            self.tree.heading(c, text=t)
            self.tree.column(c, width=w, anchor="w")
        self.tree.tag_configure("mute", foreground="#aaa")
        self.tree.pack(fill="both", expand=True)
        self.note = ttk.Label(f, foreground="#a60")
        self.note.pack(anchor="w")
        self.protocol("WM_DELETE_WINDOW", self.close)
        self.refresh()

    def patch(self, key):
        i = self.combo[key].current()
        return self.patches[i] if i >= 0 else None

    def refresh(self):
        self.tree.delete(*self.tree.get_children())
        pa, pb = self.patch("A"), self.patch("B")
        self.note.configure(text="")
        if not (pa and pb):
            return
        if pa.channel != pb.channel:
            self.note.configure(text=f"※ A は ch{pa.channel}用、B は ch{pb.channel}用です。違いは A のチャンネルで比べています。")
        rows = diff(pa, pb, self.app.params)
        for r in rows:
            self.tree.insert("", "end", values=(r.name, r.a, r.b), tags=() if r.audible else ("mute",))
        if not rows:
            self.tree.insert("", "end", values=("(違いはありません)", "", ""))

    def play(self, key, then=None):
        p = self.patch(key)
        if p is None:
            messagebox.showinfo("比べる", f"{key} の音色を選んでください。", parent=self)
            return
        if self.app.engine.writing:
            return
        self.app.apply_patch(p)                         # 全項目を送る(読み込んで送ると同じ)
        self.now.configure(text=f"いま: {key}", foreground="#c00" if key == "A" else "#06c")
        name = self.phrase.get()
        events = dict(PHRASES)[name]
        au = self.app.audition

        def start():
            au.player.play(p.channel, au.base[p.channel], au.vel.get(), events)
        self._later(150, start)                         # CC が届いてから鳴らす
        if then:
            self._later(150 + PHRASE_MS[name] + 500, then)

    def alternate(self):
        self.stop()
        seq = ["A", "B", "A", "B"]

        def step(i=0):
            if i < len(seq):
                self.play(seq[i], then=lambda: step(i + 1))
            else:
                self.now.configure(text="")
        step()

    def _later(self, ms, fn):
        self._jobs.append(self.after(ms, fn))

    def stop(self):
        for j in self._jobs:
            self.after_cancel(j)
        self._jobs.clear()
        self.app.audition.stop()
        self.now.configure(text="")

    def close(self):
        self.stop()
        self.destroy()
