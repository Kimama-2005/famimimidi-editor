"""演奏セット(Performance、SPEC_v2 5.3〜5.5)。ふぁみみみっでぃ全体を1つの楽器としてどう鳴らすか。

- slots: ch1〜ch5 の音色(コピー)。from は元の音色の id(表示用)
- link12: ch1 と ch2 の紐付け。紐付け中は slots[2].kept に ch2 の音色を保管する
- keyboard: 割り当て表(コードモードが OFF のときの振り分け)
- controls: ペダル・レバー
- chord: コードモードの設定と ON/OFF

ここは純粋な計算だけ(送らない)。操作の関数は「変わった ch」を返すので、アプリはその ch を送り直す。
"""
import copy
from dataclasses import dataclass, field

from ..music.spec import CH_KIND, CHS, Spec
from .common import ch_keys, clamp, now_iso
from .tone import Tone, blank_tone

# ---------------------------------------------------------------- 割り当て表(5.4)
PAIRS = ("off", "poly", "layer")
SHIFTS = (-24, -12, 0, 12, 24)
SPLIT = 60          # ひな形の境目 C4
TEMPLATES = {
    "ch1": "ch1 だけ",
    "poly": "ポリ(2音)",
    "unison": "ユニゾン",
    "bass_melody": "ベース+メロディ",
    "bass_poly": "ベース+ポリ",
    "bass_unison": "ベース+ユニゾン",
}


@dataclass
class Part:
    on: bool = False
    lo: int = 0
    hi: int = 127
    shift: int = 0

    def normalized(self):
        lo, hi = sorted((clamp(self.lo, 0, 127), clamp(self.hi, 0, 127)))
        shift = min(SHIFTS, key=lambda s: abs(s - int(self.shift)))
        return Part(bool(self.on), lo, hi, shift)


@dataclass
class KeyboardMap:
    pair: str = "off"
    parts: dict = field(default_factory=lambda: {ch: Part(on=(ch == 1)) for ch in CHS})

    def normalized(self):
        parts = {ch: (self.parts.get(ch) or Part()).normalized() for ch in CHS}
        return KeyboardMap(self.pair if self.pair in PAIRS else "off", parts)

    def used_chs(self):
        """音を鳴らす ch(ポリ・ユニゾンなら ch2 も)"""
        out = []
        for ch in CHS:
            if ch == 2 and self.pair != "off":
                if self.parts[1].on:
                    out.append(2)
                continue
            if self.parts[ch].on:
                out.append(ch)
        return out

    def to_dict(self):
        return {"pair": self.pair,
                "parts": {str(ch): {"on": p.on, "lo": p.lo, "hi": p.hi, "shift": p.shift} for ch, p in self.parts.items()}}

    @classmethod
    def from_dict(cls, d):
        d = d or {}
        given = ch_keys(d.get("parts"))
        parts = {}
        for ch in CHS:
            g = given.get(ch) or {}
            parts[ch] = Part(**{k: g[k] for k in ("on", "lo", "hi", "shift") if k in g}) if g else Part(on=(ch == 1))
        return cls(d.get("pair", "off"), parts).normalized()

    @classmethod
    def template(cls, name):
        if name not in TEMPLATES:
            raise ValueError(f"ひな形がありません: {name}")
        parts = {ch: Part() for ch in CHS}
        bass = name.startswith("bass_")
        parts[1] = Part(on=True, lo=SPLIT if bass else 0, hi=127)
        if bass:
            parts[3] = Part(on=True, lo=0, hi=SPLIT - 1)
        pair = {"poly": "poly", "bass_poly": "poly", "unison": "layer", "bass_unison": "layer"}.get(name, "off")
        return cls(pair, parts)


# ---------------------------------------------------------------- ペダル・レバー(5.3.5)
PEDAL_USES = ("hold", "off")
MOD_USES = ("vibrato", "duty", "expression")
BEND_RANGES = (2, 7, 12)
MOD_CC = {"vibrato": 1, "duty": 70, "expression": 11}     # レバーの値をアプリが置き換えて送る先


def _chs(v):
    return sorted({int(c) for c in (v or []) if int(c) in CHS})


@dataclass
class Controls:
    pedal_to: list = field(default_factory=lambda: [1])
    pedal_use: str = "hold"
    bend_to: list = field(default_factory=lambda: [1])
    bend_range: int = 2
    mod_to: list = field(default_factory=lambda: [1])
    mod_use: str = "vibrato"

    def normalized(self):
        return Controls(_chs(self.pedal_to), self.pedal_use if self.pedal_use in PEDAL_USES else "hold",
                        _chs(self.bend_to), min(BEND_RANGES, key=lambda r: abs(r - int(self.bend_range))),
                        _chs(self.mod_to), self.mod_use if self.mod_use in MOD_USES else "vibrato")

    def to_dict(self):
        return {"pedal": {"to": list(self.pedal_to), "use": self.pedal_use},
                "bend": {"to": list(self.bend_to), "range": self.bend_range},
                "mod": {"to": list(self.mod_to), "use": self.mod_use}}

    @classmethod
    def from_dict(cls, d):
        d = d or {}
        p, b, m = d.get("pedal") or {}, d.get("bend") or {}, d.get("mod") or {}
        c = cls()
        return cls(p.get("to", c.pedal_to), p.get("use", c.pedal_use), b.get("to", c.bend_to),
                   b.get("range", c.bend_range), m.get("to", c.mod_to), m.get("use", c.mod_use)).normalized()

    @classmethod
    def defaults_for(cls, keyboard: KeyboardMap, keep: "Controls | None" = None):
        """割り当て表から既定の送り先を決める。働き(use・range)は keep のものを残す

        ベンド・モジュレーション = 鍵域が一番高い ch(メロディ)と、ポリ・ユニゾンでつながる ch。ペダル = 使っている ch すべて
        """
        used = keyboard.used_chs()
        cands = [ch for ch in used if not (ch == 2 and keyboard.pair != "off")]
        melody = []
        if cands:
            top = max(cands, key=lambda ch: (keyboard.parts[ch].hi, keyboard.parts[ch].lo, -ch))
            melody = [top] + ([2] if top == 1 and keyboard.pair != "off" else [])
        keep = keep or cls()
        return cls(used, keep.pedal_use, melody, keep.bend_range, melody, keep.mod_use).normalized()


# ---------------------------------------------------------------- コードモードの設定(5.5)
LAYOUTS = ("song", "degree_r", "degree_l")   # オタマ互換・規則性重視は 2026-11-06 になくした(読むと "song" になる)
METHODS = ("split", "arp")
STYLES = ("piano", "organ", "strum", "pad")
BASS_RANGES = ("low", "mid")
# 奏法プリセットの中の値(画面には出さない)。strum_order 0 = 下から、1 = 上から
STYLE_VALUES = {
    "piano": {"strum_order": 0, "strum_change": True, "release_ms": 40, "jitter_ms": 6, "retrigger": True},
    "organ": {"strum_order": 0, "strum_change": False, "release_ms": 0, "jitter_ms": 0, "retrigger": False},
    "strum": {"strum_order": 1, "strum_change": True, "release_ms": 60, "jitter_ms": 4, "retrigger": True},
    "pad": {"strum_order": 0, "strum_change": True, "release_ms": 300, "jitter_ms": 10, "retrigger": True},
}
GRACE_MS = 80       # つなぎの猶予(固定)


@dataclass
class ChordSettings:
    active: bool = False
    layout: str = "song"
    method: str = "split"
    style: str = "piano"
    spread: int = 30
    bass: str = "low"
    glide: bool = False

    def normalized(self):
        return ChordSettings(bool(self.active), self.layout if self.layout in LAYOUTS else "song",
                             self.method if self.method in METHODS else "split",
                             self.style if self.style in STYLES else "piano", clamp(self.spread, 0, 500),
                             self.bass if self.bass in BASS_RANGES else "low", bool(self.glide))

    def to_dict(self):
        return {"active": self.active, "layout": self.layout, "method": self.method, "style": self.style,
                "spread": self.spread, "bass": self.bass, "glide": self.glide}

    @classmethod
    def from_dict(cls, d):
        d = d or {}
        return cls(**{k: d[k] for k in ("active", "layout", "method", "style", "spread", "bass", "glide")
                      if k in d}).normalized()

    def engine_values(self):
        """コードモードの中で使う値(プリセット+自動で決めるもの)"""
        v = dict(STYLE_VALUES[self.style])
        if self.glide:
            v["retrigger"] = False          # すべらせるため打ち直さない
        bass_floor = 36 if self.bass == "low" else 48
        upper = (60, 84) if self.bass == "low" else (72, 96)
        return {**v, "strum_ms": self.spread, "grace_ms": GRACE_MS, "bass_floor": bass_floor,
                "upper_lo": upper[0], "upper_hi": upper[1], "arp_ch": 1, "three_octaves": True,
                "method": self.method, "layout": self.layout, "glide": self.glide}


# ---------------------------------------------------------------- 演奏セット
@dataclass
class Slot:
    tone: Tone
    from_: str = ""                 # JSON では "from"
    kept: "Slot | None" = None      # 紐付け中の ch2 だけ。保管している ch2 の音色

    def to_dict(self):
        d = {"tone": self.tone.to_dict(with_id=False), "from": self.from_}
        if self.kept is not None:
            d["kept"] = {"tone": self.kept.tone.to_dict(with_id=False), "from": self.kept.from_}
        return d

    @classmethod
    def from_dict(cls, d, kind, spec: Spec | None = None):
        d = d or {}
        tone = _slot_tone(d.get("tone"), kind, spec)
        kept = None
        if d.get("kept"):
            kept = cls(_slot_tone(d["kept"].get("tone"), kind, spec), d["kept"].get("from", ""))
        return cls(tone, d.get("from", ""), kept)


def _slot_tone(d, kind, spec):
    if not d:
        return blank_tone(kind)
    d = {**d, "id": ""}
    if d.get("kind", kind) != kind:
        raise ValueError(f"音色の種類が ch と合いません({d.get('kind')} を {kind} の ch に)")
    d["kind"] = kind
    return Tone.from_dict(d, spec)


@dataclass
class Performance:
    name: str = ""
    id: str = ""
    notes: str = ""
    slots: dict = field(default_factory=lambda: {ch: Slot(blank_tone(CH_KIND[ch])) for ch in CHS})
    link12: bool = False
    keyboard: KeyboardMap = field(default_factory=KeyboardMap)
    controls: Controls = field(default_factory=Controls)
    chord: ChordSettings = field(default_factory=ChordSettings)
    created: str = ""
    updated: str = ""
    # マスターボリューム(0〜127)。5ch の音量 CC#7 に「× 値 / 127」で掛けて送る(音色の値は変えない)。
    # 割り当て表で弾くとき(map)とコードで弾くとき(chord)で別々。コードは4つの ch が重なって大きいので初期値は半分
    master_map: int = 127
    master_chord: int = 64

    def __post_init__(self):
        self.validate()

    def validate(self):
        if set(self.slots) != set(CHS):
            raise ValueError("演奏セットは ch1〜ch5 の5つの音色を必ず持ちます")
        for ch, s in self.slots.items():
            if s.tone.kind != CH_KIND[ch]:
                raise ValueError(f"ch{ch} の音色の種類が合いません: {s.tone.kind}")
            if s.kept is not None and ch != 2:
                raise ValueError("保管できるのは紐付け中の ch2 の音色だけです")

    # ---------- 音色 ----------
    def tone(self, ch) -> Tone:
        return self.slots[ch].tone

    def linked_chs(self, ch):
        """ch の音色を変えると一緒に変わる ch"""
        return [1, 2] if self.link12 and ch in (1, 2) else [ch]

    def put_tone(self, ch, tone: Tone, from_id=""):
        """音色を ch に入れる(コピー)。紐付け中の ch1・ch2 は両方に。変わった ch を返す"""
        if tone.kind != CH_KIND[ch]:
            raise ValueError(f"{tone.kind} の音色は ch{ch} に入れられません")
        chs = self.linked_chs(ch)
        for c in chs:
            t = tone.copy()
            t.id = ""
            self.slots[c].tone, self.slots[c].from_ = t, from_id
        return chs

    def set_param(self, ch, cc, value, spec: Spec):
        chs = self.linked_chs(ch)
        for c in chs:
            self.slots[c].tone.set_param(cc, value, spec)
        return chs

    def set_wave(self, samples):
        t = self.slots[5].tone
        t.wave = list(samples) if samples is not None else None
        t.__post_init__()
        return [5]

    def reset_tone(self, ch):
        """初期化(既定値だけにする)"""
        return self.put_tone(ch, blank_tone(CH_KIND[ch], ""), "")

    # ---------- 紐付け(5.3.3) ----------
    def set_link12(self, on: bool):
        """紐付ける: ch2 の音色を保管し、ch2 も ch1 の音色で鳴らす。外す: 保管していた音色に戻す。変わった ch を返す"""
        if bool(on) == self.link12:
            return []
        s2 = self.slots[2]
        if on:
            kept = Slot(s2.tone, s2.from_)
            t = self.slots[1].tone.copy()
            self.slots[2] = Slot(t, self.slots[1].from_, kept)
        else:
            if s2.kept is not None:
                self.slots[2] = Slot(s2.kept.tone, s2.kept.from_)
            else:
                self.slots[2] = Slot(s2.tone, s2.from_)
        self.link12 = bool(on)
        return [2]

    # ---------- 割り当て表・ペダル・レバー ----------
    def set_keyboard(self, keyboard: KeyboardMap):
        """割り当て表を変える。ポリ(2音)なら自動で紐付け、ペダル・レバーの送り先を付け直す。変わった ch を返す"""
        self.keyboard = keyboard.normalized()
        changed = self.set_link12(True) if self.keyboard.pair == "poly" else []
        self.controls = Controls.defaults_for(self.keyboard, self.controls)
        return changed

    def apply_template(self, name):
        return self.set_keyboard(KeyboardMap.template(name))

    # ---------- JSON ----------
    def to_dict(self):
        return {"id": self.id, "name": self.name, "notes": self.notes,
                "slots": {str(ch): self.slots[ch].to_dict() for ch in CHS}, "link12": self.link12,
                "keyboard": self.keyboard.to_dict(), "controls": self.controls.to_dict(),
                "chord": self.chord.to_dict(), "master": {"map": self.master_map, "chord": self.master_chord},
                "created": self.created, "updated": self.updated}

    @classmethod
    def from_dict(cls, d, spec: Spec | None = None):
        given = ch_keys(d.get("slots"))
        slots = {ch: Slot.from_dict(given.get(ch), CH_KIND[ch], spec) for ch in CHS}
        return cls(name=d.get("name", ""), id=d.get("id", ""), notes=d.get("notes", ""), slots=slots,
                   link12=bool(d.get("link12", False)), keyboard=KeyboardMap.from_dict(d.get("keyboard")),
                   controls=Controls.from_dict(d.get("controls")), chord=ChordSettings.from_dict(d.get("chord")),
                   created=d.get("created", ""), updated=d.get("updated", ""),
                   master_map=clamp((d.get("master") or {}).get("map", 127), 0, 127),
                   master_chord=clamp((d.get("master") or {}).get("chord", 64), 0, 127))

    def copy(self):
        return copy.deepcopy(self)

    def touch(self):
        self.updated = now_iso()
        if not self.created:
            self.created = self.updated
