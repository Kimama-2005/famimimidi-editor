"""実機の確認モード(SPEC_v2 8.2)。確認の手順をデータとして持つ。

1手順 = 「アプリが送るもの(自動)」+「ユーザーへの問い(鳴った?)」+「期待する答え」。
- 判定はいつも二択(鳴った / 鳴らない)。調べたい設定を先頭に送る
- 設定の変更(音量0など)もアプリが自動で行う。終わったら・やめたら、作業中の演奏を送り直して元に戻す
  (CC#7=0 は呼び出し番号を変えても戻らない F18 ので、必ず音量を送り直す)
- 結果は user_data/checks/日時_名前.json とログに残す(Claude はそれを読む)
ここは手順を組み立てるだけ(送らない)。実行はアプリ。
"""
from dataclasses import dataclass, field

from .device import sysex
from .music.waves import PRESETS as WAVES

TRI = WAVES["三角"]


@dataclass
class CheckStep:
    text: str                       # 何をしたか(画面に出す)
    question: str                   # 問い
    expect: str | None              # "yes"(鳴るはず)/ "no"(鳴らないはず)/ None(調べたいだけ)
    sends: list = field(default_factory=list)   # [(秒, bytes)] 送るもの。秒は始めてからの時間


@dataclass
class Check:
    name: str
    title: str
    description: str
    steps: list


def _cc(ch, cc, v):
    return bytes([0xB0 | (ch - 1), cc, v])


def _note(ch, n, vel, t=0.05, length=0.7):
    return [(t, bytes([0x90 | (ch - 1), n, vel])), (t + length, bytes([0x80 | (ch - 1), n, 0]))]


def basic_check():
    """作り直し版の基本の確認: 各 ch が鳴るか、和音、波形メモリ"""
    steps = [
        CheckStep("ch1(パルス)で C4 を鳴らしました", "いま、音が鳴りましたか?", "yes", [(0, _cc(1, 7, 127))] + _note(1, 60, 100)),
        CheckStep("ch2(パルス)で E4 を鳴らしました", "いま、音が鳴りましたか?", "yes", [(0, _cc(2, 7, 127))] + _note(2, 64, 100)),
        CheckStep("ch3(三角波)で C3 を鳴らしました", "いま、音が鳴りましたか?", "yes", [(0, _cc(3, 7, 127))] + _note(3, 48, 100)),
        CheckStep("ch4(ノイズ)でノート 6 を鳴らしました", "いま、音が鳴りましたか?", "yes", [(0, _cc(4, 7, 127))] + _note(4, 6, 100)),
        CheckStep("ch5 を DPCM にして、ノート 36 を鳴らしました", "いま、音が鳴りましたか?", "yes",
                  [(0, _cc(5, 18, 0))] + _note(5, 36, 100)),
        CheckStep("ch5 を波形メモリ(三角の波形)にして、C4 を鳴らしました", "いま、音が鳴りましたか?", "yes",
                  [(0, _cc(5, 18, 127)), (0.02, sysex.wave_data(TRI)), (0.03, _cc(5, 7, 127))] + _note(5, 60, 100, 0.1)),
        CheckStep("ch1・ch2・ch3・ch5 で C の和音を同時に鳴らしました", "いま、和音(4つの音)が鳴りましたか?", "yes",
                  [(0, _cc(5, 18, 127)), (0.02, sysex.wave_data(TRI))]
                  + _note(3, 36, 100, 0.1, 1.2) + _note(1, 76, 100, 0.1, 1.2) + _note(2, 67, 100, 0.1, 1.2)
                  + _note(5, 72, 100, 0.1, 1.2)),
        CheckStep("ch1 の音量(CC#7)を 0 にして、C4 を鳴らしました", "いま、音が鳴りましたか?", "no",
                  [(0, _cc(1, 7, 0))] + _note(1, 60, 100)),
    ]
    return Check("basic", "作り直し版の基本の確認",
                 "各 ch が鳴るか、和音、波形メモリ、音量0 を、8つの手順で確かめます。", steps)


def v0_check():
    """V0: 音量(CC#7)0 でも強く弾くと鳴ることがあるか(ch2 か ch5)"""
    steps = [CheckStep("基準: ch2 を音量 127 で、強さ 100 で C4", "いま、音が鳴りましたか?", "yes",
                       [(0, _cc(2, 7, 127))] + _note(2, 60, 100))]
    for ch, label, pre in ((2, "ch2(パルス)", []), (5, "ch5(波形メモリ)", [(0, _cc(5, 18, 127)), (0.02, sysex.wave_data(TRI))]),
                           (1, "ch1(パルス)", [])):
        for vel in (127, 64):
            steps.append(CheckStep(f"{label} の音量(CC#7)を 0 にして、強さ {vel} で C4", "いま、音が鳴りましたか?", None,
                                   pre + [(0.03, _cc(ch, 7, 0))] + _note(ch, 60, vel, 0.1)))
    return Check("v0", "音量0でも鳴るか(V0)",
                 "音量を0にした ch を強く弾いて、鳴るかどうかを調べます(法則は分かっていません)。", steps)


def places_check(tiles, ch_for_kind):
    """書き込んだ保存場所を1つずつ試す。tiles: cart_view の tiles。
    毎回、呼び出す前に音量(CC#7・CC#11)を127に戻す(音量0は PC を変えても戻らない、CLAUDE.md 9)。
    音量0の音色(書き込みテスト用など)は「鳴らないはず」と判定する"""
    steps = []
    for t in tiles:
        if t["empty"] or t["unknown"] or not t["kind"]:
            continue
        ch = ch_for_kind[t["kind"]]
        note = 6 if ch == 4 else 60
        sends = [(0, _cc(ch, 7, 127)), (0, _cc(ch, 11, 127)), (0, bytes([0xC0 | (ch - 1), t["pc"] - 1]))]             + _note(ch, note, 100, 0.15, 0.8)
        if t.get("silent"):
            steps.append(CheckStep(f"保存場所 {t['place']}「{t['name']}」(音量0の音色)を ch{ch} で呼び出して鳴らしました",
                                   "いま、音が鳴りましたか?(音量0の音色なので、正しく入っていれば鳴りません)", "no", sends))
        else:
            steps.append(CheckStep(f"保存場所 {t['place']}「{t['name']}」を ch{ch} で呼び出して鳴らしました",
                                   f"いま、「{t['name']}」の音で鳴りましたか?", "yes", sends))
    return Check("places", "保存場所を1つずつ試す",
                 f"このアプリで音色を入れた保存場所({len(steps)} か所)を、1つずつ呼び出して鳴らします。", steps)
