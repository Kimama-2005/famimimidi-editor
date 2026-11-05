"""コードモードの配置「度数+補足」(SPEC_v2 6.5.2)。基本コードの鍵と補足の鍵を同時に押してコードを作る。

インスタコードのような弾き方(押し方は同じではない)。弾けるコードの種類は、インスタコードで弾けるもの
(maj・m・7・m7・M7・mM7・6・m6・add9・madd9・sus4・dim7・aug・m7-5・分数コード)をすべて含む。

鍵盤は3つのオクターブに分ける(37鍵 C3〜C6 にそのまま収まる)。
- degree_r(右手で基本コード): C3〜B3 = 補足、C4〜B4 = 基本コード、C5〜B5 = 分数のベース
- degree_l(左手で基本コード): C3〜B3 = 基本コード、C4〜B4 = 分数のベース、C5〜B5 = 補足(ユーザー指定 2026-11-05)
C3 より下は C3〜B3 と、C6 から上は C5〜B5 と同じ扱い(オクターブ切り替えをしても弾けるように)。
- 基本コードの側(12鍵): 白鍵 = いまのキーの Ⅰ〜Ⅶ、黒鍵 = ♭Ⅱ・♭Ⅲ・#Ⅳm・♭Ⅵ・♭Ⅶ
- 補足の側(12鍵): 7・6・M7・♭5・～(メジャー⇔マイナー)・sus4・♭(半音下げ)・add9・/3rd・dim7・/5th・aug。
  いくつでも重ねられる(例: ～+7 = マイナーとメジャーを入れ替えて 7th)
- 分数のベースの鍵(12鍵): 押しながら基本コードを弾くと分数コード。並びは基本コードと同じ度数
  (オクターブの C = Ⅰ の音。キー C で右手なら G5 を押しながら Ⅳ = F/G)。ベースは ♭ の補足では下がらない
- 離すとき: 鍵を離しても RELEASE_WINDOW 秒は残った鍵のコードに切り替えない(同時に離したつもりの鍵が
  少しずれても、途中のコードが鳴らない)

画面から独立した計算だけ。
"""
from __future__ import annotations

from functools import lru_cache
from itertools import combinations

from .chords import Chord

MID_LO, TOP_LO = 60, 72      # C4〜B4 = 真ん中のオクターブ、C5 から上 = 上のオクターブ
# オクターブ(下・真ん中・上)ごとの受け持ち
ZONES = {"degree_r": ("mod", "degree", "bass"), "degree_l": ("degree", "bass", "mod")}
ZONE_LO = (48, 60, 72)       # 画面に出すときの各オクターブの C
SCHEMES = {"degree_r": "度数+補足(右手で基本コード)", "degree_l": "度数+補足(左手で基本コード)"}

# 基本コードの鍵(オクターブ内の位置)→ (キーからの度数, マイナーか)
DEGREE_KEYS = {
    0: (0, False), 2: (2, True), 4: (4, True), 5: (5, False), 7: (7, False), 9: (9, True), 11: (11, True),
    1: (1, False), 3: (3, False), 6: (6, True), 8: (8, False), 10: (10, False),
}
DEGREE_NAMES = {0: "Ⅰ", 1: "♭Ⅱ", 2: "Ⅱm", 3: "♭Ⅲ", 4: "Ⅲm", 5: "Ⅳ", 6: "#Ⅳm", 7: "Ⅴ", 8: "♭Ⅵ", 9: "Ⅵm",
                10: "♭Ⅶ", 11: "Ⅶm"}

# 補足の鍵(オクターブ内の位置)→ 働き
MODS = {0: "7", 1: "6", 2: "M7", 3: "b5", 4: "swap", 5: "sus4", 6: "flat", 7: "add9", 8: "on3", 9: "dim7",
        10: "on5", 11: "aug"}
MOD_LABELS = {"7": "7", "6": "6", "M7": "M7", "b5": "♭5", "swap": "～", "sus4": "sus4", "flat": "♭",
              "add9": "add9", "on3": "/3rd", "dim7": "dim7", "on5": "/5th", "aug": "aug"}
MOD_HELP = {"7": "7th を足す", "6": "6th を足す", "M7": "メジャー7th を足す(7 と一緒なら 6th)", "b5": "5th を半音下げる",
            "swap": "メジャーとマイナーを入れ替える", "sus4": "3rd を 4th に", "flat": "コード全体を半音下げる",
            "add9": "9th を足す", "on3": "ベースを 3rd に(分数コード)", "dim7": "dim7 にする", "on5": "ベースを 5th に(分数コード)",
            "aug": "5th を半音上げる"}
MOD_KEY = {v: k for k, v in MODS.items()}
_MAX_MODS = 4       # 押し方を探すときに重ねる補足の数の上限
RELEASE_WINDOW = 0.1    # 離してからこの秒数は、残った鍵のコードに切り替えない(実機で弾いて調整する)


def is_scheme(name: str) -> bool:
    return name in SCHEMES


def degree_on_right(scheme: str) -> bool:
    return scheme == "degree_r"


def zone(note: int, scheme: str) -> str:
    """鍵の受け持ち: "degree" 基本コード / "mod" 補足 / "bass" 分数のベース。
    C3 より下は下のオクターブ、C6 から上は上のオクターブと同じ扱い"""
    o = 0 if note < MID_LO else 1 if note < TOP_LO else 2
    return ZONES[scheme][o]


def _zone_note(what: str, off: int, scheme: str) -> int:
    return ZONE_LO[ZONES[scheme].index(what)] + off


def is_degree_note(note: int, scheme: str) -> bool:
    return zone(note, scheme) == "degree"


def bass_key_note(off: int, scheme: str = "degree_r") -> int:
    """画面に出すときの分数のベースの鍵(右手で基本コードなら C5〜B5 / 左手なら C4〜B4)"""
    return _zone_note("bass", off, scheme)


def degree_note(off: int, scheme: str) -> int:
    """画面に出すときの基本コードの鍵(右手 C4〜B4 / 左手 C3〜B3)"""
    return _zone_note("degree", off, scheme)


def mod_note(off: int, scheme: str) -> int:
    """画面に出すときの補足の鍵(右手で基本コードなら C3〜B3 / 左手なら C5〜B5)"""
    return _zone_note("mod", off, scheme)


def bass_of(key: int, off: int) -> int:
    """分数のベースの鍵 off(度数の並び)の音名"""
    return (key + DEGREE_KEYS[off % 12][0]) % 12


def build(key: int, off: int, mods=frozenset(), bass_off: int | None = None) -> Chord:
    """基本コードの鍵 off と補足の働きの集まり mods → コード。bass_off = 押している分数のベースの鍵"""
    deg, minor = DEGREE_KEYS[off % 12]
    if "swap" in mods:
        minor = not minor
    root = (key + deg - (1 if "flat" in mods else 0)) % 12
    if "dim7" in mods:
        ivs = [0, 3, 6, 9]
    else:
        third = 3 if minor else 4
        fifth = 7
        if "aug" in mods:
            fifth, third = 8, 4
        if "sus4" in mods:
            third = 5
        if "b5" in mods:
            fifth = 6
        ivs = [0, third, fifth]
        if "6" in mods or ("7" in mods and "M7" in mods):
            ivs.append(9)
        elif "7" in mods:
            ivs.append(10)
        elif "M7" in mods:
            ivs.append(11)
        if "add9" in mods:
            ivs.append(14)
    ivs = tuple(sorted(set(ivs)))
    bass = None
    if "on3" in mods:
        bass = (root + ivs[1]) % 12
    elif "on5" in mods:
        bass = (root + ivs[2]) % 12
    if bass_off is not None:
        bass = bass_of(key, bass_off)
    if bass == root:
        bass = None
    return Chord(root, ivs, bass)


def mods_of(pcs) -> frozenset:
    """押している補足の鍵(音名の集まり)→ 働きの集まり"""
    return frozenset(MODS[pc % 12] for pc in pcs)


@lru_cache(maxsize=24)
def _table(key: int) -> dict:
    """いまのキーで弾けるコード → いちばん少ない鍵での押し方 (基本コードの鍵, 補足の働きのタプル)"""
    best = {}
    names = list(MODS.values())
    for n in range(_MAX_MODS + 1):
        for combo in combinations(names, n):
            mods = frozenset(combo)
            for off in DEGREE_KEYS:
                c = build(key, off, mods)
                cost = (n, "flat" in mods, "swap" in mods, off in (1, 3, 6, 8, 10), len(combo) and combo)
                if c not in best or cost < best[c][0]:
                    best[c] = (cost, (off, tuple(sorted(mods, key=lambda m: MOD_KEY[m]))))
    return {c: v[1] for c, v in best.items()}


def how(key: int, chord: Chord):
    """コード → 押し方 {"off": 基本コードの鍵, "mods": 補足, "bass": 分数コードのベースの鍵 or None, "exact": ぴったりか}。
    補足だけで作れればそれを、作れない分数コードは分数のベースの鍵で。弾けないときは None"""
    t = _table(key % 12)
    if chord in t:
        off, mods = t[chord]
        return {"off": off, "mods": mods, "bass": None, "exact": True}
    plain = Chord(chord.root, chord.ivs)
    if plain not in t:
        return None
    off, mods = t[plain]
    mods = tuple(m for m in mods if m not in ("on3", "on5"))
    if chord.bass is None:
        return {"off": off, "mods": mods, "bass": None, "exact": True}
    return {"off": off, "mods": mods, "bass": (chord.bass - key) % 12, "exact": True}


def find(key: int, chord: Chord):
    """コード → (基本コードの鍵, 補足の働きのタプル, ぴったりか)。分数コードのベースが作れないときはベース抜きで探す。
    弾けないときは None"""
    t = _table(key % 12)
    if chord in t:
        return (*t[chord], True)
    plain = Chord(chord.root, chord.ivs)
    if plain in t:
        return (*t[plain], False)
    return None
