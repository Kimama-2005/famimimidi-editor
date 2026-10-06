"""MIDIファイル書き出しの画面。ch1〜5 それぞれに音色を選んで、1つの .mid にする。"""
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from .export import MODES, export_set
from .spec import CHANNEL_NAMES

NONE = "(なし)"


class ExportDialog(tk.Toplevel):
    def __init__(self, app, patch=None):
        super().__init__(app.root)
        self.app = app
        self.title("MIDIファイルに書き出す")
        self.transient(app.root)
        self.resizable(False, False)
        self.patches = app.library.lib.patches
        f = ttk.Frame(self, padding=12)
        f.pack(fill="both", expand=True)
        ttk.Label(f, wraplength=520, justify="left",
                  text="音色の設定を MIDI ファイル(.mid)にします。Cubase などで曲の頭(1小節目の前)に置くと、"
                       "再生したときにその音色になります。チャンネルごとに別のトラックになります。").grid(
            row=0, column=0, columnspan=2, sticky="w", pady=(0, 8))
        self.combos = {}
        for ch in range(1, 6):
            ttk.Label(f, text=f"ch{ch} {CHANNEL_NAMES[ch]}").grid(row=ch, column=0, sticky="w", padx=(0, 8))
            names = [NONE] + [f"{p.name}(ch{p.channel}用)" for p in self.patches]
            c = ttk.Combobox(f, values=names, state="readonly", width=46)
            c.current(0)
            c.grid(row=ch, column=1, sticky="w", pady=1)
            self.combos[ch] = c
        if patch is not None and patch in self.patches:
            self.combos[patch.channel].current(self.patches.index(patch) + 1)

        mf = ttk.LabelFrame(f, text="書き方", padding=6)
        mf.grid(row=6, column=0, columnspan=2, sticky="we", pady=8)
        self.mode = tk.StringVar(value="full")
        for key, text in MODES.items():
            ttk.Radiobutton(mf, text=text, value=key, variable=self.mode).pack(anchor="w")

        b = ttk.Frame(f)
        b.grid(row=7, column=0, columnspan=2, sticky="e")
        ttk.Button(b, text="書き出す…", command=self.save).pack(side="left", padx=4)
        ttk.Button(b, text="閉じる", command=self.destroy).pack(side="left")

    def save(self):
        assign = {}
        for ch, c in self.combos.items():
            i = c.current()
            if i > 0:
                assign[ch] = self.patches[i - 1]
        if not assign:
            messagebox.showinfo("書き出し", "少なくとも1つのチャンネルに音色を選んでください。", parent=self)
            return
        first = assign[min(assign)]
        path = filedialog.asksaveasfilename(parent=self, defaultextension=".mid",
                                            filetypes=[("MIDIファイル", "*.mid")],
                                            initialfile=f"famimimidi_{first.name}.mid".replace("/", "_"))
        if not path:
            return
        data, notes = export_set(assign, self.app.params, self.mode.get(), self.app.cart, self.app.engine.ch_offset)
        Path(path).write_bytes(data)
        self.app.log.note(f"MIDIファイルに書き出し: {path}(" +
                          ", ".join(f"ch{ch}={p.name}" for ch, p in sorted(assign.items())) + ")")
        messagebox.showinfo("書き出し", f"書き出しました。\n{path}" + ("\n\n" + "\n".join(notes) if notes else ""),
                            parent=self)
        self.destroy()
