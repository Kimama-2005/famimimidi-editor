"""user_data の読み書き(SPEC_v2 5.0)。

- 保存は「一時ファイルに書いて置き換える」(途中で落ちても壊れない)
- どのファイルも先頭に "format" を持つ。今の版のファイルを見つけたら、読むときに自動で移行し、
  元のファイルは user_data/old_v1/ に残す
- 読めないファイル(壊れている・知らない形)は**上書きしない**。StoreError で知らせて止める
  (特にカートリッジの控えは、ユーザーのカートリッジの唯一の記録)
"""
import json
import os
import shutil
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from ..music.spec import Spec, load_spec
from ..paths import DATA_DIR, USER_DIR
from . import migrate
from .cartmirror import FORMAT as CART_FORMAT, CartMirror
from .chordbook import FORMAT as CHORD_FORMAT, ChordBook
from .library import FORMAT as LIB_FORMAT, Library
from .prefs import FORMAT as PREFS_FORMAT, Prefs
from .session import FORMAT as SESSION_FORMAT, Session

OLD_DIR = "old_v1"


class StoreError(Exception):
    """読めないファイルがあった(上書きせずに止める)"""


def write_json(path: Path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)


def read_json(path: Path):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError) as e:
        raise StoreError(f"{path.name} を読めません({e})。ファイルはそのままにしてあります") from e


@dataclass
class Loaded:
    library: Library
    session: Session
    chordbook: ChordBook
    cart: CartMirror
    prefs: Prefs
    notes: list = field(default_factory=list)       # 移行・初回の知らせ(画面とログに出す)


class Store:
    def __init__(self, user_dir: Path = USER_DIR, data_dir: Path = DATA_DIR, spec: Spec | None = None):
        self.user_dir = Path(user_dir)
        self.data_dir = Path(data_dir)
        self.spec = spec or load_spec()
        self.notes = []

    def path(self, name):
        return self.user_dir / name

    # ---------- 控え ----------
    def _backup(self, name):
        """今の版のファイルを old_v1/ に写す(同じ名前があれば日時を付けて、前の控えを消さない)"""
        src = self.path(name)
        if not src.exists():
            return None
        dst_dir = self.user_dir / OLD_DIR
        dst_dir.mkdir(parents=True, exist_ok=True)
        dst = dst_dir / name
        if dst.exists():
            dst = dst_dir / f"{src.stem}_{datetime.now():%Y%m%d_%H%M%S_%f}{src.suffix}"
        shutil.copy2(src, dst)
        return dst

    # ---------- まとめて ----------
    def load_all(self) -> Loaded:
        self.notes = []
        settings = self._old_settings()
        out = Loaded(self.load_library(), self.load_session(settings), self.load_chordbook(), self.load_cart(),
                     self.load_prefs(settings))
        if settings is not None:
            self._backup("settings.json")
        out.notes = list(self.notes)
        return out

    def _old_settings(self):
        p = self.path("settings.json")
        need = not self.path("session.json").exists() or not self.path("prefs.json").exists()
        if need and p.exists():
            return read_json(p)
        return None

    # ---------- ライブラリ ----------
    def load_library(self) -> Library:
        p = self.path("library.json")
        if not p.exists():
            lib = self.seed_library()
            self.save_library(lib)
            self.notes.append(f"ライブラリを見本から作りました(音色 {len(lib.tones)}・演奏セット {len(lib.performances)})")
            return lib
        d = read_json(p)
        if d.get("format") == LIB_FORMAT:
            return Library.from_dict(d, self.spec)
        if migrate.is_v1_library(d):
            lib = migrate.library_from_v1(d, self.spec)
            self._backup("library.json")
            self.save_library(lib)
            self.notes.append(f"今の版のライブラリを移しました(音色 {len(lib.tones)}・演奏セット {len(lib.performances)}。元は {OLD_DIR}/)")
            return lib
        raise StoreError(f"library.json の形が分かりません(format={d.get('format')})。ファイルはそのままにしてあります")

    def seed_library(self) -> Library:
        """data/ の見本(今の版の形)を新しい形に直して使う"""
        lib = Library()
        seed = self.data_dir / "patches.json"
        if seed.exists():
            for p in read_json(seed).get("patches", []):
                t = migrate.tone_from_v1({**p, "source": "data/patches.json"}, self.spec)
                lib.tones.append(t)
        sets_dir = self.data_dir / "sets"
        if sets_dir.is_dir():
            for f in sorted(sets_dir.glob("*.json")):
                d = read_json(f)
                lib.performances += migrate.library_from_v1(d, self.spec).performances \
                    if migrate.is_v1_library(d) else Library.from_dict(d, self.spec).performances
        for t in lib.tones:
            t.created = t.created or ""
            t.touch()
        for perf in lib.performances:
            perf.touch()
        return lib

    def save_library(self, lib: Library):
        write_json(self.path("library.json"), lib.to_dict())

    # ---------- 作業中の演奏 ----------
    def load_session(self, settings=None) -> Session:
        p = self.path("session.json")
        if p.exists():
            return Session.from_dict(self._expect(p, SESSION_FORMAT), self.spec)
        if settings is not None and (settings.get("play") or settings.get("chord")):
            s = migrate.session_from_v1(settings, self.spec)
            self.notes.append("今の版の割り当て表とコードモードの設定を、作業中の演奏に移しました(5ch の音色は既定値)")
        else:
            s = Session()
        self.save_session(s)
        return s

    def save_session(self, s: Session):
        write_json(self.path("session.json"), s.to_dict())

    # ---------- 曲 ----------
    def load_chordbook(self) -> ChordBook:
        p = self.path("chordbook.json")
        if p.exists():
            return ChordBook.from_dict(self._expect(p, CHORD_FORMAT))
        old = self.path("chords.json")
        if old.exists():
            book = migrate.chordbook_from_v1(read_json(old))
            self._backup("chords.json")
            self.notes.append(f"今の版の曲(chords.json)を移しました。元は {OLD_DIR}/")
        else:
            book = ChordBook()
        self.save_chordbook(book)
        return book

    def save_chordbook(self, book: ChordBook):
        write_json(self.path("chordbook.json"), book.to_dict())

    # ---------- カートリッジの控え ----------
    def load_cart(self) -> CartMirror:
        p = self.path("cartridge.json")
        if not p.exists():
            cart = CartMirror()
            self.save_cart(cart)
            return cart
        d = read_json(p)
        if d.get("format") == CART_FORMAT:
            return CartMirror.from_dict(d)
        if migrate.is_v1_cart(d):
            cart = migrate.cart_from_v1(d)
            self._backup("cartridge.json")
            self.save_cart(cart)
            self.notes.append(f"カートリッジの控えを新しい形にしました(数値は変えていません。元は {OLD_DIR}/)")
            return cart
        raise StoreError(f"cartridge.json の形が分かりません(format={d.get('format')})。ファイルはそのままにしてあります")

    def save_cart(self, cart: CartMirror):
        """書き換えてよいのはカートリッジの書き込み部品だけ(6段目)"""
        write_json(self.path("cartridge.json"), cart.to_dict())

    # ---------- 設定 ----------
    def load_prefs(self, settings=None) -> Prefs:
        p = self.path("prefs.json")
        if p.exists():
            return Prefs.from_dict(self._expect(p, PREFS_FORMAT))
        prefs = migrate.prefs_from_v1(settings) if settings is not None else Prefs()
        self.save_prefs(prefs)
        return prefs

    def save_prefs(self, prefs: Prefs):
        write_json(self.path("prefs.json"), prefs.to_dict())

    # ---------- 実機の確認の結果 ----------
    def save_check(self, result: dict) -> Path:
        """user_data/checks/日時_名前.json"""
        d = self.user_dir / "checks"
        d.mkdir(parents=True, exist_ok=True)
        path = d / f"{datetime.now():%Y%m%d_%H%M%S}_{result.get('name', 'check')}.json"
        write_json(path, result)
        return path

    # ---------- バックアップ ----------
    def export_library(self, lib: Library, path: Path):
        write_json(Path(path), lib.to_dict())

    def read_backup(self, path: Path) -> Library:
        """バックアップ(新しい形)か今の版のライブラリを読む(取り込み用)"""
        d = read_json(Path(path))
        if d.get("format") == LIB_FORMAT:
            return Library.from_dict(d, self.spec)
        if migrate.is_v1_library(d):
            return migrate.library_from_v1(d, self.spec)
        raise StoreError("ライブラリのバックアップではありません")

    def _expect(self, p: Path, fmt):
        d = read_json(p)
        if d.get("format") != fmt:
            raise StoreError(f"{p.name} の形が分かりません(format={d.get('format')})。ファイルはそのままにしてあります")
        return d
