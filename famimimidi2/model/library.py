"""ライブラリ(user_data/library.json)。音色の一覧と演奏セットの一覧(SPEC_v2 5.0)。

中に入れるのはいつもコピー(ライブラリの元を直しても、演奏セットや作業中の演奏は変わらない)。
保存はアプリが store を通して行う(ここはファイルを触らない)。
"""
from dataclasses import dataclass, field

from ..music.spec import Spec
from .common import new_id
from .performance import Performance
from .tone import Tone

FORMAT = "famimimidi-library-v1"


@dataclass
class Library:
    tones: list = field(default_factory=list)
    performances: list = field(default_factory=list)

    # ---------- 音色 ----------
    def tone(self, tid) -> Tone | None:
        return next((t for t in self.tones if t.id == tid), None)

    def tones_of(self, kind):
        return [t for t in self.tones if t.kind == kind]

    def add_tone(self, tone: Tone, name=None) -> Tone:
        """新しく保存(コピーして新しい id)"""
        t = tone.copy()
        if name is not None:
            t.name = name
        t.id = self._free_id(t.id, t.name, "tone", self.tone)
        t.created = t.updated = ""
        t.touch()
        self.tones.append(t)
        return t

    def overwrite_tone(self, tid, tone: Tone) -> Tone:
        """上書き保存(id・名前・作った日は元のまま)"""
        old = self.tone(tid)
        if old is None:
            raise KeyError(tid)
        if old.kind != tone.kind:
            raise ValueError("種類の違う音色には上書きできません")
        t = tone.copy()
        t.id, t.name, t.created = old.id, old.name, old.created
        t.touch()
        self.tones[self.tones.index(old)] = t
        return t

    def rename_tone(self, tid, name):
        t = self.tone(tid)
        t.name = name
        t.touch()
        return t

    def delete_tone(self, tid):
        self.tones = [t for t in self.tones if t.id != tid]

    # ---------- 演奏セット ----------
    def performance(self, pid) -> Performance | None:
        return next((p for p in self.performances if p.id == pid), None)

    def add_performance(self, perf: Performance, name=None) -> Performance:
        p = perf.copy()
        if name is not None:
            p.name = name
        p.id = self._free_id(p.id, p.name, "set", self.performance)
        p.created = p.updated = ""
        p.touch()
        self.performances.append(p)
        return p

    def overwrite_performance(self, pid, perf: Performance) -> Performance:
        old = self.performance(pid)
        if old is None:
            raise KeyError(pid)
        p = perf.copy()
        p.id, p.name, p.created = old.id, old.name, old.created
        p.touch()
        self.performances[self.performances.index(old)] = p
        return p

    def rename_performance(self, pid, name):
        p = self.performance(pid)
        p.name = name
        p.touch()
        return p

    def delete_performance(self, pid):
        self.performances = [p for p in self.performances if p.id != pid]

    # ---------- 取り込み ----------
    def merge(self, other: "Library"):
        """バックアップの取り込み。同じ id があれば新しい id にして足す(上書きしない)"""
        added = []
        for t in other.tones:
            t = t.copy()
            if self.tone(t.id) or not t.id:
                t.id = new_id(t.name, "tone")
            self.tones.append(t)
            added.append(t)
        for p in other.performances:
            p = p.copy()
            if self.performance(p.id) or not p.id:
                p.id = new_id(p.name, "set")
            self.performances.append(p)
            added.append(p)
        return added

    @staticmethod
    def _free_id(current, name, prefix, getter):
        if current and getter(current) is None:
            return current
        while True:
            i = new_id(name, prefix)
            if getter(i) is None:
                return i

    # ---------- JSON ----------
    def to_dict(self):
        return {"format": FORMAT, "tones": [t.to_dict() for t in self.tones],
                "performances": [p.to_dict() for p in self.performances]}

    @classmethod
    def from_dict(cls, d, spec: Spec | None = None):
        if d.get("format") != FORMAT:
            raise ValueError(f"ライブラリのファイルの形が違います: {d.get('format')}")
        return cls([Tone.from_dict(t, spec) for t in d.get("tones", [])],
                   [Performance.from_dict(p, spec) for p in d.get("performances", [])])
