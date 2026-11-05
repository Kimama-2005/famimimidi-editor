"""曲(ChordBook、SPEC_v2 5.6)。全演奏セット共通で1冊。OtamaChord Studio のコードセットと同じ形。"""
from dataclasses import dataclass, field

FORMAT = "otamachord-set-v1"
SONGS = 12


@dataclass
class Song:
    name: str = ""
    key: int | None = None      # 0〜11 か None(自動推定)
    text: str = ""
    source: str = ""            # 取り込んだ ChordWiki のページ(保存した HTML)の場所。歌詞は表示するときだけここから読む

    def to_dict(self):
        d = {"name": self.name, "key": self.key, "text": self.text}
        if self.source:
            d["source"] = self.source
        return d

    @classmethod
    def from_dict(cls, d):
        d = d or {}
        key = d.get("key")
        key = int(key) % 12 if isinstance(key, (int, float)) and not isinstance(key, bool) else None
        return cls(str(d.get("name") or ""), key, str(d.get("text") or ""), str(d.get("source") or ""))


@dataclass
class ChordBook:
    name: str = "コードセット"
    songs: list = field(default_factory=lambda: [Song() for _ in range(SONGS)])
    common_row: list | None = None      # 4段目(全曲共通・キー C)の12個。None なら初期値

    def __post_init__(self):
        self.songs = (list(self.songs) + [Song() for _ in range(SONGS)])[:SONGS]
        if self.common_row is not None:
            row = [str(x or "") for x in self.common_row]
            self.common_row = (row + [""] * 12)[:12]

    def to_dict(self):
        # bass_floor はオタマ本体用。このアプリは使わず、書き出すときも null(オタマ側の値を上書きしない)
        return {"format": FORMAT, "name": self.name, "songs": [s.to_dict() for s in self.songs],
                "common_row": self.common_row, "bass_floor": None}

    @classmethod
    def from_dict(cls, d):
        if d.get("format") not in (FORMAT, None):
            raise ValueError(f"曲のファイルの形が違います: {d.get('format')}")
        return cls(str(d.get("name") or "コードセット"), [Song.from_dict(s) for s in d.get("songs") or []],
                   d.get("common_row"))
