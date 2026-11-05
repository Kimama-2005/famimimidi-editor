"""実装表(data/famimimidi_spec.json)の読み込みと、音色に関わる CC の決まり。

一次資料は JSON。ここでは「どの ch の音色に、どの CC が入るか」と「既定値(電源 ON の値)」を引けるようにする。
"""
import json
from dataclasses import dataclass, field
from functools import lru_cache

from ..paths import SPEC_PATH

CHS = (1, 2, 3, 4, 5)
CH_KIND = {1: "pulse", 2: "pulse", 3: "triangle", 4: "noise", 5: "dpcm_wave"}
KINDS = ("pulse", "triangle", "noise", "dpcm_wave")
KIND_CH = {"pulse": 1, "triangle": 3, "noise": 4, "dpcm_wave": 5}     # その種類の代表の ch(既定値・項目を引くため)
KIND_NAMES = {"pulse": "パルス", "triangle": "三角波", "noise": "ノイズ", "dpcm_wave": "DPCM/波形"}
CH_NAMES = {1: "パルス1", 2: "パルス2", 3: "三角波", 4: "ノイズ", 5: "DPCM/波形メモリ"}

# 音色に入れてよい種類(action / macro_ref は書き込み・マクロ系)
TONE_KINDS = ("continuous", "time_exp", "steps", "enum", "switch", "special")
# 書き込み系・リセット系(SPEC 5.2)
WRITE_RESET_CCS = frozenset({45, 46, 47, 48, 49, 50, 51, 120, 121, 123})
# 演奏セットが持つ CC(#82 ベンド幅、#20 CC#1⇔#70 入替)と、演奏中に動かす値(#2 ブレス、#64 ホールド1、#84 ポルタメント・コントロール)
PERFORMANCE_CCS = frozenset({82, 20})
PLAYING_CCS = frozenset({2, 64, 84})
NOT_TONE_CCS = WRITE_RESET_CCS | PERFORMANCE_CCS | PLAYING_CCS


@dataclass(frozen=True)
class Param:
    cc: int
    name_ja: str
    channels: tuple
    kind: str
    default: int | None
    steps: int | None = None
    options: object = None
    raw: dict = field(default_factory=dict, compare=False, hash=False, repr=False)


class Spec:
    def __init__(self, data: dict):
        self.data = data
        self.params: dict[int, Param] = {}
        for p in data["params"]:
            self.params[p["cc"]] = Param(cc=p["cc"], name_ja=p["name_ja"], channels=tuple(p["channels"]),
                                         kind=p["kind"], default=p.get("default"), steps=p.get("steps"),
                                         options=p.get("options"), raw=p)

    def name(self, cc):
        p = self.params.get(cc)
        return p.name_ja if p else ""

    def default(self, cc):
        p = self.params.get(cc)
        return p.default if p else None

    def is_tone_cc(self, cc, kind):
        """kind の音色に入れてよい CC か"""
        p = self.params.get(cc)
        return (p is not None and cc not in NOT_TONE_CCS and p.kind in TONE_KINDS
                and p.default is not None and KIND_CH[kind] in p.channels)

    def tone_ccs(self, kind):
        """kind の音色の全項目(CC 番号順)。音色を ch に入れるときは、これを全部既定値にしてから params で上書きする"""
        return [cc for cc in sorted(self.params) if self.is_tone_cc(cc, kind)]

    def tone_defaults(self, kind):
        return {cc: self.params[cc].default for cc in self.tone_ccs(kind)}


@lru_cache(maxsize=1)
def load_spec(path=SPEC_PATH) -> Spec:
    with open(path, encoding="utf-8") as f:
        return Spec(json.load(f))


def describe(msg: bytes, spec: Spec | None = None, ch_offset=0):
    """送信ログ用の日本語の説明。ch は画面の番号(1〜5)も添える"""
    if not msg:
        return ""
    st = msg[0]
    if st == 0xF0:
        if len(msg) == 21 and msg[2:4] == b"\x70\x7F":
            return "SysEx 波形データ(ch5 波形メモリ。その場で鳴らす)"
        if len(msg) == 6 and msg[2:4] == b"\x71\x7F":
            return f"SysEx 波形を登録 {msg[4] + 1}(送信値{msg[4]})"
        return "SysEx"
    if st > 0xF0:
        return {0xFE: "アクティブ・センシング", 0xF8: "クロック"}.get(st, f"システム {st:02X}")
    kind, ch = st & 0xF0, (st & 0x0F) + 1
    lch = ch - ch_offset
    chs = f"ch{ch}" if lch == ch else f"ch{ch}(音源ch{lch})"
    if kind == 0xB0 and len(msg) >= 3:
        return f"{chs} CC#{msg[1]}={msg[2]} {spec.name(msg[1]) if spec else ''}".rstrip()
    if kind == 0xC0 and len(msg) >= 2:
        return f"{chs} 呼び出し番号{msg[1] + 1}(PC 送信値{msg[1]})"
    if kind == 0x90 and len(msg) >= 3:
        return f"{chs} ノートON {msg[1]} 強さ{msg[2]}" if msg[2] else f"{chs} ノートOFF {msg[1]}"
    if kind == 0x80 and len(msg) >= 2:
        return f"{chs} ノートOFF {msg[1]}"
    if kind == 0xE0 and len(msg) >= 3:
        return f"{chs} ピッチベンド {((msg[2] << 7) | msg[1]) - 8192}"
    if kind == 0xD0 and len(msg) >= 2:
        return f"{chs} アフタータッチ {msg[1]}"
    if kind == 0xA0 and len(msg) >= 3:
        return f"{chs} キー別アフタータッチ {msg[1]}={msg[2]}"
    return ""
