"""コードモード(SPEC_v2 6.5): 1つの鍵でコードを鳴らす。今の版の famimimidi/chordmode.py を、作り直し版の決まりに直したもの。

- 鍵盤は音を鳴らすことにだけ使う(37鍵 C3〜C6): C3〜B5 = コード、C2〜B2 = 入りきらなかったコード、C6 = なにもしない。
  配置「度数+補足」(degree_r / degree_l)だけは、基本コード・補足・分数のベースの鍵を同時に押す(music/degree.py)
  曲・キー・ホールド・止めるは画面とパソコンのキー(機能キーは無い)
- 声: ベース = ch3。"split" はボイス1・2・3 = ch1・ch2・ch5(大事な2音をパルス、3番目を波形メモリ)。
  "arp" は構成音を全部 ch1 へ(ふぁみみみっでぃのアルペジエーター)
- 鳴らし方は奏法プリセット(model/performance.ChordSettings.engine_values)
- サスティンペダルは踏んでいる間コードを保持(controls.pedal)。ベンド・モジュレーション・アフタータッチは controls の to に入っているボイスへ
- コードモードの間だけ変える設定(6.5.6)は、音色と同じ間引きの列(set_cc)に入れる = 最後の値が勝つ。抜けるときは音色の値に戻す

送るのは send(msg)、時間をずらす送信はスケジューラ(1本)。画面からは独立。
"""
import random
import threading

from ..model.chordbook import ChordBook
from ..model.performance import MOD_CC, ChordSettings, Controls
from ..music import chords as cd
from ..music import degree as dg

BASS_CH = 3
UPPER_CHS = (1, 2, 5)
GLIDE_CHS = (1, 2, 3)              # ポルタメントが効く ch(波形メモリには効かない)
GLIDE_TIME = 12
WAVE_MODE_CC, ARP_CC, PORTA_CC, PORTA_TIME_CC, SUSTAIN_CC = 18, 23, 65, 5, 64
ROWS = 4


def slot_note(row, off):
    """段・位置 → 鍵(4段目は C2〜B2)"""
    return cd.COMMON_LO + off if row == cd.COMMON_ROW else cd.ROW_LO + row * 12 + off


def key_slot(note):
    """鍵 → 段・位置(コードの鍵でなければ None)"""
    if cd.COMMON_LO <= note < cd.ROW_LO:
        return cd.COMMON_ROW, note - cd.COMMON_LO
    if cd.ROW_LO <= note < cd.TOP_KEY:
        rel = note - cd.ROW_LO
        return rel // 12, rel % 12
    return None


class Voice:
    def __init__(self, ch):
        self.ch = ch
        self.target = None       # 鳴らすことにした音(None = 無音)。アルペジエーター方式の和音は音の組(tuple)
        self.sounding = None     # 実際にノートオンしている音
        self.gen = 0             # 予約を取り消すための番号


class ChordEngine:
    def __init__(self, send, to_ch0, get_value, set_cc, scheduler, rng=None, log=None, on_state=None):
        """send(bytes) / to_ch0(ch) → MIDI ch0 / get_value(ch, cc) → 音色の値(戻すとき)/ set_cc(ch, cc, v) → 間引きの列へ"""
        self._send, self._to_ch0, self._get_value, self._set_cc = send, to_ch0, get_value, set_cc
        self._sched = scheduler
        self._rng = rng or random.Random()
        self._log = log or (lambda text: None)
        self._on_state = on_state
        self._lock = threading.RLock()
        self.settings = ChordSettings()
        self.cfg = self.settings.engine_values()
        self.controls = Controls()
        self.book = ChordBook()
        self.active = False
        self.song, self.key, self.song_key = 0, 0, 0
        self.latch = self.sustain = False
        self.keys = []                 # 押しているコードの鍵(後に押したものが優先)
        self._release_gen = 0          # 度数+補足: 離したときの猶予の予約を取り消す番号
        self.vel = 100
        self._stop_gen = 0
        self.prev_upper = None
        self.current = None            # (Chord, 段, 位置)
        self.prog_pos = -1             # 進行のどこを弾いているか
        self._analyses = {}
        self._overrides = {}           # {(ch, cc): 値} コードモードの間だけ変えた設定
        self._voices = self._make_voices()
        self._select_song(0, notify=False)

    # ================================================================ 設定・曲
    def _make_voices(self):
        if self.cfg["method"] == "arp":
            return [Voice(BASS_CH), Voice(self.cfg["arp_ch"])]
        return [Voice(BASS_CH)] + [Voice(ch) for ch in UPPER_CHS]

    def channels(self):
        return [v.ch for v in self._voices]

    def configure(self, settings: ChordSettings, controls: Controls | None = None):
        with self._lock:
            was = self.active
            if was:
                self._leave()
            layout_changed = settings.layout != self.settings.layout
            self.settings = settings.normalized()
            self.cfg = self.settings.engine_values()
            if controls is not None:
                self.controls = controls.normalized()
            self._voices = self._make_voices()
            self.prev_upper = None
            if layout_changed:
                self._analyses = {}
            if was:
                self._enter()
            self._notify()

    def set_controls(self, controls: Controls):
        with self._lock:
            self.controls = controls.normalized()

    def set_book(self, book: ChordBook):
        with self._lock:
            self.book = book
            self._analyses = {}
            self._select_song(self.song, notify=True)

    def common(self):
        return cd.parse_common(self.book.common_row)

    def analysis(self, i):
        if i not in self._analyses:
            s = self.book.songs[i]
            self._analyses[i] = cd.analyze(s.text, s.key, self.common(), self.cfg["layout"])
        return self._analyses[i]

    def _select_song(self, i, notify=True):
        if 0 <= i < len(self.book.songs):
            self.song = i
            self.song_key = self.key = self.analysis(i).key
            self.prog_pos = -1
            if notify:
                self._log(f"コードモード: 曲{i + 1}「{self.book.songs[i].name}」キー {cd.SHARP[self.key]}")
                self._notify()

    def select_song(self, i):
        with self._lock:
            self._select_song(int(i))

    def next_song(self, d):
        """←/→: 曲の名前が入っている曲だけを順に"""
        with self._lock:
            filled = [i for i, s in enumerate(self.book.songs) if s.name or s.text] or [0]
            cur = filled.index(self.song) if self.song in filled else 0
            self._select_song(filled[(cur + int(d)) % len(filled)])

    def set_key(self, k):
        with self._lock:
            self.key = int(k) % 12
            self._log(f"コードモード: キー {cd.SHARP[self.key]}")
            self._notify()

    def shift_key(self, d):
        self.set_key(self.key + int(d))

    def toggle_hold(self):
        with self._lock:
            self.latch = not self.latch
            if not self.latch and not self.keys and not self.sustain:
                self._stop()
            self._log(f"コードモード: ホールド {'ON' if self.latch else 'OFF'}")
            self._notify()

    def stop_all(self):
        """パニック・画面の「止める」・Esc: 押している鍵もホールドも忘れて、すぐ止める"""
        with self._lock:
            self.keys, self.latch = [], False
            self._stop_now()
            self._notify()

    def _degree(self):
        return dg.is_scheme(self.cfg["layout"])

    def slot_note(self, row, off):
        """段・位置 → 鍵。度数+補足では 0段目 = 基本コードの鍵、1段目 = 補足の鍵、2段目 = 分数のベースの鍵"""
        if self._degree():
            lay = self.cfg["layout"]
            return dg.degree_note(off, lay) if row == 0 else dg.mod_note(off, lay) if row == 1 else dg.bass_key_note(off, lay)
        return slot_note(row, off)

    def chord_for(self, row, off):
        """段・位置 → いまの曲・キーでのコード(配置は曲のキーで作ってあるのでずらす)"""
        a = self.analysis(self.song)
        c = a.assign.table.get((row, off))
        return c.transpose(self.key - a.key) if c else None

    # ================================================================ ON/OFF
    def set_active(self, on):
        with self._lock:
            if bool(on) == self.active:
                return
            if on:
                self._enter()
            else:
                self._leave()
            self._notify()

    def _enter(self):
        self.active = True
        self.keys, self.latch, self.sustain = [], False, False
        self.prev_upper, self.current = None, None
        sets = {}
        if self.cfg["method"] == "split":
            sets[(5, WAVE_MODE_CC)] = 127                                   # ボイス3は波形メモリ
        elif self._get_value(self.cfg["arp_ch"], ARP_CC) == 0:
            sets[(self.cfg["arp_ch"], ARP_CC)] = 127                         # アルペジエーターを ON
        if self.cfg["glide"]:
            for ch in GLIDE_CHS:
                if ch in self.channels():
                    sets[(ch, PORTA_CC)] = 127
                    sets[(ch, PORTA_TIME_CC)] = GLIDE_TIME
        self._overrides = sets
        for (ch, cc), v in sets.items():
            self._set_cc(ch, cc, v)
        self._log("コードモード: ON")

    def _leave(self):
        self._stop_now()
        for (ch, cc) in self._overrides:                                     # 音色の値に戻す
            v = self._get_value(ch, cc)
            if v is not None:
                self._set_cc(ch, cc, v)
        self._overrides = {}
        self.active = False
        self.keys = []
        self._log("コードモード: OFF")

    def override_values(self):
        """コードモードの間だけ変えている設定 {(ch, cc): 値}(この間は音色の値で上書きしない)"""
        with self._lock:
            return dict(self._overrides) if self.active else {}

    # ================================================================ 入力
    def handle(self, msg: bytes):
        """入力1つ。→ 送らなかった理由(受け持ったら None)"""
        st = msg[0] if msg else 0
        if not 0x80 <= st < 0xF0:
            return "鍵盤の操作は使いません"
        kind = st & 0xF0
        with self._lock:
            if not self.active:
                return "コードモードが OFF です"
            if kind in (0x80, 0x90) and len(msg) >= 3:
                if kind == 0x90 and msg[2] > 0:
                    return self.note_on(msg[1], msg[2])
                return self.note_off(msg[1])
            if kind == 0xB0 and len(msg) >= 3 and msg[1] == SUSTAIN_CC:
                if self.controls.pedal_use == "off":
                    return "サスティンペダルは「使わない」にしてあります"
                self.sustain = msg[2] >= 64
                if not self.sustain and not self.latch and not self.keys:
                    self._stop_after_grace()
                self._notify()
                return None
            if kind == 0xB0 and len(msg) >= 3 and msg[1] == 1:
                use = self.controls.mod_use
                for ch in self._to_voices(self.controls.mod_to, duty=use == "duty"):
                    self._send(bytes([0xB0 | self._to_ch0(ch), MOD_CC[use], msg[2]]))
                return None
            if kind == 0xE0 and len(msg) >= 3:
                for ch in self._to_voices(self.controls.bend_to):
                    self._send(bytes([0xE0 | self._to_ch0(ch)]) + msg[1:3])
                return None
            if kind == 0xD0 and len(msg) >= 2:
                for ch in self._to_voices(self.controls.mod_to):
                    self._send(bytes([0xD0 | self._to_ch0(ch), msg[1]]))
                return None
            return "鍵盤の操作は使いません(鍵盤は音を鳴らすことにだけ使う)"

    def _to_voices(self, to, duty=False):
        chs = [ch for ch in dict.fromkeys(self.channels()) if ch in to]
        return [ch for ch in chs if ch in (1, 2)] if duty else chs

    def note_on(self, note, vel=100):
        if self._degree():
            return self._degree_on(note, vel)
        slot = key_slot(note)
        if slot is None:
            return "コードの鍵ではありません(C2〜B5 で弾きます)"
        if note in self.keys:
            self.keys.remove(note)
        self.keys.append(note)
        self.vel = vel
        if not self._play_slot(*slot):
            return "この鍵にはコードがありません"
        return None

    def note_off(self, note):
        if self._degree():
            return self._degree_off(note)
        if note in self.keys:
            self.keys.remove(note)
            if self.keys:
                self._play_slot(*key_slot(self.keys[-1]), strike=False)    # まだ押している鍵に戻る(打ち直さない)
            elif not self.sustain and not self.latch:
                self._stop_after_grace()
        return None

    def play_slot(self, row, off, on=True, vel=None):
        """画面のコードの表を押した(鍵と同じ扱い)"""
        with self._lock:
            if not self.active:
                return False
            note = self.slot_note(int(row), int(off))
            if on:
                self.note_on(note, vel or self.vel)
            else:
                self.note_off(note)
            return True

    # ---------- 度数+補足 ----------
    def _held_degree(self):
        """押している基本コードの鍵(後に押したもの)と、補足の働きと、分数のベースの鍵(なければ None)"""
        lay = self.cfg["layout"]
        zones = {"degree": [], "mod": [], "bass": []}
        for n in self.keys:
            zones[dg.zone(n, lay)].append(n)
        degs, basses = zones["degree"], zones["bass"]
        return (degs[-1] if degs else None), dg.mods_of(zones["mod"]), (basses[-1] % 12 if basses else None)

    def _degree_on(self, note, vel):
        if note in self.keys:
            self.keys.remove(note)
        self.keys.append(note)
        self.vel = vel
        self._release_gen += 1              # 離したときの猶予の予約を取り消す(新しく押した方が勝つ)
        deg, mods, bass = self._held_degree()
        if deg is None:
            return None                     # 補足・ベースだけ: 基本コードの鍵が来たら効く
        # 基本コードの鍵 = 打ち直す。補足・ベースの鍵 = 押さえているコードをその場で変える(打ち直さない)。どれも進行は進みうる
        self._degree_play(deg, mods, strike=dg.is_degree_note(note, self.cfg["layout"]), advance=True, bass=bass)
        return None

    def _degree_off(self, note):
        if note not in self.keys:
            return None
        self.keys.remove(note)
        self._release_gen += 1
        g = self._release_gen
        deg, _, _ = self._held_degree()
        if deg is not None:
            # 残った鍵のコードに戻すのは猶予のあと。その間にほかの鍵も離した(同時に離したつもり)なら途中のコードを鳴らさない
            def later():
                if g != self._release_gen or not self.active:
                    return
                d, m, b = self._held_degree()
                if d is not None:
                    self._degree_play(d, m, strike=False, advance=False, bass=b)
            self._at(dg.RELEASE_WINDOW * 1000, later)
        elif dg.is_degree_note(note, self.cfg["layout"]) and not self.sustain and not self.latch:
            self._stop_after_grace()
        return None

    def _degree_play(self, deg, mods, strike, advance, bass=None):
        off = deg % 12
        c = dg.build(self.key, off, mods, bass)
        if not strike and self.current and self.current[0] == c:
            return
        self._play(c, 0, off, strike, advance)

    def _stop_after_grace(self):
        """全部離したとき: つなぎの猶予の間に次のコードが来なければ止める"""
        self._stop_gen += 1
        g = self._stop_gen
        if self.cfg["grace_ms"] <= 0:
            self._stop()
            return

        def later():
            if g == self._stop_gen and self.active and not self.keys and not self.sustain and not self.latch:
                self._stop()
        self._at(self.cfg["grace_ms"], later)

    def _play_slot(self, row, off, strike=True):
        c = self.chord_for(row, off)
        if c is None:
            return False
        self._play(c, row, off, strike)
        return True

    # ================================================================ 鳴らす
    def _wants(self, chord):
        c = self.cfg
        bass = cd.bass_note(chord, c["bass_floor"])
        if c["method"] == "arp":
            n = min(len(cd.upper_pcs(chord, 5)), 5)
            notes = cd.voice_upper(chord, self.prev_upper if self.prev_upper and len(self.prev_upper) == n else None,
                                   n, c["upper_lo"], c["upper_hi"])
            self.prev_upper = notes
            return [bass, tuple(notes)]
        upper = cd.voice_upper(chord, self.prev_upper, 3, c["upper_lo"], c["upper_hi"])
        self.prev_upper = upper
        rank = {pc: r for r, pc in enumerate(cd.upper_pcs(chord, 5))}
        seen = set()

        def importance(n):
            r = rank.get(n % 12, 99) + (50 if n % 12 in seen else 0)       # 同じ音名の2つ目は後回し
            seen.add(n % 12)
            return r
        ranked = sorted(upper, key=importance)
        lo, hi = sorted(ranked[:2])
        prev = (self._voices[1].target, self._voices[2].target)             # 前と同じ音をそのまま受け持てる並びを優先
        ch1, ch2 = max([(hi, lo), (lo, hi)], key=lambda p: (sum(a == b for a, b in zip(p, prev)), p[0] > p[1]))
        return [bass, ch1, ch2, ranked[2]]

    def _play(self, chord, row, off, strike=True, advance=None):
        """strike = 打ち直す(新しく押した)。advance = 進行を進めてよいか(省略時は strike と同じ)"""
        self._stop_gen += 1                                                 # 猶予中の「止める」を取り消す
        wants = self._wants(chord)
        retrig = self.cfg["retrigger"] and strike
        changing = [i for i, (v, w) in enumerate(zip(self._voices, wants))
                    if w is not None and (v.target != w or retrig)]
        moving = [i for i in changing if self._voices[i].target is None or self.cfg["strum_change"]]
        delays = self._spread(moving, wants, self.cfg["strum_ms"], release=False)
        for i, (v, w) in enumerate(zip(self._voices, wants)):
            if i not in changing and v.target == w and v.sounding == w:
                v.gen += 1
                continue
            v.target = w
            v.gen += 1
            self._at(delays.get(i, 0), self._change, v, v.gen, w, retrig)
        self.current = (chord, row, off)
        if strike if advance is None else advance:
            self._advance_progression(chord)
        self._notify()

    def _advance_progression(self, chord):
        """新しく弾いたコードが「次のコード」のときだけ1つ進む。ほかのコードを弾いても飛ばさない
        (前は進行の先から同じコードを探して飛んでいた。離して押さえたままのコードに戻ったときも進んでいた)"""
        prog = self.progression()
        if not prog:
            return
        i = (self.prog_pos + 1) % len(prog)
        if prog[i] == chord:
            self.prog_pos = i

    def set_next(self, i):
        """進行の i 番目を「次に弾くコード」にする(画面で進行のコードを押した)"""
        with self._lock:
            n = len(self.progression())
            if n:
                self.prog_pos = (int(i) - 1) % n if int(i) > 0 else -1
            self._notify()

    def progression(self):
        a = self.analysis(self.song)
        return [c.transpose(self.key - a.key) for c in a.chords]

    def _stop(self):
        self._stop_gen += 1
        sounding = [i for i, v in enumerate(self._voices) if v.target is not None]
        wants = [v.target for v in self._voices]
        delays = self._spread(sounding, wants, self.cfg["release_ms"], release=True)
        for i in sounding:
            v = self._voices[i]
            v.target = None
            v.gen += 1
            self._at(delays.get(i, 0), self._change, v, v.gen, None)
        self.current = None
        self._notify()

    def _stop_now(self):
        self._stop_gen += 1
        for v in self._voices:
            v.target = None
            v.gen += 1
            self._change(v, v.gen, None)
        self.current = None

    def _at(self, ms, fn, *args):
        if ms <= 0:
            fn(*args)
        else:
            self._sched.at(ms / 1000, lambda: self._locked(fn, *args))

    def _locked(self, fn, *args):
        with self._lock:
            fn(*args)

    def _change(self, v, gen, want, retrig=False):
        """声 v を want に。ふつうは新しい音のノートオンを先に、古い音のノートオフを後に(つないで持ち替え、F39)。
        retrig のときは古い音を止めてから鳴らす(だんだん消える音色で、消えた声が戻らなかったため)"""
        if gen != v.gen:
            return
        old = v.sounding
        old_set = set(old) if isinstance(old, tuple) else ({old} if old is not None else set())
        new_set = set(want) if isinstance(want, tuple) else ({want} if want is not None else set())
        c0 = self._to_ch0(v.ch)
        if retrig and new_set:
            for n in sorted(old_set):
                self._send(bytes([0x80 | c0, n, 0]))
            for n in sorted(new_set):
                self._send(bytes([0x90 | c0, n, self.vel]))
            v.sounding = want
            return
        for n in sorted(new_set - old_set):
            self._send(bytes([0x90 | c0, n, self.vel]))
        for n in sorted(old_set - new_set):
            self._send(bytes([0x80 | c0, n, 0]))
        v.sounding = want

    def _spread(self, idxs, wants, spread_ms, release):
        """声ごとの遅れ(ms)。入るときは順番どおり、抜けるときは逆順(同じ高さならベースが先に入り最後に抜ける)"""
        if not idxs or spread_ms <= 0:
            return {}
        order = list(idxs)
        up_first = self.cfg["strum_order"] == 1

        def height(i):
            w = wants[i]
            n = min(w) if isinstance(w, tuple) else w
            return (n if n is not None else 0) * 8 + (0 if i == 0 else i)

        order.sort(key=height, reverse=up_first != release)
        n = len(order)
        out = {}
        for r, i in enumerate(order):
            d = spread_ms * r / (n - 1) if n > 1 else 0
            if self.cfg["jitter_ms"]:
                d += self._rng.randint(0, self.cfg["jitter_ms"])
            out[i] = d
        return out

    # ================================================================ 画面へ
    def state(self):
        with self._lock:
            a = self.analysis(self.song)
            chord = None
            if self.current:
                c, row, off = self.current
                chord = {"name": c.label(self.key), "row": row, "off": off, "note": self.slot_note(row, off)}
            prog = self.progression()
            nxt = None
            if prog:
                i = (self.prog_pos + 1) % len(prog)
                nxt = self._next_view(prog[i], i)
            return {"active": self.active, "song": self.song, "song_name": self.book.songs[self.song].name,
                    "key": self.key, "song_key": self.song_key, "key_name": self.key_name(self.key),
                    "latch": self.latch, "sustain": self.sustain, "chord": chord, "next": nxt,
                    "prog_pos": self.prog_pos, "method": self.cfg["method"],
                    "overflow": [c.name() for c in a.assign.overflow], "errors": a.errors}

    def _next_view(self, c, i):
        """次に弾くコードの表示: 光らせる鍵(notes)とコードの表のます(cells)。度数+補足では補足の鍵も"""
        nxt = {"name": c.label(self.key), "index": i, "row": None, "off": None, "note": None, "notes": [], "cells": []}
        if self._degree():
            h = dg.how(self.key, c)
            if h is None:
                return nxt
            off, mods, b = h["off"], h["mods"], h["bass"]
            lay = self.cfg["layout"]
            cells = [[0, off]] + [[1, dg.MOD_KEY[m]] for m in mods]
            notes = [self.slot_note(r, o) for r, o in cells]
            words = [dg.DEGREE_NAMES[off]] + [dg.MOD_LABELS[m] for m in mods]
            if b is not None:
                cells.append([2, b])
                notes.append(dg.bass_key_note(b, lay))
                words.append(f"ベース {dg.DEGREE_NAMES[b].rstrip('m')}")
            nxt.update(row=0, off=off, note=notes[0], cells=cells, exact=h["exact"], notes=notes, how=" + ".join(words))
            return nxt
        slot = self._slot_of(c)
        if slot:
            nxt.update(row=slot[0], off=slot[1], note=slot_note(*slot), notes=[slot_note(*slot)], cells=[list(slot)])
        return nxt

    @staticmethod
    def key_name(k):
        return cd.FLAT[k] if k in cd.FLAT_KEYS else cd.SHARP[k]

    def _slot_of(self, chord):
        for row in (0, 1, 2, 3):
            for off in range(12):
                if self.chord_for(row, off) == chord:
                    return row, off
        return None

    def view(self):
        """コードの表(段 × 12鍵)・進行・曲の一覧(画面の組み立て用)"""
        with self._lock:
            rows = []
            degree = self._degree()
            lay = self.cfg["layout"]
            order = ((2, 0, 1) if dg.degree_on_right(lay) else (1, 2, 0)) if degree else (2, 1, 0, 3)   # 上から高いオクターブ
            for row in order:
                cells = []
                for off in range(12):
                    if degree and row == 2:
                        cells.append({"name": "/" + (cd.FLAT if self.key in cd.FLAT_KEYS or off in (1, 3, 8, 10) else cd.SHARP)[dg.bass_of(self.key, off)],
                                      "note": self.slot_note(row, off), "tip": f"ベース {dg.DEGREE_NAMES[off].rstrip('m')}",
                                      "mod": True})
                        continue
                    if degree and row == 1:
                        m = dg.MODS[off]
                        cells.append({"name": dg.MOD_LABELS[m], "note": self.slot_note(row, off), "tip": dg.MOD_HELP[m],
                                      "mod": True})
                        continue
                    c = self.chord_for(row, off)
                    cell = {"name": c.label(self.key) if c else "", "note": self.slot_note(row, off)}
                    if degree:
                        cell["tip"] = dg.DEGREE_NAMES[off]
                    cells.append(cell)
                rows.append({"row": row, "title": cd.ROW_TITLES[self.cfg["layout"]][row].replace("\n", " "),
                             "cells": cells})
            prog = [c.label(self.key) for c in self.progression()]
            songs = [{"name": s.name, "key": s.key, "empty": not (s.name or s.text)} for s in self.book.songs]
            return {"rows": rows, "progression": prog, "songs": songs, "state": self.state(),
                    "layouts": [[k, v] for k, v in cd.SCHEMES.items()]}

    def _notify(self):
        if self._on_state:
            try:
                self._on_state(self.state())
            except Exception:  # noqa: BLE001
                pass

    def shutdown(self):
        with self._lock:
            if self.active:
                self._leave()
        self._sched.stop()
