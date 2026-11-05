"""音色をつくる画面のカード(SPEC_v2 7.3)。どの項目をどのカードに置き、いつ見せるか。画面から独立した計算だけ。

- カードは ch の種類(kind)で決まる。その種類に無い項目のカードは出さない
- 使っていない機能のカードは ON/OFF のスイッチで閉じる(スイッチが値を変える)
- 「コントローラーの割り当て」は値と関係なく、ふだんは閉じておく(fold)
- 詳細表示(全 CC の一覧)は作らない。以前の版の詳細表示にしかなかった項目は、ここのカードか演奏セットへ
- 時間は秒数を出さない(「すぐ ↔ ゆっくり」)

画面は「どう見せるか」だけ。表示・非表示の判定と値の変換はここで行う(JS と二重に書かない)。
"""
from dataclasses import dataclass, field
from typing import Callable

from .spec import Spec

ON, OFF = 127, 0


@dataclass
class Control:
    key: str
    label: str
    help: str
    kind: str                         # "choice" / "slider" / "steps" / "toggle"
    cc: int | None = None
    choices: list = field(default_factory=list)   # choice: [(表示, 値)]。空なら実装表から
    lo: int = 0
    hi: int = 127
    left: str = ""
    right: str = ""
    show: Callable = lambda v: True
    get: Callable | None = None       # toggle: v -> bool
    set: Callable | None = None       # toggle: (v, bool) -> {cc: 値}
    ccs: tuple = ()                   # toggle が触る CC(この種類で使えるか)

    def needs(self):
        return self.ccs or ((self.cc,) if self.cc is not None else ())


@dataclass
class Card:
    key: str
    title: str
    help: str
    controls: list
    switch: Control | None = None     # カードを開け閉めするスイッチ(値を変える)
    fold: bool = False                # 値と関係なく、ふだんは閉じておく
    special: str = ""                 # 画面で特別な絵を描く("duty" / "env" / "wave")


def _on(v, cc):
    return v.get(cc, 0) >= 64


def _vib_on(v):
    return v.get(1, 0) > v.get(81, 20)


def _trem_on(v):
    return v.get(92, 0) > v.get(89, 20)


def _arp_on(v):
    return v.get(23, 0) != 0


def _toggle(key, label, cc, help_=""):
    return Control(key, label, help_ or "オン/オフ", "toggle", ccs=(cc,), get=lambda v: _on(v, cc),
                   set=lambda v, on: {cc: ON if on else OFF})


ASSIGN_HELP = ("OFF / Modulation(ビブラート)/ PitchUp・PitchDown(音程を上げ下げ)/ Tremolo / VolumeUp・VolDown / "
               "HalfDown(半音下げ)/ Expression")

CARDS = [
    Card("duty", "デューティ比",
         "パルス波(ch1・ch2)の音の太さ。フィルターの無い音源なので、パルスの音色はほぼこれで決まります。",
         [Control("duty", "デューティ比",
                  "12.5% = 一番細く鋭い\n25% = ファミコンのメロディの定番\n50% = 丸くオルガン寄り(電源 ON のとき)\n"
                  "75% = 25% を反転しただけなので、聞こえ方は 25% とほぼ同じ",
                  "choice", 70, choices=[("12.5%", 16), ("25%", 48), ("50%", 80), ("75%", 112)])],
         special="duty"),
    Card("wave", "波形メモリの波形",
         "ch5 を「波形メモリ」にしたときに鳴る音の形。16本の棒をなぞって描きます(上ほど大きい)。\n"
         "波形は ch5 の音色の一部で、音色・演奏セットと一緒に保存され、入れると送られます(カートリッジには保存しません)。\n"
         "DPCM にすると、ドラムの音(ノート番号で音が変わる)になります。",
         [Control("wavemode", "波形メモリ / DPCM", "波形メモリ = 描いた波形で鳴る。DPCM = ドラムの音。DPCM は音量が効きません",
                  "choice", 18, choices=[("波形メモリ", 127), ("DPCM", 0)]),
          Control("waveres", "解像度", "波形の細かさ。自動 = 高い音ほど粗くして、音程を保つ", "choice", 19,
                  show=lambda v: _on(v, 18))],
         special="wave"),
    Card("env", "エンベロープ(ADSR)",
         "音を鳴らしてから消えるまでの音量の変化。\nA(アタック)= 鳴り始めてから最大になるまで\nD(ディケイ)= 最大からサステインまで減る速さ\n"
         "S(サステイン)= 押し続けている間の音量\nR(リリース)= 鍵盤を離してから消えるまで",
         [Control("atk", "アタック", "鳴り始めてから最大の音量になるまで。0 ですぐ最大", "slider", 73, left="すぐ", right="ゆっくり"),
          Control("atklv", "鳴り始めの音量", "アタックが 0 より大きいときの鳴り始めの音量(ここから最大まで上がる)", "steps", 12,
                  show=lambda v: v.get(73, 0) > 0),
          Control("dec", "ディケイ", "最大からサステインまで減る速さ。サステインが最大のときは効きません", "slider", 75,
                  left="速い", right="遅い", show=lambda v: v.get(79, 127) < 120),
          Control("sus", "サステイン", "押し続けている間の音量。0 にすると、ディケイで消える打楽器的な音", "steps", 79),
          Control("rel", "リリース", "鍵盤を離してから消えるまでの余韻", "slider", 72, left="すぐ消える", right="長い余韻"),
          Control("holdauto", "ホールド・タイム 自動", "ホールド(サスティンペダル)で離したあとの伸び。自動 = 音色に合わせて決める",
                  "toggle", ccs=(21,), get=lambda v: _on(v, 21), set=lambda v, on: {21: ON if on else OFF}),
          Control("hold", "ホールド・タイム", "ホールド(サスティンペダル)を踏んで離したあと、音が伸びる長さ", "slider", 83,
                  left="短い", right="長い", show=lambda v: not _on(v, 21))],
         special="env"),
    Card("basic", "基本", "音量など、どの音色にも共通の設定。",
         [Control("vol", "ボリューム", "この ch の音量。0 にすると、PC を変えても戻りません(戻すときは上げる)", "slider", 7,
                  left="小", right="大"),
          Control("expr", "エクスプレッション", "ボリュームに掛け算される2つめの音量。曲の中の強弱に使う", "slider", 11,
                  left="小", right="大"),
          Control("detune", "デチューン", "音程を少しずらす(1あたり約1セント。ファミコンの音程の段階に丸められます)。"
                  "ch2 だけずらすと、ch1 と重ねたときに厚みが出る", "slider", 85, left="低く", right="高く"),
          Control("velfix", "ベロシティ固定", "オンにすると、弱く弾いても一定の強さで鳴る", "toggle", ccs=(9,),
                  get=lambda v: v.get(9, 0) >= 8, set=lambda v, on: {9: 127 if on else 0}),
          _toggle("memory", "ノート記憶モード", 22,
                  "オンにすると、後から押した音を離したとき、押さえたままの前の音に戻る(アルペジエーターがオフのときだけ)")]),
    Card("noise", "ノイズの周期切り替え",
         "ch4 では、モジュレーション(CC#1)が「周期の切り替え」になります(どう聞こえるかは未確認)。",
         [Control("noisemod", "モジュレーション", "ノイズの周期を切り替える(未確認)", "slider", 1, left="0", right="127"),
          Control("noiserate", "切り替えの速さ", "モジュレーション・レート(CC#76)。ch4 では周期を切り替える速さになるはず(未確認)",
                  "slider", 76, lo=0, hi=20, left="ゆっくり", right="速い"),
          Control("noiseorder", "ノート順", "ノート番号と音の高さの並び。逆順(電源 ON のとき)は、番号が小さいほど高い", "choice", 17,
                  choices=[("逆順", 0), ("正順", 127)])]),
    Card("vib", "ビブラート", "音程を周期的に揺らす。ディレイで遅らせると、伸ばした音だけ揺れます。",
         [Control("vibrate", "速さ", "5〜8 くらいが歌のビブラート", "slider", 76, lo=0, hi=20, left="ゆっくり", right="速い"),
          Control("vibdepth", "深さ", "揺れる幅(半音単位)。1 でも十分に揺れます", "slider", 77, lo=1, hi=12, left="浅い", right="深い"),
          Control("vibdelay", "ディレイ", "揺れ始めるまでの時間", "slider", 78, left="すぐ", right="遅れて"),
          Control("vibwave", "波形", "揺れ方。Pulse にすると2つの音程を行き来するトリル", "choice", 80)],
         switch=Control("vibon", "ビブラート", "", "toggle", get=_vib_on, ccs=(1, 81),
                        set=lambda v, on: {1: max(64, v.get(81, 20) + 1)} if on else {1: 0})),
    Card("trem", "トレモロ", "音量を周期的に揺らす。うっすら掛けると揺らぎと輝きが出ます。",
         [Control("tremamt", "量", "トレモロをどれくらい掛けるか", "slider", 92, left="弱い", right="強い"),
          Control("tremrate", "速さ", "揺れる速さ", "slider", 86, lo=0, hi=60, left="ゆっくり", right="速い"),
          Control("tremdepth", "深さ", "揺れる幅", "steps", 87),
          Control("tremwave", "波形", "揺れ方。Pulse 系にするとブツ切れのゲート効果", "choice", 88)],
         switch=Control("tremon", "トレモロ", "", "toggle", get=_trem_on, ccs=(92, 89),
                        set=lambda v, on: {92: max(40, v.get(89, 20) + 1)} if on else {92: 0})),
    Card("arp", "アルペジエーター",
         "押した和音を高速で順番に鳴らす。単音しか出ないファミコンで和音を聞かせる、チップチューン特有の音。",
         [Control("arptype", "動き出す条件", "1ノートから / 2ノート以上押したときだけ", "choice", 23,
                  choices=[("1ノートから", 1), ("2ノート以上", 2)]),
          Control("arptime", "速さ", "3〜6 で和音に聞こえ、上げるほど分散和音", "slider", 24, left="速い(和音)", right="遅い"),
          Control("arpoff", "1音の長さ", "短くすると音の間に隙間ができる", "slider", 25, left="短い", right="長い"),
          Control("arporder", "順番", "上がる、下がる、行き来する、ランダム など", "choice", 26),
          Control("arpoct", "オクターブ範囲", "何オクターブ分くり返すか", "choice", 27)],
         switch=Control("arpon", "アルペジエーター", "", "toggle", get=_arp_on, ccs=(23,),
                        set=lambda v, on: {23: 1} if on else {23: 0})),
    Card("porta", "ポルタメント", "次の音へ音程をすべらせる。ごく短く掛けると、つながったフレーズに。",
         [Control("portatime", "時間", "すべる時間。3〜6 でさりげなく", "slider", 5, left="短い", right="長い")],
         switch=_toggle("portaon", "ポルタメント", 65)),
    Card("sweep", "スイープ", "ファミコン本体の機能で、音程を自動で上げ下げする。ジャンプ音やレーザー音のような効果音に。",
         [Control("sweepdir", "方向", "上がるか下がるか", "choice", 14, choices=[("下降", 0), ("上昇", 127)]),
          Control("sweeptime", "間隔", "変化の間隔", "steps", 15),
          Control("sweepshift", "細かさ", "1回あたりの変化の細かさ", "steps", 16)],
         switch=_toggle("sweepon", "スイープ", 13)),
    Card("assign", "コントローラーの割り当て",
         "鍵盤のアフタータッチ(押し込み)と、ブレス・コントロールで何を動かすか。ふだんは使わないので閉じてあります。",
         [Control("aftertouch", "アフタータッチ", ASSIGN_HELP, "choice", 30),
          Control("breath", "ブレス・コントロール", ASSIGN_HELP, "choice", 3)],
         fold=True),
]
CONTROLS = {c.key: c for card in CARDS for c in ([card.switch] if card.switch else []) + card.controls}


def _avail(kind, spec: Spec):
    return set(spec.tone_ccs(kind))


def cards_for(kind, spec: Spec):
    """この種類で使える項目だけのカード(使える項目が無いカードは出さない)"""
    avail = _avail(kind, spec)
    out = []
    for card in CARDS:
        if card.key == "noise" and kind != "noise":
            continue                  # CC#1 は ch1〜3 ではビブラートのカード
        if card.switch and not all(x in avail for x in card.switch.needs()):
            continue
        cs = [c for c in card.controls if c.needs() and all(x in avail for x in c.needs())]
        if cs:
            out.append(Card(card.key, card.title, card.help, cs, card.switch, card.fold, card.special))
    return out


def choices_of(c: Control, spec: Spec):
    if c.choices:
        return c.choices
    p = spec.params[c.cc]
    if p.kind == "enum" and isinstance(p.options, list):
        return [(label, i) for i, label in enumerate(p.options)]
    if p.kind == "steps":
        return [(label, step_value(p.steps, i)) for i, label in enumerate(step_labels(p))]
    if p.kind == "switch":
        labels = p.options if isinstance(p.options, list) and len(p.options) == 2 else ["OFF", "ON"]
        return list(zip(labels, (0, 127)))
    return []


def step_labels(p):
    if isinstance(p.options, list) and len(p.options) == p.steps:
        return list(p.options)
    return [str(k) for k in range(p.steps)]


def step_value(steps, k):
    """段階 k(0始まり)の真ん中の値(docs/02: floor(k*128/N + 64/N))"""
    return (k * 128 + 64) // steps


def step_index(steps, value):
    return min(value * steps // 128, steps - 1)


def describe(kind, spec: Spec):
    """画面の組み立て用(値に関係なく決まる部分)"""
    def ctl(c):
        d = {"key": c.key, "label": c.label, "help": c.help, "kind": c.kind}
        if c.kind == "choice":
            d["choices"] = [label for label, _ in choices_of(c, spec)]
        elif c.kind == "steps":
            d["steps"] = step_labels(spec.params[c.cc])
        elif c.kind == "slider":
            d.update(lo=c.lo, hi=c.hi, left=c.left, right=c.right)
        return d
    return [{"key": card.key, "title": card.title, "help": card.help, "special": card.special, "fold": card.fold,
             "switch": card.switch.key if card.switch else None, "controls": [ctl(c) for c in card.controls]}
            for card in cards_for(kind, spec)]


def current_index(c: Control, spec: Spec, value):
    opts = choices_of(c, spec)
    p = spec.params[c.cc]
    if p.kind == "steps":
        return step_index(p.steps, value)
    if p.kind == "switch" and not c.choices:
        return 1 if value >= 64 else 0
    return min(range(len(opts)), key=lambda i: abs(opts[i][1] - value)) if opts else 0


def state(kind, values: dict, spec: Spec):
    """いまの値に合わせた表示(各項目の値・選択位置・オン/オフ・見せるか、カードが開いているか)"""
    controls, cards = {}, {}
    for card in cards_for(kind, spec):
        cards[card.key] = {"on": bool(card.switch.get(values)) if card.switch else True}
        for c in ([card.switch] if card.switch else []) + card.controls:
            s = {"show": bool(c.show(values))}
            if c.kind == "toggle":
                s["on"] = bool(c.get(values))
            elif c.kind in ("choice", "steps"):
                s["index"] = current_index(c, spec, values.get(c.cc, 0))
            else:
                s["value"] = values.get(c.cc, 0)
            controls[c.key] = s
    env = {str(cc): values[cc] for cc in (73, 12, 75, 79, 72) if cc in values}
    return {"controls": controls, "cards": cards, "env": env, "has_sus": 79 in values}


def updates_for(key, action, x, values: dict, spec: Spec):
    """画面の操作 → {CC: 値}。action: "toggle"(x=bool)/ "index"(x=選択位置)/ "value"(x=数)"""
    c = CONTROLS.get(key)
    if c is None:
        raise ValueError(f"知らない項目です: {key}")
    if action == "toggle":
        return c.set(values, bool(x))
    if action == "index":
        p = spec.params[c.cc]
        if p.kind == "steps" and not c.choices:
            return {c.cc: step_value(p.steps, max(0, min(p.steps - 1, int(x))))}
        opts = choices_of(c, spec)
        return {c.cc: opts[max(0, min(len(opts) - 1, int(x)))][1]}
    out = {c.cc: max(c.lo, min(c.hi, int(x)))}
    if c.cc == 83:
        out[21] = OFF             # ホールド・タイムを変えると自動は OFF になる(実装表)
    return out


ENV_CCS = (73, 12, 75, 79, 72)


def env_updates(upd: dict):
    """エンベロープのグラフをつまんだ → {CC: 値}(知らない CC は捨てる)"""
    return {int(k): max(0, min(127, int(v))) for k, v in upd.items() if int(k) in ENV_CCS}
