"""作業中の演奏(Session、SPEC_v2 5.3.2)。いま画面で触っている演奏セット。アプリを閉じても残る。

- performance は画面の値そのもの。アプリが最後に送った値の控えも兼ねる(カートリッジは読めないので)
- 鍵盤の受け方は保存しない(いる場所で決まる)
"""
from dataclasses import dataclass, field

from ..music.spec import Spec
from .performance import Performance

FORMAT = "famimimidi-session-v1"


@dataclass
class Session:
    performance: Performance = field(default_factory=Performance)
    loaded_from: str = ""
    dirty: bool = False

    # ---------- ライブラリとのやりとり ----------
    def load(self, perf: Performance):
        """ライブラリの演奏セットを読み込む(コピー)。送るのはアプリ"""
        self.performance = perf.copy()
        self.loaded_from = perf.id
        self.dirty = False

    def snapshot(self, name=None, id_=None) -> Performance:
        """ライブラリに保存するためのコピー"""
        p = self.performance.copy()
        if name is not None:
            p.name = name
        if id_ is not None:
            p.id = id_
        return p

    def saved_as(self, perf: Performance):
        """ライブラリに保存したあと"""
        self.performance.id, self.performance.name = perf.id, perf.name
        self.performance.created, self.performance.updated = perf.created, perf.updated
        self.loaded_from = perf.id
        self.dirty = False

    def changed(self, chs=None):
        self.dirty = True
        return chs

    # ---------- 関所への答え ----------
    def is_silent(self, ch, spec: Spec):
        """音量(CC#7)かエクスプレッション(CC#11)が 0 か(関所がノートオンを省くのに使う)"""
        t = self.performance.tone(ch)
        return t.value(7, spec) == 0 or t.value(11, spec) == 0

    # ---------- JSON ----------
    def to_dict(self):
        return {"format": FORMAT, "performance": self.performance.to_dict(),
                "loaded_from": self.loaded_from, "dirty": self.dirty}

    @classmethod
    def from_dict(cls, d, spec: Spec | None = None):
        if d.get("format") != FORMAT:
            raise ValueError(f"作業中の演奏のファイルの形が違います: {d.get('format')}")
        return cls(Performance.from_dict(d.get("performance") or {}, spec), d.get("loaded_from", ""),
                   bool(d.get("dirty", False)))
