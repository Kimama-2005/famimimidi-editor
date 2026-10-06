"""試聴: 画面上の鍵盤とテストフレーズ。送信はすべて engine.send を通す。"""
import tkinter as tk
from tkinter import ttk

from .phrases import PHRASES, PhrasePlayer

# 各 ch の鍵盤の開始ノートと、鳴る範囲(実装表)
DEFAULT_BASE = {1: 60, 2: 60, 3: 48, 4: 0, 5: 36}
NOTE_RANGE = {1: (33, 108), 2: (33, 108), 3: (21, 96), 4: (0, 127), 5: (0, 127)}
NAMES = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]
WHITE = [0, 2, 4, 5, 7, 9, 11]

def note_name(n):
    return f"{NAMES[n % 12]}{n // 12 - 1}"


class Keyboard(tk.Canvas):
    """2オクターブ+1音の鍵盤。押している間ノートオン"""
    WW, WH, BW, BH = 30, 90, 18, 56

    def __init__(self, parent, on_press, on_release):
        super().__init__(parent, width=self.WW * 15 + 1, height=self.WH + 1,
                         highlightthickness=0, bg="#ddd")
        self.on_press, self.on_release = on_press, on_release
        self.base = 60
        self.lo, self.hi = 0, 127
        self.held = None
        self.bind("<ButtonPress-1>", self._press)
        self.bind("<ButtonRelease-1>", self._release)
        self.bind("<Leave>", self._release)

    def configure_range(self, base, lo, hi):
        self.base, self.lo, self.hi = base - base % 12, lo, hi
        self.draw()

    def _keys(self):
        """(note, 黒鍵か, x1, y1, x2, y2)。黒鍵を後に並べる(当たり判定で優先)"""
        whites, blacks = [], []
        for i in range(15):
            octave, w = divmod(i, 7)
            n = self.base + octave * 12 + WHITE[w]
            x = i * self.WW
            whites.append((n, False, x, 0, x + self.WW, self.WH))
            if WHITE[w] in (0, 2, 5, 7, 9) and i < 14:
                bx = x + self.WW - self.BW // 2
                blacks.append((n + 1, True, bx, 0, bx + self.BW, self.BH))
        return whites + blacks

    def draw(self):
        self.delete("all")
        for n, black, x1, y1, x2, y2 in self._keys():
            ok = self.lo <= n <= self.hi
            if black:
                fill = "#222" if ok else "#888"
            else:
                fill = "white" if ok else "#bbb"
            if n == self.held:
                fill = "#6af"
            self.create_rectangle(x1, y1, x2, y2, fill=fill, outline="#555")
            if not black and n % 12 == 0:
                self.create_text((x1 + x2) / 2, y2 - 10, text=note_name(n), font=("", 8))

    def note_at(self, x, y):
        for n, black, x1, y1, x2, y2 in reversed(self._keys()):
            if x1 <= x < x2 and y1 <= y < y2:
                return n
        return None

    def _press(self, e):
        n = self.note_at(e.x, e.y)
        if n is None or not (self.lo <= n <= self.hi):
            return
        self.held = n
        self.on_press(n)
        self.draw()

    def _release(self, e):
        if self.held is not None:
            n, self.held = self.held, None
            self.on_release(n)
            self.draw()


class AuditionPanel(ttk.LabelFrame):
    """現在のタブの ch で鳴らす"""

    def __init__(self, parent, engine, get_channel):
        super().__init__(parent, text="試聴(いま開いているタブの ch で鳴らします)")
        self.engine = engine
        self.get_channel = get_channel
        self.player = PhrasePlayer(engine)
        self.base = dict(DEFAULT_BASE)

        left = ttk.Frame(self)
        left.pack(side="left", padx=6, pady=4)
        self.kb = Keyboard(left, self._note_on, self._note_off)
        self.kb.pack()
        nav = ttk.Frame(left)
        nav.pack(fill="x")
        ttk.Button(nav, text="◀ オクターブ下", command=lambda: self.shift(-12)).pack(side="left")
        ttk.Button(nav, text="オクターブ上 ▶", command=lambda: self.shift(12)).pack(side="left", padx=4)
        self.range_label = ttk.Label(nav, foreground="#666")
        self.range_label.pack(side="left", padx=6)

        right = ttk.Frame(self)
        right.pack(side="left", fill="y", padx=10, pady=4)
        row = ttk.Frame(right)
        row.pack(anchor="w")
        ttk.Label(row, text="ベロシティ").pack(side="left")
        self.vel = tk.IntVar(value=100)
        tk.Scale(row, from_=1, to=127, orient="horizontal", length=140, variable=self.vel,
                 showvalue=True).pack(side="left")
        ttk.Label(right, text="テストフレーズ(鍵盤の一番左の C が基準)").pack(anchor="w", pady=(6, 2))
        grid = ttk.Frame(right)
        grid.pack(anchor="w")
        for i, (name, events) in enumerate(PHRASES):
            ttk.Button(grid, text=name, command=lambda ev=events: self.play(ev)).grid(
                row=i // 3, column=i % 3, sticky="we", padx=2, pady=2)
        ttk.Button(grid, text="フレーズ停止", command=self.stop).grid(
            row=(len(PHRASES)) // 3 + 1, column=0, sticky="we", padx=2, pady=2)
        self.channel_changed()

    def channel_changed(self):
        ch = self.get_channel()
        lo, hi = NOTE_RANGE[ch]
        self.kb.configure_range(self.base[ch], lo, hi)
        self.range_label.configure(text=f"ch{ch} の鳴る範囲: ノート {lo}〜{hi}(灰色の鍵は範囲外)")

    def shift(self, d):
        ch = self.get_channel()
        self.base[ch] = max(0, min(108, self.base[ch] + d))
        self.channel_changed()

    def _note_on(self, n):
        c0 = self.engine.midi_ch0(self.get_channel())
        self.engine.send(bytes([0x90 | c0, n, self.vel.get()]), "試聴")

    def _note_off(self, n):
        c0 = self.engine.midi_ch0(self.get_channel())
        self.engine.send(bytes([0x80 | c0, n, 0]), "試聴")

    def play(self, events):
        ch = self.get_channel()
        self.player.play(ch, self.kb.base, self.vel.get(), events)

    def stop(self):
        self.player.stop()
