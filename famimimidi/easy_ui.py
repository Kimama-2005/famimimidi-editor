"""かんたん表示(フェーズB)。まとまりごとに、シンセ用語のタイトル+「?」の説明で見せる。中身は easy.py。

フェーズCで画面を作り直すので、ここは tkinter の最小限の実装にとどめる。
"""
import tkinter as tk
from tkinter import ttk

from .easy import choices_of, current_choice, groups_for
from .editor import load_presets
from .library import Patch


class Tooltip:
    """マウスを乗せると説明を出す"""

    def __init__(self, widget, text):
        self.widget, self.text, self.tip, self.job = widget, text, None, None
        widget.bind("<Enter>", self._schedule, add="+")
        widget.bind("<Leave>", self._hide, add="+")

    def _schedule(self, e):
        self.job = self.widget.after(250, self._show)

    def _show(self):
        x = self.widget.winfo_rootx() + 16
        y = self.widget.winfo_rooty() + self.widget.winfo_height() + 4
        self.tip = tk.Toplevel(self.widget)
        self.tip.wm_overrideredirect(True)
        self.tip.geometry(f"+{x}+{y}")
        tk.Label(self.tip, text=self.text, justify="left", wraplength=360, bg="#fffbe6", relief="solid",
                 borderwidth=1, padx=6, pady=4).pack()

    def _hide(self, e):
        if self.job:
            self.widget.after_cancel(self.job)
            self.job = None
        if self.tip:
            self.tip.destroy()
            self.tip = None


def help_mark(parent, text):
    lab = tk.Label(parent, text="?", fg="white", bg="#6a8fd8", font=("", 8, "bold"), width=2, cursor="question_arrow")
    Tooltip(lab, text)
    return lab


class EasyPanel(ttk.Frame):
    def __init__(self, parent, tab, app):
        super().__init__(parent)
        self.tab, self.app, self.params = tab, app, app.params
        self._quiet = False

        top = ttk.Frame(self)
        top.pack(fill="x", padx=6, pady=(4, 2))
        ttk.Label(top, text="おまかせで始める:").pack(side="left")
        self.presets = [p for p in load_presets() if p["channel"] == tab.channel]
        self.preset = ttk.Combobox(top, state="readonly", width=34,
                                   values=[f"[{p['group']}] {p['name']}" for p in self.presets])
        self.preset.pack(side="left", padx=4)
        self.preset.bind("<<ComboboxSelected>>",
                         lambda e: self.preset_desc.configure(text=self.presets[self.preset.current()]["desc"]))
        ttk.Button(top, text="この音にする", command=self.apply_preset).pack(side="left")
        self.preset_desc = ttk.Label(top, foreground="#666")
        self.preset_desc.pack(side="left", padx=8)
        if not self.presets:
            self.preset.configure(values=["(このチャンネル用はまだありません)"])

        canvas = tk.Canvas(self, highlightthickness=0)
        sb = ttk.Scrollbar(self, orient="vertical", command=canvas.yview)
        inner = ttk.Frame(canvas)
        inner.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.create_window((0, 0), window=inner, anchor="nw")
        canvas.configure(yscrollcommand=sb.set)
        canvas.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")
        canvas.bind("<Enter>", lambda e: app.set_scroll_target(canvas))
        inner.bind("<Enter>", lambda e: app.set_scroll_target(canvas))

        self.rows = []      # (control, row_widgets, updater)
        groups = groups_for(tab.channel, self.params)
        for gi, g in enumerate(groups):
            head = ttk.Frame(inner)
            ttk.Label(head, text=g.title, font=("", 10, "bold")).pack(side="left")
            help_mark(head, g.help).pack(side="left", padx=4)
            lf = ttk.LabelFrame(inner, labelwidget=head, padding=(8, 2))
            lf.grid(row=gi // 2, column=gi % 2, sticky="nwe", padx=6, pady=4)
            for ri, c in enumerate(g.controls):
                self._build_control(lf, ri, c)
        inner.columnconfigure(0, weight=1)
        inner.columnconfigure(1, weight=1)

    # ---------- 部品 ----------
    def _build_control(self, parent, row, c):
        name = ttk.Label(parent, text=c.label, width=24)
        mark = help_mark(parent, c.help)
        cell = ttk.Frame(parent)
        name.grid(row=row, column=0, sticky="w")
        mark.grid(row=row, column=1, padx=(0, 6))
        cell.grid(row=row, column=2, sticky="w", pady=1)
        widgets = (name, mark, cell)

        if c.kind == "toggle":
            var = tk.BooleanVar()
            ttk.Checkbutton(cell, text="オン", variable=var,
                            command=lambda: self._change(c.set(self.tab.values(), var.get()))).pack(side="left")
            upd = lambda v: var.set(bool(c.get(v)))
        elif c.kind == "choice":
            opts = choices_of(c, self.params)
            if len(opts) <= 4:
                var = tk.IntVar()
                for i, (label, _) in enumerate(opts):
                    ttk.Radiobutton(cell, text=label, value=i, variable=var,
                                    command=lambda: self._change({c.cc: opts[var.get()][1]})).pack(side="left")
                upd = lambda v: var.set(current_choice(c, self.params, v.get(c.cc, 0)))
            else:
                cb = ttk.Combobox(cell, values=[o[0] for o in opts], state="readonly", width=16)
                cb.pack(side="left")
                cb.bind("<<ComboboxSelected>>", lambda e: self._change({c.cc: opts[cb.current()][1]}))
                upd = lambda v: cb.current(current_choice(c, self.params, v.get(c.cc, 0)))
        elif c.kind == "steps":
            p = self.params[c.cc]
            labels = p.step_labels()
            if all(s.isdigit() for s in labels):          # 数字だけの段階は「14 / 15」のように上限も見せる
                labels = [f"{s} / {labels[-1]}" for s in labels]
            text = ttk.Label(cell, width=8)
            sc = tk.Scale(cell, from_=0, to=len(labels) - 1, orient="horizontal", length=180, showvalue=False)
            sc.configure(command=lambda s: self._scale(c, sc, int(float(s)), p.step_value(int(float(s))),
                                                       text, labels[int(float(s))]))
            sc.pack(side="left")
            text.pack(side="left", padx=4)
            upd = lambda v: self._set_scale(sc, p.step_index(v.get(c.cc, 0)), text, labels[p.step_index(v.get(c.cc, 0))])
        else:   # slider
            ttk.Label(cell, text=c.left, foreground="#666", width=8, anchor="e").pack(side="left")
            text = ttk.Label(cell, width=4)
            sc = tk.Scale(cell, from_=c.lo, to=c.hi, orient="horizontal", length=180, showvalue=False)
            sc.configure(command=lambda s: self._scale(c, sc, int(float(s)), int(float(s)), text, str(int(float(s)))))
            sc.pack(side="left")
            ttk.Label(cell, text=c.right, foreground="#666").pack(side="left")
            text.pack(side="left", padx=4)
            upd = lambda v: self._set_scale(sc, min(max(v.get(c.cc, 0), c.lo), c.hi), text, str(v.get(c.cc, 0)))
        self.rows.append((c, widgets, upd))

    def _set_scale(self, sc, pos, text, label):
        sc._prog = pos          # 表示合わせで動かした位置(この位置への command は送らない)
        sc.set(pos)
        text.configure(text=label)

    def _scale(self, c, sc, pos, value, text, label):
        # tk.Scale は set() のあとにも遅れて command を呼ぶ。表示合わせで動かした位置なら送らない
        # (段階の途中の値や、範囲外の値を勝手に丸めて送らないため)
        if getattr(sc, "_prog", None) == pos:
            return
        sc._prog = None
        text.configure(text=label)
        if not self._quiet and self.tab.values().get(c.cc) != value:
            self._change({c.cc: value})

    def _change(self, updates):
        if self._quiet:
            return
        self.tab.set_values(updates)
        self.refresh()

    # ---------- 表示 ----------
    def refresh(self):
        v = self.tab.values()
        self._quiet = True
        try:
            for c, widgets, upd in self.rows:
                upd(v)
                show = c.show(v)
                for w in widgets:
                    (w.grid if show else w.grid_remove)()
        finally:
            self.after_idle(self._unquiet)

    def _unquiet(self):
        self._quiet = False

    def apply_preset(self):
        i = self.preset.current()
        if i < 0 or not self.presets:
            return
        p = self.presets[i]
        self.app.apply_patch(Patch(id=p["id"], name=p["name"], channel=p["channel"], cc=p["cc"],
                                   notes=p["desc"]))
