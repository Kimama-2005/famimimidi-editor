"""フェーズC の新しい画面(pywebview)。画面は famimimidi/web/ の HTML/CSS/JS。

起動: .venv\\Scripts\\python -m famimimidi.webapp   (run.bat から)
画面 → Python は Bridge のメソッド(pywebview.api.xxx)、Python → 画面は evaluate_js で通知する。
送信は必ず core.engine.send() を通す(関所・ログ)。
"""
import ctypes
import json
import os
import queue
import threading
import time
import uuid
from pathlib import Path

import webview

from . import cart_actions, editor, play, single, wave
from .cartridge import plan_text
from .compare import diff
from .export import MODES as EXPORT_MODES, export_set
from .phrases import PHRASES, PhrasePlayer
from .core import OFFSETS, THEMES, Core
from .library import Patch, PerfSet
from .sets import compute_base, current_base, full_values, sounds_on_cart, status
from .spec import CHANNEL_NAMES

WEB = Path(__file__).resolve().parent / "web"
ICON = Path(__file__).resolve().parent / "icon.ico"
NOTE_RANGE = {1: (33, 108), 2: (33, 108), 3: (21, 96), 4: (0, 127), 5: (0, 127)}


class Bridge:
    """画面から呼ぶ窓口。戻り値は JSON にできるものだけ。
    (pywebview は公開属性をたどって画面に見せるので、中身は _ で始まる名前にして隠す)"""

    def __init__(self, core: Core):
        self._core = core
        self._window = None
        self._ready = threading.Event()     # 画面の準備ができたら立てる(ログを流し始める合図)
        self._dispatch = None               # JsDispatcher
        self._player = PhrasePlayer(core.engine)

    # ---------- 初期表示 ----------
    def init(self):
        self._ready.set()
        c = self._core
        return {"status": c.status(), "ports": c.ports(),
                "offsets": [[k, v] for k, v in OFFSETS.items()], "themes": [[k, v] for k, v in THEMES.items()],
                "channels": [[ch, CHANNEL_NAMES[ch], *NOTE_RANGE[ch]] for ch in range(1, 6)],
                "templates": [[k, label, play.to_json(play.template(k))] for k, (label, _) in play.TEMPLATES.items()]}

    # ---------- 接続・設定 ----------
    def ports(self):
        return self._core.ports()

    def connect(self, out_name, in_name):
        r = self._core.connect(out_name, in_name or None)
        r["status"] = self._core.status()
        return r

    def disconnect(self):
        self._core.disconnect()
        return self._core.status()

    def set_thru(self, on):
        self._core.set_thru(on)

    def set_tab(self, ch):
        """開いているタブが変わった(鍵盤の弾き方が「開いているタブのch」のときの送り先)"""
        self._core.set_tab(int(ch))
        return self._core.status()

    def set_play(self, cfg):
        """鍵盤の弾き方(2音・鍵盤を分ける)"""
        self._core.set_play(cfg)
        return self._core.status()

    def layer_copy(self, amount=16):
        """重ねる用に ch1 の音色を ch2 へ(ずらす量 amount セント)"""
        self._core.copy_for_layer(amount)
        return self._state(2)

    def set_offset(self, offset):
        self._core.set_offset(int(offset))

    def set_theme(self, theme):
        self._core.set_theme(theme)

    # ---------- 音色エディタ ----------
    def _state(self, ch):
        c = self._core
        s = editor.state(ch, c.values[ch], c.params)
        s["loaded"] = c.loaded[ch].name if c.loaded[ch] else None
        s["loaded_id"] = c.loaded[ch].id if c.loaded[ch] and c.lib.get(c.loaded[ch].id) else None
        return s

    def editor(self, ch):
        ch = int(ch)
        c = self._core
        presets = [{k: p[k] for k in ("id", "name", "group", "desc")} for p in editor.load_presets() if p["channel"] == ch]
        return {"spec": editor.spec(ch, c.params), "state": self._state(ch), "presets": presets,
                "view": c.settings.get("view", "easy")}

    def ctl(self, ch, key, action, x):
        """かんたん表示の操作"""
        ch = int(ch)
        c = self._core
        c.set_values(ch, editor.updates_for(key, action, x, c.values[ch], c.params))
        return self._state(ch)

    def detail_set(self, ch, cc, action, x):
        """詳細表示の操作"""
        ch = int(ch)
        c = self._core
        c.set_values(ch, editor.detail_update(cc, action, x, c.params))
        return self._state(ch)

    def env(self, ch, updates):
        """エンベロープのグラフの操作(アタック/アタック・レベル/ディケイ/サスティン/リリースだけ受け付ける)"""
        ch = int(ch)
        allowed = {73, 12, 75, 79, 72}
        self._core.set_values(ch, {int(k): v for k, v in updates.items() if int(k) in allowed})
        return self._state(ch)

    def preset(self, ch, preset_id):
        ch = int(ch)
        p = next((p for p in editor.load_presets() if p["id"] == preset_id), None)
        if p:
            self._core.apply_patch(Patch(id=p["id"], name=p["name"], channel=p["channel"], cc=p["cc"]), ch)
        return self._state(ch)

    def reset(self, ch):
        self._core.reset_defaults(int(ch))
        return self._state(int(ch))

    def send_all(self, ch):
        self._core.send_all(int(ch))
        return self._state(int(ch))

    def set_view(self, view):
        self._core.settings["view"] = "detail" if view == "detail" else "easy"
        self._core.save_settings()

    # ---------- ライブラリ ----------
    def lib_list(self):
        return [{"id": p.id, "name": p.name, "channel": p.channel, "category": p.category}
                for p in self._core.lib.patches]

    def lib_info(self, pid):
        c = self._core
        p = c.lib.get(pid)
        if not p:
            return None
        rows = [[c.params[cc].name_ja, c.params[cc].format_value(v)] for cc, v in p.cc if cc in c.params]
        return {"id": p.id, "name": p.name, "channel": p.channel, "category": p.category, "notes": p.notes,
                "updated": p.updated, "cc": rows}

    def lib_load(self, pid):
        p = self._core.lib.get(pid)
        if not p:
            return None
        self._core.apply_patch(p)
        return {"ch": p.channel, "state": self._state(p.channel)}

    def lib_save_new(self, ch, name, category, notes):
        if not str(name).strip():
            return {"error": "名前を入れてください"}
        p = self._core.save_new(int(ch), str(name).strip(), category, notes)
        return {"id": p.id, "state": self._state(int(ch))}

    def lib_overwrite(self, pid, ch):
        try:
            self._core.overwrite(pid, int(ch))
        except ValueError as e:
            return {"error": str(e)}
        return {"id": pid, "state": self._state(int(ch))}

    def lib_meta(self, pid, name, category, notes):
        p = self._core.lib.get(pid)
        if p and str(name).strip():
            p.name, p.category, p.notes = str(name).strip(), category or "other", notes
            self._core.lib.update(p)

    def lib_delete(self, pid):
        p = self._core.lib.get(pid)
        if p:
            self._core.lib.delete(pid)
            self._core.log.note(f"ライブラリから削除: {p.name}")

    # ---------- 演奏セット ----------
    def set_list(self):
        c = self._core
        cur = c.loaded_set.id if c.loaded_set else None
        return [{"id": d.id, "name": d.name, "summary": play.describe_map(play.normalize(d.play)), "current": d.id == cur}
                for d in c.lib.sets]

    def set_info(self, sid):
        d = self._core.lib.get_set(sid)
        if not d:
            return None
        cfg = play.normalize(d.play)
        parts = []
        for ch in range(1, 6):
            part = d.parts.get(str(ch)) or {}
            p = cfg["parts"][ch]
            used = p["on"] or (ch == 2 and cfg["pair"] != "off" and cfg["parts"][1]["on"])
            parts.append({"ch": ch, "name": part.get("name") or ("(初期設定)" if not part.get("cc") else "(名前なし)"),
                          "used": used})
        return {"id": d.id, "name": d.name, "notes": d.notes, "updated": d.updated,
                "summary": play.describe_map(cfg), "parts": parts}

    def set_load(self, sid):
        try:
            self._core.load_set(sid)
        except ValueError as e:
            return {"error": str(e)}
        return {"status": self._core.status()}

    def set_save_new(self, name, notes):
        if not str(name).strip():
            return {"error": "名前を入れてください"}
        d = self._core.save_set(str(name).strip(), notes or "")
        return {"id": d.id}

    def set_overwrite(self, sid):
        try:
            self._core.overwrite_set(sid)
        except ValueError as e:
            return {"error": str(e)}
        return {"id": sid}

    def set_meta(self, sid, name, notes):
        d = self._core.lib.get_set(sid)
        if d and str(name).strip():
            d.name, d.notes = str(name).strip(), notes or ""
            self._core.lib.update_set(d)

    def set_delete(self, sid):
        d = self._core.lib.get_set(sid)
        if d:
            self._core.lib.delete_set(sid)
            if self._core.loaded_set is d:
                self._core.loaded_set = None
            self._core.log.note(f"演奏セットを削除: {d.name}")

    # ---------- カートリッジ(保存場所) ----------
    def cart_view(self):
        c = self._core
        return {"places": cart_actions.places(c), "startup": cart_actions.startup_rows(c),
                "tidy": cart_actions.tidy_rows(c), "connected": bool(c.engine.output_name)}

    def cart_plan(self, kind, a=None, b=None):
        """書き込みの計画を作り、確認画面の内容を返す(まだ送らない)。実行は cart_run(token) だけ"""
        c = self._core
        try:
            if kind == "save":
                patch = c.lib.get(b)
                if patch is None:
                    return {"error": "ライブラリから音色を選んでください"}
                plan = cart_actions.plan_save(c, int(a), patch)
            elif kind == "clear":
                plan = cart_actions.plan_clear(c, int(a))
            elif kind == "startup":
                plan = cart_actions.plan_startup(c, int(a), int(b))
            elif kind == "startup_reset":
                plan = cart_actions.plan_startup_reset(c, int(a))
            elif kind == "tidy":
                plan = cart_actions.plan_tidy(c, int(a))
            elif kind == "advanced":
                patch = c.lib.get(b["patch_id"])
                if patch is None:
                    return {"error": "ライブラリから音色を選んでください"}
                plan = cart_actions.plan_advanced(c, patch, int(b["macro"]), b["ccs"],
                                                  int(b["pc"]) if b.get("pc") else None,
                                                  int(b["startup_ch"]) if b.get("startup_ch") else None)
            elif kind == "assign":
                plan = cart_actions.plan_assign_existing(c, int(a), int(b["pc"]) if b.get("pc") else None,
                                                         int(b["startup_ch"]) if b.get("startup_ch") else None)
            elif kind == "assign_many":
                if not b:
                    return {"error": "割り当てる PC を選んでください"}
                plan = cart_actions.plan_assign_many_pcs(c, b)
            elif kind == "wave":
                plan = cart_actions.plan_wave(c, int(a), [int(v) for v in b["samples"]], str(b["name"]).strip() or "名前なし")
            else:
                return {"error": f"不明な操作: {kind}"}
        except ValueError as e:
            return {"error": str(e)}
        token = uuid.uuid4().hex
        self._plans = {token: plan}          # 最新の1件だけを有効にする
        return {"token": token, "title": plan.title, "lines": plan.lines, "ok_text": plan.ok_text,
                "detail": plan_text(plan.steps), "secs": round(sum(s.wait_ms for s in plan.steps) / 1000)}

    def cart_run(self, token):
        """確認画面で「進める」を押したときだけ呼ばれる。進み具合と結果は onWriteProgress / onWriteDone で画面へ"""
        plan = getattr(self, "_plans", {}).pop(token, None)
        if plan is None:
            return {"error": "確認画面の有効期限が切れました。もう一度やり直してください。"}
        c = self._core

        def progress(i, n, text):
            self._js(f"window.onWriteProgress && onWriteProgress({i}, {n}, {json.dumps(text, ensure_ascii=False)})")

        def done(ok, message):
            for kind, ch in plan.after:
                if kind == "tidy_check" and ok:
                    s = status(c.cart, c.lib, c.params, ch)
                    if s.count > 1 and s.tidy_needed:
                        message += f"\n\nch{ch} の音色どうしで切り替えると、設定が残る可能性があります。" \
                                   f"下の「ch{ch} 整える」を押すと、まとめて直せます。"
            self._js(f"window.onWriteDone && onWriteDone({json.dumps(ok)}, {json.dumps(message, ensure_ascii=False)})")

        err = c.run_write(plan, progress, done)
        if err:
            return {"error": err}
        return {"started": True, "secs": round(sum(s.wait_ms for s in plan.steps) / 1000)}

    # ---------- 詳細な管理 ----------
    def cart_tables(self):
        return cart_actions.tables(self._core)

    def cart_candidates(self, pid, pc):
        p = self._core.lib.get(pid)
        return cart_actions.candidates(self._core, p, int(pc)) if p else None

    def pc_send(self, ch, pc):
        """任意の PC を送る(書き込みではない)"""
        e = self._core.engine
        return e.send(bytes([0xC0 | e.midi_ch0(int(ch)), int(pc) - 1]), "PC送信")

    def check_play(self, pc):
        """1つずつ試す: 音量を戻す → PC → 1音(ch1)。無音なら、その PC のマクロが音を消した"""
        e = self._core.engine
        if e.writing:
            return False
        c0 = e.midi_ch0(1)
        for n, v in ((7, 127), (11, 127)):
            e.send(bytes([0xB0 | c0, n, v]), "PCチェック")
        e.send(bytes([0xC0 | c0, int(pc) - 1]), "PCチェック")
        threading.Timer(0.15, e.send, args=(bytes([0x90 | c0, 72, 100]), "PCチェック")).start()
        threading.Timer(0.65, e.send, args=(bytes([0x80 | c0, 72, 0]), "PCチェック")).start()
        return True

    def check_mark(self, pc, ok):
        m = self._core.cart.pc_map.get(int(pc))
        self._core.log.note(f"PCチェック: PC{pc} = {'鳴った' if ok else '無音'}(対応表ではマクロ{m})")

    def cart_try(self, pc, ch):
        """呼び出して鳴らす: 音量を戻す → 呼び出し番号 → ド・ミ・ソ → 和音"""
        e = self._core.engine
        if e.writing:
            return False
        c0 = e.midi_ch0(int(ch))
        for n, v in ((7, 127), (11, 127)):
            e.send(bytes([0xB0 | c0, n, v]), "かんたん")
        e.send(bytes([0xC0 | c0, int(pc) - 1]), "かんたん")
        plan = [(0.15 + i * 0.3, bytes([0x90 | c0, n, 100])) for i, n in enumerate((60, 64, 67))]
        plan += [(0.4 + i * 0.3, bytes([0x80 | c0, n, 0])) for i, n in enumerate((60, 64, 67))]
        plan += [(1.2, bytes([0x90 | c0, n, 100])) for n in (60, 64, 67)]
        plan += [(2.4, bytes([0x80 | c0, n, 0])) for n in (60, 64, 67)]
        for t, msg in plan:
            threading.Timer(t, e.send, args=(msg, "かんたん")).start()
        return True

    def send_base(self, ch):
        """土台を今だけ送る(保存しない)"""
        ch = int(ch)
        c = self._core
        base = current_base(c.cart, ch) or compute_base(
            [full_values(p, c.params, ch) for p in sounds_on_cart(c.cart, c.lib, ch).values()], c.params)
        if not base:
            return False
        c.set_values(ch, base)
        c.log.note(f"ch{ch} の土台を送信(保存はしない): {base}")
        return True

    def _js(self, code):
        """画面への知らせ。列に入れるだけで待たない(書き込みのスレッドを画面の応答で止めないため)"""
        if self._dispatch:
            self._dispatch.post(code)

    # ---------- 試聴フレーズ ----------
    def phrases(self):
        return [name for name, _ in PHRASES]

    def play_phrase(self, ch, name, base, vel=100):
        events = dict(PHRASES).get(name)
        if events is None or self._core.engine.writing:
            return False
        self._player.play(int(ch), int(base), int(vel), events)
        return True

    def stop_phrase(self):
        self._player.stop()

    # ---------- 波形メモリ(ch5) ----------
    def wave_state(self):
        waves = self._core.cart.waves
        return {"presets": wave.PRESETS,
                "slots": [{"pc": pc, "name": (waves.get(pc) or {}).get("name"),
                           "has": bool((waves.get(pc) or {}).get("samples"))} for pc in wave.PCS]}

    def _wave_play(self, pre, note):
        e = self._core.engine
        if e.writing:
            return False
        c0 = e.midi_ch0(5)
        for msg in pre:
            e.send(msg, "波形メモリ")
        e.send(bytes([0xB0 | c0, 18, 127]), "波形メモリ")          # ch5 を波形メモリモードに
        threading.Timer(0.1, e.send, args=(bytes([0x90 | c0, int(note), 127]), "波形メモリ")).start()
        threading.Timer(1.1, e.send, args=(bytes([0x80 | c0, int(note), 0]), "波形メモリ")).start()
        return True

    def wave_preview(self, samples, note):
        """描いた波形を送って鳴らす(カートリッジには保存しない)"""
        try:
            return self._wave_play([wave.data_sysex(samples)], note)
        except ValueError:
            return False

    def wave_recall(self, pc, note):
        return self._wave_play([bytes([0xC0 | self._core.engine.midi_ch0(5), int(pc) - 1])], note)

    def wave_drum(self):
        e = self._core.engine
        return e.send(bytes([0xB0 | e.midi_ch0(5), 18, 0]), "波形メモリ")

    def wave_load(self, pc):
        w = self._core.cart.waves.get(int(pc))
        return w if w and w.get("samples") else None

    # ---------- A/B 比較 ----------
    def ab_diff(self, a_id, b_id):
        c = self._core
        pa, pb = c.lib.get(a_id), c.lib.get(b_id)
        if not (pa and pb):
            return None
        rows = [{"name": r.name, "a": r.a, "b": r.b, "audible": r.audible} for r in diff(pa, pb, c.params)]
        return {"rows": rows, "same_ch": pa.channel == pb.channel, "a_ch": pa.channel, "b_ch": pb.channel}

    def ab_play(self, pid, phrase, base=None):
        """音色の全項目を送ってから(CC が届くのを少し待って)フレーズを鳴らす"""
        c = self._core
        p = c.lib.get(pid)
        events = dict(PHRASES).get(phrase)
        if not p or events is None or c.engine.writing:
            return None
        c.apply_patch(p)
        b = int(base) if base is not None else {1: 60, 2: 60, 3: 48, 4: 0, 5: 36}[p.channel]
        threading.Timer(0.15, self._player.play, args=(p.channel, b, 100, events)).start()
        return {"ch": p.channel, "ms": max(s + d for s, d, _ in events)}

    # ---------- ファイル(MIDI 書き出し、ライブラリのバックアップ) ----------
    def _save_dialog(self, filename, types):
        r = self._window.create_file_dialog(webview.FileDialog.SAVE, save_filename=filename, file_types=types)
        if not r:
            return None
        return r if isinstance(r, str) else r[0]

    def export_midi(self, assign, mode):
        c = self._core
        pats = {int(ch): c.lib.get(pid) for ch, pid in assign.items() if pid}
        pats = {ch: p for ch, p in pats.items() if p}
        if not pats:
            return {"error": "少なくとも1つのチャンネルに音色を選んでください"}
        first = pats[min(pats)]
        path = self._save_dialog(f"famimimidi_{first.name}.mid".replace("/", "_"), ("MIDIファイル (*.mid)",))
        if not path:
            return {"cancel": True}
        data, notes = export_set(pats, c.params, mode, c.cart, c.engine.ch_offset)
        Path(path).write_bytes(data)
        c.log.note(f"MIDIファイルに書き出し: {path}(" + ", ".join(f"ch{ch}={p.name}" for ch, p in sorted(pats.items())) + ")")
        return {"path": path, "notes": notes}

    def export_modes(self):
        return [[k, v] for k, v in EXPORT_MODES.items()]

    def lib_backup(self):
        path = self._save_dialog("famimimidi_library.json", ("JSON (*.json)",))
        if not path:
            return {"cancel": True}
        self._core.lib.export(Path(path))
        self._core.log.note(f"ライブラリを書き出し: {path}")
        return {"path": path}

    def lib_restore(self):
        r = self._window.create_file_dialog(webview.FileDialog.OPEN, file_types=("JSON (*.json)",))
        if not r:
            return {"cancel": True}
        path = r[0] if not isinstance(r, str) else r
        try:
            added = self._core.lib.import_file(Path(path))
        except (OSError, ValueError, TypeError, KeyError) as e:
            return {"error": f"取り込めませんでした: {e}"}
        n_sets = sum(isinstance(a, PerfSet) for a in added)
        self._core.log.note(f"{path} から 音色 {len(added) - n_sets} 個・演奏セット {n_sets} 個を取り込み")
        return {"count": len(added) - n_sets, "sets": n_sets}

    # ---------- 演奏 ----------
    def note(self, ch, note, vel, on):
        e = self._core.engine
        c0 = e.midi_ch0(int(ch))
        msg = bytes([0x90 | c0, int(note), int(vel)]) if on else bytes([0x80 | c0, int(note), 0])
        return e.send(msg, "画面鍵盤")

    def panic(self):
        if self._core.engine.writing:
            self._core.log.note("書き込み中のためパニックは送りません")
            return False
        self._player.stop()
        self._core.engine.panic()
        return True

    def open_log_dir(self):
        os.startfile(self._core.log.path.parent)


class JsDispatcher:
    """Python → 画面の知らせを、1本のスレッドで順番に evaluate_js する。
    evaluate_js は画面の応答を待つので、複数のスレッドから同時に呼んだり、画面のスレッド(閉じる操作の処理など)
    から呼んだりすると固まる(C3 の確認で実際に起きた)。ほかの場所は post() で列に入れるだけにする"""

    def __init__(self, window, ready: threading.Event):
        self._window, self._ready = window, ready
        self._q = queue.Queue()
        threading.Thread(target=self._run, daemon=True).start()

    def post(self, code):
        self._q.put(code)

    def stop(self):
        self._q.put(None)

    def _run(self):
        self._ready.wait()
        while True:
            code = self._q.get()
            if code is None:
                return
            try:
                self._window.evaluate_js(code)
            except Exception:  # noqa: BLE001 — 画面を閉じる途中などは無視
                pass


def _pump_log(core: Core, dispatch: JsDispatcher, ready: threading.Event, stop: threading.Event):
    """送信ログを画面へ流す(100ms ごとにまとめて)。画面の準備ができるまでは溜めておく"""
    ready.wait()
    while not stop.is_set():
        lines = []
        try:
            while len(lines) < 300:
                lines.append(core.log.lines.get_nowait())
        except queue.Empty:
            pass
        if lines:
            dispatch.post(f"window.onLog && window.onLog({json.dumps(lines, ensure_ascii=False)})")
        time.sleep(0.1)


def main():
    if not single.acquire():          # 2つ同時に起動させない
        return
    # タスクバーで python.exe の仲間にまとめられず、このソフトのアイコンで出るように
    ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("Famimimidi.SoundEditor")
    core = Core()
    bridge = Bridge(core)
    window = webview.create_window("FAMIMIMIDI SOUND EDITOR", url=str(WEB / "index.html"), js_api=bridge,
                                   width=1360, height=880, min_size=(1100, 720), background_color="#000000")
    bridge._window = window
    dispatch = JsDispatcher(window, bridge._ready)
    bridge._dispatch = dispatch
    stop = threading.Event()

    def on_closing():
        # ここは画面のスレッドで呼ばれるので evaluate_js を直接呼ばない(固まる)
        if core.engine.writing:
            if core.write_overdue():
                core.log.note("書き込みが予定の時間を大きく過ぎても終わらないため、閉じることを許可しました")
                return True
            dispatch.post("window.toast && toast('カートリッジに書き込み中です。終わるまで閉じないでください。', 'danger')")
            return False          # 閉じない
        return True

    def on_start():
        # 前回のポートに自動で接続する(失敗しても画面で知らせるだけ)
        want = core.settings.get("out_name")
        if want and want in core.ports()["out"]:
            core.connect(want, core.settings.get("in_name"))
        threading.Thread(target=_pump_log, args=(core, dispatch, bridge._ready, stop), daemon=True).start()

    window.events.closing += on_closing
    core.log.note("新しい画面(フェーズC)で起動")
    try:
        webview.start(on_start, http_server=True, icon=str(ICON))
    finally:
        stop.set()
        dispatch.stop()
        core.shutdown()


if __name__ == "__main__":
    main()
