"""コード名の解析・コードモードの鍵盤の配置・ボイシング(SPEC_v2 6.5)。以前の版の famimimidi/chords.py から移した。

自作の「オタマコード」(OtamaChord Studio の otamatune/chords.py と OtamaCodeFirmware)と同じ表・同じ手順。
違うのは声の数だけ: オタマは ベース+上5声、ふぁみみみっでぃは ベース(三角波)+上3声(パルス1・2、波形メモリ)。
上3声に入りきらないコード(4和音・9th など)は、大事な音から選ぶ(UPPER_PRIORITY)。
曲データの型は model/chordbook.py(オタマのコードセット otamachord-set-v1 と同じ形)。
作り直し版では機能キー(C6 との組み合わせ・UP の鍵)を使わない(鍵盤は音を鳴らすことにだけ使う、SPEC 1.5-7)。
画面から独立した計算だけ。
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from itertools import combinations

SHARP = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]
FLAT = ["C", "D♭", "D", "E♭", "E", "F", "G♭", "G", "A♭", "A", "B♭", "B"]
FLAT_KEYS = {1, 3, 5, 6, 8, 10}   # D♭ E♭ F G♭ A♭ B♭ はフラット表記

# 構成音(ルートからの半音数)
MAJ = (0, 4, 7)
MIN = (0, 3, 7)
DOM7 = (0, 4, 7, 10)
MAJ7 = (0, 4, 7, 11)
MIN7 = (0, 3, 7, 10)
M7B5 = (0, 3, 6, 10)

QUALITIES: dict[str, tuple[int, ...]] = {
    "": MAJ, "m": MIN, "7": DOM7, "M7": MAJ7, "m7": MIN7, "mM7": (0, 3, 7, 11),
    "6": (0, 4, 7, 9), "m6": (0, 3, 7, 9), "sus4": (0, 5, 7), "sus2": (0, 2, 7),
    "7sus4": (0, 5, 7, 10), "add9": (0, 4, 7, 14), "madd9": (0, 3, 7, 14),
    "9": (0, 4, 7, 10, 14), "m9": (0, 3, 7, 10, 14), "M9": (0, 4, 7, 11, 14),
    "69": (0, 4, 7, 9, 14), "m7b5": M7B5, "dim": (0, 3, 6), "dim7": (0, 3, 6, 9),
    "aug": (0, 4, 8), "aug7": (0, 4, 8, 10), "7b9": (0, 4, 7, 10, 13),
    "7#9": (0, 4, 7, 10, 15), "5": (0, 7),
}
_ALIASES = {
    "M": "", "maj": "", "min": "m", "mi": "m", "-": "m", "maj7": "M7", "△7": "M7", "Δ7": "M7", "△": "M7",
    "mmaj7": "mM7", "m△7": "mM7", "sus": "sus4", "79": "9", "m79": "m9", "M79": "M9",
    "maj9": "M9", "add2": "add9", "6add9": "69", "6/9": "69", "m7-5": "m7b5", "ø": "m7b5",
    "ø7": "m7b5", "o": "dim", "o7": "dim7", "+": "aug", "7#5": "aug7", "7+5": "aug7",
    "+7": "aug7", "7-9": "7b9", "7+9": "7#9", "dim5": "dim", "msus4": "sus4",
}
_DISPLAY = {"m7b5": "m7♭5", "7b9": "7♭9", "M7": "M7"}

# コードモードの鍵盤 (キーからの度数, 構成音)。index = オクターブ内の位置 (C=0 … B=11)
ROW1 = [  # C3〜B3: 基本の3和音 + J-POPでよく使う借用・セカンダリー
    (0, MAJ), (2, DOM7), (2, MIN), (4, DOM7), (4, MIN), (5, MAJ),
    (5, MIN), (7, MAJ), (8, MAJ), (9, MIN), (10, MAJ), (11, M7B5),
]
ROW2 = [  # C4〜B4: 4和音(おしゃれ版)+ よく使う経過コード
    (0, MAJ7), (0, DOM7), (2, MIN7), (3, MAJ7), (4, MIN7), (5, MAJ7),
    (6, M7B5), (7, DOM7), (8, MAJ7), (9, MIN7), (9, DOM7), (11, M7B5),
]
ROWS = [ROW1, ROW2]
CUSTOM_ROW, COMMON_ROW = 2, 3     # 3段目(曲ごと)、4段目(全曲共通。オクターブ DOWN で出る)
SLOTS = 12
NUM_SONGS = 12

# 4段目の初期値。全曲共通・キーCで書いたもの(他のキーでは移調される)
COMMON_DEFAULT = ["C/E", "C#dim7", "G/B", "F/G", "Csus4", "Fadd9",
                  "Fm6", "Gsus4", "C/G", "G7sus4", "Bb/C", "Cadd9"]

# 鍵盤(37鍵 C3〜C6): C3〜B5 = 1〜3段目、C2〜B2 = 4段目(オクターブ DOWN。入りきらないときだけ)、C6 = なにもしない
COMMON_LO, ROW_LO, TOP_KEY = 36, 48, 84      # C2, C3, C6

# 上3声で優先する音(ルートからの半音数 mod 12 の順)。ベースがルートを受け持つので、ルートは最後
#   3度 → (3度が無ければ sus の 4度・2度) → 7度 → 減5度・増5度 → 6度 → テンション → 完全5度 → ルート
UPPER_PRIORITY_THIRD = (3, 4)
UPPER_PRIORITY_REST = (10, 11, 6, 8, 9, 1, 2, 3, 5, 7, 0)
OCTAVE_TENSIONS = {13: 1, 14: 2, 15: 3, 17: 5, 21: 9}
SPREAD_PENALTY = 0.4      # 上3声が1オクターブより広がる半音ごとの罰点


@dataclass(frozen=True)
class Chord:
    root: int                    # ルートの音名 (0=C)
    ivs: tuple[int, ...]         # ルートからの半音数
    bass: int | None = None      # 分数コードのベース音名(None = ルート)

    @property
    def mask(self) -> int:
        m = 0
        for i in self.ivs:
            m |= 1 << i
        return m

    @property
    def pcs(self) -> frozenset[int]:
        return frozenset((self.root + i) % 12 for i in self.ivs)

    @property
    def bass_pc(self) -> int:
        return self.root if self.bass is None else self.bass

    def name(self, flats: bool = False) -> str:
        names = FLAT if flats else SHARP
        q = next((k for k, v in QUALITIES.items() if v == self.ivs), None)
        q = _DISPLAY.get(q, q) if q is not None else "(" + ",".join(map(str, self.ivs)) + ")"
        s = names[self.root] + q
        if self.bass is not None and self.bass != self.root:
            s += "/" + names[self.bass]
        return s

    def label(self, key: int) -> str:
        """キーに合わせた表記。フラット系のキーと、♭Ⅱ・♭Ⅲ・♭Ⅵ・♭Ⅶ・Ⅳm の借用コードは♭で書く"""
        deg = (self.root - key) % 12
        return self.name(key in FLAT_KEYS or deg in (1, 3, 8, 10))

    def transpose(self, n: int) -> "Chord":
        return Chord((self.root + n) % 12, self.ivs, None if self.bass is None else (self.bass + n) % 12)


_NOTE_RE = re.compile(r"([A-Ga-g])([#♯b♭]?)")


def _pc(letter: str, acc: str) -> int:
    pc = SHARP.index(letter.upper())
    if acc in ("#", "♯"):
        pc += 1
    elif acc in ("b", "♭"):
        pc -= 1
    return pc % 12


def parse(symbol: str) -> Chord:
    """'Am7', 'F#m7-5', 'C/G', 'ConG', 'G7(9)', 'Bbmaj7' などを解析する。"""
    s = symbol.strip().replace("（", "(").replace("）", ")").replace("　", "")
    m = _NOTE_RE.match(s)
    if not m:
        raise ValueError(f"コード名が読めません: {symbol}")
    root = _pc(m.group(1), m.group(2))
    rest = s[m.end():]
    bass = None
    mb = re.search(r"(?:/|on)([A-Ga-g])([#♯b♭]?)$", rest)
    if mb:
        bass = _pc(mb.group(1), mb.group(2))
        rest = rest[:mb.start()]
    q = rest.replace("(", "").replace(")", "").replace(",", "").replace("♭", "b").replace("♯", "#")
    q = q.replace("-5", "b5") if q.startswith(("m7", "-7")) else q
    if q.startswith("-") and q != "-":
        q = "m" + q[1:]
    q = _ALIASES.get(q, q)
    if q not in QUALITIES:
        raise ValueError(f"コードの種類が読めません: {symbol}")
    if bass == root:
        bass = None
    return Chord(root, QUALITIES[q], bass)


def tokenize(text: str) -> list[str]:
    """コード進行テキストからコード名を順に取り出す(| や改行、カンマ区切りOK)"""
    out = []
    for tok in re.split(r"[\s|｜、,→\-]+(?![57]|b5|9)", text):
        tok = tok.strip()
        if tok and tok not in ("%", "N.C.", "NC", "/"):
            out.append(tok)
    return out


def parse_progression(text: str) -> tuple[list[Chord], list[str]]:
    chords, errors = [], []
    for tok in tokenize(text):
        try:
            chords.append(parse(tok))
        except ValueError as e:
            errors.append(str(e))
    return chords, errors


def row_chord(row: int, offset: int, key: int) -> Chord:
    deg, ivs = ROWS[row][offset]
    return Chord((key + deg) % 12, ivs)


def find_slot(ch: Chord, key: int) -> tuple[int, int] | None:
    """1段目・2段目の鍵盤で弾けるなら (段, 位置)"""
    if ch.bass is not None:
        return None
    for row in range(2):
        for off in range(12):
            if row_chord(row, off, key) == ch:
                return row, off
    return None


def estimate_key(chords: list[Chord]) -> int:
    """1・2段目の鍵盤でいちばん多く弾けるキー(同点なら最初/最後のコードがⅠのキー)"""
    def score(k):
        s = sum(1.0 for c in chords if find_slot(c, k))
        s += 0.3 * sum(1 for c in chords if c.ivs in (MAJ, MAJ7) and c.root == k)
        if chords and chords[-1].root == k:
            s += 0.5
        return s
    return max(range(12), key=score) if chords else 0


@dataclass
class Assignment:
    slots: dict[Chord, tuple[int, int]]   # コード → (段, 位置)
    customs: list[Chord | None]           # 3段目の12枠
    overflow: list[Chord]                 # 入りきらなかったコード
    table: dict = field(default_factory=dict)   # (段, 位置) → コード(曲のキーで)。鍵盤の配置そのもの


def assign(chords: list[Chord], key: int, customs: list[Chord | None] | None = None,
           common: list[Chord | None] | None = None, common_first: bool = True) -> Assignment:
    """曲のコードを鍵盤に割り当てる。
    1・2段目 → 4段目(全曲共通・common はキーCで書いたもの)→ 3段目の枠(白鍵から順に)の順に探す。
    common_first=False なら 4段目より先に3段目へ入れ、3段目が埋まったときだけ4段目を使う
    (4段目はオクターブ DOWN が要るので、37鍵の鍵盤 C3〜C6 だけで弾けるように。2026-11-05)"""
    common_k = [c.transpose(key) if c else None for c in (common or [])]
    order = [0, 2, 4, 5, 7, 9, 11, 1, 3, 6, 8, 10]
    custom = list(customs) if customs else [None] * SLOTS
    custom += [None] * (SLOTS - len(custom))
    slots, overflow = {}, []
    for c in dict.fromkeys(chords):
        s = find_slot(c, key)
        if s:
            slots[c] = s
            continue
        if common_first and c in common_k:
            slots[c] = (COMMON_ROW, common_k.index(c))
            continue
        if c in custom:
            slots[c] = (CUSTOM_ROW, custom.index(c))
            continue
        free = next((o for o in order if custom[o] is None), None)
        if free is not None:
            custom[free] = c
            slots[c] = (CUSTOM_ROW, free)
        elif c in common_k:                    # 3段目が埋まっていたら4段目
            slots[c] = (COMMON_ROW, common_k.index(c))
        else:
            overflow.append(c)
    return Assignment(slots, custom, overflow)


def parse_common(symbols: list[str] | None) -> list[Chord | None]:
    out = []
    for sym in (list(symbols or COMMON_DEFAULT) + [""] * SLOTS)[:SLOTS]:
        try:
            out.append(parse(sym) if str(sym).strip() else None)
        except ValueError:
            out.append(None)
    return out


# ---------------- ボイシング ----------------
def upper_order(ch: Chord) -> list[int]:
    """上の声の音(ルートからの半音数)を、大事な順に並べる。
    3度(無ければ sus の4度・2度)→ 7度 → 減5度・増5度 → 6度 → テンション → 完全5度 → ルート。
    ただし dim・m7♭5 は ♭5 を 7度より先(♭5 が無いと m7 と同じ音になる)。
    分数コードは、ベースが鳴らす音を一番後ろ、ルートを3度の次へ(上でルートが抜けないように)"""
    ivs = []
    for i in ch.ivs:
        i = OCTAVE_TENSIONS.get(i, i % 12)
        if i not in ivs:
            ivs.append(i)
    has_third = any(i in UPPER_PRIORITY_THIRD for i in ivs)
    order = list(UPPER_PRIORITY_THIRD) if has_third else [5, 2]
    order += [i for i in UPPER_PRIORITY_REST if i not in order]
    if 6 in ivs and 7 not in ivs:                       # dim・m7♭5
        order.remove(6)
        order.insert(order.index(10), 6)
    if ch.bass is not None and ch.bass != ch.root:
        order.remove(0)
        order.insert(len(UPPER_PRIORITY_THIRD) if has_third else 2, 0)
        b = (ch.bass - ch.root) % 12
        if b in order:
            order.remove(b)
        order.append(b)
    return sorted(ivs, key=lambda i: order.index(i) if i in order else len(order))


def upper_pcs(ch: Chord, voices: int) -> list[int]:
    """上の声で鳴らす音名(最大 voices 個)。大事な順"""
    return [(ch.root + i) % 12 for i in upper_order(ch)[:voices]]


def voice_upper(ch: Chord, prev: list[int] | None, voices: int = 3, lo: int = 60, hi: int = 84) -> list[int]:
    """上の声を決める(オタマと同じ評価): 前の和音からの動きが小さく、密集しすぎない形。音の低い順。
    オタマ(5声)と違って3声しかないので、1オクターブより広がる形には罰点を足す(まとまった和音に聞こえるように)"""
    need = set(upper_pcs(ch, voices))
    third = {(ch.root + i) % 12 for i in ch.ivs if i % 12 in (3, 4)}
    seventh = {(ch.root + i) % 12 for i in ch.ivs if i % 12 in (10, 11)}
    cands = [n for n in range(lo, hi + 1) if n % 12 in need]
    center = (lo + hi) / 2 + 1
    for span_max in (19, 24, 36):
        best, best_cost = None, None
        for combo in combinations(cands, voices):
            if combo[-1] - combo[0] > span_max or {n % 12 for n in combo} != need:
                continue
            cost = 0.0
            if prev and len(prev) == voices:
                cost += sum(abs(a - b) for a, b in zip(combo, prev))
            cost += 0.5 * abs(sum(combo) / voices - center)
            cost += 3 * sum(1 for a, b in zip(combo, combo[1:]) if b - a == 1)
            cost += SPREAD_PENALTY * max(0, combo[-1] - combo[0] - 12)
            for pc in third | seventh:   # 3度・7度の重複は避ける
                cost += 2 * max(0, sum(1 for n in combo if n % 12 == pc) - 1)
            if best_cost is None or cost < best_cost:
                best, best_cost = list(combo), cost
        if best:
            return best
    return sorted(cands[:voices])


def bass_note(ch: Chord, floor: int) -> int:
    """ベースの音: floor 以上で一番低い、そのベース音名の音"""
    n = floor
    while n % 12 != ch.bass_pc:
        n += 1
    return n


@dataclass
class Analysis:
    chords: list[Chord]
    errors: list[str]
    key: int
    auto_key: int
    assign: Assignment


def analyze(text: str, key: int | None, common: list[Chord | None] | None = None, scheme: str = "otama") -> Analysis:
    """曲(コード進行のテキストとキー)→ 鍵盤の配置。4段目(オクターブ DOWN)は3段目が埋まったときだけ使う
    (37鍵 C3〜C6 で弾けるように。SPEC 5.5「3オクターブに収める = いつも」)"""
    chords, errors = parse_progression(text)
    auto = estimate_key(chords)
    k = auto if key is None else key
    return Analysis(chords, errors, k, auto, layout(chords, k, scheme, common, common_first=False))


# ---------------- 鍵盤の配置(3通り) ----------------
# otama   オタマ互換: 1段目=基本の3和音+J-POP の借用・セカンダリー、2段目=4和音、3段目=曲ごと(出てくる順)、4段目=全曲共通
# regular 規則性重視: どの段も「鍵の名前 = コードのルート(キーからの度数)」。1段目=3和音、2段目=4和音
#         (白鍵=音階の上のコード、黒鍵=音階の外のルート ♭Ⅱ・♭Ⅲ・#Ⅳ・♭Ⅵ・♭Ⅶ)、3段目=曲の変わり種をルートの位置に
# song    曲の弾きやすさ重視: その曲でよく使うコードを白鍵の弾きやすい所に、続けて弾くコードどうしを近くに
# degree_r / degree_l 度数+補足: 基本コードの鍵と補足の鍵を同時に押す(music/degree.py)。左右どちらの手で基本コードを弾くか
SCHEMES = {"otama": "オタマ互換", "regular": "規則性重視", "song": "曲の弾きやすさ重視",
           "degree_r": "度数+補足(右手で基本コード)", "degree_l": "度数+補足(左手で基本コード)"}
DIM = (0, 3, 6)
REG_ROW1 = [(0, MAJ), (1, MAJ), (2, MIN), (3, MAJ), (4, MIN), (5, MAJ),
            (6, DIM), (7, MAJ), (8, MAJ), (9, MIN), (10, MAJ), (11, DIM)]
REG_ROW2 = [(0, MAJ7), (1, MAJ7), (2, MIN7), (3, MAJ7), (4, MIN7), (5, MAJ7),
            (6, M7B5), (7, DOM7), (8, MAJ7), (9, MIN7), (10, DOM7), (11, M7B5)]
ROW_TITLES = {
    "otama": {3: "4段目 C2〜B2\n(DOWN)・全曲共通", 0: "1段目 C3〜B3\n基本コード", 1: "2段目 C4〜B4\n4和音など",
              2: "3段目 C5〜B5\nこの曲用"},
    "regular": {3: "C2〜B2(DOWN)\n入りきらない分", 0: "C3〜B3 3和音\n鍵=ルート", 1: "C4〜B4 4和音\n鍵=ルート",
                2: "C5〜B5 変わり種\nルートの位置"},
    "song": {3: "C2〜B2(DOWN)\n入りきらない分", 0: "C3〜B3", 1: "C4〜B4\nよく使うコード", 2: "C5〜B5"},
    "degree_r": {2: "C5〜B5\n分数のベース", 0: "C4〜B4\n基本コード", 1: "C3〜B3\n補足"},
    "degree_l": {1: "C5〜B5\n補足", 2: "C4〜B4\n分数のベース", 0: "C3〜B3\n基本コード"},
}


def _finish(table, overflow):
    slots = {}
    for pos, c in sorted(table.items()):
        slots.setdefault(c, pos)
    customs = [table.get((CUSTOM_ROW, o)) for o in range(SLOTS)]
    return Assignment(slots, customs, overflow, table)


def layout(chords: list[Chord], key: int, scheme: str = "otama", common=None, common_first: bool = True) -> Assignment:
    """曲のコードの鍵盤の配置。table は曲のキーでのコード(移調するときはずらす)"""
    if scheme == "regular":
        return _layout_regular(chords, key)
    if scheme == "song":
        return _layout_song(chords)
    if scheme in ("degree_r", "degree_l"):
        return _layout_degree(chords, key)
    a = assign(chords, key, common=common, common_first=common_first)
    table = {(r, o): row_chord(r, o, key) for r in (0, 1) for o in range(SLOTS)}
    for o, c in enumerate(a.customs):
        if c:
            table[(CUSTOM_ROW, o)] = c
    for o, c in enumerate(common or []):
        if c:
            table[(COMMON_ROW, o)] = c.transpose(key)
    a.table = table
    return a


def _layout_degree(chords, key):
    """度数+補足: 1段目 = 基本コードの鍵(補足なし)。曲のコードは鍵と補足の組み合わせで作る。作れないものだけ overflow"""
    from . import degree
    table = {(0, o): degree.build(key, o) for o in range(SLOTS)}
    overflow = [c for c in dict.fromkeys(chords) if degree.find(key, c) is None]
    return _finish(table, overflow)


def _layout_regular(chords, key):
    table = {}
    for r, row in ((0, REG_ROW1), (1, REG_ROW2)):
        for o, (deg, ivs) in enumerate(row):
            table[(r, o)] = Chord((key + deg) % 12, ivs)
    fixed = set(table.values())
    overflow = []
    for c in dict.fromkeys(chords):
        if c in fixed:
            continue
        pos = (c.root - key) % 12                       # ルートの位置。ふさがっていたら近い空きへ(右→左の順)
        for row in (CUSTOM_ROW, COMMON_ROW):
            spot = next(((row, (pos + d) % 12) for d in (0, 1, -1, 2, -2, 3, -3, 4, -4, 5, -5, 6)
                         if (row, (pos + d) % 12) not in table), None)
            if spot:
                table[spot] = c
                break
        else:
            overflow.append(c)
    return _finish(table, overflow)


# 曲の弾きやすさ重視: 37鍵の C3〜B5(36鍵)のうち、白鍵・真ん中ほど弾きやすいとみなす
WHITE_PCS = (0, 2, 4, 5, 7, 9, 11)
_LAYOUT_KEYS = list(range(48, 84))


def key_x(n: int) -> float:
    """鍵盤の上の横位置(白鍵1つ分 = 1)。黒鍵は白鍵の間"""
    octave, pc = divmod(n, 12)
    if pc in WHITE_PCS:
        return octave * 7 + WHITE_PCS.index(pc)
    return octave * 7 + WHITE_PCS.index(pc - 1) + 0.5


HOME_X = key_x(60) + 3          # 真ん中のオクターブの真ん中(F4 あたり)
BLACK_COST, HOME_COST = 5.0, 0.08    # 黒鍵の重み 5: 気まぐれロマンティックで平均移動 白鍵2.4個・黒鍵10回(1.5 だと黒鍵42回)


def song_cost(pos: dict, counts, pairs) -> float:
    """配置の弾きにくさ: 続けて弾くコードの距離 + 黒鍵 + 真ん中からの遠さ(どれも使う回数で重み)"""
    cost = sum(n * abs(key_x(pos[a]) - key_x(pos[b])) for (a, b), n in pairs.items())
    for c, n in counts.items():
        k = pos[c]
        cost += n * ((BLACK_COST if k % 12 not in WHITE_PCS else 0) + HOME_COST * abs(key_x(k) - HOME_X))
    return cost


def _layout_song(chords):
    from collections import Counter
    counts = Counter(chords)
    pairs = Counter((a, b) for a, b in zip(chords, chords[1:]) if a != b)
    uniq = [c for c, _ in counts.most_common()]
    keys = sorted(_LAYOUT_KEYS, key=lambda k: ((k % 12) not in WHITE_PCS, abs(key_x(k) - HOME_X), k))
    placed, overflow = uniq[:len(keys)], uniq[len(keys):]
    pos = {c: keys[i] for i, c in enumerate(placed)}    # よく使う順に、弾きやすい鍵から
    best = song_cost(pos, counts, pairs)
    improved = True
    while improved:                                     # 入れ替え・空いた鍵への移動で、弾きにくさが減る限り直す
        improved = False
        for a in placed:
            for b in placed:
                if a == b or pos[a] >= pos[b]:
                    continue
                pos[a], pos[b] = pos[b], pos[a]
                c = song_cost(pos, counts, pairs)
                if c < best - 1e-9:
                    best, improved = c, True
                else:
                    pos[a], pos[b] = pos[b], pos[a]
            used = set(pos.values())
            for k in keys:
                if k in used:
                    continue
                old = pos[a]
                pos[a] = k
                c = song_cost(pos, counts, pairs)
                if c < best - 1e-9:
                    best, improved = c, True
                    used = set(pos.values())
                else:
                    pos[a] = old
    table = {((k - ROW_LO) // 12, (k - ROW_LO) % 12): c for c, k in pos.items()}
    return _finish(table, overflow)


# ---------- ChordWiki のページ(保存した HTML)からコード進行を取り出す ----------
_CW_LINE = re.compile(r'<p class="line[^"]*">(.*?)</p>', re.S)
_CW_SPAN = re.compile(r'<span class="(chord|word|wordtop)"[^>]*>(.*?)</span>', re.S)
_CW_SKIP = {"N.C.", "NC", "○", "×", "%", "-"}


def _cw_text(fragment: str) -> str:
    import html as _html
    return _html.unescape(re.sub(r"<[^>]+>", "", fragment)).strip()


def from_chordwiki(page: str) -> tuple[dict, list[str]]:
    """ChordWiki の HTML → ({"name", "key", "text"}, 読めなかったコード名)。
    コード(class="chord")と小節線(歌詞の欄や記号の |)だけを使い、歌詞は取り込まない。行は1行ずつ残す"""
    title = re.search(r'<h1 class="title">(.*?)</h1>', page, re.S)
    name = _cw_text(title.group(1)) if title else ""
    name = re.split(r"\s*[(（]", name)[0].strip() or name      # 「(ドラマ…主題歌)」などの添え書きは外す
    key = None
    mk = re.search(r'<p class="key">\s*(?:Key|キー)\s*[:：]\s*([A-G][#♯b♭]?)', page)
    if mk:
        key = _pc(mk.group(1)[0], mk.group(1)[1:])
    out_lines, unread = [], []
    for body in _CW_LINE.findall(page):
        toks = []
        for kind, frag in _CW_SPAN.findall(body):
            text = _cw_text(frag)
            if kind == "chord":
                for part in re.split(r"(\|)", text):
                    part = part.strip()
                    if not part or part in _CW_SKIP:
                        continue
                    if part == "|":
                        toks.append("|")
                        continue
                    try:
                        parse(part)
                        toks.append(part)
                    except ValueError:
                        unread.append(part)
            elif "|" in text and toks:          # 歌詞の欄にある小節線だけ使う(歌詞そのものは使わない)
                toks.append("|")
        if any(t != "|" for t in toks):
            line = " ".join(toks)
            out_lines.append(re.sub(r"(\|\s*)+", "| ", line).strip())
    return {"name": name, "key": key, "text": "\n".join(out_lines)}, sorted(set(unread))


def decode_page(raw: bytes) -> str | None:
    """保存した ChordWiki のページのバイト列 → 文字列(文字コードが分からなければ None)"""
    for enc in ("utf-8", "cp932", "euc-jp"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return None


def _seg_chord(part: str):
    """コード欄の1つ → (表示する文字, 進行に入るか)"""
    try:
        parse(part)
        return part, True
    except ValueError:
        return part, False


def sheet_from_chordwiki(page: str) -> list[dict]:
    """ChordWiki のページ → 画面に出す譜面(歌詞つき)。**表示するときだけ作り、保存しない**(歌詞は取り込まない決まり)。
    行 = {"kind": "line", "segs": [{"chord": 名前 or None, "ci": 進行の何番目 or None, "lyric": 歌詞, "bar": 小節線か}]}
    見出し = {"kind": "comment", "text": …}。ci は from_chordwiki が取り込むコードと同じ順番"""
    lines, ci = [], 0
    for m in re.finditer(r'<p class="line([^"]*)">(.*?)</p>', page, re.S):
        cls, body = m.group(1), m.group(2)
        if "comment" in cls:
            t = _cw_text(body)
            if t:
                lines.append({"kind": "comment", "text": t})
            continue
        segs = []
        for kind, frag in _CW_SPAN.findall(body):
            text = _cw_text(frag)
            if kind == "chord":
                for part in re.split(r"(\|)", text):
                    part = part.strip()
                    if not part or part in _CW_SKIP:
                        continue
                    if part == "|":
                        segs.append({"chord": None, "ci": None, "lyric": "", "bar": True})
                        continue
                    name, ok = _seg_chord(part)
                    segs.append({"chord": name, "ci": ci if ok else None, "lyric": "", "bar": False})
                    if ok:
                        ci += 1
            else:
                if segs and not segs[-1]["bar"]:
                    segs[-1]["lyric"] += text
                else:
                    segs.append({"chord": None, "ci": None, "lyric": text, "bar": False})
        if segs:
            lines.append({"kind": "line", "segs": segs})
    return lines


def sheet_from_text(text: str) -> list[dict]:
    """曲のコード進行のテキスト → 行ごとの譜面(歌詞なし)。ci は parse_progression と同じ順番"""
    lines, ci = [], 0
    for raw in text.splitlines():
        segs = []
        for i, piece in enumerate(re.split(r"[|｜]", raw)):
            if i > 0:
                segs.append({"chord": None, "ci": None, "lyric": "", "bar": True})
            for tok in tokenize(piece):
                name, ok = _seg_chord(tok)
                segs.append({"chord": name, "ci": ci if ok else None, "lyric": "", "bar": False})
                if ok:
                    ci += 1
        if any(s["chord"] for s in segs):
            lines.append({"kind": "line", "segs": segs})
    return lines


def sheet_chords(lines: list[dict]) -> list[Chord]:
    return [parse(s["chord"]) for ln in lines if ln["kind"] == "line" for s in ln["segs"] if s["ci"] is not None]


def note_name(n: int) -> str:
    return f"{SHARP[n % 12]}{n // 12 - 1}"
