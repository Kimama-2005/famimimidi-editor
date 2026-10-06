"""かんたん保存: 「保存場所(40か所)」と「呼び出し番号」だけで、音色をカートリッジにしまう画面。

中身は詳細画面と同じ仕組み(マクロ記録+PC割り当て、CC#50)。
マクロ番号・10個の制限・PC の送信値は、この画面では見せずに自動で決める。
"""
import tkinter as tk
from tkinter import messagebox, ttk

from .cartridge import MAX_CCS, NEUTRAL_MACRO, PCS, plan_assign, plan_record, plan_text
from .cartridge_ui import WriteDialog, run_write
from .sets import (apply_ops, base_id, build_tidy, cc_for_single_save, compute_base, current_base,
                   full_values, sounds_on_cart, status)

INTRO = ("ふぁみみみっでぃには、音色をしまっておける「保存場所」が 40 か所あります。\n"
         "しまった音色は、鍵盤(KROSS2 など)やこのソフトから、その場所の「呼び出し番号」を送ると呼び出せます。"
         "電源を切っても消えません。")


def place_of(pc):
    return pc - PCS[0] + 1


class SimpleConfirm(tk.Toplevel):
    """やさしい言葉の確認。「元に戻せない」ことへのチェックがないと保存できない"""

    def __init__(self, parent, title, lines, steps, ok_text):
        super().__init__(parent)
        self.title(title)
        self.transient(parent)
        self.resizable(False, False)
        self.ok = False
        self.steps = steps
        f = ttk.Frame(self, padding=14)
        f.pack(fill="both", expand=True)
        for i, line in enumerate(lines):
            ttk.Label(f, text=line, wraplength=460, justify="left",
                      font=("", 11, "bold") if i == 0 else ("", 10),
                      foreground="#a60" if line.startswith("※") else "").pack(anchor="w", pady=1)
        secs = sum(s.wait_ms for s in steps) / 1000
        ttk.Label(f, foreground="#a00", wraplength=460, justify="left",
                  text=f"保存には約{secs:.0f}秒かかります。その間はファミコンの電源を切らないでください。").pack(
            anchor="w", pady=(8, 0))
        self.agree = tk.BooleanVar()
        ttk.Checkbutton(f, text="元に戻せないことを分かったうえで進める", variable=self.agree,
                        command=lambda: self.go.configure(state="normal" if self.agree.get() else "disabled")
                        ).pack(anchor="w", pady=8)
        b = ttk.Frame(f)
        b.pack(fill="x")
        ttk.Button(b, text="くわしい送信内容", command=self.show_detail).pack(side="left")
        ttk.Button(b, text="やめる", command=self.destroy).pack(side="right")
        self.go = ttk.Button(b, text=ok_text, command=self._ok, state="disabled")
        self.go.pack(side="right", padx=4)
        self.grab_set()
        self.wait_window()

    def show_detail(self):
        w = tk.Toplevel(self)
        w.title("くわしい送信内容")
        t = tk.Text(w, width=78, height=min(26, len(self.steps) + 2), font=("MS Gothic", 10))
        t.insert("1.0", plan_text(self.steps))
        t.configure(state="disabled")
        t.pack(fill="both", expand=True)

    def _ok(self):
        self.ok = True
        self.destroy()


class SimpleCartWindow(tk.Toplevel):
    def __init__(self, app, patch=None):
        super().__init__(app.root)
        self.app = app
        self.title("カートリッジに音色を保存(かんたん)")
        self.geometry("1000x900")
        f = ttk.Frame(self, padding=10)
        f.pack(fill="both", expand=True)
        ttk.Label(f, text=INTRO, wraplength=960, justify="left").pack(anchor="w", pady=(0, 8))

        body = ttk.Frame(f)
        body.pack(fill="both", expand=True)
        self.tree = ttk.Treeview(body, columns=("place", "num", "name"), show="headings", selectmode="browse")
        for c, t, w in [("place", "保存場所", 70), ("num", "呼び出し番号", 90), ("name", "入っている音色", 300)]:
            self.tree.heading(c, text=t)
            self.tree.column(c, width=w, anchor="w")
        self.tree.pack(side="left", fill="both", expand=True)
        sb = ttk.Scrollbar(body, orient="vertical", command=self.tree.yview)
        sb.pack(side="left", fill="y")
        self.tree.configure(yscrollcommand=sb.set)
        self.tree.bind("<<TreeviewSelect>>", lambda e: self._show())

        side = ttk.Frame(body, padding=(12, 0, 0, 0))
        side.pack(side="left", fill="y")
        self.head = ttk.Label(side, font=("", 13, "bold"))
        self.head.pack(anchor="w")
        self.content = ttk.Label(side, wraplength=380, justify="left")
        self.content.pack(anchor="w", pady=(2, 10))

        tf = ttk.LabelFrame(side, text="試しに鳴らす", padding=6)
        tf.pack(fill="x")
        ttk.Label(tf, text="鳴らすチャンネル").pack(side="left")
        self.try_ch = ttk.Combobox(tf, values=[str(c) for c in range(1, 6)], state="readonly", width=3)
        self.try_ch.set("1")
        self.try_ch.pack(side="left", padx=4)
        ttk.Button(tf, text="♪ 呼び出して鳴らす(ド・ミ・ソ → 和音)", command=self.try_play).pack(side="left", padx=6)

        pf = ttk.LabelFrame(side, text="この場所に音色を入れる", padding=6)
        pf.pack(fill="x", pady=8)
        self.patches = self.app.library.lib.patches
        self.patch_combo = ttk.Combobox(pf, state="readonly", width=44,
                                        values=[f"{p.name}(ch{p.channel}用)" for p in self.patches])
        self.patch_combo.pack(anchor="w")
        if patch is not None and patch in self.patches:
            self.patch_combo.current(self.patches.index(patch))
        b = ttk.Frame(pf)
        b.pack(fill="x", pady=(6, 0))
        ttk.Button(b, text="ここに入れる…", command=self.save_here).pack(side="left")
        ttk.Button(b, text="くわしく設定して入れる…", command=self.save_advanced).pack(side="left", padx=6)
        ttk.Button(side, text="この場所を空にする…", command=self.clear_here).pack(anchor="w")

        sf = ttk.LabelFrame(f, text="電源を入れたときの音色(チャンネルごと)", padding=6)
        sf.pack(fill="x", pady=(10, 0))
        self.startup_rows = {}
        for ch in range(1, 6):
            ttk.Label(sf, text=f"ch{ch}").grid(row=ch, column=0, sticky="w")
            cur = ttk.Label(sf, width=44)
            cur.grid(row=ch, column=1, sticky="w", padx=4)
            combo = ttk.Combobox(sf, state="readonly", width=40)
            combo.grid(row=ch, column=2, padx=4, pady=1)
            ttk.Button(sf, text="これにする…", command=lambda c=ch: self.set_startup(c)).grid(row=ch, column=3)
            ttk.Button(sf, text="ふつうに戻す…", command=lambda c=ch: self.reset_startup(c)).grid(row=ch, column=4, padx=4)
            self.startup_rows[ch] = (cur, combo)

        tf2 = ttk.LabelFrame(f, text="音色の切り替えを整える(共通の土台と、切り替えの後始末)", padding=6)
        tf2.pack(fill="x", pady=(8, 0))
        ttk.Label(tf2, foreground="#666", wraplength=940, justify="left",
                  text="1か所に入るのは10項目までなので、呼び出したときに前の音色の設定が残ることがあります。"
                       "「整える」を押すと、同じチャンネルの音色どうしで切り替えても設定が残らないように保存し直し、"
                       "どの音色にも共通の設定は「土台」として電源を入れたときに自動で入るようにします。").grid(
            row=0, column=0, columnspan=4, sticky="w")
        self.tidy_rows = {}
        for ch in range(1, 6):
            ttk.Label(tf2, text=f"ch{ch}").grid(row=ch, column=0, sticky="w")
            lab = ttk.Label(tf2, width=78)
            lab.grid(row=ch, column=1, sticky="w", padx=4)
            ttk.Button(tf2, text="整える…", command=lambda c=ch: self.tidy(c)).grid(row=ch, column=2, pady=1)
            ttk.Button(tf2, text="土台を今だけ送る", command=lambda c=ch: self.send_base(c)).grid(row=ch, column=3, padx=4)
            self.tidy_rows[ch] = lab

        foot = ttk.Frame(f)
        foot.pack(fill="x", pady=(8, 0))
        ttk.Label(foot, foreground="#666",
                  text="保存したら、ファミコンの電源を入れ直してから「呼び出して鳴らす」で確かめてください。").pack(side="left")
        ttk.Button(foot, text="詳細な管理…", command=self.open_detail).pack(side="right")
        self.refresh()
        first = next((pc for pc in PCS if self.app.cart.pc_map.get(pc) == NEUTRAL_MACRO), PCS[0])
        self.tree.selection_set(str(first))
        self.tree.see(str(first))

    # ---------- 表示 ----------
    def name_of(self, pc):
        st = self.app.cart
        m = st.pc_map.get(pc)
        if m is None:
            return "(不明 — 呼び出して確かめてください)"
        if m == NEUTRAL_MACRO:
            return "(空き)"
        return st.slot(m).label

    def patch_of(self, pc):
        m = self.app.cart.pc_map.get(pc)
        pid = self.app.cart.slot(m).patch_id if m is not None else ""
        return self.app.library.lib.get(pid) if pid else None

    def refresh(self):
        sel = self.selected()
        self.tree.delete(*self.tree.get_children())
        for pc in PCS:
            self.tree.insert("", "end", iid=str(pc), values=(f"場所 {place_of(pc)}", pc, self.name_of(pc)))
        if sel:
            self.tree.selection_set(str(sel))
        filled = [pc for pc in PCS if self.app.cart.pc_map.get(pc) not in (None, NEUTRAL_MACRO)]
        self.place_choices = filled
        values = [f"場所 {place_of(pc)}(番号 {pc}): {self.name_of(pc)}" for pc in filled]
        st = self.app.cart
        for ch, (cur, combo) in self.startup_rows.items():
            m = st.startup.get(ch)
            if m is None:
                text = "わからない(設定していない)"
            elif m == NEUTRAL_MACRO:
                text = "ふつう(何も変えない)"
            elif st.slot(m).patch_id == base_id(ch):
                text = f"ch{ch} の土台(共通の設定)"
            else:
                pcs = [pc for pc in st.users(m)[0]]
                text = (f"場所 {place_of(pcs[0])}: " if pcs else "") + st.slot(m).label
            cur.configure(text=text)
            combo["values"] = values
        for ch, lab in self.tidy_rows.items():
            s = status(st, self.app.library.lib, self.app.params, ch)
            if s.count == 0:
                text, color = "このチャンネル用の音色は入っていません", "#666"
            elif s.tidy_needed:
                parts = []
                if s.to_rewrite:
                    places = "、".join(f"場所{place_of(pc)}" for pc in s.to_rewrite)
                    parts.append(f"{places} で前の音色の設定が残る可能性")
                if not s.base_ok:
                    parts.append("土台が最新ではありません")
                text, color = f"音色 {s.count} 個: " + " / ".join(parts) + " → 整えてください", "#a60"
            elif s.unavoidable:
                places = "、".join(f"場所{place_of(pc)}" for pc in s.unavoidable)
                text, color = (f"整っています(音色 {s.count} 個)。ただし {places} は10項目に入りきらない設定が"
                               "あり、切り替えで残ることがあります"), "#060"
            else:
                text, color = f"整っています(音色 {s.count} 個)", "#060"
            lab.configure(text=text, foreground=color)
        self._show()

    def selected(self):
        s = self.tree.selection() if hasattr(self, "tree") else ()
        return int(s[0]) if s else None

    def _show(self):
        pc = self.selected()
        if pc is None:
            return
        self.head.configure(text=f"場所 {place_of(pc)}(呼び出し番号 {pc})")
        self.content.configure(text=f"入っている音色: {self.name_of(pc)}")
        p = self.patch_of(pc)
        self.try_ch.set(str(p.channel if p else 1))

    # ---------- 操作 ----------
    def _busy(self):
        if self.app.engine.writing:
            messagebox.showinfo("保存中", "ほかの保存が終わるまで待ってください。", parent=self)
            return True
        if not self.app.engine.output_name:
            messagebox.showerror("未接続", "ふぁみみみっでぃに接続していません。メイン画面の「接続」を押してください。",
                                 parent=self)
            return True
        return False

    def try_play(self):
        pc = self.selected()
        if pc is None:
            return
        eng = self.app.engine
        c0 = eng.midi_ch0(int(self.try_ch.get()))
        for n, v in ((7, 127), (11, 127)):
            eng.send(bytes([0xB0 | c0, n, v]), "かんたん")
        eng.send(bytes([0xC0 | c0, pc - 1]), "かんたん")
        # ド・ミ・ソ を1音ずつ → 最後に和音(アルペジエーターが効いていれば音が高速で入れ替わる)
        for i, note in enumerate((60, 64, 67)):
            self.after(150 + i * 300, lambda n=note: eng.send(bytes([0x90 | c0, n, 100]), "かんたん"))
            self.after(400 + i * 300, lambda n=note: eng.send(bytes([0x80 | c0, n, 0]), "かんたん"))
        for note in (60, 64, 67):
            self.after(1200, lambda n=note: eng.send(bytes([0x90 | c0, n, 100]), "かんたん"))
            self.after(2400, lambda n=note: eng.send(bytes([0x80 | c0, n, 0]), "かんたん"))

    def save_here(self):
        pc = self.selected()
        i = self.patch_combo.current()
        if pc is None or i < 0:
            messagebox.showinfo("音色を入れる", "左で場所を、右で音色を選んでください。", parent=self)
            return
        if self._busy():
            return
        patch = self.patches[i]
        st = self.app.cart
        # 同じチャンネルのほかの音色から切り替えても設定が残らないように選ぶ(A)
        ccs, dropped = cc_for_single_save(st, self.app.library.lib, self.app.params, patch, pc)
        if not ccs:
            messagebox.showinfo("音色を入れる", "この音色は初期設定と同じなので、保存する内容がありません。", parent=self)
            return
        try:
            m = st.macro_for_pc(pc)
        except ValueError as e:
            messagebox.showerror("音色を入れる", str(e), parent=self)
            return
        lines = [f"場所 {place_of(pc)} に「{patch.name}」を入れます。"]
        old = self.name_of(pc)
        if old != "(空き)":
            lines.append(f"※ いま入っている「{old}」は消えます。")
        if dropped:
            lines.append(f"※ 1か所に入るのは{MAX_CCS}項目までなので、次の設定は入りません"
                         f"(切り替えたときに前の音色の値が残ることがあります): {self._names(dropped)}")
        lines.append(f"※ 保存が終わると、呼び出し番号 {pc} でこの音色になります。")
        steps = plan_record(m, ccs, self.app.engine.midi_ch0(1), pc=pc)
        if not SimpleConfirm(self, "音色を入れる", lines, steps, "保存する").ok:
            return
        self.app.log.note(f"かんたん保存: 場所{place_of(pc)}(PC{pc})← {patch.name}(マクロ{m} を使用)")
        ch = patch.channel

        def after(st):
            st.record_done(m, ccs, patch.name, patch.id, pc, None)
            self.app.root.after(100, lambda: self._suggest_tidy(ch))
        run_write(self.app, steps, after, m, pc, None,
                  f"場所 {place_of(pc)} に「{patch.name}」を保存しました。\n\n"
                  "ファミコンの電源を入れ直してから、「呼び出して鳴らす」で確かめてください。")

    def _names(self, ccs):
        return "、".join(self.app.params[c].name_ja for c in ccs if c in self.app.params)

    def _suggest_tidy(self, ch):
        s = status(self.app.cart, self.app.library.lib, self.app.params, ch)
        if s.count > 1 and s.tidy_needed:
            messagebox.showinfo("整えるのがおすすめです",
                                f"ch{ch} には音色が {s.count} 個入っています。この音色を入れたことで、"
                                "ほかの場所から切り替えたときに設定が残る可能性があります。\n\n"
                                f"画面下の「ch{ch} 整える…」を押すと、まとめて直せます。", parent=self)

    def tidy(self, ch):
        if self._busy():
            return
        st = self.app.cart
        try:
            t = build_tidy(st, self.app.library.lib, self.app.params, ch, self.app.engine.midi_ch0(1))
        except ValueError as e:
            messagebox.showerror("整える", str(e), parent=self)
            return
        if not t.steps:
            messagebox.showinfo("整える", f"ch{ch} はもう整っています。", parent=self)
            return
        lines = [f"ch{ch} の音色を整えます(保存し直す場所 {len(t.rewrites)} か所)。"]
        if t.rewrites:
            lines.append("保存し直す場所: " + "、".join(f"場所{place_of(pc)}「{self.name_of(pc)}」" for pc in t.rewrites))
        if t.base_changed:
            if t.plan.base:
                lines.append(f"土台(どの音色にも共通の設定): {self._names(t.plan.base)}")
                old = t.old_startup
                if old is not None and old != 19 and st.slot(old).patch_id != base_id(ch):
                    lines.append(f"※ 電源を入れたときの ch{ch} は「{st.slot(old).label}」から「ch{ch} の土台」に変わります。"
                                 "音色は呼び出し番号で選んでください。")
            else:
                lines.append(f"※ 共通の設定が無くなったので、電源を入れたときの ch{ch} を「ふつう」に戻します。")
        dropped = {pc: d for pc, d in t.plan.dropped.items() if d}
        for pc, d in dropped.items():
            lines.append(f"※ 場所{place_of(pc)} は{MAX_CCS}項目に入りきらないため、次の設定は切り替えで残ることがあります: "
                         f"{self._names(d)}")
        if not SimpleConfirm(self, f"ch{ch} を整える", lines, t.steps, "整える").ok:
            return
        self.app.log.note(f"ch{ch} を整える: 保存し直し {t.rewrites}、土台 {t.plan.base if t.base_changed else '変更なし'}")

        def fail(st, error, recorded):
            for name, args in t.ops:
                m, pc, sch = (args[0], args[4], args[5]) if name == "record_done" else args
                st.failed(m, pc, sch, name == "record_done", error)
        run_write(self.app, t.steps, lambda st: apply_ops(st, t.ops), None, None, None,
                  f"ch{ch} を整えました。\n\nファミコンの電源を入れ直してから、各場所を「呼び出して鳴らす」で確かめてください。",
                  on_failure=fail)

    def send_base(self, ch):
        """B1: 土台を今だけ送る(カートリッジには保存しない。電源を切ると消える)"""
        sounds = sounds_on_cart(self.app.cart, self.app.library.lib, ch)
        base = current_base(self.app.cart, ch) or compute_base(
            [full_values(p, self.app.params, ch) for p in sounds.values()], self.app.params)
        if not base:
            messagebox.showinfo("土台", f"ch{ch} には共通の土台がありません。", parent=self)
            return
        c0 = self.app.engine.midi_ch0(ch)
        for c, v in base.items():
            self.app.engine.send(bytes([0xB0 | c0, c, v]), "土台")
        self.app.log.note(f"ch{ch} の土台を送信(保存はしない): {base}")

    def save_advanced(self):
        i = self.patch_combo.current()
        if i < 0:
            messagebox.showinfo("くわしく設定", "右で音色を選んでください。", parent=self)
            return
        if not self._busy():
            WriteDialog(self.app, self.patches[i])

    def clear_here(self):
        pc = self.selected()
        if pc is None or self._busy():
            return
        if self.name_of(pc) == "(空き)":
            messagebox.showinfo("空にする", "この場所はもう空いています。", parent=self)
            return
        steps = plan_assign(NEUTRAL_MACRO, self.app.engine.midi_ch0(1), pc=pc)
        lines = [f"場所 {place_of(pc)} を空にします。",
                 f"※ いま入っている「{self.name_of(pc)}」は、この場所からは呼び出せなくなります。"]
        if not SimpleConfirm(self, "空にする", lines, steps, "空にする").ok:
            return
        run_write(self.app, steps, lambda st: st.assign_done(NEUTRAL_MACRO, pc, None),
                  NEUTRAL_MACRO, pc, None, f"場所 {place_of(pc)} を空にしました。")

    def set_startup(self, ch):
        cur, combo = self.startup_rows[ch]
        i = combo.current()
        if i < 0:
            messagebox.showinfo("電源を入れたときの音色", "右のリストから、音色の入った場所を選んでください。", parent=self)
            return
        if self._busy():
            return
        pc = self.place_choices[i]
        m = self.app.cart.pc_map[pc]
        steps = plan_assign(m, self.app.engine.midi_ch0(1), startup_ch=ch)
        lines = [f"電源を入れたときの ch{ch} の音色を、場所 {place_of(pc)}「{self.name_of(pc)}」にします。",
                 "※ 設定の途中で、ch1 の音が一時的にこの音色に変わります。"]
        if not SimpleConfirm(self, "電源を入れたときの音色", lines, steps, "設定する").ok:
            return
        run_write(self.app, steps, lambda st: st.assign_done(m, None, ch), m, None, ch,
                  f"電源を入れたときの ch{ch} の音色を設定しました。\n電源を入れ直すと確かめられます。")

    def reset_startup(self, ch):
        if self._busy():
            return
        steps = plan_assign(NEUTRAL_MACRO, self.app.engine.midi_ch0(1), startup_ch=ch)
        lines = [f"電源を入れたときの ch{ch} の音色を、ふつう(何も変えない)に戻します。"]
        if not SimpleConfirm(self, "電源を入れたときの音色", lines, steps, "戻す").ok:
            return
        run_write(self.app, steps, lambda st: st.assign_done(NEUTRAL_MACRO, None, ch), NEUTRAL_MACRO, None, ch,
                  f"電源を入れたときの ch{ch} の音色を、ふつうに戻しました。")

    def open_detail(self):
        self.app.open_cart_window()
