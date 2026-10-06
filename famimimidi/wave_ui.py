"""ch5 波形メモリエディタの画面(フェーズCで作り直す前提の最小限の画面。中身は wave.py)。"""
import tkinter as tk
from tkinter import messagebox, ttk

from .cartridge_ui import run_write
from .simple_ui import SimpleConfirm
from .wave import LEVELS, PCS, POINTS, PRESETS, data_sysex, plan_register

CELL = 24
NOTES = {"低い(ド3)": 48, "ふつう(ド4)": 60, "高い(ド5)": 72}


class WaveWindow(tk.Toplevel):
    def __init__(self, app):
        super().__init__(app.root)
        self.app = app
        self.title("波形メモリ(ch5)")
        self.resizable(False, False)
        self.samples = list(PRESETS["三角"])
        f = ttk.Frame(self, padding=10)
        f.pack(fill="both", expand=True)
        ttk.Label(f, wraplength=640, justify="left",
                  text="ch5の「波形メモリ」で鳴らす音の形を描きます。16本の棒をマウスでなぞって描いてください"
                       "(上ほど大きい)。「試しに鳴らす」はカートリッジに保存しません。"
                       "「登録…」で PC61〜76 に保存すると、電源を切っても残ります。").grid(
            row=0, column=0, columnspan=2, sticky="w", pady=(0, 8))

        self.canvas = tk.Canvas(f, width=CELL * POINTS, height=CELL * LEVELS, bg="#101010",
                                highlightthickness=1, highlightbackground="#888")
        self.canvas.grid(row=1, column=0, rowspan=3, sticky="n")
        self.canvas.bind("<Button-1>", self._draw_at)
        self.canvas.bind("<B1-Motion>", self._draw_at)

        side = ttk.Frame(f, padding=(12, 0, 0, 0))
        side.grid(row=1, column=1, sticky="n")
        pf = ttk.LabelFrame(side, text="形を選ぶ", padding=6)
        pf.pack(fill="x")
        for i, name in enumerate(PRESETS):
            ttk.Button(pf, text=name, command=lambda n=name: self.set_samples(PRESETS[n])).grid(
                row=i // 2, column=i % 2, sticky="we", padx=1, pady=1)
        self.values = ttk.Label(side, font=("MS Gothic", 9), foreground="#555")
        self.values.pack(anchor="w", pady=6)

        tf = ttk.LabelFrame(side, text="試しに鳴らす(保存しない)", padding=6)
        tf.pack(fill="x")
        self.pitch = ttk.Combobox(tf, values=list(NOTES), state="readonly", width=12)
        self.pitch.set("ふつう(ド4)")
        self.pitch.pack(side="left")
        ttk.Button(tf, text="♪ 鳴らす", command=self.preview).pack(side="left", padx=4)
        ttk.Button(side, text="ch5 をドラムに戻す", command=self.back_to_drum).pack(anchor="w", pady=(4, 8))

        rf = ttk.LabelFrame(side, text="カートリッジに登録(保存)", padding=6)
        rf.pack(fill="x")
        ttk.Label(rf, text="名前").grid(row=0, column=0, sticky="w")
        self.name = ttk.Entry(rf, width=24)
        self.name.insert(0, "三角")
        self.name.grid(row=0, column=1, sticky="w", pady=1)
        ttk.Label(rf, text="登録先").grid(row=1, column=0, sticky="w")
        self.slot = ttk.Combobox(rf, state="readonly", width=34)
        self.slot.grid(row=1, column=1, sticky="w", pady=1)
        b = ttk.Frame(rf)
        b.grid(row=2, column=0, columnspan=2, sticky="w", pady=(4, 0))
        ttk.Button(b, text="登録…", command=self.register).pack(side="left")
        ttk.Button(b, text="登録したものを呼び出して鳴らす", command=self.recall).pack(side="left", padx=4)
        ttk.Button(b, text="編集に読み込む", command=self.load_slot).pack(side="left")
        self.refresh()
        self.redraw()

    # ---------- 描画 ----------
    def set_samples(self, samples):
        self.samples = list(samples)
        self.redraw()

    def _draw_at(self, e):
        col = min(max(e.x // CELL, 0), POINTS - 1)
        val = min(max(LEVELS - 1 - e.y // CELL, 0), LEVELS - 1)
        if self.samples[col] != val:
            self.samples[col] = val
            self.redraw()

    def redraw(self):
        c = self.canvas
        c.delete("all")
        for i in range(1, LEVELS):
            c.create_line(0, i * CELL, POINTS * CELL, i * CELL, fill="#222")
        c.create_line(0, CELL * 7.5 + CELL / 2, POINTS * CELL, CELL * 7.5 + CELL / 2, fill="#444", dash=(2, 2))
        for i, v in enumerate(self.samples):
            x0, x1 = i * CELL + 2, (i + 1) * CELL - 2
            y = (LEVELS - 1 - v) * CELL
            c.create_rectangle(x0, y, x1, LEVELS * CELL, fill="#1e5aa8", outline="")
            c.create_rectangle(x0, y, x1, y + CELL, fill="#f8b800", outline="")
        self.values.configure(text="値: " + " ".join(f"{v:X}" for v in self.samples))

    def refresh(self):
        waves = self.app.cart.waves
        values = []
        for pc in PCS:
            w = waves.get(pc)
            values.append(f"PC{pc}(送信値{pc - 1}): " + (w["name"] if w else "(このソフトでは未登録)"))
        cur = self.slot.current()
        self.slot["values"] = values
        self.slot.current(cur if cur >= 0 else 0)

    # ---------- 操作 ----------
    def _ready(self):
        if not self.app.engine.output_name:
            messagebox.showerror("未接続", "ふぁみみみっでぃに接続していません。", parent=self)
            return False
        if self.app.engine.writing:
            messagebox.showinfo("保存中", "保存が終わるまで待ってください。", parent=self)
            return False
        return True

    def _play(self, pre):
        eng = self.app.engine
        c0 = eng.midi_ch0(5)
        for msg in pre:
            eng.send(msg, "波形メモリ")
        eng.send(bytes([0xB0 | c0, 18, 127]), "波形メモリ")          # ch5 を波形メモリモードに
        note = NOTES[self.pitch.get()]
        self.after(100, lambda: eng.send(bytes([0x90 | c0, note, 127]), "波形メモリ"))
        self.after(1100, lambda: eng.send(bytes([0x80 | c0, note, 0]), "波形メモリ"))

    def preview(self):
        if self._ready():
            self._play([data_sysex(self.samples)])

    def recall(self):
        if self._ready():
            pc = PCS[self.slot.current()]
            self._play([bytes([0xC0 | self.app.engine.midi_ch0(5), pc - 1])])

    def back_to_drum(self):
        if self._ready():
            self.app.engine.send(bytes([0xB0 | self.app.engine.midi_ch0(5), 18, 0]), "波形メモリ")

    def load_slot(self):
        w = self.app.cart.waves.get(PCS[self.slot.current()])
        if not w or not w.get("samples"):
            messagebox.showinfo("読み込み", "このソフトで登録した記録がないので、読み込めません。", parent=self)
            return
        self.set_samples(w["samples"])
        self.name.delete(0, "end")
        self.name.insert(0, w["name"])

    def register(self):
        if not self._ready():
            return
        pc = PCS[self.slot.current()]
        name = self.name.get().strip() or "名前なし"
        samples = list(self.samples)
        old = self.app.cart.waves.get(pc)
        lines = [f"波形「{name}」を PC{pc} に登録します。",
                 "※ " + (f"いま登録されている「{old['name']}」は消えます。" if old else
                         "この場所に以前なにが登録されていたかは、このソフトでは分かりません(上書きされます)。"),
                 f"※ 登録後は、ch5 を波形メモリにして PC{pc} を送ると、この波形になります。"]
        steps = plan_register(samples, pc)
        if not SimpleConfirm(self, "波形を登録", lines, steps, "登録する").ok:
            return
        self.app.log.note(f"波形を登録: PC{pc} ← {name} {samples}")

        def done(st):
            st.wave_done(pc, samples, name)
            self.after(0, self.refresh)
        run_write(self.app, steps, done, None, None, None,
                  f"PC{pc} に「{name}」を登録しました。\n\nファミコンの電源を入れ直してから、"
                  "「登録したものを呼び出して鳴らす」で確かめてください。",
                  on_failure=lambda st, error, recorded: st.wave_failed(pc, error))
