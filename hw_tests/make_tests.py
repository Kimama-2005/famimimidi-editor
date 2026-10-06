"""実機テスト用 MIDI ファイル生成(第2回)。

標準ライブラリだけで SMF(format 1)を書き出す。
Domino は「1トラックに複数チャンネル」を読み込めないので、
トラック0 = テンポ/名前、以降 = チャンネルごとに1トラック、にする。

各 .mid と同名の .txt に、送信順・時刻(ms)・バイト列の一覧を書き出す
(ユーザーの報告と突き合わせるため)。

使い方:  python hw_tests/make_tests.py      → hw_tests/out/ に出力
"""
import struct
from pathlib import Path

TPQ = 480
TEMPO_US = 600000          # 100 BPM → 1 tick = 1.25 ms
MS_PER_TICK = TEMPO_US / 1000 / TPQ
OUT = Path(__file__).parent / "out"

# 既に実績のある待ち時間(T0 と同じ)
T_GAP = 480        # 600ms  一般的な間隔
T_CC = 60          # 75ms   マクロ内のCC間隔
T_AFTER_STOP = 1440  # 1.8s  CC45=0 のあと
T_AFTER_EXEC = 720   # 0.9s  CC47 のあと
T_AFTER_ASSIGN = 480  # 0.6s CC51/CC50 のあと


def vlq(n):
    o = [n & 0x7F]
    n >>= 7
    while n:
        o.append((n & 0x7F) | 0x80)
        n >>= 7
    return bytes(reversed(o))


def cc(ch, num, val):
    """ch は 1 始まり"""
    return bytes([0xB0 | (ch - 1), num, val])


def pc(ch, data):
    return bytes([0xC0 | (ch - 1), data])


def non(ch, note, vel):
    return bytes([0x90 | (ch - 1), note, vel])


def nof(ch, note):
    return bytes([0x80 | (ch - 1), note, 0])


class Song:
    def __init__(self, name):
        self.name = name
        self.ev = []   # (tick, seq, bytes)

    def add(self, tick, msg):
        self.ev.append((tick, len(self.ev), msg))

    def track_bytes(self, events, name=None, tempo=False):
        d = b""
        if name:
            nb = name.encode("ascii", "replace")
            d += vlq(0) + b"\xFF\x03" + vlq(len(nb)) + nb
        if tempo:
            d += vlq(0) + b"\xFF\x51\x03" + TEMPO_US.to_bytes(3, "big")
        last = 0
        for t, _, m in events:
            d += vlq(t - last) + m
            last = t
        d += vlq(0) + b"\xFF\x2F\x00"
        return b"MTrk" + struct.pack(">I", len(d)) + d

    def save(self, stem):
        OUT.mkdir(exist_ok=True)
        ev = sorted(self.ev)
        # 同じ tick に別チャンネルのイベントがあると、Domino 上の順序が保証されない
        seen = {}
        for t, _, m in ev:
            ch = m[0] & 0x0F
            if t in seen and seen[t] != ch:
                raise ValueError(f"{stem}: tick {t} に複数チャンネルのイベントがある")
            seen[t] = ch
        chans = sorted({m[0] & 0x0F for _, _, m in ev})
        tracks = [self.track_bytes([], name=self.name, tempo=True)]
        for c in chans:
            tracks.append(self.track_bytes([e for e in ev if e[2][0] & 0x0F == c],
                                           name=f"ch{c + 1}"))
        with open(OUT / f"{stem}.mid", "wb") as f:
            f.write(b"MThd" + struct.pack(">IHHH", 6, 1, len(tracks), TPQ))
            for tr in tracks:
                f.write(tr)
        with open(OUT / f"{stem}.txt", "w", encoding="utf-8") as f:
            f.write(f"{stem}  ({self.name})\n")
            f.write("時刻(ms)   バイト列      意味\n")
            for t, _, m in ev:
                f.write(f"{t * MS_PER_TICK:9.1f}  {m.hex(' ').upper():<12}  {describe(m)}\n")
        print(f"wrote {stem}.mid  ({len(ev)} events, {ev[-1][0] * MS_PER_TICK / 1000:.1f}s)")


def describe(m):
    st, ch = m[0] & 0xF0, (m[0] & 0x0F) + 1
    if st == 0xB0:
        return f"ch{ch} CC#{m[1]}={m[2]}"
    if st == 0xC0:
        return f"ch{ch} PC{m[1] + 1}(送信値{m[1]})"
    if st == 0x90:
        return f"ch{ch} ノートON {m[1]} vel{m[2]}"
    if st == 0x80:
        return f"ch{ch} ノートOFF {m[1]}"
    return ""


def record_macro(s, t, n, ccs, ch=1):
    """ユーザーマクロ n を記録して実行する(実績のある手順)。戻り値は次の tick。
    ccs: [(ch, cc, val)]  先頭10個までしか記録されない(F8)"""
    assert len(ccs) <= 10
    s.add(t, cc(ch, 49, 47)); t += T_GAP
    s.add(t, cc(ch, 45, n)); t += T_GAP
    for c, num, val in ccs:
        s.add(t, cc(c, num, val)); t += T_CC
    t += T_GAP - T_CC
    s.add(t, cc(ch, 45, 0)); t += T_AFTER_STOP
    s.add(t, cc(ch, 47, n)); t += T_AFTER_EXEC
    return t


MUTE = [(1, 7, 0), (1, 11, 0)]          # マクロ20の中身(T5と同じ)
NEUTRAL = [(1, 7, 127), (1, 11, 127)]   # マクロ19の中身(T0で記録済み)


def make_t2():
    """U4: 1つのマクロで複数チャンネルを変えられるか。T2 をトラック分割しただけ。"""
    s = Song("T2b multi-ch macro")
    t = record_macro(s, 0, 10, [(1, 70, 16), (4, 7, 0)])
    # 記録中の CC は生でも効く(F11)ので、前半のために戻す
    s.add(t, cc(1, 70, 80)); t += 30
    s.add(t, cc(4, 7, 127)); t += 30
    s.add(t, cc(4, 75, 14)); t += 30
    s.add(t, cc(4, 79, 0)); t += 30
    s.add(t, cc(4, 12, 127)); t += T_GAP

    def phrase(t):
        for note in (72, 76, 79, 84):
            s.add(t, non(1, note, 110))
            s.add(t + 1, non(4, 6, 120))
            s.add(t + 40, nof(4, 6))
            s.add(t + 120, non(4, 6, 120))
            s.add(t + 160, nof(4, 6))
            s.add(t + 220, nof(1, note))
            t += 240
        return t

    t = phrase(t) + T_GAP * 2
    s.add(t, cc(1, 47, 10)); t += T_GAP   # マクロ10を実行
    phrase(t)
    s.save("T2b_multichannel")


def make_t7():
    """U1: 電源ON後、SELECT+→ ×9 でどの PC に着くか。PC89 だけを無音にする。"""
    s = Song("T7 mute PC89 only")
    t = record_macro(s, 0, 20, MUTE)
    s.add(t, cc(1, 51, 88)); t += T_AFTER_ASSIGN   # PC89 ← マクロ20(無音)
    s.add(t, cc(1, 7, 127)); t += T_CC            # 生の音量を戻す
    s.add(t, cc(1, 11, 127)); t += T_GAP
    s.save("T7_mute_pc89_only")


def make_t6():
    """U3: CC#50(電源ONマクロ)が効くか。ch1 の電源ONマクロを「無音」にする。"""
    s = Song("T6 startup macro = mute")
    t = record_macro(s, 0, 20, MUTE)
    s.add(t, cc(1, 50, 1)); t += T_AFTER_ASSIGN    # ch1 電源ON ← マクロ20(無音)
    s.add(t, cc(1, 7, 127)); t += T_CC
    s.add(t, cc(1, 11, 127)); t += T_GAP
    s.save("T6_startup_mute")


def make_restore():
    """T6/T7 の後片付け。PC89 と ch1 電源ONマクロを T0 の状態に戻す。"""
    # マクロ19(音量最大)と11(J-POP標準)は T0 で記録済みなので、実行して割り当てるだけ
    s = Song("R2 restore PC89 + startup")
    t = 0
    s.add(t, cc(1, 49, 47)); t += T_GAP
    s.add(t, cc(1, 47, 19)); t += T_AFTER_EXEC
    s.add(t, cc(1, 51, 88)); t += T_AFTER_ASSIGN   # PC89 ← マクロ19
    s.add(t, cc(1, 47, 11)); t += T_AFTER_EXEC
    s.add(t, cc(1, 50, 1)); t += T_AFTER_ASSIGN    # ch1 電源ON ← マクロ11
    s.add(t, cc(1, 7, 127)); t += T_GAP
    s.save("R2_restore")


def phrase(s, t, bars=1):
    """ch1 メロディ(ド・ミ・ソ・ド)+ ch4 ノイズ(1拍に2発)。bars 回くり返す"""
    for _ in range(bars):
        for note in (72, 76, 79, 84):
            s.add(t, non(1, note, 110))
            s.add(t + 1, non(4, 6, 120))
            s.add(t + 40, nof(4, 6))
            s.add(t + 120, non(4, 6, 120))
            s.add(t + 160, nof(4, 6))
            s.add(t + 220, nof(1, note))
            t += 240
    return t


def restore_live(s, t):
    """ch1 と ch4 の音量を生で戻し、ch4 を短いノイズにする(マクロには入らない)"""
    for c, num, val in [(1, 7, 127), (1, 11, 127), (4, 7, 127), (4, 11, 127),
                        (4, 75, 14), (4, 79, 0), (4, 12, 127)]:
        s.add(t, cc(c, num, val)); t += 30
    return t + T_GAP


def make_t9():
    """U4 再試験(T2b は判定が聴き分けだった)。判定はすべて「無音かどうか」。
    マクロはすべて ch1 で記録・実行する。
      マクロ14 = [ch1 CC#7=0]                 対照: 手順そのものが効くか
      マクロ15 = [ch4 CC#7=0]                 他chのCCだけのマクロはどこに効くか
      マクロ16 = [ch4 CC#7=0, ch1 CC#7=0]     他chのCCのあとに ch1 のCCが記録されるか
    仮説ごとの予想(メロディ / ノイズ):
      他chのCCは無視される       … 15: 鳴る/鳴る   16: 無音/鳴る
      chが捨てられ実行chに効く   … 15: 無音/鳴る   16: 無音/鳴る
      chごと記録される(本命)     … 15: 鳴る/無音   16: 無音/無音
      他chのCCで記録が壊れる     … 15: 鳴る/鳴る   16: 鳴る/鳴る
    """
    s = Song("T9 multi-ch macro (mute)")
    t = record_macro(s, 0, 14, [(1, 7, 0)])
    t = record_macro(s, t, 15, [(4, 7, 0)])
    t = record_macro(s, t, 16, [(4, 7, 0), (1, 7, 0)])
    t = restore_live(s, t) + T_GAP * 2          # ここまで約16秒、音は鳴らない
    t = phrase(s, t, 2) + T_GAP * 2              # 第1部: 何もしない(両方鳴るはず)
    for m in (14, 15, 16):                       # 第2〜4部
        s.add(t, cc(1, 47, m)); t += T_GAP
        t = phrase(s, t, 2) + T_GAP
        t = restore_live(s, t) + T_GAP
    s.save("T9_multichannel_mute")


def make_t8():
    """U1 確認: SELECT+→ ×9 = PC89 か、→ が +1 か。PC89=音量最大、PC90=無音 にする"""
    s = Song("T8 PC89 neutral, PC90 mute")
    t = 0
    s.add(t, cc(1, 49, 47)); t += T_GAP
    s.add(t, cc(1, 47, 19)); t += T_AFTER_EXEC     # マクロ19(音量最大、T0で記録済み)
    s.add(t, cc(1, 51, 88)); t += T_AFTER_ASSIGN   # PC89 ← 19
    s.add(t, cc(1, 47, 20)); t += T_AFTER_EXEC     # マクロ20(無音、T5/T7で記録済み)
    s.add(t, cc(1, 51, 89)); t += T_AFTER_ASSIGN   # PC90 ← 20
    s.add(t, cc(1, 7, 127)); t += T_CC
    s.add(t, cc(1, 11, 127)); t += T_GAP
    s.save("T8_pc89_neutral_pc90_mute")


def make_r3():
    """T8 の後片付け: PC90 をマクロ19(音量最大)に戻す"""
    s = Song("R3 restore PC90")
    t = 0
    s.add(t, cc(1, 49, 47)); t += T_GAP
    s.add(t, cc(1, 47, 19)); t += T_AFTER_EXEC
    s.add(t, cc(1, 51, 89)); t += T_AFTER_ASSIGN   # PC90 ← 19
    s.add(t, cc(1, 7, 127)); t += T_GAP
    s.save("R3_restore")


def make_t10():
    """仮説「記録中、値が変わらない CC は記録されない」の確認(段階3 C(2) で PC96 が音量を戻さなかった)。
      マクロ21 = [CC#7=127] を、ch1 の音量が **127 のまま**記録   → PC99
      マクロ22 = [CC#7=127] を、ch1 の音量を **0 にしてから**記録 → PC100
      マクロ17 = [CC#7=0](段階3で記録済み)→ PC97
    再生部(PC だけで切り替える):
      1 何もしない → 鳴る / 2 PC97 → 無音 / 3 PC99 → ? / 4 PC97 → 無音 / 5 PC100 → ?
    仮説どおりなら 3=無音、5=鳴る
    """
    s = Song("T10 same-value CC recording")
    t = 0
    s.add(t, cc(1, 7, 127)); t += T_GAP                  # 念のため 127 にそろえる(生)
    t = record_macro(s, t, 21, [(1, 7, 127)])            # 同じ値で記録
    s.add(t, cc(1, 51, 98)); t += T_AFTER_ASSIGN         # PC99 ← 21
    s.add(t, cc(1, 7, 0)); t += T_GAP                    # 生で 0 にしてから
    t = record_macro(s, t, 22, [(1, 7, 127)])            # 違う値で記録
    s.add(t, cc(1, 51, 99)); t += T_AFTER_ASSIGN         # PC100 ← 22
    s.add(t, cc(1, 7, 127)); t += T_GAP * 3              # ここまで約10秒、音は鳴らない

    def melody(t):
        for note in (72, 76, 79, 84):
            s.add(t, non(1, note, 110))
            s.add(t + 200, nof(1, note))
            t += 240
        return t + T_GAP * 2

    t = melody(t)                                        # 1
    for data in (96, 98, 96, 99):                        # 2: PC97, 3: PC99, 4: PC97, 5: PC100
        s.add(t, pc(1, data)); t += T_GAP
        t = melody(t)
    s.add(t, cc(1, 7, 127)); t += T_GAP                  # 最後に音量を戻す(生)
    s.save("T10_same_value_record")


def make_t11():
    """書き込みなし。PC と CC#47(マクロ実行)と生の CC だけで、次を「鳴った/無音」で見る。
      1 ch1 を生で音量0 → マクロ19を直接実行 → ch1 メロディ   (鳴れば マクロ19 は音量を戻せる)
      2 ch2 メロディ(何もしない)                             (鳴るはず)
      3 ch2 に PC97(マクロ17=音量0)→ ch2 メロディ           (無音なら PC は受けたchに効く: U8)
      4 ch1 メロディ                                          (鳴れば ch2 への PC は ch1 に影響しない)
      5 ch5 ドン×4(DPCM、何もしない)                         (鳴るはず)
      6 ch5 を生で音量0 → ドン×4                               (無音なら DPCM も音量CCに従う)
      7 ch5 の音量を戻す → ch5 でマクロ17を直接実行 → ドン×4   (無音なら ch5 でもマクロが効く: U13)
      8 ch5 の音量を戻す → ch5 に PC97 → ドン×4                (無音なら ch5 でも PC→マクロが効く)
    """
    s = Song("T11 no-write checks")
    t = 0
    for c, num, val in [(1, 7, 127), (1, 11, 127), (2, 7, 127), (2, 11, 127),
                        (5, 18, 0), (5, 7, 127), (5, 11, 127)]:   # ch5 は DPCM モードに
        s.add(t, cc(c, num, val)); t += 30
    t += T_GAP * 2

    def melody(t, ch, base):
        for n in (0, 4, 7, 12):
            s.add(t, non(ch, base + n, 110))
            s.add(t + 200, nof(ch, base + n))
            t += 240
        return t + T_GAP * 2

    def kicks(t):
        for _ in range(4):
            s.add(t, non(5, 36, 120))
            s.add(t + 100, nof(5, 36))
            t += 240
        return t + T_GAP * 2

    # 1
    s.add(t, cc(1, 7, 0)); t += T_GAP
    s.add(t, cc(1, 49, 47)); t += T_CC
    s.add(t, cc(1, 47, 19)); t += T_AFTER_EXEC
    t = melody(t, 1, 72)
    s.add(t, cc(1, 7, 127)); t += T_GAP
    # 2, 3, 4
    t = melody(t, 2, 84)
    s.add(t, pc(2, 96)); t += T_GAP
    t = melody(t, 2, 84)
    t = melody(t, 1, 72)
    s.add(t, cc(2, 7, 127)); t += T_GAP
    # 5, 6
    t = kicks(t)
    s.add(t, cc(5, 7, 0)); t += T_GAP
    t = kicks(t)
    # 7
    s.add(t, cc(5, 7, 127)); t += T_GAP
    s.add(t, cc(5, 47, 17)); t += T_AFTER_EXEC
    t = kicks(t)
    # 8
    s.add(t, cc(5, 7, 127)); t += T_CC
    s.add(t, cc(5, 11, 127)); t += T_GAP
    s.add(t, pc(5, 96)); t += T_GAP
    t = kicks(t)
    # 後片付け(生): 音量を戻し、ch5 を初期の PC8 に
    s.add(t, cc(5, 7, 127)); t += T_CC
    s.add(t, pc(5, 7)); t += T_CC
    s.add(t, cc(2, 7, 127)); t += T_CC
    s.add(t, cc(1, 7, 127)); t += T_GAP
    s.save("T11_no_write_checks")


def make_t12():
    """A1 / U13: ch5 で保存した音色(マクロ)が効くか。
    ch5 は DPCM に音量が効かない(F25)ので「CC#18 = 波形メモリモード」で判定する:
      DPCM モードではノート60に音が割り当てられていない → 無音、波形メモリモードなら音程のある音が鳴る
      マクロ23 = [CC#18=127] を ch1 で記録 → PC103、マクロ24 = 同じものを ch5 で記録 → PC104
    再生部(ch5):
      1 ノート36(ドラム)… 鳴るはず(ch5 が生きている確認)
      2 ノート60 … 無音のはず(DPCM モード)
      3 生で CC#18=127 → ノート60   鳴るはず(波形メモリモードなら鳴る、という前提の確認)
      4 ch5 でマクロ23を直接実行 → ノート60   鳴れば「ch1 で記録したマクロが ch5 で効く」
      5 ch5 でマクロ24を直接実行 → ノート60   鳴れば「ch5 で記録したマクロが ch5 で効く」
      6 ch5 に PC96(マクロ19 = 波形メモリに関係ない)→ ノート60   無音のはず(対照)
      7 ch5 に PC103 → ノート60   鳴れば「ch5 でも 呼び出し番号 → マクロ が効く」
      8 ch5 に PC104 → ノート60
    3〜8 の前には毎回 ch5 を DPCM モード(CC#18=0)に戻す。最後に PC103/104 を空き(マクロ19)に戻す
    """
    s = Song("T12 ch5 macro (wave mode)")
    t = 0
    s.add(t, cc(5, 18, 0)); t += T_CC
    s.add(t, pc(5, 7)); t += T_CC                        # ch5 の初期値 PC8
    t = record_macro(s, t + T_GAP, 23, [(1, 18, 127)])   # ch1 で記録
    s.add(t, cc(1, 51, 102)); t += T_AFTER_ASSIGN        # PC103 ← 23
    s.add(t, cc(5, 45, 24)); t += T_GAP                  # ch5 で記録(CC#49 は ch5 に無いので送らない)
    s.add(t, cc(5, 18, 127)); t += T_GAP
    s.add(t, cc(5, 45, 0)); t += T_AFTER_STOP
    s.add(t, cc(5, 47, 24)); t += T_AFTER_EXEC
    s.add(t, cc(5, 51, 103)); t += T_AFTER_ASSIGN        # PC104 ← 24
    s.add(t, cc(5, 18, 0)); t += T_GAP * 3               # ここまで約12秒、音は鳴らない

    def notes(t, note, n=2):
        for _ in range(n):
            s.add(t, non(5, note, 120))
            s.add(t + 360, nof(5, note))
            t += 480
        return t + T_GAP * 2

    t = notes(t, 36)                                     # 1
    t = notes(t, 60)                                     # 2
    # 3〜8。3 は前提の確認: マクロを使わず生で波形メモリモードにすると、ノート60 が鳴るか
    for action in (cc(5, 18, 127), cc(5, 47, 23), cc(5, 47, 24), pc(5, 95), pc(5, 102), pc(5, 103)):
        s.add(t, cc(5, 18, 0)); t += T_CC
        s.add(t, action); t += T_AFTER_EXEC
        t = notes(t, 60)
    # 後片付け: ch5 を DPCM・PC8 に戻し、PC103/104 を空き(マクロ19)に
    s.add(t, cc(5, 18, 0)); t += T_CC
    s.add(t, pc(5, 7)); t += T_GAP
    s.add(t, cc(1, 49, 47)); t += T_GAP
    s.add(t, cc(1, 47, 19)); t += T_AFTER_EXEC
    s.add(t, cc(1, 51, 102)); t += T_AFTER_ASSIGN
    s.add(t, cc(1, 51, 103)); t += T_AFTER_ASSIGN
    s.save("T12_ch5_macro")


def make_t13():
    """A1 / U13 の再試験。T12 は「DPCM でノート60は無音」という前提が外れて判定できなかった(全部鳴った)。
    今度はアルペジエーター(CC#23、ch5 対応)で判定する: ノート36(バスドラム)とノート38(スネア)を同時に押すと、
      アルペジエーター OFF … 後から押した1音だけ(単音・後着優先)
      アルペジエーター ON  … ドン・タンが交互に繰り返す
    マクロ23 = [CC#23=127](ch1 で記録)→ PC103
    再生部(すべて ch5、DPCM モード。毎回の前に CC#23=0 に戻す):
      1 何もしない → 1つだけ
      2 生で CC#23=127 → 交互(前提の確認)
      3 ch5 でマクロ23を直接実行 → 交互なら「ch1 で記録したマクロが ch5 で効く」
      4 ch5 に PC96(マクロ19、アルペジエーターに関係ない)→ 1つだけ(対照)
      5 ch5 に PC103 → 交互なら「ch5 でも 呼び出し番号 → マクロ が効く」
    最後に PC103 を空き(マクロ19)に戻す
    """
    s = Song("T13 ch5 macro (arpeggiator)")
    t = 0
    for c, num, val in [(5, 18, 0), (5, 23, 0), (5, 24, 12)]:   # DPCM、アルペジエーター OFF、速さ約100ms
        s.add(t, cc(c, num, val)); t += T_CC
    s.add(t, pc(5, 7)); t += T_CC
    t = record_macro(s, t + T_GAP, 23, [(1, 23, 127)])
    s.add(t, cc(1, 23, 0)); t += T_CC                    # 記録中に ch1 にも効いたので戻す(F11)
    s.add(t, cc(1, 51, 102)); t += T_AFTER_ASSIGN        # PC103 ← 23
    t += T_GAP * 3                                       # ここまで約8秒、音は鳴らない

    def chord(t):
        s.add(t, non(5, 36, 120))
        s.add(t + 20, non(5, 38, 120))
        s.add(t + 1400, nof(5, 36))
        s.add(t + 1420, nof(5, 38))
        return t + 1420 + T_GAP * 2

    t = chord(t)                                         # 1
    for action in (cc(5, 23, 127), cc(5, 47, 23), pc(5, 95), pc(5, 102)):   # 2〜5
        s.add(t, cc(5, 23, 0)); t += T_CC
        s.add(t, action); t += T_AFTER_EXEC
        t = chord(t)
    s.add(t, cc(5, 23, 0)); t += T_CC
    s.add(t, pc(5, 7)); t += T_GAP
    s.add(t, cc(1, 49, 47)); t += T_GAP
    s.add(t, cc(1, 47, 19)); t += T_AFTER_EXEC
    s.add(t, cc(1, 51, 102)); t += T_AFTER_ASSIGN        # PC103 → 空き
    s.add(t, cc(1, 51, 103)); t += T_AFTER_ASSIGN        # PC104 も念のため(T12 の後片付けが届いたか音では確かめられない)
    s.save("T13_ch5_arp")


if __name__ == "__main__":
    make_t13()
    make_t12()
    make_t11()
    make_t2()
    make_t7()
    make_t6()
    make_restore()
    make_t9()
    make_t8()
    make_r3()
    make_t10()
