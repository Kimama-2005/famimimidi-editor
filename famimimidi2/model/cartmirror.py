"""カートリッジの控え(CartMirror、SPEC_v2 5.7)。

カートリッジの中身は読めないので、アプリが書いたことの記録がこれだけ。
**書き換えてよいのはカートリッジの書き込み部品だけ**(6段目で作る)。ここは型と JSON だけ。
"""
import copy
from dataclasses import dataclass, field

FORMAT = "famimimidi-cart-v1"
MACROS = range(1, 41)           # 保存場所 1〜40
PCS = range(89, 129)            # 呼び出し番号(送信値は -1)
WAVE_SLOTS = range(61, 77)
CHS = range(1, 6)
NEUTRAL_MACRO = 19              # 音量最大(空きの呼び出し番号の割り当て先)
SILENT_MACRO = 20               # テスト用の無音(予約)
ROLES = ("tone", "base", "neutral")


@dataclass
class MacroRecord:
    params: list | None = None  # 実際に記録した10個以内の CC。None は中身不明
    label: str = ""
    certain: bool = False       # False = 書いたはずだが失敗・途中で止まった = 中身不明
    from_: str = ""             # 元の音色の id(JSON では "from")
    role: str = "tone"          # "tone" / "base:N"(整えるの土台)/ "neutral"
    written: str = ""
    extra: dict = field(default_factory=dict)      # 知らない項目はそのまま残す

    def to_dict(self):
        return {**copy.deepcopy(self.extra), "params": copy.deepcopy(self.params), "label": self.label,
                "certain": self.certain, "from": self.from_, "role": self.role, "written": self.written}

    @classmethod
    def from_dict(cls, d):
        known = {"params", "label", "certain", "from", "role", "written"}
        return cls(copy.deepcopy(d.get("params")), d.get("label", ""), bool(d.get("certain", False)),
                   d.get("from", ""), d.get("role", "tone"), d.get("written", ""),
                   {k: copy.deepcopy(v) for k, v in d.items() if k not in known})


@dataclass
class CartMirror:
    macros: dict = field(default_factory=dict)      # 1〜40 -> MacroRecord
    pc_map: dict = field(default_factory=dict)      # 89〜128 -> マクロ番号か None
    startup: dict = field(default_factory=lambda: {ch: None for ch in CHS})
    waves: dict = field(default_factory=dict)       # 61〜76 -> {"name", "samples", "written"}
    history: list = field(default_factory=list)
    note: str = "カートリッジに書いた内容の、パソコン側の控え。カートリッジからは読み出せない"

    def macro_for_pc(self, pc):
        return self.pc_map.get(pc)

    def to_dict(self):
        return {"format": FORMAT, "note": self.note,
                "macros": {str(m): r.to_dict() for m, r in sorted(self.macros.items())},
                "pc_map": {str(pc): m for pc, m in sorted(self.pc_map.items())},
                "startup": {str(ch): m for ch, m in sorted(self.startup.items())},
                "waves": {str(n): copy.deepcopy(w) for n, w in sorted(self.waves.items())},
                "history": copy.deepcopy(self.history)}

    @classmethod
    def from_dict(cls, d):
        if d.get("format") != FORMAT:
            raise ValueError(f"カートリッジの控えのファイルの形が違います: {d.get('format')}")
        return cls({int(m): MacroRecord.from_dict(r) for m, r in (d.get("macros") or {}).items()},
                   {int(pc): m for pc, m in (d.get("pc_map") or {}).items()},
                   {**{ch: None for ch in CHS}, **{int(ch): m for ch, m in (d.get("startup") or {}).items()}},
                   {int(n): copy.deepcopy(w) for n, w in (d.get("waves") or {}).items()},
                   copy.deepcopy(d.get("history") or []), d.get("note") or cls.note)
