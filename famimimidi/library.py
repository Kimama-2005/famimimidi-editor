"""音色ライブラリ(user_data/library.json)。

2階建て(フェーズE): 1ch 分の「音色」(Patch)と、5ch 分の音色+鍵盤の割り当て表をまとめた「演奏セット」(PerfSet)。
セットの中の音色はコピーで持つ(元の音色を直してもセットは変わらない)。

音色の cc は「既定値(電源ON時の値)と違うものだけ」を、意味のある順に持つ。
読み込むときは「全項目を既定値にしてから cc を上書きし、全部送る」。
こうすると CC#121(リセット)を使わずに、前の音色の設定が残らない(CLAUDE.md の事実3)。
順序は段階3のマクロ化で「先頭10個」を決めるのに使う。
"""
import json
import os
import re
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path

from .spec import ROOT

LIBRARY_PATH = ROOT / "user_data" / "library.json"
SEED_PATH = ROOT / "data" / "patches.json"
# 音色に入れてはいけない CC(書き込み・マクロ実行・リセット類)
EXCLUDED_CCS = {45, 46, 47, 48, 49, 50, 51, 120, 121, 123}
CATEGORIES = ["lead", "backing", "bass", "drums", "fx", "other"]


def now_iso():
    return datetime.now().astimezone().isoformat(timespec="seconds")


@dataclass
class Patch:
    id: str
    name: str
    channel: int
    category: str = "other"
    cc: list = field(default_factory=list)     # [[cc, value], ...] 順序に意味がある
    notes: str = ""
    created: str = ""
    updated: str = ""
    source: str = ""                           # 取り込み元(例: data/patches.json)

    def cc_dict(self):
        return {c: v for c, v in self.cc}


@dataclass
class PerfSet:
    """演奏セット。parts は ch(文字列 "1"〜"5")→ {"name", "cc": [[cc, v]], "source": 元の音色の id}。
    play は鍵盤の割り当て表(play.py の pair / parts。mode は含めない)"""
    id: str
    name: str
    parts: dict = field(default_factory=dict)
    play: dict = field(default_factory=dict)
    notes: str = ""
    created: str = ""
    updated: str = ""

    def part_patch(self, ch):
        """ch の音色を Patch として(id は「セットid:ch」。ライブラリの音色とは別物)"""
        d = self.parts.get(str(ch)) or {}
        return Patch(id=f"{self.id}:{ch}", name=d.get("name") or f"{self.name} ch{ch}", channel=ch,
                     cc=[list(x) for x in d.get("cc", [])])


def clean_cc(pairs):
    """除外CCを外し、重複は後勝ちで1つにする(順序は最初に出た位置)。(残り, 外したCC番号) を返す"""
    order, values, removed = [], {}, []
    for c, v in pairs:
        c, v = int(c), int(v)
        if c in EXCLUDED_CCS:
            removed.append(c)
            continue
        if c not in values:
            order.append(c)
        values[c] = max(0, min(127, v))
    return [[c, values[c]] for c in order], removed


def diff_from_defaults(values: dict, params, previous_order=()):
    """画面の値 → 既定値と違う CC だけのリスト。前の順序を保ち、新しいものは CC 番号順で後ろに足す"""
    diff = {c: v for c, v in values.items() if params[c].default is None or v != params[c].default}
    head = [c for c in previous_order if c in diff]
    tail = sorted(c for c in diff if c not in head)
    return [[c, diff[c]] for c in head + tail]


def new_id(name):
    base = re.sub(r"[^0-9A-Za-z]+", "_", name).strip("_").lower()[:24]
    return f"{base or 'patch'}_{uuid.uuid4().hex[:6]}"


class Library:
    def __init__(self, path: Path = LIBRARY_PATH, seed: Path = SEED_PATH):
        self.path = path
        self.patches: list[Patch] = []
        self.sets: list[PerfSet] = []
        if path.exists():
            self.load()
        else:
            self.import_seed(seed)
            self.save()

    # ---------- ファイル ----------
    def load(self):
        with open(self.path, encoding="utf-8") as f:
            data = json.load(f)
        self.patches = [Patch(**p) for p in data.get("patches", [])]
        self.sets = [PerfSet(**d) for d in data.get("sets", [])]

    def save(self):
        """一時ファイルに書いてから置き換える(書き込み中に落ちても壊れない)"""
        self.path.parent.mkdir(exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(self._data(), f, ensure_ascii=False, indent=2)
        os.replace(tmp, self.path)

    def _data(self, patches=None, sets=None):
        return {"version": 2, "patches": [asdict(p) for p in (self.patches if patches is None else patches)],
                "sets": [asdict(d) for d in (self.sets if sets is None else sets)]}

    def import_seed(self, seed: Path):
        """data/patches.json(claude.ai で作った音色)を取り込む"""
        with open(seed, encoding="utf-8") as f:
            data = json.load(f)
        added = []
        for p in data.get("patches", []):
            cc, removed = clean_cc(p["cc"])
            notes = p.get("desc", "")
            if removed:
                notes += f"\n(取り込み時に CC#{', #'.join(map(str, sorted(set(removed))))} を除外。" \
                         "読み込み時は全項目を既定値にしてから送るので、リセットと同じ結果になる)"
            if p.get("macro_ready"):
                notes += "\n(マクロ用に10個へ絞った版。単体で読み込むと、共通の土台は既定値になる)"
            added.append(self.add(Patch(id=p["id"], name=p["name"], channel=p["channel"],
                                        category=p.get("category", "other"), cc=cc,
                                        notes=notes.strip(), source="data/patches.json"),
                                  save=False))
        return added

    def export(self, path: Path, patches=None):
        """バックアップ(音色と演奏セットの両方)"""
        with open(path, "w", encoding="utf-8") as f:
            json.dump(self._data(patches), f, ensure_ascii=False, indent=2)

    def import_file(self, path: Path):
        """書き出したファイルを取り込む。同じ id があれば別 id にして追加する(上書きしない)"""
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        added = []
        for d in data.get("patches", []):
            p = Patch(**d)
            p.cc, _ = clean_cc(p.cc)
            if self.get(p.id):
                p.id = new_id(p.name)
            added.append(self.add(p, save=False))
        for d in data.get("sets", []):
            ps = PerfSet(**d)
            for part in ps.parts.values():
                part["cc"], _ = clean_cc(part.get("cc", []))
            if self.get_set(ps.id):
                ps.id = new_id(ps.name)
            added.append(self.add_set(ps, save=False))
        self.save()
        return added

    # ---------- 操作 ----------
    def get(self, pid):
        return next((p for p in self.patches if p.id == pid), None)

    def add(self, patch: Patch, save=True):
        patch.created = patch.created or now_iso()
        patch.updated = patch.updated or patch.created
        self.patches.append(patch)
        if save:
            self.save()
        return patch

    def update(self, patch: Patch):
        patch.updated = now_iso()
        self.save()

    def delete(self, pid):
        self.patches = [p for p in self.patches if p.id != pid]
        self.save()

    # ---------- 演奏セット ----------
    def get_set(self, sid):
        return next((d for d in self.sets if d.id == sid), None)

    def add_set(self, ps: PerfSet, save=True):
        ps.created = ps.created or now_iso()
        ps.updated = ps.updated or ps.created
        self.sets.append(ps)
        if save:
            self.save()
        return ps

    def update_set(self, ps: PerfSet):
        ps.updated = now_iso()
        self.save()

    def delete_set(self, sid):
        self.sets = [d for d in self.sets if d.id != sid]
        self.save()
