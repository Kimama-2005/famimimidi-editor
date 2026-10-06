"""カートリッジ関連の画面: 書き込みダイアログ、確認ダイアログ、対応表ウィンドウ。

書き込み(CC#45/50/51)は必ず ConfirmDialog を通る。カートリッジは読み出せないので、
結果は CartState(user_data/cartridge.json)に記録する。
"""
import time
import tkinter as tk
from tkinter import messagebox, ttk

from .cartridge import (MACROS, MAX_CCS, PCS, RESERVED, WriteJob, macro_candidates,
                        plan_assign, plan_assign_many, plan_record, plan_text)


def _combo_index(values, prefix):
    for i, v in enumerate(values):
        if v.startswith(prefix):
            return i
    return 0


class ConfirmDialog(tk.Toplevel):
    """送信内容をすべて見せ、「取り消せない」ことへの同意がないと実行できない"""

    def __init__(self, parent, title, summary, warnings, steps):
        super().__init__(parent)
        self.title(title)
        self.transient(parent)
        self.ok = False
        f = ttk.Frame(self, padding=10)
        f.pack(fill="both", expand=True)
        ttk.Label(f, text="カートリッジに書き込みます。書き込んだ内容は取り消せません。",
                  foreground="#a00", font=("", 11, "bold")).pack(anchor="w")
        secs = sum(s.wait_ms for s in steps) / 1000
        ttk.Label(f, foreground="#a00",
                  text=f"書き込み中(約{secs:.0f}秒)は、ファミコンの電源を切ったりケーブルを抜いたりしないでください。"
                  ).pack(anchor="w")
        ttk.Label(f, text=summary, justify="left").pack(anchor="w", pady=(6, 0))
        for w in warnings:
            ttk.Label(f, text="⚠ " + w, foreground="#a60", justify="left", wraplength=620).pack(anchor="w")
        ttk.Label(f, text="送信する内容(音源ch1で送ります。送信中はほかの送信・スルーを止めます):").pack(anchor="w", pady=(8, 0))
        txt = tk.Text(f, width=80, height=min(24, len(steps) + 2), font=("MS Gothic", 10))
        txt.insert("1.0", plan_text(steps))
        txt.configure(state="disabled")
        txt.pack(fill="both", expand=True)
        self.agree = tk.BooleanVar()
        ttk.Checkbutton(f, text="取り消せないことを理解しました", variable=self.agree,
                        command=self._toggle).pack(anchor="w", pady=6)
        b = ttk.Frame(f)
        b.pack(anchor="e")
        self.go = ttk.Button(b, text="書き込む", command=self._ok, state="disabled")
        self.go.pack(side="left", padx=4)
        ttk.Button(b, text="やめる", command=self.destroy).pack(side="left")
        self.grab_set()
        self.wait_window()

    def _toggle(self):
        self.go.configure(state="normal" if self.agree.get() else "disabled")

    def _ok(self):
        self.ok = True
        self.destroy()


class WritingWindow(tk.Toplevel):
    """書き込み中に出し続ける警告。書き込みが終わるまで閉じられない"""

    def __init__(self, root, total_ms):
        super().__init__(root)
        self.title("書き込み中")
        self.transient(root)
        self.resizable(False, False)
        self.protocol("WM_DELETE_WINDOW", lambda: None)   # × で閉じさせない
        self.total = total_ms / 1000
        self.start = time.monotonic()
        f = tk.Frame(self, bg="#fff3f3", padx=24, pady=18)
        f.pack(fill="both", expand=True)
        tk.Label(f, text="⚠ カートリッジに書き込み中です", bg="#fff3f3", fg="#c00",
                 font=("", 16, "bold")).pack(anchor="w")
        tk.Label(f, bg="#fff3f3", font=("", 12), justify="left",
                 text="終わるまで、次のことをしないでください。\n"
                      "  ・ファミコンの電源を切る/リセットボタンを押す\n"
                      "  ・USBケーブルやMIDIケーブルを抜く\n"
                      "  ・このソフトを閉じる").pack(anchor="w", pady=(8, 10))
        self.bar = ttk.Progressbar(f, length=420, maximum=max(self.total, 0.1))
        self.bar.pack(anchor="w")
        self.status = tk.Label(f, bg="#fff3f3", font=("", 10), fg="#333")
        self.status.pack(anchor="w", pady=(6, 0))
        self.step = tk.Label(f, bg="#fff3f3", font=("", 9), fg="#666")
        self.step.pack(anchor="w")
        self.update_idletasks()
        x = root.winfo_rootx() + (root.winfo_width() - self.winfo_width()) // 2
        y = root.winfo_rooty() + (root.winfo_height() - self.winfo_height()) // 3
        self.geometry(f"+{max(x, 0)}+{max(y, 0)}")
        self.grab_set()
        self._tick()

    def _tick(self):
        if not self.winfo_exists():
            return
        t = min(time.monotonic() - self.start, self.total)
        self.bar["value"] = t
        self.status.configure(text=f"あと約 {max(self.total - t, 0):.0f} 秒")
        self.after(200, self._tick)

    def set_step(self, text):
        if self.winfo_exists():
            self.step.configure(text=text)

    def close(self):
        self.grab_release()
        self.destroy()


def run_write(app, steps, on_success, m, pc, startup_ch, done_message, on_failure=None):
    """書き込みジョブを実行し、終わったら対応表を更新する(失敗時は「不明」にする)。
    on_failure(st, error, recorded) を渡すと、失敗時の対応表の更新をそれに任せる"""
    if on_failure is None:
        def on_failure(st, error, recorded):
            st.failed(m, pc, startup_ch, recorded, error)
    if not app.engine.output_name:
        messagebox.showerror("書き込み", "出力ポートに接続していません。")
        return
    app.set_busy(True)
    warn = WritingWindow(app.root, sum(s.wait_ms for s in steps))

    def progress(i, n, text):
        app.root.after(0, lambda: warn.set_step(f"{i}/{n}  {text}"))

    def done(ok, error, recorded):
        def ui():
            warn.close()
            st = app.cart
            if ok:
                on_success(st)
            else:
                on_failure(st, error, recorded)
            st.save()
            app.set_busy(False)
            app.refresh_cart_views()
            if ok:
                app.log.note("書き込み完了。対応表を更新しました")
                messagebox.showinfo("書き込み完了", done_message)
            else:
                app.log.note(f"書き込み失敗: {error}")
                messagebox.showerror("書き込み失敗",
                                     f"{error}\n\n影響したかもしれない番号は、対応表で「不明」にしました。")
        app.root.after(0, ui)

    WriteJob(app.engine, steps, done, progress).start()


def verify_message(pc, startup_ch):
    lines = ["確認のしかた:", "1. ファミコンの電源を入れ直す(記録中に送ったCCが生で残っているため)"]
    if pc:
        lines.append(f"2. カートリッジ対応表の「PCを送る」で PC{pc} を送って弾く(KROSS2 なら PC{pc})")
    if startup_ch:
        lines.append(f"{'3' if pc else '2'}. 電源を入れた直後の ch{startup_ch} がその音色になっているか弾いて確かめる")
    return "\n".join(lines)


class WriteDialog(tk.Toplevel):
    """音色 → マクロに記録(+PC/電源ONに割り当て)"""

    def __init__(self, app, patch):
        super().__init__(app.root)
        self.app, self.patch = app, patch
        self.title(f"カートリッジに書き込む: {patch.name}")
        self.transient(app.root)
        st = app.cart
        cand, same = macro_candidates(patch.cc, app.params)
        self.items = cand      # [[cc, v]] 並べ替え対象(先頭10個を記録)

        f = ttk.Frame(self, padding=10)
        f.pack(fill="both", expand=True)
        ttk.Label(f, text=f"音色: {patch.name}(ch{patch.channel}用)", font=("", 11, "bold")).grid(
            row=0, column=0, columnspan=3, sticky="w")
        ttk.Label(f, text=f"マクロには先頭 {MAX_CCS} 個の CC だけが記録されます。"
                          "音色ごとに差の大きいものを上に並べてください。", foreground="#666").grid(
            row=1, column=0, columnspan=3, sticky="w")
        self.tree = ttk.Treeview(f, columns=("no", "cc", "name", "val", "st"), show="headings", height=14)
        for c, t, w in [("no", "順", 36), ("cc", "CC", 50), ("name", "名前", 190), ("val", "値", 44), ("st", "", 150)]:
            self.tree.heading(c, text=t)
            self.tree.column(c, width=w, anchor="w")
        self.tree.grid(row=2, column=0, rowspan=4, sticky="nsew", pady=4)
        bb = ttk.Frame(f)
        bb.grid(row=2, column=1, sticky="n", padx=4)
        ttk.Button(bb, text="↑ 上へ", command=lambda: self.move(-1)).pack(fill="x")
        ttk.Button(bb, text="↓ 下へ", command=lambda: self.move(1)).pack(fill="x", pady=2)
        ttk.Button(bb, text="外す", command=self.remove).pack(fill="x", pady=(10, 0))
        if same:
            ttk.Label(f, foreground="#666", wraplength=460, justify="left",
                      text="既定値と同じなので外したCC: " + ", ".join(f"#{c}={v}" for c, v in same)).grid(
                row=6, column=0, columnspan=2, sticky="w")

        opt = ttk.LabelFrame(f, text="書き込み先", padding=6)
        opt.grid(row=2, column=2, rowspan=4, sticky="nsew", padx=(10, 0))
        ttk.Label(opt, text="マクロ番号(1〜40)").pack(anchor="w")
        free = st.free_macros()
        order = free + [m for m in MACROS if m not in free]
        self.macro_values = [st.macro_text(m) + ("  ← 空き" if m in free else "") for m in order]
        self.macro_nums = order
        self.macro = ttk.Combobox(opt, values=self.macro_values, state="readonly", width=52)
        self.macro.current(0)
        self.macro.pack(anchor="w", pady=(0, 8))

        self.use_pc = tk.BooleanVar(value=True)
        ttk.Checkbutton(opt, text="PC に割り当てる(KROSS2 などの音色切り替えで呼び出せる)",
                        variable=self.use_pc).pack(anchor="w")
        self.pc_values = [st.pc_text(pc) for pc in PCS]
        self.pc = ttk.Combobox(opt, values=self.pc_values, state="readonly", width=52)
        fp = st.free_pcs()
        self.pc.current(PCS.index(fp[0]) if fp else 0)
        self.pc.pack(anchor="w", pady=(0, 8))

        self.use_startup = tk.BooleanVar(value=False)
        ttk.Checkbutton(opt, text="電源ONマクロにする(電源を入れた直後の音色)",
                        variable=self.use_startup).pack(anchor="w")
        row = ttk.Frame(opt)
        row.pack(anchor="w")
        ttk.Label(row, text="ch").pack(side="left")
        self.startup_ch = ttk.Combobox(row, values=[str(c) for c in range(1, 6)], state="readonly", width=4)
        self.startup_ch.set(str(patch.channel))
        self.startup_ch.pack(side="left")

        ttk.Label(opt, foreground="#666", wraplength=380, justify="left",
                  text="マクロはチャンネルを記録しません。PCを受けたchに効きます(docs/03 F20)。"
                       "記録は音源ch1で行うので、書き込み中は ch1 の音も変わります。").pack(anchor="w", pady=(10, 0))

        b = ttk.Frame(f)
        b.grid(row=7, column=0, columnspan=3, sticky="e", pady=(8, 0))
        ttk.Button(b, text="内容を確認して書き込む…", command=self.confirm).pack(side="left", padx=4)
        ttk.Button(b, text="閉じる", command=self.destroy).pack(side="left")
        f.columnconfigure(0, weight=1)
        self.refresh()

    def refresh(self, select=None):
        self.tree.delete(*self.tree.get_children())
        for i, (c, v) in enumerate(self.items):
            name = self.app.params[c].name_ja if c in self.app.params else "?"
            st = "記録する" if i < MAX_CCS else "入らない(11個目以降)"
            self.tree.insert("", "end", iid=str(i), values=(i + 1, f"#{c}", name, v, st),
                             tags=("in" if i < MAX_CCS else "out",))
        self.tree.tag_configure("out", foreground="#999")
        if select is not None:
            self.tree.selection_set(str(select))

    def _sel(self):
        s = self.tree.selection()
        return int(s[0]) if s else None

    def move(self, d):
        i = self._sel()
        if i is None or not 0 <= i + d < len(self.items):
            return
        self.items[i], self.items[i + d] = self.items[i + d], self.items[i]
        self.refresh(i + d)

    def remove(self):
        i = self._sel()
        if i is not None:
            del self.items[i]
            self.refresh()

    def confirm(self):
        st = self.app.cart
        ccs = self.items[:MAX_CCS]
        if not ccs:
            messagebox.showwarning("書き込み", "記録する CC がありません。", parent=self)
            return
        m = self.macro_nums[self.macro.current()]
        pc = PCS[self.pc.current()] if self.use_pc.get() else None
        sch = int(self.startup_ch.get()) if self.use_startup.get() else None
        warnings = []
        if len(self.items) > MAX_CCS:
            dropped = ", ".join(f"#{c}" for c, _ in self.items[MAX_CCS:])
            warnings.append(f"{len(self.items) - MAX_CCS} 個の CC は入りません: {dropped}")
        if m in RESERVED:
            warnings.append(f"マクロ{m} はテスト用に予約している番号です({RESERVED[m]})")
        pcs, chs = st.users(m)
        others = [p for p in pcs if p != pc]
        if others or chs:
            warnings.append(f"マクロ{m} は {'PC' + ','.join(map(str, others)) if others else ''}"
                            f"{' 電源ON ch' + ','.join(map(str, chs)) if chs else ''} でも使われています。"
                            "それらの音もすべて変わります")
        if pc and st.pc_map.get(pc) not in (19, None):
            warnings.append(f"PC{pc} の今の割り当て(マクロ{st.pc_map[pc]} {st.slot(st.pc_map[pc]).label})を上書きします")
        if sch and st.startup.get(sch) is not None:
            warnings.append(f"ch{sch} の電源ONマクロ(今はマクロ{st.startup[sch]})を上書きします")
        steps = plan_record(m, ccs, self.app.engine.midi_ch0(1), pc, sch)
        summary = (f"マクロ{m} ← {self.patch.name}(CC {len(ccs)}個)\n"
                   f"今のマクロ{m}: {st.slot(m).label}\n"
                   + (f"PC{pc}(送信値{pc - 1})→ マクロ{m}\n" if pc else "")
                   + (f"ch{sch} の電源ONマクロ → マクロ{m}\n" if sch else ""))
        if not ConfirmDialog(self, "書き込みの確認", summary, warnings, steps).ok:
            return
        self.destroy()
        patch = self.patch
        self.app.log.note(f"書き込み: マクロ{m} ← {patch.name} / PC{pc} / 電源ON ch{sch}")
        run_write(self.app, steps,
                  lambda st: st.record_done(m, ccs, patch.name, patch.id, pc, sch),
                  m, pc, sch, f"マクロ{m} に「{patch.name}」を書き込みました。\n\n" + verify_message(pc, sch))


class BulkAssignDialog(tk.Toplevel):
    """複数の PC をまとめて割り当てる。「PCを選ぶ → マクロを選ぶ → 予定に追加」を繰り返し、確認は1回"""

    def __init__(self, win, preselect=()):
        super().__init__(win)
        self.win, self.app = win, win.app
        self.title("PCをまとめて割り当てる")
        self.transient(win)
        st = self.app.cart
        self.plan = {}      # pc -> m
        f = ttk.Frame(self, padding=10)
        f.pack(fill="both", expand=True)
        ttk.Label(f, text="① 左で PC を選ぶ(Ctrl / Shift で複数)② マクロを選ぶ ③「予定に追加」。"
                          "何組でも追加でき、最後にまとめて1回だけ確認します。", foreground="#666").grid(
            row=0, column=0, columnspan=3, sticky="w")
        self.pcs = tk.Listbox(f, selectmode="extended", width=58, height=22, exportselection=False)
        for pc in PCS:
            self.pcs.insert("end", st.pc_text(pc))
        for pc in preselect:
            self.pcs.selection_set(pc - PCS[0])
        self.pcs.grid(row=1, column=0, rowspan=4, sticky="nsew")
        mid = ttk.Frame(f)
        mid.grid(row=1, column=1, sticky="n", padx=8)
        ttk.Label(mid, text="マクロ").pack(anchor="w")
        self.macro = ttk.Combobox(mid, values=[st.macro_text(m) for m in MACROS], state="readonly", width=40)
        self.macro.current(MACROS.index(19))
        self.macro.pack(anchor="w")
        ttk.Button(mid, text="予定に追加 →", command=self.add).pack(fill="x", pady=(8, 2))
        ttk.Button(mid, text="← 予定から外す", command=self.remove).pack(fill="x")
        self.planbox = tk.Listbox(f, width=44, height=22, selectmode="extended")
        self.planbox.grid(row=1, column=2, rowspan=4, sticky="nsew")
        b = ttk.Frame(f)
        b.grid(row=5, column=0, columnspan=3, sticky="e", pady=(8, 0))
        self.count = ttk.Label(b)
        self.count.pack(side="left", padx=8)
        ttk.Button(b, text="内容を確認して割り当てる…", command=self.confirm).pack(side="left", padx=4)
        ttk.Button(b, text="閉じる", command=self.destroy).pack(side="left")
        self._show()

    def _show(self):
        st = self.app.cart
        self.planbox.delete(0, "end")
        self._plan_order = sorted(self.plan)
        for pc in self._plan_order:
            m = self.plan[pc]
            self.planbox.insert("end", f"PC{pc} ← マクロ{m} {st.slot(m).label}")
        self.count.configure(text=f"予定 {len(self.plan)} 件(約{len(self.plan) * 0.6 + 2:.0f}秒)")

    def add(self):
        m = MACROS[self.macro.current()]
        for i in self.pcs.curselection():
            self.plan[PCS[i]] = m
        self._show()

    def remove(self):
        for i in self.planbox.curselection():
            self.plan.pop(self._plan_order[i], None)
        self._show()

    def confirm(self):
        st = self.app.cart
        plan = dict(self.plan)
        try:
            steps = plan_assign_many(plan, self.app.engine.midi_ch0(1))
        except ValueError as e:
            messagebox.showwarning("まとめて割り当て", str(e), parent=self)
            return
        changed = [pc for pc, m in plan.items() if st.pc_map.get(pc) != m]
        summary = f"{len(plan)} 個の PC を割り当てます(対応表と違うもの {len(changed)} 個)\n"
        warnings = ["割り当てのために各マクロを一度実行するので、ch1 の音が変わります。終わったら電源を入れ直してください"]
        if not ConfirmDialog(self, "まとめて割り当ての確認", summary, warnings, steps).ok:
            return
        self.destroy()
        self.app.log.note(f"まとめて割り当て: {len(plan)} 件")
        run_write(self.app, steps, lambda st: st.assign_many_done(plan), None, None, None,
                  f"{len(plan)} 個の PC を割り当てました。\n\n電源を入れ直してから、"
                  "「PCを1つずつ試す」で確かめられます。",
                  on_failure=lambda st, error, recorded: st.assign_many_failed(plan, error))


class CartridgeWindow(tk.Toplevel):
    """対応表の表示、PC送信、既存マクロの割り当て"""

    def __init__(self, app):
        super().__init__(app.root)
        self.app = app
        self.title("カートリッジの対応表(PC側の記録)")
        self.geometry("980x720")
        f = ttk.Frame(self, padding=8)
        f.pack(fill="both", expand=True)
        ttk.Label(f, foreground="#a00", text="カートリッジの中身は読み出せません。"
                  "この表は、このソフト(と過去の実機テスト)で書いた内容の記録です。").pack(anchor="w")

        # PC を送る(書き込みではない)
        pcf = ttk.LabelFrame(f, text="PCを送る(音色の切り替え。書き込みではありません)", padding=6)
        pcf.pack(fill="x", pady=6)
        ttk.Label(pcf, text="ch").pack(side="left")
        self.send_ch = ttk.Combobox(pcf, values=[str(c) for c in range(1, 6)], state="readonly", width=4)
        self.send_ch.set("1")
        self.send_ch.pack(side="left", padx=(2, 10))
        ttk.Label(pcf, text="PC").pack(side="left")
        self.send_pc = tk.Spinbox(pcf, from_=1, to=128, width=5, command=self._pc_label)
        self.send_pc.delete(0, "end")
        self.send_pc.insert(0, "89")
        self.send_pc.pack(side="left", padx=2)
        self.send_pc.bind("<KeyRelease>", lambda e: self._pc_label())
        self.pc_label = ttk.Label(pcf, width=60)
        self.pc_label.pack(side="left", padx=6)
        ttk.Button(pcf, text="送信", command=self.send_pc_now).pack(side="left")

        # PC を1つずつ試す(書き込みではない)。音量を生で戻してから PC を送るので、
        # 「無音」= そのPCのマクロが音を消した、と判定できる(F18: 音量はPCを変えても残るため)
        ck = ttk.LabelFrame(f, text="PCを1つずつ試す(音源ch1。毎回 音量を127に戻す → PC → 1音。書き込みではありません)",
                            padding=6)
        ck.pack(fill="x", pady=(0, 6))
        self.check_pc = 89
        self.check_results = {}
        self.check_label = ttk.Label(ck, font=("", 12, "bold"), width=52)
        self.check_label.pack(side="left")
        ttk.Button(ck, text="◀", width=3, command=lambda: self._check_move(-1)).pack(side="left")
        ttk.Button(ck, text="▶", width=3, command=lambda: self._check_move(1)).pack(side="left", padx=(0, 8))
        ttk.Button(ck, text="鳴らす", command=self.check_play).pack(side="left")
        ttk.Button(ck, text="鳴った → 次", command=lambda: self.check_mark(True)).pack(side="left", padx=4)
        ttk.Button(ck, text="無音 → 次", command=lambda: self.check_mark(False)).pack(side="left")
        sumrow = ttk.Frame(f)
        sumrow.pack(fill="x")
        self.check_summary = ttk.Label(sumrow, foreground="#333", wraplength=700, justify="left")
        self.check_summary.pack(side="left", anchor="w")
        ttk.Button(sumrow, text="PCをまとめて割り当てる…",
                   command=self.open_bulk).pack(side="right")

        # 表
        tables = ttk.PanedWindow(f, orient="horizontal")
        tables.pack(fill="both", expand=True)
        mf = ttk.LabelFrame(tables, text="ユーザーマクロ 1〜40")
        self.mtree = ttk.Treeview(mf, columns=("m", "label", "n", "use", "w"), show="headings")
        for c, t, w in [("m", "番号", 40), ("label", "内容", 230), ("n", "CC数", 44), ("use", "使用先", 150), ("w", "書き込み", 90)]:
            self.mtree.heading(c, text=t)
            self.mtree.column(c, width=w, anchor="w")
        self.mtree.pack(fill="both", expand=True)
        self.mtree.bind("<<TreeviewSelect>>", lambda e: self._show_macro())
        tables.add(mf, weight=3)
        rf = ttk.Frame(tables)
        pf = ttk.LabelFrame(rf, text="PC 89〜128 の割り当て")
        pf.pack(fill="both", expand=True)
        self.ptree = ttk.Treeview(pf, columns=("pc", "m", "label"), show="headings", height=14)
        for c, t, w in [("pc", "PC(送信値)", 80), ("m", "マクロ", 50), ("label", "内容", 200)]:
            self.ptree.heading(c, text=t)
            self.ptree.column(c, width=w, anchor="w")
        self.ptree.pack(fill="both", expand=True)
        sf = ttk.LabelFrame(rf, text="電源ONマクロ(CC#50)")
        sf.pack(fill="x")
        self.startup_label = ttk.Label(sf, justify="left")
        self.startup_label.pack(anchor="w", padx=4, pady=2)
        tables.add(rf, weight=2)

        self.detail = ttk.Label(f, justify="left", foreground="#333")
        self.detail.pack(anchor="w", pady=4)

        # 既存マクロの割り当て
        af = ttk.LabelFrame(f, text="記録済みのマクロを割り当てる(マクロの中身は変えません)", padding=6)
        af.pack(fill="x")
        ttk.Label(af, text="マクロ").grid(row=0, column=0, sticky="e")
        self.a_macro = ttk.Combobox(af, state="readonly", width=48)
        self.a_macro.grid(row=0, column=1, sticky="w", padx=4)
        self.a_use_pc = tk.BooleanVar(value=True)
        ttk.Checkbutton(af, text="PC", variable=self.a_use_pc).grid(row=1, column=0, sticky="e")
        self.a_pc = ttk.Combobox(af, state="readonly", width=48)
        self.a_pc.grid(row=1, column=1, sticky="w", padx=4)
        self.a_use_startup = tk.BooleanVar(value=False)
        ttk.Checkbutton(af, text="電源ON ch", variable=self.a_use_startup).grid(row=2, column=0, sticky="e")
        self.a_ch = ttk.Combobox(af, values=[str(c) for c in range(1, 6)], state="readonly", width=4)
        self.a_ch.set("1")
        self.a_ch.grid(row=2, column=1, sticky="w", padx=4)
        ttk.Button(af, text="内容を確認して割り当てる…", command=self.assign).grid(row=0, column=2, rowspan=3, padx=10)
        self.refresh()

    # ---------- 表示 ----------
    def refresh(self):
        st = self.app.cart
        self.mtree.delete(*self.mtree.get_children())
        for m in MACROS:
            s = st.slot(m)
            pcs, chs = st.users(m)
            use = []
            if pcs:
                use.append(f"PC{pcs[0]}" if len(pcs) == 1 else f"PC {len(pcs)}枠")
            if chs:
                use.append("電源ON ch" + ",".join(map(str, chs)))
            n = "?" if s.cc is None else str(len(s.cc))
            self.mtree.insert("", "end", iid=str(m), values=(m, s.label, n, " / ".join(use), s.written[:10]))
        self.ptree.delete(*self.ptree.get_children())
        for pc in PCS:
            m = st.pc_map.get(pc)
            label = "不明" if m is None else st.slot(m).label
            self.ptree.insert("", "end", values=(f"PC{pc}({pc - 1})", "?" if m is None else m, label))
        self.startup_label.configure(text="\n".join(
            f"ch{ch}: " + ("不明/未設定" if m is None else f"マクロ{m} {st.slot(m).label}")
            for ch, m in sorted(st.startup.items())))
        self.a_macro["values"] = [st.macro_text(m) for m in MACROS]
        if self.a_macro.current() < 0:
            self.a_macro.current(0)
        cur = self.a_pc.current()
        self.a_pc["values"] = [st.pc_text(pc) for pc in PCS]
        self.a_pc.current(cur if cur >= 0 else 0)
        self._pc_label()
        self._check_show()

    def _show_macro(self):
        s = self.mtree.selection()
        if not s:
            return
        slot = self.app.cart.slot(int(s[0]))
        if slot.cc is None:
            text = "中身: 不明"
        else:
            params = self.app.params
            text = "中身: " + ", ".join(
                f"CC#{c}={v}({params[c].name_ja if c in params else '?'})" for c, v in slot.cc)
        self.detail.configure(text=f"マクロ{s[0]}  {text}" + ("" if slot.certain else "(推定)"))

    def _pc_label(self):
        try:
            pc = int(self.send_pc.get())
        except ValueError:
            self.pc_label.configure(text="")
            return
        if 89 <= pc <= 128:
            self.pc_label.configure(text=self.app.cart.pc_text(pc))
        elif 1 <= pc <= 4:
            self.pc_label.configure(text=f"PC{pc}(送信値{pc - 1}): デューティ比(ch1,2)")
        elif 1 <= pc <= 128:
            self.pc_label.configure(text=f"PC{pc}(送信値{pc - 1}): 工場プリセット")
        else:
            self.pc_label.configure(text="1〜128")

    # ---------- 操作 ----------
    def send_pc_now(self):
        try:
            pc = int(self.send_pc.get())
        except ValueError:
            return
        if not 1 <= pc <= 128:
            return
        ch = int(self.send_ch.get())
        self.app.engine.send(bytes([0xC0 | self.app.engine.midi_ch0(ch), pc - 1]), "PC送信")

    def open_bulk(self):
        if self.app.engine.writing:
            return
        silent = [pc for pc, ok in self.check_results.items() if not ok]
        if not silent:   # チェックしていなければ、対応表で無音マクロ(20)・不明になっている PC
            silent = [pc for pc in PCS if self.app.cart.pc_map.get(pc) in (20, None)]
        BulkAssignDialog(self, preselect=silent)

    # ---------- PC を1つずつ試す ----------
    def _check_show(self):
        pc = self.check_pc
        mark = {True: " → 鳴った", False: " → 無音"}.get(self.check_results.get(pc), "")
        self.check_label.configure(text=self.app.cart.pc_text(pc) + mark)
        silent = [p for p, ok in sorted(self.check_results.items()) if not ok]
        self.check_summary.configure(
            text=f"試した数 {len(self.check_results)}/40 ・ 無音だったPC: {', '.join(map(str, silent)) or 'なし'}")

    def _check_move(self, d):
        self.check_pc = min(max(self.check_pc + d, 89), 128)
        self._check_show()

    def check_play(self):
        eng = self.app.engine
        c0 = eng.midi_ch0(1)
        for n, v in ((7, 127), (11, 127)):
            eng.send(bytes([0xB0 | c0, n, v]), "PCチェック")
        eng.send(bytes([0xC0 | c0, self.check_pc - 1]), "PCチェック")
        # マクロの実行が終わるのを少し待ってから鳴らす
        self.after(150, lambda: eng.send(bytes([0x90 | c0, 72, 100]), "PCチェック"))
        self.after(650, lambda: eng.send(bytes([0x80 | c0, 72, 0]), "PCチェック"))

    def check_mark(self, ok):
        pc = self.check_pc
        self.check_results[pc] = ok
        m = self.app.cart.pc_map.get(pc)
        self.app.log.note(f"PCチェック: PC{pc} = {'鳴った' if ok else '無音'}(対応表ではマクロ{m})")
        if pc < 128:
            self.check_pc += 1
            self._check_show()
            self.check_play()
        else:
            self._check_show()

    def assign(self):
        st = self.app.cart
        m = MACROS[self.a_macro.current()]
        pc = PCS[self.a_pc.current()] if self.a_use_pc.get() else None
        sch = int(self.a_ch.get()) if self.a_use_startup.get() else None
        try:
            steps = plan_assign(m, self.app.engine.midi_ch0(1), pc, sch)
        except ValueError as e:
            messagebox.showwarning("割り当て", str(e), parent=self)
            return
        warnings = []
        if st.slot(m).cc is None:
            warnings.append(f"マクロ{m} の中身は不明です")
        if pc and st.pc_map.get(pc) not in (19, None):
            warnings.append(f"PC{pc} の今の割り当て(マクロ{st.pc_map[pc]})を上書きします")
        if sch and st.startup.get(sch) is not None:
            warnings.append(f"ch{sch} の電源ONマクロ(今はマクロ{st.startup[sch]})を上書きします")
        warnings.append(f"割り当てのためにマクロ{m} を一度実行するので、ch1 の音が変わります")
        summary = (f"マクロ{m}: {st.slot(m).label}\n"
                   + (f"PC{pc}(送信値{pc - 1})→ マクロ{m}\n" if pc else "")
                   + (f"ch{sch} の電源ONマクロ → マクロ{m}\n" if sch else ""))
        if not ConfirmDialog(self, "割り当ての確認", summary, warnings, steps).ok:
            return
        self.app.log.note(f"割り当て: マクロ{m} → PC{pc} / 電源ON ch{sch}")
        run_write(self.app, steps, lambda st: st.assign_done(m, pc, sch), m, pc, sch,
                  "割り当てました。\n\n" + verify_message(pc, sch))
