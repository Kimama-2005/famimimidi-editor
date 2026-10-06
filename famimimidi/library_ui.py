"""ライブラリの画面(左側の一覧)。ファイル(user_data/library.json)への保存のみで、カートリッジには書かない。"""
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from .library import CATEGORIES, Library, Patch, diff_from_defaults, new_id
from .ab_ui import ABWindow
from .export_ui import ExportDialog
from .spec import CHANNEL_NAMES


class PatchDialog(tk.Toplevel):
    """名前・分類・メモの入力。result に dict が入る(キャンセル時 None)"""

    def __init__(self, parent, title, name="", category="other", notes="", channel_text=""):
        super().__init__(parent)
        self.title(title)
        self.transient(parent)
        self.resizable(False, False)
        self.result = None
        f = ttk.Frame(self, padding=10)
        f.pack(fill="both", expand=True)
        if channel_text:
            ttk.Label(f, text=channel_text, foreground="#666").grid(row=0, column=0, columnspan=2, sticky="w")
        ttk.Label(f, text="名前").grid(row=1, column=0, sticky="e", padx=4, pady=2)
        self.name = ttk.Entry(f, width=40)
        self.name.insert(0, name)
        self.name.grid(row=1, column=1, sticky="w", pady=2)
        ttk.Label(f, text="分類").grid(row=2, column=0, sticky="e", padx=4, pady=2)
        self.cat = ttk.Combobox(f, values=CATEGORIES, width=12)
        self.cat.set(category)
        self.cat.grid(row=2, column=1, sticky="w", pady=2)
        ttk.Label(f, text="メモ").grid(row=3, column=0, sticky="ne", padx=4, pady=2)
        self.notes = tk.Text(f, width=40, height=6)
        self.notes.insert("1.0", notes)
        self.notes.grid(row=3, column=1, pady=2)
        b = ttk.Frame(f)
        b.grid(row=4, column=1, sticky="e", pady=(8, 0))
        ttk.Button(b, text="OK", command=self._ok).pack(side="left", padx=4)
        ttk.Button(b, text="キャンセル", command=self.destroy).pack(side="left")
        self.name.focus_set()
        self.grab_set()
        self.wait_window()

    def _ok(self):
        name = self.name.get().strip()
        if not name:
            messagebox.showwarning("名前", "名前を入れてください。", parent=self)
            return
        self.result = {"name": name, "category": self.cat.get().strip() or "other",
                       "notes": self.notes.get("1.0", "end-1c").strip()}
        self.destroy()


class LibraryPanel(ttk.LabelFrame):
    def __init__(self, parent, app):
        super().__init__(parent, text="音色ライブラリ(PCに保存)")
        self.app = app
        self.lib = Library()

        self.tree = ttk.Treeview(self, columns=("ch", "cat"), show="tree headings", height=14,
                                 selectmode="browse")
        self.tree.heading("#0", text="名前")
        self.tree.heading("ch", text="ch")
        self.tree.heading("cat", text="分類")
        self.tree.column("#0", width=200)
        self.tree.column("ch", width=36, anchor="center")
        self.tree.column("cat", width=64)
        self.tree.pack(fill="both", expand=True, padx=4, pady=4)
        self.tree.bind("<<TreeviewSelect>>", lambda e: self._show_detail())
        self.tree.bind("<Double-1>", lambda e: self.load_selected())

        btns = ttk.Frame(self)
        btns.pack(fill="x", padx=4)
        for i, (text, cmd) in enumerate([
                ("読み込んで送る", self.load_selected), ("新規保存…", self.save_new),
                ("上書き保存", self.overwrite), ("名前・メモ…", self.edit_meta),
                ("削除", self.delete), ("★ カートリッジに保存…", self.write_to_cart),
                ("MIDIファイルに書き出し…", lambda: ExportDialog(self.app, self.selected())),
                ("音色を比べる(A/B)…", lambda: ABWindow(self.app)),
                ("ライブラリのバックアップ…", self.export),
                ("バックアップから取り込み…", self.import_file)]):
            ttk.Button(btns, text=text, command=cmd).grid(row=i // 2, column=i % 2, sticky="we", padx=1, pady=1)
        btns.columnconfigure(0, weight=1)
        btns.columnconfigure(1, weight=1)

        self.detail = tk.Text(self, height=10, width=36, wrap="word", font=("", 9), state="disabled")
        self.detail.pack(fill="both", padx=4, pady=4)
        self.refresh()

    # ---------- 表示 ----------
    def refresh(self, select=None):
        self.tree.delete(*self.tree.get_children())
        for p in self.lib.patches:
            self.tree.insert("", "end", iid=p.id, text=p.name, values=(p.channel, p.category))
        if select and self.tree.exists(select):
            self.tree.selection_set(select)
            self.tree.see(select)
        self._show_detail()

    def selected(self):
        sel = self.tree.selection()
        return self.lib.get(sel[0]) if sel else None

    def _show_detail(self):
        p = self.selected()
        self.detail.configure(state="normal")
        self.detail.delete("1.0", "end")
        if p:
            params = self.app.params
            lines = [f"{p.name}", f"ch{p.channel} {CHANNEL_NAMES.get(p.channel, '')} / {p.category}",
                     f"設定 {len(p.cc)}個(カートリッジに保存するときは、初期値と違うものを上から10個):"]
            for i, (c, v) in enumerate(p.cc, 1):
                name = params[c].name_ja if c in params else "?"
                lines.append(f"  {i:2}. CC#{c}={v} {name}")
            if p.notes:
                lines += ["", p.notes]
            lines += ["", f"更新: {p.updated}"]
            self.detail.insert("1.0", "\n".join(lines))
        self.detail.configure(state="disabled")

    # ---------- 操作 ----------
    def load_selected(self):
        p = self.selected()
        if not p:
            messagebox.showinfo("読み込み", "一覧から音色を選んでください。")
            return
        self.app.apply_patch(p)

    def save_new(self):
        tab = self.app.current_tab()
        dlg = PatchDialog(self, "新規保存", channel_text=f"ch{tab.channel} の現在の値を保存します")
        if not dlg.result:
            return
        prev = tab.loaded_patch.cc if tab.loaded_patch else []
        p = Patch(id=new_id(dlg.result["name"]), channel=tab.channel,
                  cc=diff_from_defaults(tab.values(), self.app.params, [c for c, _ in prev]), **dlg.result)
        self.lib.add(p)
        tab.set_loaded(p)
        self.refresh(select=p.id)
        self.app.log.note(f"ライブラリに新規保存: {p.name}(ch{p.channel}、CC {len(p.cc)}個)")

    def overwrite(self):
        p = self.selected()
        if not p:
            messagebox.showinfo("上書き保存", "上書きする音色を一覧から選んでください。")
            return
        tab = self.app.current_tab()
        msg = f"「{p.name}」を、ch{tab.channel} の現在の値で上書きします。よろしいですか?"
        if p.channel != tab.channel:
            msg += f"\n\n注意: この音色は ch{p.channel} 用ですが、ch{tab.channel} として保存されます。"
        if not messagebox.askyesno("上書き保存", msg):
            return
        p.cc = diff_from_defaults(tab.values(), self.app.params, [c for c, _ in p.cc])
        p.channel = tab.channel
        self.lib.update(p)
        tab.set_loaded(p)
        self.refresh(select=p.id)
        self.app.log.note(f"ライブラリを上書き保存: {p.name}(ch{p.channel}、CC {len(p.cc)}個)")

    def edit_meta(self):
        p = self.selected()
        if not p:
            return
        dlg = PatchDialog(self, "名前・メモ", p.name, p.category, p.notes)
        if dlg.result:
            p.name, p.category, p.notes = dlg.result["name"], dlg.result["category"], dlg.result["notes"]
            self.lib.update(p)
            self.refresh(select=p.id)

    def delete(self):
        p = self.selected()
        if p and messagebox.askyesno("削除", f"「{p.name}」をライブラリから削除します。よろしいですか?\n"
                                           "(PC上の一覧から消すだけで、カートリッジには影響しません)"):
            self.lib.delete(p.id)
            self.refresh()
            self.app.log.note(f"ライブラリから削除: {p.name}")

    def write_to_cart(self):
        """かんたん保存の画面を、この音色を選んだ状態で開く"""
        self.app.open_simple(self.selected())

    def export(self):
        path = filedialog.asksaveasfilename(defaultextension=".json", filetypes=[("JSON", "*.json")],
                                            initialfile="famimimidi_library.json")
        if path:
            self.lib.export(Path(path))
            self.app.log.note(f"ライブラリを書き出し: {path}")

    def import_file(self):
        path = filedialog.askopenfilename(filetypes=[("JSON", "*.json")])
        if not path:
            return
        try:
            added = self.lib.import_file(Path(path))
        except (OSError, ValueError, TypeError, KeyError) as e:
            messagebox.showerror("取り込み", f"取り込めませんでした: {e}")
            return
        self.refresh()
        self.app.log.note(f"{path} から {len(added)} 個の音色を取り込み")
