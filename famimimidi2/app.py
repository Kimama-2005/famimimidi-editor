"""アプリ(状態の持ち主、SPEC_v2 4.1)。

作業中の演奏・ライブラリ・曲・カートリッジの控え・設定を持ち、画面の操作を受けて下の層に指示する。
- 送信は必ず関所(gate)を通す
- 作業中の演奏は変わるたびに少し間引いて自動保存する
- 鍵盤の受け方は「いる場所」(place)で決まる: "play" = ♪ 演奏セット、1〜5 = その ch の音色づくり
"""
import copy
import json
import queue
import threading
import uuid
from pathlib import Path

from .device import sysex
from .device import virtual
from .device.gate import Gate, SendLog, Source
from .model.store import Store
from .model.tone import Tone, clean_params, load_messages
from .music import tonecards
from .music.spec import CH_KIND, CHS, KIND_NAMES, load_spec
from .music.waves import PRESETS as WAVE_PRESETS
from .model.chordbook import ChordBook, Song
from .model.performance import TEMPLATES, ChordSettings, Controls, KeyboardMap
from .music import chords as cd
from .paths import DATA_DIR, LOG_DIR, USER_DIR
from .performance.chordmode import ChordEngine
from .performance.router import Router
from .performance.scheduler import ManualScheduler, Scheduler
from .cartridge import mirror, plans, tidy
from .cartridge.writer import WriteJob
from . import checks
from .model.common import now_iso
from .music.spec import KIND_CH

SCREEN_IN_CH0 = 15          # 画面の鍵盤を振り分けるときの入力 ch(外部の鍵盤と混ざらないように)
SAVE_DELAY = 0.5            # 作業中の演奏の自動保存の間引き(秒)
NOTE_RANGE = {1: (33, 108), 2: (33, 108), 3: (21, 96), 4: (0, 127), 5: (0, 127)}
TAB_NAMES = {1: "1 パルス", 2: "2 パルス", 3: "3 三角波", 4: "4 ノイズ", 5: "5 DPCM/波形"}     # タブと同じ書き方


PRESET_PREFIX = "preset:"   # 左の一覧の「おまかせの見本」の id(ライブラリには入っていない。変えられない)


def _winmm():
    from .device import winmm
    return winmm


def load_presets(data_dir, spec):
    """data/easy_presets.json(おまかせ)→ 見本の音色の並び"""
    path = data_dir / "easy_presets.json"
    if not path.exists():
        return []
    with open(path, encoding="utf-8") as f:
        raw = json.load(f).get("presets", [])
    out = []
    for p in raw:
        kind = CH_KIND[int(p.get("channel", 1))]
        params, _ = clean_params(p.get("cc") or [], kind, spec)
        out.append(Tone(name=p.get("name", ""), kind=kind, params=params, notes=p.get("desc", ""),
                        source="data/easy_presets.json", id=PRESET_PREFIX + p["id"]))
    return out



def _silences(params):
    """記録した CC に音量0(CC#7=0 か CC#11=0)が入っている"""
    return any(int(c) in (7, 11) and int(v) == 0 for c, v in (params or []))

class App:
    def __init__(self, user_dir=USER_DIR, log_dir=LOG_DIR, data_dir=DATA_DIR, midi=None, threads=True):
        self.spec = load_spec()
        self.store = Store(user_dir, data_dir, self.spec)
        loaded = self.store.load_all()           # 読めないファイルがあれば StoreError(上書きしない)
        self.library, self.session = loaded.library, loaded.session
        self.chordbook, self.cart, self.prefs = loaded.chordbook, loaded.cart, loaded.prefs
        self.notes = loaded.notes
        self.presets = load_presets(Path(data_dir), self.spec)
        self.log = SendLog(log_dir)
        for n in self.notes:
            self.log.note(n)
        self.gate = Gate(self.log, self.spec, is_silent=lambda ch: self.session.is_silent(ch, self.spec))
        self.gate.ch_offset = self.prefs.ch_offset
        self.midi = midi if midi is not None else _winmm()
        self.virtual = virtual.VirtualOut(lookup=self._pc_params)   # 仮想ファミコン(このパソコンで鳴らす)
        self._real_out = ""              # 仮想ファミコンにする前の本物の出力(戻すとき用)
        self.place = "play"
        self.router = Router(self.gate.midi_ch0)
        perf = self.session.performance
        self.router.configure(place="play", keyboard=perf.keyboard, controls=perf.controls, follow=self.prefs.kb_follow)
        self._lock = threading.RLock()
        self._in = None
        self._inbox = queue.Queue()
        self._save_timer = None
        self._stop = threading.Event()
        self.chord_listeners = []        # コードモードの状態が変わったら呼ぶ(画面への知らせ)
        self._plans = {}                 # 番号札 → 確認待ちの書き込み計画
        self._job = None
        self._check = None              # 実機の確認モードの途中経過
        self.scheduler = Scheduler() if threads else ManualScheduler()
        self.chord = ChordEngine(send=lambda m: self.gate.send(m, Source.CHORD), to_ch0=self.gate.midi_ch0,
                                 get_value=lambda ch, cc: self.session.performance.tone(ch).value(cc, self.spec),
                                 set_cc=self.gate.queue_cc, scheduler=self.scheduler, log=self.log.note,
                                 on_state=self._chord_state)
        self.chord.configure(perf.chord, perf.controls)
        self.chord.set_book(self.chordbook)
        self._sync_chord()               # 前回コードで弾いていたら、そのまま(接続したときに上書きの値も送られる)
        if threads:
            self.gate.start()
            threading.Thread(target=self._input_loop, name="input", daemon=True).start()

    # ================================================================ 接続
    def ports(self):
        return {"out": self.midi.list_outputs() + [virtual.NAME], "in": self.midi.list_inputs(),
                "want_out": self.prefs.out_name, "want_in": self.prefs.in_name}

    @property
    def is_virtual(self):
        return self.gate.output_name == virtual.NAME

    def _pc_params(self, pc):
        """仮想ファミコン: 呼び出し番号 pc に入っている音色の CC(カートリッジの控えから)"""
        m = self.cart.pc_map.get(pc)
        if m is None:
            return None
        return mirror.record(self.cart, m).params

    def toggle_virtual(self):
        """上の「🎮 仮想ファミコン」: 仮想ファミコンで鳴らす ⇔ 本物のふぁみみみっでぃに戻す"""
        if self.is_virtual:
            back, keyin = self._real_out, self.prefs.in_name
            self.disconnect()
            self.log.note("仮想ファミコンをやめました")
            if back and back in self.midi.list_outputs():
                return self.connect(back, keyin)
            self.prefs.out_name = back
            self.store.save_prefs(self.prefs)
            return {"ok": True, "message": ""}
        if self.gate.writing:
            return {"ok": False, "message": "書き込み中です"}
        if self.prefs.out_name != virtual.NAME:
            self._real_out = self.prefs.out_name
        return self.connect(virtual.NAME, self.prefs.in_name)

    def connect(self, out_name, in_name=None):
        """名前で開いて、作業中の演奏を全部送る(10章-2)。→ {"ok", "message"}"""
        self.disconnect()
        outs, ins = self.midi.list_outputs(), self.midi.list_inputs()
        if out_name == virtual.NAME:
            self.virtual.take()
            self.gate.set_output(self.virtual)
            self.log.note("仮想ファミコンで鳴らします(このパソコンの音。カートリッジへの書き込みはできません)")
        elif out_name not in outs:
            return {"ok": False, "message": f"出力ポート「{out_name}」が見つかりません。USB ケーブルを確かめてください。"}
        else:
            try:
                self.gate.set_output(self.midi.OutputPort(outs.index(out_name), out_name))
            except self.midi.MidiPortError as e:
                self.log.note(f"出力の接続に失敗: {e}")
                return {"ok": False, "message": str(e)}
        message = ""
        if in_name:
            if in_name in ins:
                try:
                    self._in = self.midi.InputPort(ins.index(in_name), in_name, self.on_input)
                    self.log.note(f"入力に接続: {in_name}")
                except self.midi.MidiPortError as e:
                    self.log.note(f"入力の接続に失敗: {e}")
                    message = f"{e}\n出力だけつないだ状態で続けます。"
            else:
                message = f"入力ポート「{in_name}」が見つかりません。出力だけつなぎました。"
        self.prefs.out_name = out_name
        self.prefs.in_name = self._in.name if self._in else (in_name or "")
        self.store.save_prefs(self.prefs)
        self.send_session(Source.RESEND)
        return {"ok": True, "message": message}

    def disconnect(self):
        with self._lock:
            offs = self.router.release_all()
        for m in offs:
            self.gate.send(m, Source.THRU)
        if self._in:
            self._in.close()
            self.log.note(f"入力を切断: {self._in.name}")
            self._in = None
        self.gate.set_output(None)

    def auto_connect(self):
        """起動時: 前のポートへつなぐ(見つからなければ何もしない)"""
        if self.prefs.out_name and self.prefs.out_name in self.midi.list_outputs() + [virtual.NAME]:
            return self.connect(self.prefs.out_name, self.prefs.in_name)
        return None

    # ================================================================ 送る
    def _queue_tone(self, ch):
        t = self.session.performance.tone(ch)
        over = self.chord.override_values()
        for cc, v in load_messages(t.values(self.spec)):
            self.gate.queue_cc(ch, cc, over.get((ch, cc), v))

    def send_chs(self, chs, source=Source.EDITOR):
        """ch の音色を全部送る(全項目を既定値+params で。CC#121 は使わない)。波形は CC#18 の後に"""
        chs = sorted(set(chs))
        for ch in chs:
            self._queue_tone(ch)
        self.gate.flush(source)
        for ch in chs:
            wave = self.session.performance.tone(ch).wave
            if wave is not None:
                self.gate.send(sysex.wave_data(wave), source)

    def send_controls(self, source=Source.EDITOR):
        """ペダル・レバーの設定: ベンド幅 CC#82 を bend.to の ch へ(CC#82 は ch1〜3 だけ)"""
        c = self.session.performance.controls
        for ch in c.bend_to:
            if ch <= 3:
                self.gate.queue_cc(ch, 82, c.bend_range)
        self.gate.flush(source)

    def send_session(self, source=Source.RESEND):
        """作業中の演奏を全部送る(接続したとき・「送り直す」)"""
        self.log.note("作業中の演奏を全部送ります")
        self.send_chs(CHS, source)
        self.send_controls(source)

    # ================================================================ 場所
    def set_place(self, place):
        """タブを開いた。場所が変わった瞬間に鳴っている音を止める"""
        place = "play" if place == "play" else int(place)
        with self._lock:
            offs = self.router.configure(place=place)
            self.place = place
        for m in offs:
            self.gate.send(m, Source.THRU)
        self._sync_chord()
        return self.state()

    def set_kb_follow(self, on):
        """1〜5 のタブでの外部の鍵盤: この ch だけ(False)/ 演奏セットどおり(True)"""
        on = bool(on)
        if on != self.prefs.kb_follow:
            with self._lock:
                offs = self.router.configure(follow=on)
            for m in offs:
                self.gate.send(m, Source.THRU)
            self.chord.stop_all()
            self.prefs.kb_follow = on
            self.store.save_prefs(self.prefs)
            self.log.note(f"1〜5 のタブでの外部の鍵盤: {'演奏セットどおり' if on else 'この ch だけ'}")
            self._sync_chord()
        return self.state()

    def _sync_chord(self, configure=False):
        """コードモードが効くのは「コードで弾く」で、♪ のタブか「外部の鍵盤: 演奏セットどおり」のとき"""
        perf = self.session.performance
        if configure:
            self.chord.configure(perf.chord, perf.controls)
        self.chord.set_active(perf.chord.active and (self.place == "play" or self.prefs.kb_follow))

    def _chord_state(self, st):
        for fn in list(self.chord_listeners):
            fn(st)

    def _sync_router(self):
        perf = self.session.performance
        with self._lock:
            offs = self.router.configure(keyboard=perf.keyboard, controls=perf.controls)
        for m in offs:
            self.gate.send(m, Source.THRU)

    # ================================================================ 演奏
    def on_input(self, msg: bytes):
        """入力ポートのコールバック(winmm のスレッド)。列に入れるだけ"""
        self._inbox.put(msg)

    def _input_loop(self):
        while not self._stop.is_set():
            try:
                msg = self._inbox.get(timeout=0.1)
            except queue.Empty:
                continue
            self.handle_input(msg, Source.THRU)

    def handle_input(self, msg: bytes, source=Source.THRU, solo=False):
        """solo = 画面の鍵盤を 1〜5 のタブで弾いた(タブの ch だけ。コードモードも通さない)"""
        if not self.gate.accept_input(msg):
            return
        if self.chord.active and not solo:
            reason = self.chord.handle(msg)
            if reason:
                self.log.write("IN", msg, f"{self.gate._describe(msg)} … {reason}", source)
            return
        with self._lock:
            out, reason = self.router.route(msg, solo=solo)
        if reason:
            self.log.write("IN", msg, f"{self.gate._describe(msg)} … {reason}", source)
        for m in out:
            self.gate.send(m, source)

    def screen_note(self, note, vel, on):
        """画面の鍵盤。♪ のタブでは外部の鍵盤と同じ振り分け、1〜5 のタブではその ch だけ"""
        note, vel = int(note), max(1, min(127, int(vel)))
        msg = bytes([0x90 | SCREEN_IN_CH0, note, vel]) if on else bytes([0x80 | SCREEN_IN_CH0, note, 0])
        self.handle_input(msg, Source.SCREEN, solo=isinstance(self.place, int))
        return True

    def panic(self):
        if self.gate.writing:
            self.log.note("書き込み中なのでパニックは送りません")
            return False
        with self._lock:
            self.router.release_all()
        self.chord.stop_all()
        self.gate.panic()
        return True

    # ================================================================ 演奏セットの操作
    def _changed(self):
        self.session.changed()
        self.save_session_soon()

    def toggle_link12(self):
        perf = self.session.performance
        chs = perf.set_link12(not perf.link12)
        self.log.note(f"ch1 と ch2 の紐付け: {'ON(ch2 の音色は保管)' if perf.link12 else 'OFF(ch2 の音色を戻す)'}")
        self.send_chs(chs)
        self._changed()
        return self.state()

    def set_chord_active(self, on):
        """弾き方(割り当て表で弾く / コードで弾く)"""
        perf = self.session.performance
        if bool(on) != perf.chord.active:
            with self._lock:
                offs = self.router.release_all()
            for m in offs:
                self.gate.send(m, Source.THRU)
            perf.chord.active = bool(on)
            self._sync_chord()
            self._changed()
        return self.state()

    # ---------- 割り当て表・ペダル・レバー(4段目) ----------
    def set_keyboard(self, d):
        """割り当て表を変える。ポリなら自動で紐付け、ペダル・レバーの送り先を付け直す"""
        perf = self.session.performance
        chs = perf.set_keyboard(KeyboardMap.from_dict(d))
        if chs:
            self.log.note("ポリ(2音)にしたので、ch1 と ch2 を紐付けました(ch2 の音色は保管)")
        self.send_chs(chs)
        self.send_controls()
        self._sync_router()
        self._changed()
        return self.state()

    def apply_template(self, name):
        if name not in TEMPLATES:
            return {"error": "そのひな形はありません"}
        st = self.set_keyboard(KeyboardMap.template(name).to_dict())
        self.log.note(f"割り当て表のひな形「{TEMPLATES[name]}」")
        return st

    def set_controls(self, d):
        perf = self.session.performance
        perf.controls = Controls.from_dict(d)
        self.send_controls()
        self._sync_router()
        self.chord.set_controls(perf.controls)
        self._changed()
        return self.state()

    def load_performance(self, pid):
        """ライブラリの演奏セットを読み込む(SPEC 6.3 の順)"""
        perf = self.library.performance(pid)
        if perf is None:
            return {"error": "その演奏セットが見つかりません"}
        with self._lock:                                  # 1. 鳴っている音を止める
            offs = self.router.release_all()
        for m in offs:
            self.gate.send(m, Source.THRU)
        self.session.load(perf)                           # 2. 作業中の演奏を置き換える
        self.log.note(f"演奏セット「{perf.name}」を読み込みます")
        self.send_chs(CHS)                                # 3. 5ch の音色
        self.send_controls()                              # 4. ペダル・レバー
        self._sync_router()                               #    割り当て表
        self._sync_chord(configure=True)                  # 5. コードモード(上書きは音色と同じ間引きの列へ)
        self.save_session_soon()
        return self.state()

    def resend(self):
        self.send_session(Source.RESEND)
        return self.state()

    # ================================================================ 音色の操作(左の一覧)
    def put_tone(self, ch, tid):
        """左の一覧の音色を「この ch に入れる」"""
        ch = int(ch)
        t = self._find_tone(tid)
        if t is None:
            return {"error": "その音色が見つかりません"}
        if t.kind != CH_KIND[ch]:
            return {"error": f"{KIND_NAMES[t.kind]}の音色は {TAB_NAMES[ch]} に入れられません"}
        chs = self.session.performance.put_tone(ch, t, t.id)
        self.log.note(f"音色「{t.name}」を ch{'・ch'.join(map(str, chs))} に入れます")
        self.send_chs(chs)
        self._changed()
        return self.state()

    def _find_tone(self, tid):
        if tid and tid.startswith(PRESET_PREFIX):
            return next((p for p in self.presets if p.id == tid), None)
        return self.library.tone(tid)

    def reset_tone(self, ch):
        chs = self.session.performance.reset_tone(int(ch))
        self.send_chs(chs)
        self._changed()
        return self.state()

    def save_tone_new(self, ch, name):
        perf = self.session.performance
        ch = int(ch)
        t = self.library.add_tone(perf.tone(ch), name=(name or "").strip() or "新しい音色")
        for c in perf.linked_chs(ch):
            perf.slots[c].tone.name, perf.slots[c].from_ = t.name, t.id
        self.store.save_library(self.library)
        self._changed()
        self.log.note(f"音色「{t.name}」をライブラリに保存しました")
        return {**self.state(), "selected": t.id}

    def overwrite_tone(self, ch, tid):
        if str(tid).startswith(PRESET_PREFIX):
            return {"error": "おまかせの見本は変えられません。「この ch に入れる」で入れてから、新しく保存してください"}
        perf = self.session.performance
        ch = int(ch)
        old = self.library.tone(tid)
        if old is None:
            return {"error": "その音色が見つかりません"}
        if old.kind != perf.tone(ch).kind:
            return {"error": "種類の違う音色には上書きできません"}
        t = self.library.overwrite_tone(tid, perf.tone(ch))
        for c in perf.linked_chs(ch):
            perf.slots[c].tone.name, perf.slots[c].from_ = t.name, t.id
        self.store.save_library(self.library)
        self._changed()
        self.log.note(f"音色「{t.name}」を上書き保存しました")
        return self.state()

    def rename_tone(self, tid, name):
        if str(tid).startswith(PRESET_PREFIX):
            return {"error": "おまかせの見本は変えられません。「この ch に入れる」で入れてから、新しく保存してください"}
        name = (name or "").strip()
        if not name or self.library.tone(tid) is None:
            return {"error": "名前を入れてください"}
        self.library.rename_tone(tid, name)
        self.store.save_library(self.library)
        return self.state()

    def delete_tone(self, tid):
        if str(tid).startswith(PRESET_PREFIX):
            return {"error": "おまかせの見本は変えられません。「この ch に入れる」で入れてから、新しく保存してください"}
        t = self.library.tone(tid)
        if t is None:
            return {"error": "その音色が見つかりません"}
        self.library.delete_tone(tid)
        for s in self.session.performance.slots.values():   # 作業中の音色はそのまま。元の印だけ外す
            if s.from_ == tid:
                s.from_ = ""
        self.store.save_library(self.library)
        self.save_session_soon()
        self.log.note(f"音色「{t.name}」をライブラリから削除しました")
        return self.state()

    # ================================================================ 音色をつくる(1〜5 のタブ、SPEC 7.3)
    def tone_view(self, ch):
        """カードの組み立てと、いまの値"""
        ch = int(ch)
        t = self.session.performance.tone(ch)
        return {"ch": ch, "kind": t.kind, "cards": tonecards.describe(t.kind, self.spec),
                "state": self.tone_state(ch), "wave_presets": [[k, v] for k, v in WAVE_PRESETS.items()]}

    def tone_state(self, ch):
        t = self.session.performance.tone(int(ch))
        st = tonecards.state(t.kind, t.values(self.spec), self.spec)
        st["wave"] = list(t.wave) if t.wave is not None else None
        st["name"] = t.name
        return st

    def _apply_updates(self, ch, updates):
        """音色の値を変えて送る(紐付け中は ch1・ch2 の両方)。送るのは間引きの列(最後の値が勝つ)"""
        perf = self.session.performance
        chs = perf.linked_chs(ch)
        over = self.chord.override_values()
        for cc, v in updates.items():
            perf.set_param(ch, cc, v, self.spec)
            for c in chs:
                if (c, cc) not in over:          # コードモードの間だけ変えている設定は送らない(6.2-4)
                    self.gate.queue_cc(c, cc, perf.tone(c).value(cc, self.spec))
        self._changed()
        return {"tone": self.tone_state(ch), "state": self.state()}

    def tone_set(self, ch, key, action, x):
        ch = int(ch)
        t = self.session.performance.tone(ch)
        return self._apply_updates(ch, tonecards.updates_for(key, action, x, t.values(self.spec), self.spec))

    def tone_env(self, ch, updates):
        return self._apply_updates(int(ch), tonecards.env_updates(updates))

    def set_wave(self, samples):
        """ch5 の波形を描いた。音色に入れて、波形データの SysEx を送る(その場で鳴らす。カートリッジには保存しない)"""
        samples = sysex.check_samples(samples)
        self.session.performance.set_wave(samples)
        self.gate.send(sysex.wave_data(samples), Source.EDITOR)
        self._changed()
        return {"tone": self.tone_state(5), "state": self.state()}

    # ================================================================ コードモード(5段目)
    def _chord_labels(self):
        """下の鍵盤に書くコード名 {鍵: 名前}"""
        out = {}
        for r in self.chord.view()["rows"]:
            for c in r["cells"]:
                if c["name"]:
                    out[str(c["note"])] = c["name"]
        return out

    def chord_view(self):
        v = self.chord.view()
        v["settings"] = self.session.performance.chord.to_dict()
        v["book"] = self.chordbook.to_dict()
        v["labels"] = self._chord_labels()
        v["keyboard"] = self.keyboard_view()      # 下の鍵盤のコード名も一緒に描き直す(配置・曲・キーを変えたとき)
        v["sheet"], v["sheet_note"] = self._sheet()
        shift = self.chord.key - self.chord.analysis(self.chord.song).key
        if shift:                                 # 移調しているときは譜面のコード名もずらす
            for ln in v["sheet"]:
                for sg in ln.get("segs", []):
                    if sg["ci"] is not None:
                        sg["chord"] = v["progression"][sg["ci"]]
        return v

    def set_chord_settings(self, d):
        """配置・ボイシング・奏法プリセット・ストラム幅・ベースの音域・グライド"""
        perf = self.session.performance
        perf.chord = ChordSettings.from_dict({**perf.chord.to_dict(), **(d or {}), "active": perf.chord.active})
        self._sync_chord(configure=True)
        self._changed()
        return self.chord_view()

    def chord_song(self, i):
        self.chord.select_song(int(i))
        return self.chord_view()

    def chord_next_song(self, d):
        self.chord.next_song(int(d))
        return self.chord_view()

    def chord_key(self, k=None, delta=None):
        if delta is not None:
            self.chord.shift_key(int(delta))
        else:
            self.chord.set_key(int(k))
        return self.chord_view()

    def chord_set_next(self, i):
        self.chord.set_next(int(i))
        return self.chord.state()

    def chord_hold(self):
        self.chord.toggle_hold()
        return self.chord.state()

    def chord_stop(self):
        self.chord.stop_all()
        return self.chord.state()

    def chord_play(self, row, off, on, vel=100):
        """画面のコードの表を押した / 離した"""
        return self.chord.play_slot(row, off, bool(on), int(vel))

    def save_song(self, i, name, key, text, source=None):
        """曲の編集(全演奏セット共通の1冊)。読めないコード名を返す。source = 取り込んだページの場所(None = 今のまま)"""
        i = int(i)
        key = None if key in (None, "", "auto") else int(key) % 12
        if source is None:
            source = self.chordbook.songs[i].source
        self.chordbook.songs[i] = Song(str(name or ""), key, str(text or ""), source)
        self.store.save_chordbook(self.chordbook)
        self.chord.set_book(self.chordbook)
        _, errors = cd.parse_progression(text or "")
        return {"view": self.chord_view(), "errors": errors}

    def import_chordbook(self, data):
        """OtamaChord Studio のコードセット / songs.json(曲の配列)を取り込む(12曲まるごと置き換え)"""
        if isinstance(data, list):
            data = {"songs": data}
        if not isinstance(data, dict) or not isinstance(data.get("songs"), list):
            return {"error": "コードセットのファイルではありません"}
        book = ChordBook.from_dict({**data, "format": data.get("format") or "otamachord-set-v1"})
        self.chordbook = book
        self.store.save_chordbook(book)
        self.chord.set_book(book)
        self.log.note(f"曲を取り込みました: {book.name}")
        return {"view": self.chord_view()}

    def import_chordwiki(self, i, page, source=""):
        """保存した ChordWiki のページ(HTML)から、曲 i にコード進行を取り込む。歌詞は取り込まない
        (ページの場所 source だけ覚え、歌詞は表示するときだけそこから読む)"""
        song, unread = cd.from_chordwiki(page)
        if not song["text"]:
            return {"error": "コード進行が見つかりませんでした(ChordWiki のページを「名前を付けて保存」したファイルを選んでください)"}
        r = self.save_song(i, song["name"], song["key"], song["text"], source=str(source or ""))
        r["unread"] = unread
        return r

    def _sheet(self):
        """進行の欄の譜面。取り込んだ ChordWiki のページがあって進行と合えば歌詞つき(表示するときだけ読む)、
        なければ曲のテキストの行と小節線。→ (行の列, 歌詞のことの一言 or "")"""
        song = self.chordbook.songs[self.chord.song]
        lines = cd.sheet_from_text(song.text)
        if not song.source:
            return lines, ""
        p = Path(song.source)
        try:
            stamp = (str(p), p.stat().st_mtime)
        except OSError:
            return lines, "取り込んだ ChordWiki のページが見つからないので、歌詞は出せません(ファイルを動かしたか消した)"
        if getattr(self, "_sheet_cache", (None,))[0] != stamp:
            page = cd.decode_page(p.read_bytes())
            self._sheet_cache = (stamp, cd.sheet_from_chordwiki(page) if page else None)
        sheet = self._sheet_cache[1]
        if not sheet:
            return lines, "取り込んだ ChordWiki のページを読めないので、歌詞は出せません"
        try:
            same = cd.sheet_chords(sheet) == cd.parse_progression(song.text)[0]
        except ValueError:
            same = False
        if not same:
            return lines, "曲のコードを編集したので、歌詞の位置と合いません(歌詞は出していません)"
        return copy.deepcopy(sheet), ""                 # 写しを返す(移調で書き換えてもキャッシュは変えない)

    # ================================================================ カートリッジ(6段目)
    def cart_view(self):
        """保存場所40のタイル・電源を入れたときの音色・整える・波形の登録"""
        c, lib = self.cart, self.library
        tiles = []
        for pc in range(89, 129):
            m = c.pc_map.get(pc)
            kind = mirror.tone_kind(c, m, lib) if m is not None else None
            tiles.append({"place": mirror.place_of(pc), "pc": pc, "name": plans.name_at(c, pc),
                          "empty": m == mirror.NEUTRAL_MACRO, "unknown": m is None, "kind": kind,
                          "certain": bool(m is not None and mirror.record(c, m).certain),
                          "silent": bool(m is not None and m != mirror.NEUTRAL_MACRO
                                         and _silences(mirror.record(c, m).params))})
        startup = []
        for ch in CHS:
            m = c.startup.get(ch)
            if m is None:
                text = "わからない(このアプリでは設定していない)"
            elif m == mirror.NEUTRAL_MACRO:
                text = "ふつう(何も変えない)"
            else:
                r = mirror.record(c, m)
                pcs = mirror.users(c, m)[0]
                text = (f"保存場所 {mirror.place_of(pcs[0])}: " if pcs else "") + (r.label or f"マクロ{m}")
            startup.append({"ch": ch, "text": text, "macro": m})
        tidy_rows = []
        for ch in CHS:
            st = tidy.status(c, lib, self.spec, ch)
            if st.count == 0:
                text, kind = "この ch の種類の音色は入っていません", "none"
            elif st.needed:
                parts = []
                if st.to_rewrite:
                    parts.append("、".join(f"保存場所 {mirror.place_of(pc)}" for pc in st.to_rewrite) + " で前の音色の設定が残る可能性")
                if not st.base_ok:
                    parts.append("土台が最新ではありません")
                text, kind = f"音色 {st.count} 個: " + " / ".join(parts), "warn"
            else:
                text, kind = f"整っています(音色 {st.count} 個)", "ok"
                if st.unavoidable:
                    text += "。ただし10項目に入りきらない設定があり、切り替えで残ることがあります"
            tidy_rows.append({"ch": ch, "text": text, "kind": kind, "needed": st.needed})
        waves = [{"slot": n, "name": (c.waves.get(n) or {}).get("name", "")} for n in range(61, 77)]
        return {"tiles": tiles, "startup": startup, "tidy": tidy_rows, "waves": waves,
                "writing": self.gate.writing, "connected": bool(self.gate.output_name),
                "perf_chs": plans.perf_chs(self.session.performance),
                "slots": [{"ch": ch, "name": self.session.performance.tone(ch).name} for ch in CHS]}

    def cart_plan(self, kind, args=None):
        """書き込みの計画を作る(送らない)。確認画面に出す文と番号札を返す"""
        if self.is_virtual:
            return {"error": "仮想ファミコンではカートリッジに書き込めません(本物のカートリッジの控えを守るため)。ふぁみみみっでぃにつないでから使ってください"}
        a = args or {}
        c, perf, ch0 = self.cart, self.session.performance, self.gate.midi_ch0(1)
        try:
            if kind == "save":
                ch = int(a["ch"])
                plan = plans.plan_save(c, self.library, self.spec, perf.tone(ch), int(a["place"]), ch, ch0,
                                       from_id=perf.slots[ch].from_)
            elif kind == "clear":
                plan = plans.plan_clear(c, int(a["place"]), ch0)
            elif kind == "startup":
                plan = plans.plan_startup(c, int(a["ch"]), None if a.get("place") in (None, "", "normal") else int(a["place"]), ch0)
            elif kind == "tidy":
                plan = plans.plan_tidy(c, self.library, self.spec, int(a["ch"]), ch0)
            elif kind == "wave":
                wave = perf.tone(5).wave
                if wave is None:
                    return {"error": "ch5 の音色に波形が入っていません(5 のタブで描いてください)"}
                plan = plans.plan_wave(c, int(a["slot"]), wave, a.get("name") or perf.tone(5).name or "波形")
            elif kind == "perf_places":
                plan = plans.plan_perf_places(c, self.library, self.spec, perf, a.get("places") or {}, ch0)
            elif kind == "perf_startup":
                plan = plans.plan_perf_startup(c, self.spec, perf, ch0)
            else:
                return {"error": f"知らない書き込みです: {kind}"}
        except (ValueError, KeyError) as e:
            return {"error": str(e)}
        token = uuid.uuid4().hex
        self._plans = {token: plan}             # 確認待ちは1つだけ
        return {"token": token, "title": plan.title, "lines": plan.lines, "seconds": round(plan.seconds, 1),
                "ok_text": plan.ok_text, "detail": plan.text()}

    def cart_run(self, token, on_progress=None, on_done=None, sleep=None):
        """確認画面で「元に戻せない」にチェックして押した計画を実行する。→ 始められなければ {"error"}"""
        if self.is_virtual:
            return {"error": "仮想ファミコンではカートリッジに書き込めません(本物のカートリッジの控えを守るため)。ふぁみみみっでぃにつないでから使ってください"}
        plan = self._plans.pop(token, None)
        if plan is None:
            return {"error": "確認の期限が切れました。もう一度やり直してください"}
        if not self.gate.output_name:
            return {"error": "ふぁみみみっでぃにつながっていません"}
        if self.gate.writing or (self._job and not self._job.done):
            return {"error": "ほかの書き込みが終わるまで待ってください"}
        with self._lock:
            self.router.release_all()
        self.chord.stop_all()
        self.log.note(f"書き込み: {plan.title}(予定 約{plan.seconds:.1f}秒)")

        def done(ok, error):
            if ok:
                plans.apply_success(self.cart, plan)
                self.log.note("書き込み完了。控えを更新しました")
            else:
                plans.apply_failure(self.cart, plan, error)
                self.log.note(f"書き込み失敗: {error}")
            self.store.save_cart(self.cart)
            self.send_chs([1])                  # 記録・実行は ch1 で行うので、ch1 を作業中の音色に戻す
            if on_done:
                on_done(ok, plan.done_message if ok else
                        f"{error}\n影響したかもしれない保存場所は、控えで「不明」にしました。")

        self._job = WriteJob(self.gate, plan, done, on_progress, **({"sleep": sleep} if sleep else {}))
        if sleep:
            self._job.run()                     # テスト: その場で
        else:
            self._job.start()
        return {"ok": True, "seconds": plan.seconds}

    def write_overdue(self):
        return bool(self._job and self._job.overdue)

    def cart_call(self, place, ch=1):
        """保存場所を呼び出して鳴らす(呼び出し番号を送り、C4 を少し鳴らす)。作業中の音色とずれるので、あとで「送り直す」"""
        pc, ch = mirror.pc_of(place), int(ch)
        c0 = self.gate.midi_ch0(ch)
        self.log.note(f"保存場所 {place}(呼び出し番号 {pc})を ch{ch} で呼び出して鳴らします")
        self.gate.send(bytes([0xC0 | c0, pc - 1]), Source.AUDITION)
        note = 60 if ch != 4 else 6
        self.gate.send(bytes([0x90 | c0, note, 100]), Source.AUDITION)
        self.scheduler.at(0.6, lambda: self.gate.send(bytes([0x80 | c0, note, 0]), Source.AUDITION))
        return True

    # ================================================================ 実機の確認モード(7段目、SPEC 8.2)
    def check_list(self):
        places = checks.places_check(self.cart_view()["tiles"], KIND_CH)
        return [{"name": c.name, "title": c.title, "description": c.description, "steps": len(c.steps)}
                for c in (checks.basic_check(), checks.v0_check(), places)]

    def _build_check(self, name):
        if name == "basic":
            return checks.basic_check()
        if name == "v0":
            return checks.v0_check()
        if name == "places":
            return checks.places_check(self.cart_view()["tiles"], KIND_CH)
        raise ValueError(f"知らない確認です: {name}")

    def check_start(self, name):
        if not self.gate.output_name:
            return {"error": "ふぁみみみっでぃにつながっていません"}
        if self.is_virtual:
            return {"error": "実機の確認は、ふぁみみみっでぃにつないでから使ってください(いまは仮想ファミコンです)"}
        if self.gate.writing:
            return {"error": "書き込み中です"}
        try:
            c = self._build_check(name)
        except ValueError as e:
            return {"error": str(e)}
        if not c.steps:
            return {"error": "確かめる手順がありません(このアプリで音色を入れた保存場所がありません)"}
        with self._lock:
            self.router.release_all()
        self.chord.stop_all()
        self.gate.panic()
        self._check = {"check": c, "i": 0, "answers": [], "started": now_iso()}
        self.log.note(f"===== 実機の確認「{c.title}」を始めます =====")
        self._play_step()
        return self.check_state()

    def _play_step(self):
        ck = self._check
        step = ck["check"].steps[ck["i"]]
        self.log.note(f"確認 {ck['i'] + 1}/{len(ck['check'].steps)}: {step.text}")
        for t, msg in step.sends:
            msg = self._offset(msg)
            if t <= 0:
                self.gate.send(msg, Source.CHECK, skip_silent=True)
            else:
                self.scheduler.at(t, lambda m=msg: self.gate.send(m, Source.CHECK, skip_silent=True))

    def _offset(self, msg):
        """手順の ch(1〜5)を、ch のずれに合わせる"""
        if msg and 0x80 <= msg[0] < 0xF0:
            return bytes([(msg[0] & 0xF0) | self.gate.midi_ch0((msg[0] & 0x0F) + 1)]) + msg[1:]
        return msg

    def check_again(self):
        if not self._check:
            return {"error": "確認をしていません"}
        self.gate.panic()
        self._play_step()
        return self.check_state()

    def check_answer(self, answer):
        """answer: "yes"(鳴った)/ "no"(鳴らない)"""
        ck = self._check
        if not ck:
            return {"error": "確認をしていません"}
        step = ck["check"].steps[ck["i"]]
        ok = None if step.expect is None else (answer == step.expect)
        ck["answers"].append({"step": ck["i"] + 1, "text": step.text, "question": step.question,
                              "expect": step.expect, "answer": answer, "as_expected": ok, "time": now_iso()})
        self.log.note(f"確認 {ck['i'] + 1} の答え: {'鳴った' if answer == 'yes' else '鳴らない'}"
                      + ("" if ok is None else ("(予想どおり)" if ok else "(予想と違う)")))
        ck["i"] += 1
        if ck["i"] >= len(ck["check"].steps):
            return self._finish_check(stopped=False)
        self.gate.panic()
        self._play_step()
        return self.check_state()

    def check_stop(self):
        if not self._check:
            return {"done": True}
        return self._finish_check(stopped=True)

    def _finish_check(self, stopped):
        ck, self._check = self._check, None
        c = ck["check"]
        self.gate.panic()
        self.send_session(Source.CHECK)                 # 変えた設定を元に戻す(音量も送り直す)
        result = {"format": "famimimidi-check-v1", "name": c.name, "title": c.title, "started": ck["started"],
                  "finished": now_iso(), "stopped": stopped, "steps": len(c.steps), "answers": ck["answers"],
                  "out_port": self.gate.output_name, "ch_offset": self.prefs.ch_offset}
        path = self.store.save_check(result)
        unexpected = [a for a in ck["answers"] if a["as_expected"] is False]
        self.log.note(f"===== 実機の確認「{c.title}」を{'途中でやめました' if stopped else '終えました'}。"
                      f"結果: {path.name}(予想と違う答え {len(unexpected)} 個) =====")
        return {"done": True, "stopped": stopped, "file": str(path), "answers": ck["answers"],
                "unexpected": len(unexpected), "title": c.title}

    def check_state(self):
        ck = self._check
        if not ck:
            return {"running": False}
        c = ck["check"]
        step = c.steps[ck["i"]]
        return {"running": True, "name": c.name, "title": c.title, "i": ck["i"], "n": len(c.steps),
                "text": step.text, "question": step.question}

    # ================================================================ 演奏セットの保存(左の一覧)
    def save_performance_new(self, name):
        p = self.library.add_performance(self.session.snapshot(), name=(name or "").strip() or "新しい演奏セット")
        self.session.saved_as(p)
        self.store.save_library(self.library)
        self.save_session_soon()
        self.log.note(f"演奏セット「{p.name}」を保存しました")
        return {**self.state(), "selected": p.id}

    def overwrite_performance(self, pid):
        if self.library.performance(pid) is None:
            return {"error": "その演奏セットが見つかりません"}
        p = self.library.overwrite_performance(pid, self.session.snapshot())
        self.session.saved_as(p)
        self.store.save_library(self.library)
        self.save_session_soon()
        self.log.note(f"演奏セット「{p.name}」を上書き保存しました")
        return self.state()

    def rename_performance(self, pid, name):
        name = (name or "").strip()
        if not name or self.library.performance(pid) is None:
            return {"error": "名前を入れてください"}
        p = self.library.rename_performance(pid, name)
        if self.session.loaded_from == pid:
            self.session.performance.name = p.name
            self.save_session_soon()
        self.store.save_library(self.library)
        return self.state()

    def delete_performance(self, pid):
        p = self.library.performance(pid)
        if p is None:
            return {"error": "その演奏セットが見つかりません"}
        self.library.delete_performance(pid)
        if self.session.loaded_from == pid:
            self.session.loaded_from = ""
            self.session.performance.id = ""
            self.save_session_soon()
        self.store.save_library(self.library)
        self.log.note(f"演奏セット「{p.name}」をライブラリから削除しました")
        return self.state()

    # ================================================================ 設定
    def set_theme(self, theme):
        self.prefs.theme = theme
        self.prefs.__post_init__()
        self.store.save_prefs(self.prefs)
        return self.state()

    def set_offset(self, offset):
        """電源 ON のときのボタンで ch がずれた。鳴っている音を止め、ずらした ch へ送り直す"""
        with self._lock:
            offs = self.router.release_all()
        for m in offs:
            self.gate.send(m, Source.THRU)
        self.prefs.ch_offset = int(offset)
        self.prefs.__post_init__()
        self.gate.ch_offset = self.prefs.ch_offset
        self.store.save_prefs(self.prefs)
        self.log.note(f"ch のずれ: {self.prefs.ch_offset}(ch{1 + self.prefs.ch_offset}〜{5 + self.prefs.ch_offset})")
        if self.gate.output_name:
            self.send_session()
        return self.state()

    # ================================================================ 保存
    def save_session_soon(self):
        if self._save_timer:
            self._save_timer.cancel()
        self._save_timer = threading.Timer(SAVE_DELAY, self.save_session_now)
        self._save_timer.daemon = True
        self._save_timer.start()

    def save_session_now(self):
        if self._save_timer:
            self._save_timer.cancel()
            self._save_timer = None
        self.store.save_session(self.session)

    def shutdown(self):
        """終了時。保存して、何も送らずにポートを閉じる"""
        self._stop.set()
        self.chord.shutdown()
        self.save_session_now()
        if self._in:
            self._in.close()
            self._in = None
        self.gate.shutdown()
        self.log.close()

    # ================================================================ 画面へ渡す形
    def state(self):
        perf, s = self.session.performance, self.session
        slots = []
        for ch in CHS:
            sl = perf.slots[ch]
            slots.append({"ch": ch, "name": sl.tone.name, "from": sl.from_, "kind": sl.tone.kind,
                          "linked": perf.link12 and ch == 2,
                          "kept": sl.kept.tone.name if sl.kept else None,
                          "silent": s.is_silent(ch, self.spec)})
        return {
            "connection": {"out": self.gate.output_name, "in": self._in.name if self._in else None,
                           "writing": self.gate.writing, "virtual": self.is_virtual},
            "prefs": {"theme": self.prefs.theme, "ch_offset": self.prefs.ch_offset, "kb_follow": self.prefs.kb_follow},
            "place": self.place,
            "session": {"name": perf.name, "id": perf.id, "loaded_from": s.loaded_from, "dirty": s.dirty,
                        "link12": perf.link12, "chord_active": perf.chord.active, "slots": slots,
                        "keyboard": perf.keyboard.to_dict(), "controls": perf.controls.to_dict(),
                        "templates": [[k, v] for k, v in TEMPLATES.items()]},
            "keyboard": self.keyboard_view(),
        }

    def side_list(self, place):
        """左の一覧(開いているタブで中身が変わる)"""
        perf = self.session.performance
        if place == "play":
            items = [{"id": p.id, "name": p.name, "sub": "コード" if p.chord.active else "割り当て",
                      "current": p.id == self.session.loaded_from, "notes": p.notes,
                      "tones": [p.slots[ch].tone.name for ch in CHS]} for p in self.library.performances]
            return {"title": "演奏セット", "place": "play", "items": items,
                    "info": "演奏セット = 5つの ch の音色・鍵盤の割り当て・ペダル・レバー・コードモードをまとめたもの。読み込むと全部が切り替わります。"}
        ch = int(place)
        kind = CH_KIND[ch]
        cur = perf.slots[ch].from_
        def item(t, sub=""):
            return {"id": t.id, "name": t.name, "sub": sub or ("波形" if t.wave is not None else ""),
                    "current": t.id == cur and bool(cur), "notes": t.notes, "category": t.category,
                    "preset": t.id.startswith(PRESET_PREFIX)}
        items = [item(t) for t in self.library.tones_of(kind)]
        presets = [item(t, "見本") for t in self.presets if t.kind == kind]
        if presets:
            items += [{"id": "", "name": "── おまかせの見本 ──", "header": True}] + presets
        if kind == "pulse":
            info = "パルスの音色は ch1・ch2 のどちらにも入ります。"
            if perf.link12:
                info += "\n🔗 紐付け中: ch2 も ch1 の音色で鳴ります。"
        else:
            info = f"選んで「この ch に入れる」と、いまの演奏セットの {TAB_NAMES[ch]} に入ります。"
        return {"title": f"{ch} {KIND_NAMES[kind]} の音色", "place": ch, "kind": kind, "items": items, "info": info}

    def keyboard_view(self):
        """下の鍵盤の表示: 鳴り方の一言と、鍵ごとの鳴る ch(色の帯)"""
        perf = self.session.performance
        if self.place != "play":
            ch = self.place
            lo, hi = NOTE_RANGE[ch]
            text = (f"音色づくり ― 外部の鍵盤は演奏セットどおり、画面の鍵盤は {TAB_NAMES[ch]} だけ" if self.prefs.kb_follow
                    else f"音色づくり ― {TAB_NAMES[ch]} だけ鳴る")
            return {"mode": "tone", "text": text,
                    "zones": {str(n): [ch] for n in range(lo, hi + 1)}}
        if perf.chord.active:
            st = self.chord.state()
            name = st["song_name"] or f"曲{st['song'] + 1}"
            return {"mode": "chord", "text": f"演奏セットどおり ― コード({name}・キー {st['key_name']})",
                    "zones": {}, "labels": self._chord_labels()}
        kb = perf.keyboard
        zones = {}
        for n in range(0, 128):
            chs = []
            for ch in CHS:
                if ch == 2 and kb.pair != "off":
                    continue
                p = kb.parts[ch]
                if p.on and p.lo <= n <= p.hi:
                    chs += [1, 2] if ch == 1 and kb.pair != "off" else [ch]
            if chs:
                zones[str(n)] = chs
        return {"mode": "map", "text": "演奏セットどおり ― 割り当て表", "zones": zones}
