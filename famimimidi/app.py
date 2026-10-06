"""ふぁみみみっでぃ 音色エディタ — tkinter 版の画面(フェーズC の新しい画面ができるまでの標準。以後は予備)。

接続・MIDIスルー・パラメーター編集・試聴・ライブラリ・カートリッジ・送信ログ。
"""
import os
import tkinter as tk
from tkinter import messagebox, ttk

from . import winmm
from .audition import AuditionPanel
from .easy_ui import EasyPanel
from .cartridge import CartState
from .cartridge_ui import CartridgeWindow
from .simple_ui import SimpleCartWindow
from .wave_ui import WaveWindow
from .engine import MidiEngine, SendLog
from .library_ui import LibraryPanel
from .settings import load_settings, save_settings
from .spec import CHANNEL_NAMES, editable_params, load_spec

NO_INPUT = "(使わない)"
OFFSETS = [(0, "ch1〜5(通常起動)"), (5, "ch6〜10(Bを押しながら電源ON)"), (10, "ch11〜15(A+Bを押しながら電源ON)")]
LOG_MAX_LINES = 5000


class ParamRow:
    """1つの CC の行。値を変えると engine.set_cc で(間引いて)送る"""

    def __init__(self, parent, row, param, channel, engine):
        self.p, self.ch, self.engine = param, channel, engine
        self.value = param.default if param.default is not None else 0
        self._quiet = False

        ttk.Label(parent, text=f"CC#{param.cc}").grid(row=row, column=0, sticky="e", padx=(4, 6))
        ttk.Label(parent, text=param.name_ja).grid(row=row, column=1, sticky="w")
        cell = ttk.Frame(parent)
        cell.grid(row=row, column=2, sticky="w", padx=6, pady=1)
        ttk.Label(parent, text=param.hint(), foreground="#666").grid(row=row, column=3, sticky="w")

        k = param.kind
        if k in ("continuous", "time_exp", "special"):
            self.scale = tk.Scale(cell, from_=0, to=127, orient="horizontal", length=260,
                                  showvalue=False, command=self._on_scale)
            self.scale.pack(side="left")
            self.num = ttk.Label(cell, width=4, anchor="e")
            self.num.pack(side="left", padx=4)
            self._show = lambda v: (self.scale.set(v), self.num.configure(text=str(v)))
        elif k == "steps":
            self._make_combo(cell, param.step_labels(), param.step_value, param.step_index)
        elif k == "enum":
            labels = param.enum_labels()
            self._make_combo(cell, [f"{i}: {s}" for i, s in enumerate(labels)],
                             lambda i: i, lambda v: min(v, len(labels) - 1))
        elif k == "switch":
            labels = param.switch_labels()
            if labels == ["OFF", "ON"]:
                self.var = tk.BooleanVar()
                ttk.Checkbutton(cell, text="ON", variable=self.var,
                                command=lambda: self._changed(127 if self.var.get() else 0)).pack(side="left")
                self._show = lambda v: self.var.set(v >= 64)
            else:
                self._make_combo(cell, labels, lambda i: 127 if i else 0, lambda v: 1 if v >= 64 else 0)
        self._display(self.value)

    def _make_combo(self, cell, labels, to_value, to_index):
        self.combo = ttk.Combobox(cell, values=labels, state="readonly", width=24)
        self.combo.pack(side="left")
        self.combo.bind("<<ComboboxSelected>>",
                        lambda e: self._changed(to_value(self.combo.current())))
        self._show = lambda v: self.combo.current(to_index(v))

    def _on_scale(self, s):
        # tk.Scale は set() のあとにも遅れて command を呼ぶので、_quiet では防げない。
        # 値が変わっていなければ送らない
        v = int(float(s))
        self.num.configure(text=str(v))
        if not self._quiet and v != self.value:
            self._changed(v)

    def _changed(self, v):
        self.value = v
        self.engine.set_cc(self.ch, self.p.cc, v)

    def _display(self, v):
        self._quiet = True
        try:
            self._show(v)
        finally:
            self._quiet = False

    def set_value(self, v, send):
        self.value = v
        self._display(v)
        if send:
            self.engine.set_cc(self.ch, self.p.cc, v)


class ChannelTab:
    def __init__(self, notebook, channel, params, engine, app):
        self.channel = channel
        self.loaded_patch = None
        self.frame = ttk.Frame(notebook)
        bar = ttk.Frame(self.frame)
        bar.pack(fill="x", padx=6, pady=4)
        ttk.Button(bar, text="表示中の値を全部送る", command=self.send_all).pack(side="left")
        ttk.Button(bar, text="既定値に戻して送る", command=self.reset_defaults).pack(side="left", padx=6)
        self.loaded_label = ttk.Label(bar, text="音色: (なし)")
        self.loaded_label.pack(side="left", padx=10)
        self.view = tk.StringVar(value=app.settings.get("view", "easy"))
        ttk.Radiobutton(bar, text="詳細", value="detail", variable=self.view,
                        command=lambda: app.set_view(self.view.get())).pack(side="right")
        ttk.Radiobutton(bar, text="かんたん", value="easy", variable=self.view,
                        command=lambda: app.set_view(self.view.get())).pack(side="right", padx=4)
        ttk.Label(bar, text="表示:").pack(side="right")
        ttk.Label(self.frame, foreground="#666",
                  text="カートリッジの状態は読み出せないため、画面の値と実際の音はずれることがあります。"
                       "「表示中の値を全部送る」で揃えられます。").pack(anchor="w", padx=6)

        self.easy = EasyPanel(self.frame, self, app)
        self.detail = ttk.Frame(self.frame)
        canvas = tk.Canvas(self.detail, highlightthickness=0)
        sb = ttk.Scrollbar(self.detail, orient="vertical", command=canvas.yview)
        inner = ttk.Frame(canvas)
        inner.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.create_window((0, 0), window=inner, anchor="nw")
        canvas.configure(yscrollcommand=sb.set)
        canvas.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")
        canvas.bind("<Enter>", lambda e: app.set_scroll_target(canvas))
        inner.bind("<Enter>", lambda e: app.set_scroll_target(canvas))

        self.rows = [ParamRow(inner, i, p, channel, engine)
                     for i, p in enumerate(sorted(editable_params(params, channel), key=lambda p: p.cc))]
        self.show_view(self.view.get())

    def show_view(self, view):
        self.view.set(view)
        if view == "easy":
            self.detail.pack_forget()
            self.easy.refresh()
            self.easy.pack(fill="both", expand=True)
        else:
            self.easy.pack_forget()
            self.detail.pack(fill="both", expand=True)

    def set_values(self, updates):
        """かんたん表示などからの変更。送って、両方の表示を揃える"""
        by_cc = {r.p.cc: r for r in self.rows}
        for c, v in updates.items():
            if c in by_cc:
                by_cc[c].set_value(v, send=True)

    def send_all(self):
        for r in self.rows:
            r.set_value(r.value, send=True)

    def reset_defaults(self):
        for r in self.rows:
            if r.p.default is not None:
                r.set_value(r.p.default, send=True)
        self.set_loaded(None)
        self.easy.refresh()

    def values(self):
        return {r.p.cc: r.value for r in self.rows}

    def apply(self, patch):
        """全項目を既定値にしてから音色の値で上書きし、全部送る(CC#121 は使わない)。
        この ch に無い CC は送らず、その番号を返す"""
        vals = patch.cc_dict()
        for r in self.rows:
            v = vals.get(r.p.cc, r.p.default)
            if v is not None:
                r.set_value(v, send=True)
        self.set_loaded(patch)
        self.easy.refresh()
        return sorted(set(vals) - {r.p.cc for r in self.rows})

    def set_loaded(self, patch):
        self.loaded_patch = patch
        self.loaded_label.configure(text=f"音色: {patch.name}" if patch else "音色: (なし)")


class App:
    def __init__(self, root):
        self.root = root
        root.title("ふぁみみみっでぃ 音色エディタ(段階3)")
        root.geometry("1400x980")
        self.spec, self.params = load_spec()
        self.log = SendLog()
        self.engine = MidiEngine(self.log, self.params)
        self.settings = load_settings()
        self.cart = CartState.load()
        self.cart_window = None
        self.simple_window = None
        self._scroll_canvas = None

        self._build_connection()
        self._build_body()
        # Combobox のホイールで値が変わって CC が飛ばないようにし、代わりに一覧をスクロールする
        root.bind_class("TCombobox", "<MouseWheel>", self._on_wheel)
        root.bind_all("<MouseWheel>", self._on_wheel)

        self.refresh_ports()
        self.engine.ch_offset = self.settings.get("ch_offset", 0)
        self.offset_var.set(self.engine.ch_offset)
        self.thru_var.set(self.settings.get("thru", True))
        self.engine.thru_enabled = self.thru_var.get()
        self.remap_var.set(self.settings.get("thru_remap", True))
        self._on_remap(save=False)
        self._update_tab_titles()
        self.log.note("書き込み系(CC#45/50/51)は確認ダイアログ経由でのみ送ります。SysEx は未対応のため遮断します")
        # 前回使った出力ポートがあれば自動で接続する(失敗してもダイアログは出さない)
        if self.settings.get("out_name") in self.out_names:
            self.connect(auto=True)
        root.protocol("WM_DELETE_WINDOW", self.on_close)
        self._poll_log()

    # ---------- 画面 ----------
    def _build_connection(self):
        f = ttk.LabelFrame(self.root, text="接続")
        f.pack(fill="x", padx=8, pady=(8, 4))
        ttk.Label(f, text="出力(ふぁみみみっでぃ側)").grid(row=0, column=0, sticky="e", padx=4)
        self.out_combo = ttk.Combobox(f, state="readonly", width=36)
        self.out_combo.grid(row=0, column=1, padx=4, pady=2)
        ttk.Label(f, text="入力(KROSS2 など)").grid(row=1, column=0, sticky="e", padx=4)
        self.in_combo = ttk.Combobox(f, state="readonly", width=36)
        self.in_combo.grid(row=1, column=1, padx=4, pady=2)
        ttk.Button(f, text="一覧を更新", command=self.refresh_ports).grid(row=0, column=2, padx=4)
        ttk.Button(f, text="接続", command=self.connect).grid(row=0, column=3, padx=4)
        ttk.Button(f, text="切断", command=self.disconnect).grid(row=1, column=3, padx=4)
        self.status = ttk.Label(f, text="未接続", foreground="#a00")
        self.status.grid(row=0, column=4, rowspan=2, sticky="w", padx=8)

        g = ttk.Frame(self.root)
        g.pack(fill="x", padx=8, pady=2)
        ttk.Label(g, text="音源のチャンネル:").pack(side="left")
        self.offset_var = tk.IntVar(value=0)
        for val, label in OFFSETS:
            ttk.Radiobutton(g, text=label, value=val, variable=self.offset_var,
                            command=self._on_offset).pack(side="left", padx=4)
        self.thru_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(g, text="MIDIスルー(入力の演奏を出力へ流す)", variable=self.thru_var,
                        command=self._on_thru).pack(side="left", padx=(16, 4))
        self.remap_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(g, text="開いているタブのchで鳴らす", variable=self.remap_var,
                        command=self._on_remap).pack(side="left")
        tk.Button(g, text="パニック(全音停止)", bg="#c33", fg="white",
                  command=self.panic).pack(side="right")
        ttk.Button(g, text="詳細な管理…", command=self.open_cart_window).pack(side="right", padx=(2, 8))
        ttk.Button(g, text="波形メモリ(ch5)…", command=lambda: WaveWindow(self)).pack(side="right", padx=2)
        ttk.Button(g, text="★ カートリッジに音色を保存(かんたん)…",
                   command=self.open_simple).pack(side="right", padx=2)
        self.busy_label = ttk.Label(g, text="", foreground="#a00", font=("", 10, "bold"))
        self.busy_label.pack(side="right", padx=8)

    def _build_body(self):
        hp = ttk.PanedWindow(self.root, orient="horizontal")
        hp.pack(fill="both", expand=True, padx=8, pady=4)
        pw = ttk.PanedWindow(hp, orient="vertical")
        self.nb = ttk.Notebook(pw)
        self.tabs = []
        for ch in range(1, 6):
            t = ChannelTab(self.nb, ch, self.params, self.engine, self)
            self.nb.add(t.frame, text=f"ch{ch} {CHANNEL_NAMES[ch]}")
            self.tabs.append(t)
        pw.add(self.nb, weight=3)
        self.audition = AuditionPanel(pw, self.engine, lambda: self.current_tab().channel)
        pw.add(self.audition, weight=0)
        self.nb.bind("<<NotebookTabChanged>>", lambda e: self._on_tab_changed())
        self.library = LibraryPanel(hp, self)
        hp.add(self.library, weight=0)
        hp.add(pw, weight=1)

        lf = ttk.LabelFrame(pw, text="送信ログ(ファイルにも保存)")
        bar = ttk.Frame(lf)
        bar.pack(fill="x")
        ttk.Button(bar, text="ログをコピー", command=self.copy_log).pack(side="left", padx=2, pady=2)
        ttk.Button(bar, text="ログフォルダを開く", command=self.open_log_dir).pack(side="left", padx=2)
        ttk.Button(bar, text="画面のログを消去", command=lambda: self.log_text.delete("1.0", "end")).pack(side="left", padx=2)
        self.log_text = tk.Text(lf, height=8, font=("MS Gothic", 10), wrap="none")
        lsb = ttk.Scrollbar(lf, orient="vertical", command=self.log_text.yview)
        self.log_text.configure(yscrollcommand=lsb.set)
        self.log_text.pack(side="left", fill="both", expand=True)
        lsb.pack(side="right", fill="y")
        pw.add(lf, weight=1)

    def _update_tab_titles(self):
        off = self.engine.ch_offset
        for t in self.tabs:
            extra = f"(MIDI ch{t.channel + off})" if off else ""
            self.nb.tab(t.frame, text=f"ch{t.channel} {CHANNEL_NAMES[t.channel]}{extra}")

    def current_tab(self):
        return self.tabs[self.nb.index(self.nb.select())]

    def apply_patch(self, patch):
        tab = self.tabs[patch.channel - 1]
        self.nb.select(tab.frame)
        self.log.note(f"音色を読み込み: {patch.name}(ch{patch.channel})… 全項目を既定値+音色の値で送信")
        skipped = tab.apply(patch)
        if skipped:
            self.log.note(f"ch{patch.channel} では効かないため送らなかった CC: {skipped}")

    def panic(self):
        if self.engine.writing:
            self.log.note("書き込み中のためパニックは送りません(書き込み終了時に自動で送ります)")
            return
        self.audition.stop()
        self.engine.panic()

    # ---------- カートリッジ ----------
    def open_cart_window(self):
        if self.cart_window and self.cart_window.winfo_exists():
            self.cart_window.lift()
            return
        self.cart_window = CartridgeWindow(self)

    def open_simple(self, patch=None):
        if self.simple_window and self.simple_window.winfo_exists():
            self.simple_window.destroy()
        self.simple_window = SimpleCartWindow(self, patch)

    def refresh_cart_views(self):
        for w in (self.cart_window, self.simple_window):
            if w and w.winfo_exists():
                w.refresh()

    def set_busy(self, busy):
        """書き込みの前後。鳴っている音を止めてから始め、終わったらもう一度止める
        (書き込み中はノートオフも止めるため)"""
        if busy:
            self.audition.stop()
            self.engine.panic()
            self.busy_label.configure(text="● 書き込み中(送信を止めています)")
        else:
            self.engine.panic()
            self.busy_label.configure(text="")

    def set_view(self, view):
        """かんたん/詳細 を全タブで切り替えて覚えておく"""
        for t in self.tabs:
            t.show_view(view)
        self.settings["view"] = view
        save_settings(self.settings)

    def set_scroll_target(self, canvas):
        self._scroll_canvas = canvas

    def _on_wheel(self, e):
        c = self._scroll_canvas
        w = self.root.winfo_containing(e.x_root, e.y_root)
        # ログ欄の上ではログをスクロールさせる
        if w is self.log_text:
            return None
        if c is not None:
            c.yview_scroll(int(-e.delta / 120), "units")
        return "break"

    # ---------- 接続 ----------
    def refresh_ports(self):
        self.out_names = winmm.list_outputs()
        self.in_names = winmm.list_inputs()
        self.out_combo["values"] = self.out_names
        self.in_combo["values"] = [NO_INPUT] + self.in_names
        want_out = self.settings.get("out_name")
        want_in = self.settings.get("in_name")
        if want_out in self.out_names:
            self.out_combo.current(self.out_names.index(want_out))
        elif not self.out_combo.get():
            # 初回は PC 内蔵の音源(GS Wavetable)を避ける。迷ったら選ばずにユーザーに任せる
            cands = [i for i, n in enumerate(self.out_names) if "Wavetable" not in n and "microKEY" not in n]
            if len(cands) == 1:
                self.out_combo.current(cands[0])
        if want_in in self.in_names:
            self.in_combo.current(self.in_names.index(want_in) + 1)
        elif not self.in_combo.get():
            self.in_combo.current(0)
        self.log.note(f"出力ポート: {self.out_names or 'なし'} / 入力ポート: {self.in_names or 'なし'}")

    def connect(self, auto=False):
        self.disconnect(quiet=True)
        oi = self.out_combo.current()
        if oi < 0:
            messagebox.showwarning("接続", "出力ポートを選んでください。")
            return
        try:
            self.engine.set_output(winmm.OutputPort(oi, self.out_names[oi]))
        except winmm.MidiPortError as e:
            self.log.note(f"出力の接続に失敗: {e}")
            if auto:
                self.status.configure(text="前回のポートに自動接続できませんでした\n(ログを参照)",
                                      foreground="#a00")
                return
            messagebox.showerror("出力ポートを開けません", str(e))
            self._update_status()
            return
        ii = self.in_combo.current() - 1
        if ii >= 0:
            try:
                self.engine.set_input(winmm.InputPort(ii, self.in_names[ii], self.engine.on_input))
            except winmm.MidiPortError as e:
                self.log.note(f"入力の接続に失敗: {e}")
                if not auto:
                    messagebox.showerror("入力ポートを開けません", str(e) + "\n\n出力だけ接続した状態で続けます。")
        self.settings["out_name"] = self.engine.output_name
        self.settings["in_name"] = self.engine.input_name
        save_settings(self.settings)
        self._update_status()

    def disconnect(self, quiet=False):
        self.engine.set_input(None)
        self.engine.set_output(None)
        self._update_status()

    def _update_status(self):
        o, i = self.engine.output_name, self.engine.input_name
        if o:
            self.status.configure(text=f"出力: {o}\n入力: {i or 'なし'}", foreground="#060")
        else:
            self.status.configure(text="未接続", foreground="#a00")

    def _on_offset(self):
        self.engine.ch_offset = self.offset_var.get()
        self.settings["ch_offset"] = self.engine.ch_offset
        save_settings(self.settings)
        self._update_tab_titles()
        self.log.note(f"音源のチャンネルを {dict(OFFSETS)[self.engine.ch_offset]} に設定")

    def _on_tab_changed(self):
        self.audition.channel_changed()
        if self.remap_var.get():
            self.engine.thru_channel = self.current_tab().channel

    def _on_remap(self, save=True):
        on = self.remap_var.get()
        self.engine.thru_channel = self.current_tab().channel if on else None
        if save:
            self.settings["thru_remap"] = on
            save_settings(self.settings)
            self.log.note(f"スルーの演奏を{'開いているタブのchで鳴らす' if on else 'そのままのchで流す'}")

    def _on_thru(self):
        self.engine.thru_enabled = self.thru_var.get()
        self.settings["thru"] = self.engine.thru_enabled
        save_settings(self.settings)
        self.log.note(f"MIDIスルー: {'ON' if self.engine.thru_enabled else 'OFF'}")

    # ---------- ログ ----------
    def _poll_log(self):
        lines = []
        try:
            while len(lines) < 500:
                lines.append(self.log.lines.get_nowait())
        except Exception:  # queue.Empty
            pass
        if lines:
            at_end = self.log_text.yview()[1] > 0.999
            self.log_text.insert("end", "\n".join(lines) + "\n")
            n = int(self.log_text.index("end-1c").split(".")[0])
            if n > LOG_MAX_LINES:
                self.log_text.delete("1.0", f"{n - LOG_MAX_LINES}.0")
            if at_end:
                self.log_text.see("end")
        self.root.after(50, self._poll_log)

    def copy_log(self):
        self.root.clipboard_clear()
        self.root.clipboard_append(self.log_text.get("1.0", "end-1c"))

    def open_log_dir(self):
        os.startfile(self.log.path.parent)

    def on_close(self):
        if self.engine.writing:
            messagebox.showwarning("書き込み中", "カートリッジに書き込み中です。終わるまで閉じないでください。")
            return
        self.audition.stop()
        self.engine.shutdown()
        self.log.close()
        self.root.destroy()


def main():
    from . import single
    if not single.acquire():          # 新しい画面と同時に起動させない
        return
    root = tk.Tk()
    App(root)
    root.mainloop()
