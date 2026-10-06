"""data/famimimidi_spec.json の読み込みと、値の変換。"""
import json
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SPEC_PATH = ROOT / "data" / "famimimidi_spec.json"

# エディタ画面に出す kind(action / macro_ref はマクロ・書き込み系なので段階1では出さない)
EDITABLE_KINDS = ("continuous", "time_exp", "steps", "enum", "switch", "special")
HIDDEN_CCS = {49}   # マクロ切り替え。マクロ機能と一緒に扱う

CHANNEL_NAMES = {1: "パルス波1", 2: "パルス波2", 3: "三角波", 4: "ノイズ", 5: "DPCM/波形メモリ"}


@dataclass
class Param:
    cc: int
    name_ja: str
    channels: list
    kind: str
    default: int | None
    steps: int | None = None
    options: list | dict | None = None
    range_desc: str = ""
    note: str = ""
    raw: dict = field(default_factory=dict, repr=False)

    # --- 表示値 ⇔ 送信値 ---
    def step_labels(self):
        if isinstance(self.options, list) and len(self.options) == self.steps:
            return list(self.options)
        # 実装表の表記に合わせて 0 始まり(例: Sweep時間 既定値16 = 「1」、トレモロ・デプス 40 = 「5」)
        return [str(k) for k in range(self.steps)]

    def step_value(self, k):
        """段階k(0始まり)の中央値。docs/02: floor(k*128/N + 64/N)"""
        return (k * 128 + 64) // self.steps

    def step_index(self, value):
        return min(value * self.steps // 128, self.steps - 1)

    def enum_labels(self):
        return list(self.options) if isinstance(self.options, list) else []

    def switch_labels(self):
        if isinstance(self.options, list) and len(self.options) == 2:
            return self.options
        return ["OFF", "ON"]

    def format_value(self, v):
        """人が読む表記(例: デューティ 48 → "25%"、スイッチ 127 → "ON")"""
        if v is None:
            return "-"
        if self.kind == "steps":
            return self.step_labels()[self.step_index(v)]
        if self.kind == "enum" and isinstance(self.options, list):
            return self.options[min(v, len(self.options) - 1)]
        if self.kind == "switch":
            return self.switch_labels()[1 if v >= 64 else 0]
        return str(v)

    def hint(self):
        if self.kind == "time_exp":
            return "指数的に長くなる(127で約5秒)" if self.cc == 5 else "指数的に長くなる(127で約10秒)"
        return self.range_desc


def load_spec(path=SPEC_PATH):
    with open(path, encoding="utf-8") as f:
        spec = json.load(f)
    params = {}
    for p in spec["params"]:
        params[p["cc"]] = Param(
            cc=p["cc"], name_ja=p["name_ja"], channels=p["channels"], kind=p["kind"],
            default=p.get("default"), steps=p.get("steps"), options=p.get("options"),
            range_desc=p.get("range_desc", ""), note=p.get("note", ""), raw=p)
    return spec, params


def editable_params(params, channel):
    return [p for p in params.values()
            if channel in p.channels and p.kind in EDITABLE_KINDS and p.cc not in HIDDEN_CCS]


def describe(msg: bytes, params=None, ch_offset=0):
    """送信ログ用の日本語説明。ch は画面上の番号(1〜5)に直して表示する"""
    if not msg:
        return ""
    st = msg[0]
    if st == 0xF0:
        if len(msg) == 21 and msg[2:4] == b"\x70\x7F":
            return "SysEx 波形データ(ch5 波形メモリ)"
        if len(msg) == 6 and msg[2:4] == b"\x71\x7F":
            return f"SysEx 波形を PC{msg[4] + 1}(送信値{msg[4]})に登録"
        return "SysEx"
    if st > 0xF0:
        return {0xFE: "アクティブ・センシング", 0xF8: "クロック"}.get(st, f"システム {st:02X}")
    kind, ch = st & 0xF0, (st & 0x0F) + 1
    lch = ch - ch_offset
    chs = f"ch{ch}" if lch == ch else f"ch{ch}(音源ch{lch})"
    if kind == 0xB0 and len(msg) >= 3:
        name = params[msg[1]].name_ja if params and msg[1] in params else ""
        return f"{chs} CC#{msg[1]}={msg[2]} {name}".rstrip()
    if kind == 0xC0 and len(msg) >= 2:
        return f"{chs} PC{msg[1] + 1}(送信値{msg[1]})"
    if kind == 0x90 and len(msg) >= 3:
        return f"{chs} ノートON {msg[1]} vel{msg[2]}" if msg[2] else f"{chs} ノートOFF {msg[1]}"
    if kind == 0x80:
        return f"{chs} ノートOFF {msg[1]}"
    if kind == 0xE0 and len(msg) >= 3:
        return f"{chs} ピッチベンド {((msg[2] << 7) | msg[1]) - 8192}"
    if kind == 0xD0:
        return f"{chs} アフタータッチ {msg[1]}"
    if kind == 0xA0:
        return f"{chs} キー別アフタータッチ {msg[1]}={msg[2]}"
    return ""
