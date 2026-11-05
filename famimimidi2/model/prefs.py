"""アプリの設定(Prefs、SPEC_v2 5.8)。演奏と関係ないものだけ(接続・ch のずれ・テーマ)。"""
from dataclasses import dataclass

FORMAT = "famimimidi-prefs-v1"
THEMES = ("rpg", "console", "crt")
OFFSETS = (0, 5, 10)


@dataclass
class Prefs:
    out_name: str = ""
    in_name: str = ""
    ch_offset: int = 0
    theme: str = "rpg"
    kb_follow: bool = False     # 1〜5 のタブでも、外部の鍵盤は演奏セットどおり(割り当て表・コードモード)に鳴らす

    def __post_init__(self):
        self.ch_offset = int(self.ch_offset) if int(self.ch_offset) in OFFSETS else 0
        self.theme = self.theme if self.theme in THEMES else "rpg"
        self.kb_follow = bool(self.kb_follow)

    def to_dict(self):
        return {"format": FORMAT, "out_name": self.out_name, "in_name": self.in_name,
                "ch_offset": self.ch_offset, "theme": self.theme, "kb_follow": self.kb_follow}

    @classmethod
    def from_dict(cls, d):
        return cls(**{k: d[k] for k in ("out_name", "in_name", "ch_offset", "theme", "kb_follow") if k in d and d[k] is not None})
