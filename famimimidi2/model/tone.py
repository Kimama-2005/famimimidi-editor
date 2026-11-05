"""音色(Tone、SPEC_v2 5.2)。1つの ch で鳴らす音の設定。

- params は「既定値と違う CC だけ」を意味のある順で持つ(カートリッジに入れるときの優先の手がかり)
- kind はどの種類の ch 用か(パルス用は ch1・ch2 のどちらにも入る)
- ch に入れるときは、その種類の全項目を既定値にしてから params で上書きして全部送る(CC#121 は使わない)
"""
import copy
from dataclasses import dataclass, field

from ..device import sysex
from ..music.spec import KINDS, NOT_TONE_CCS, Spec
from .common import now_iso

CATEGORIES = ("lead", "backing", "bass", "drums", "fx", "other")

# カートリッジに入れるときの重要度(SPEC 5.3.4)。表に無いものは後ろ(元の順)
IMPORTANCE = [70, 23, 24, 79, 75, 72, 1, 78, 73, 65, 12, 92, 25, 26, 27, 76, 77, 86, 87, 5, 81, 85, 88, 89,
              80, 84, 83, 21, 22, 9, 13, 14, 15, 16, 30, 3, 2]
MACRO_CAPACITY = 10      # ユーザーマクロに記録できるのは先頭10個の CC まで(事実1)


def clean_params(pairs, kind, spec: Spec):
    """params を決まりどおりにそろえる。(そろえた params, 外した CC 番号の並び) を返す

    - 書き込み系・リセット系・演奏セットが持つ CC・演奏中に動かす値、この種類に無い CC は外す
    - 同じ CC は1回だけ(位置は最初に出たところ、値は後の方)
    - 値は 0〜127。既定値と同じものは外す
    """
    order, values, removed = [], {}, []
    for c, v in pairs or []:
        c, v = int(c), max(0, min(127, int(v)))
        if c in NOT_TONE_CCS or not spec.is_tone_cc(c, kind):
            removed.append(c)
            continue
        if c not in values:
            order.append(c)
        values[c] = v
    out = []
    for c in order:
        if values[c] == spec.default(c):
            continue
        out.append([c, values[c]])
    return out, removed


@dataclass
class Tone:
    name: str
    kind: str
    params: list = field(default_factory=list)      # [[CC, 値], ...] 既定値と違うものだけ。順に意味がある
    wave: list | None = None                         # kind = dpcm_wave のときだけ。None なら「波形は今のまま」
    category: str = "other"
    notes: str = ""
    source: str = ""
    id: str = ""
    created: str = ""
    updated: str = ""

    def __post_init__(self):
        if self.kind not in KINDS:
            raise ValueError(f"音色の種類が正しくありません: {self.kind}")
        if self.category not in CATEGORIES:
            self.category = "other"
        if self.wave is not None:
            if self.kind != "dpcm_wave":
                raise ValueError("波形を持てるのは DPCM/波形(ch5)の音色だけです")
            self.wave = sysex.check_samples(self.wave)
        self.params = [[int(c), int(v)] for c, v in self.params]

    # ---------- 値 ----------
    def value(self, cc, spec: Spec):
        """この音色を入れたときの CC の値(params に無ければ既定値)"""
        for c, v in self.params:
            if c == cc:
                return v
        return spec.default(cc)

    def values(self, spec: Spec):
        """全項目の値(CC 番号順の dict)= 既定値を params で上書きしたもの"""
        vals = spec.tone_defaults(self.kind)
        for c, v in self.params:
            vals[c] = v
        return vals

    def set_param(self, cc, value, spec: Spec):
        """1つの項目を変える。既定値に戻したら params から外す。新しい項目は後ろに足す"""
        cc, value = int(cc), max(0, min(127, int(value)))
        if not spec.is_tone_cc(cc, self.kind):
            raise ValueError(f"CC#{cc} はこの音色に入れない項目です")
        idx = next((i for i, (c, _) in enumerate(self.params) if c == cc), None)
        if value == spec.default(cc):
            if idx is not None:
                del self.params[idx]
        elif idx is None:
            self.params.append([cc, value])
        else:
            self.params[idx][1] = value

    def normalize(self, spec: Spec):
        self.params, removed = clean_params(self.params, self.kind, spec)
        return removed

    # ---------- カートリッジ ----------
    def macro_params(self, spec: Spec, capacity=MACRO_CAPACITY):
        """カートリッジの保存場所に入れる10個(重要度順、SPEC 5.3.4)。既定値と同じものは除く"""
        diff = [[c, v] for c, v in self.params if v != spec.default(c)]
        rank = {c: i for i, c in enumerate(IMPORTANCE)}
        diff.sort(key=lambda cv: rank.get(cv[0], len(IMPORTANCE)))     # sort は安定なので表に無いものは元の順
        return diff[:capacity], diff[capacity:]

    # ---------- JSON ----------
    def to_dict(self, with_id=True):
        d = {"id": self.id, "name": self.name, "kind": self.kind, "params": [list(p) for p in self.params],
             "wave": list(self.wave) if self.wave is not None else None, "category": self.category,
             "notes": self.notes, "source": self.source, "created": self.created, "updated": self.updated}
        if not with_id:
            del d["id"]
        return d

    @classmethod
    def from_dict(cls, d, spec: Spec | None = None):
        keys = ("id", "name", "kind", "params", "wave", "category", "notes", "source", "created", "updated")
        kw = {k: copy.deepcopy(d[k]) for k in keys if k in d and (d[k] is not None or k == "wave")}
        t = cls(**kw)
        if spec is not None:
            t.normalize(spec)
        return t

    def copy(self):
        return copy.deepcopy(self)

    def touch(self):
        self.updated = now_iso()
        if not self.created:
            self.created = self.updated


def blank_tone(kind, name=""):
    """既定値だけの音色(params が空)"""
    return Tone(name=name, kind=kind)


def load_messages(ch_values: dict):
    """全項目の値 {CC: 値} → 送る (CC, 値) の並び。CC#18(波形メモリモード)は先に送り、波形データがその後に効くようにする"""
    items = sorted(ch_values.items(), key=lambda cv: (cv[0] != 18, cv[0]))
    return items
