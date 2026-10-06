"""フェーズB: 音色編集の簡易版の「まとまり・説明・値の変換」。画面から独立(フェーズCでも使う)。

方針(2026-09-30 ユーザーと合意):
- まとまりの名前はシンセサイザーの用語(デューティ比、エンベロープ …)。「?」で、ふつうの言葉の説明を出す
- 時間は秒数を出さず「短い ↔ 長い」(実測しない)
- 使っていない機能の細かい設定は隠す(sets.relevant と同じ考え方)
"""
from dataclasses import dataclass, field
from typing import Callable

ON, OFF = 127, 0


@dataclass
class Control:
    key: str
    label: str
    help: str
    kind: str                         # "choice"(選択肢)/ "slider"(0〜127 など)/ "steps"(段階)/ "toggle"(オン・オフ)
    cc: int | None = None             # 1つの CC にそのまま対応する場合
    choices: list = field(default_factory=list)   # choice: [(表示, 値)]
    lo: int = 0
    hi: int = 127
    left: str = ""                    # slider の左端の言葉
    right: str = ""
    show: Callable = lambda v: True   # v: {cc: 値} → この項目を出すか
    get: Callable | None = None       # toggle 用: v → bool
    set: Callable | None = None       # toggle 用: (v, bool) → {cc: 値}
    ccs: tuple = ()                   # toggle が触る CC(このチャンネルで使えるかの判定用)

    def needs(self):
        return self.ccs or ((self.cc,) if self.cc is not None else ())


@dataclass
class Group:
    key: str
    title: str
    help: str
    controls: list


def _on(v, cc):
    return v.get(cc, 0) >= 64


def _vib_on(v):
    return v.get(1, 0) > v.get(81, 20)


def _trem_on(v):
    return v.get(92, 0) > v.get(89, 20)


def _arp_on(v):
    return v.get(23, 0) != 0


GROUPS = [
    Group("duty", "デューティ比",
          "パルス波(ch1・ch2)の音の太さ。フィルターの無い音源なので、パルス波の音色はほぼこれで決まります。",
          [Control("duty", "デューティ比",
                   "12.5% = 一番細く鋭い。混んだ伴奏の中でも抜ける\n25% = ファミコンのメロディの定番。鼻にかかった芯のある音\n"
                   "50% = 丸くオルガン寄り(電源ON時)\n75% = 25% を反転しただけなので、聞こえ方は 25% とほぼ同じ",
                   "choice", 70, choices=[("12.5% 細い", 16), ("25% 定番", 48), ("50% 丸い", 80), ("75%", 112)])]),
    Group("env", "エンベロープ(ADSR)",
          "音を鳴らしてから消えるまでの音量の変化。\nA(アタック)= 鳴り始めてから最大になるまで\nD(ディケイ)= 最大からサスティンまで減っていく速さ\n"
          "S(サスティン)= 押し続けている間の音量\nR(リリース)= 鍵盤を離してから消えるまで",
          [Control("atk", "アタック・タイム", "鳴り始めてから最大の音量になるまでの時間。0 ですぐ最大。上げると、ふわっと立ち上がる。"
                   "時間は指数的に伸びるので、まず 10〜30 で試すのがおすすめ",
                   "slider", 73, left="すぐ", right="ゆっくり"),
           Control("atklv", "アタック・レベル", "鳴り始めの音量。アタック・タイムが 0 より大きいときに効きます"
                   "(ここから最大まで上がる)", "steps", 12, show=lambda v: v.get(73, 0) > 0),
           Control("dec", "ディケイ・タイム", "最大の音量からサスティン・レベルまで減っていく速さ。"
                   "サスティン・レベルが最大のときは効かないので隠れます", "slider", 75, left="速い", right="遅い",
                   show=lambda v: v.get(79, 127) < 120),
           Control("sus", "サスティン・レベル", "鍵盤を押し続けている間の音量。最大なら減衰しない(オルガンのよう)。"
                   "0 にすると、ディケイで消える打楽器的な音になる", "steps", 79),
           Control("rel", "リリース・タイム", "鍵盤を離してから音が消えるまでの余韻", "slider", 72, left="すぐ消える",
                   right="長い余韻")]),
    Group("vib", "ビブラート",
          "音程を周期的に揺らす効果。歌うような表情が付きます。ディレイで遅らせると、短い音は揺れず、伸ばした音だけ揺れます。",
          [Control("vibon", "ビブラート", "オン/オフ。オンにすると「モジュレーション量」を無効区間より大きくします",
                   "toggle", get=_vib_on, ccs=(1, 81),
                   set=lambda v, on: {1: max(64, v.get(81, 20) + 1)} if on else {1: 0}),
           Control("vibrate", "モジュレーション・レート", "揺れる速さ。5〜8 くらいが歌のビブラート", "slider", 76,
                   lo=0, hi=20, left="ゆっくり", right="速い", show=_vib_on),
           Control("vibdepth", "モジュレーション・デプス", "揺れる幅(半音単位)。1 でも十分に揺れます", "slider", 77,
                   lo=1, hi=12, left="浅い", right="深い", show=_vib_on),
           Control("vibdelay", "モジュレーション・ディレイ", "揺れ始めるまでの時間。34〜54 くらいが使いやすい", "slider", 78,
                   left="すぐ", right="遅れて", show=_vib_on),
           Control("vibwave", "モジュレーション波形", "揺れ方。Pulse にすると2つの音程を行き来するトリルになります", "choice", 80,
                   show=_vib_on)]),
    Group("trem", "トレモロ",
          "音量を周期的に揺らす効果。うっすら掛けると音に揺らぎと輝きが出ます。",
          [Control("tremon", "トレモロ", "オン/オフ", "toggle", get=_trem_on, ccs=(92, 89),
                   set=lambda v, on: {92: max(40, v.get(89, 20) + 1)} if on else {92: 0}),
           Control("tremamt", "トレモロ量", "トレモロをどれくらい掛けるか", "slider", 92, left="弱い", right="強い",
                   show=_trem_on),
           Control("tremrate", "トレモロ・レート", "揺れる速さ", "slider", 86, lo=0, hi=60, left="ゆっくり", right="速い",
                   show=_trem_on),
           Control("tremdepth", "トレモロ・デプス", "揺れる幅", "steps", 87, show=_trem_on),
           Control("tremwave", "トレモロ波形", "揺れ方。Pulse 系にするとブツ切れのゲート効果になります", "choice", 88,
                   show=_trem_on)]),
    Group("arp", "アルペジエーター",
          "押した和音を高速で順番に鳴らす機能。単音しか出ないファミコンで和音を聞かせる、チップチューン特有のビリビリした和音になります。",
          [Control("arptype", "アルペジエーター・タイプ", "OFF / 1ノートから / 2ノート以上押したときだけ作動", "choice", 23),
           Control("arptime", "アルペジエーター・タイム", "音を切り替える速さ。3〜6 で和音に聞こえ、上げるほど分散和音になる",
                   "slider", 24, left="速い(和音)", right="遅い(分散和音)", show=_arp_on),
           Control("arpoff", "ノートオフタイム", "1音ごとの長さ。短くすると音の間に隙間ができる", "slider", 25, left="短い",
                   right="長い", show=_arp_on),
           Control("arporder", "再生順序", "上がる、下がる、行き来する、ランダム など", "choice", 26, show=_arp_on),
           Control("arpoct", "オクターブ範囲", "何オクターブ分くり返すか。広げると派手になる", "choice", 27, show=_arp_on)]),
    Group("porta", "ポルタメント",
          "次の音へ音程をすべらせる効果。ごく短く掛けると、つながった自然なフレーズになります。",
          [Control("portaon", "ポルタメント", "オン/オフ", "toggle", get=lambda v: _on(v, 65), ccs=(65,),
                   set=lambda v, on: {65: ON if on else OFF}),
           Control("portatime", "ポルタメント・タイム", "すべる時間。3〜6 でさりげなく", "slider", 5, left="短い", right="長い",
                   show=lambda v: _on(v, 65))]),
    Group("pitch", "ピッチ",
          "音程の細かい調整。",
          [Control("detune", "デチューン", "音程を少しずらす(1あたり約1セント)。ch2 だけずらすと、ch1 と重ねたときに厚みが出る",
                   "slider", 85, left="低く", right="高く"),
           Control("bend", "ピッチベンド・センシティビティ", "ピッチベンドを一番まで倒したときに、何半音動くか", "slider", 82,
                   lo=0, hi=24, left="狭い", right="広い")]),
    Group("sweep", "スイープ",
          "ファミコン本体のハードウェア機能で、音程を自動で上げ下げする。ジャンプ音やレーザー音のような効果音に。",
          [Control("sweepon", "スイープ・モード", "オン/オフ", "toggle", get=lambda v: _on(v, 13), ccs=(13,),
                   set=lambda v, on: {13: ON if on else OFF}),
           Control("sweepdir", "スイープ変化方向", "上がるか下がるか", "choice", 14, choices=[("下降", 0), ("上昇", 127)],
                   show=lambda v: _on(v, 13)),
           Control("sweeptime", "スイープ時間", "変化の間隔", "steps", 15, show=lambda v: _on(v, 13)),
           Control("sweepshift", "スイープ周波数変化", "1回あたりの変化の細かさ", "steps", 16, show=lambda v: _on(v, 13))]),
    Group("basic", "基本",
          "音量など、どの音色にも共通の設定。",
          [Control("vol", "ボリューム", "このチャンネルの音量", "slider", 7, left="小", right="大"),
           Control("velfix", "ベロシティ固定", "オンにすると、鍵盤を弱く弾いても一定の強さで鳴る", "toggle", ccs=(9,),
                   get=lambda v: v.get(9, 0) >= 8, set=lambda v, on: {9: 127 if on else 0}),
           Control("memory", "ノート記憶モード", "オンにすると、後から押した音を離したとき、押さえたままの前の音に戻る"
                   "(アルペジエーターがオフのときだけ)", "toggle", ccs=(22,), get=lambda v: _on(v, 22),
                   set=lambda v, on: {22: ON if on else OFF}),
           Control("noiseorder", "ノート順(ノイズ)", "ch4 のノート番号と音の高さの並び。逆順(電源ON時)は、番号が小さいほど高い",
                   "choice", 17, choices=[("逆順", 0), ("正順", 127)]),
           Control("wavemode", "波形メモリモード", "ch5 を、ドラム(DPCM)から、描いた波形で鳴らすモードに切り替える", "toggle",
                   ccs=(18,), get=lambda v: _on(v, 18), set=lambda v, on: {18: ON if on else OFF})]),
]


def groups_for(ch, params):
    """このチャンネルで使える項目だけのまとまり(使える項目が無いまとまりは出さない)"""
    from .spec import editable_params
    avail = {p.cc for p in editable_params(params, ch)}
    out = []
    for g in GROUPS:
        cs = [c for c in g.controls if c.needs() and all(x in avail for x in c.needs())]
        if cs:
            out.append(Group(g.key, g.title, g.help, cs))
    return out


def choices_of(control, params):
    """choice の選択肢 [(表示, 値)]。指定が無ければ実装表の選択肢から作る"""
    if control.choices:
        return control.choices
    p = params[control.cc]
    if p.kind == "enum":
        return [(label, i) for i, label in enumerate(p.enum_labels())]
    if p.kind == "steps":
        return [(label, p.step_value(i)) for i, label in enumerate(p.step_labels())]
    if p.kind == "switch":
        return list(zip(p.switch_labels(), (0, 127)))
    return []


def current_choice(control, params, value):
    """いまの値に当たる選択肢の番号"""
    opts = choices_of(control, params)
    p = params[control.cc]
    if p.kind == "steps":
        idx = p.step_index(value)
        return next((i for i, (_, v) in enumerate(opts) if p.step_index(v) == idx), 0)
    if p.kind == "switch":
        return 1 if value >= 64 else 0
    return min(range(len(opts)), key=lambda i: abs(opts[i][1] - value)) if opts else 0
