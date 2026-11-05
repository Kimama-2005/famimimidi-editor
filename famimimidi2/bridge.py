"""画面(pywebview)⇔ アプリの窓口。画面は famimimidi2/web/。

起動: python -m famimimidi2(run.bat から)
- 画面 → Python: Bridge のメソッド(pywebview.api.xxx)。戻り値は JSON にできるものだけ
- Python → 画面: JsDispatcher の1本のスレッドだけが evaluate_js を呼ぶ(複数のスレッドや画面のスレッドから呼ぶと固まった)
- pywebview は公開属性をたどって画面に見せるので、中身は _ で始まる名前にして隠す
"""
import ctypes
import json
import queue
import threading
import time
from pathlib import Path

from .app import App
from .device import single
from .model.prefs import OFFSETS, THEMES
from .model.store import StoreError
from .music.spec import CH_NAMES

WEB = Path(__file__).resolve().parent / "web"
ICON = Path(__file__).resolve().parent / "icon.ico"
TITLE = "FAMIMIMIDI SOUND EDITOR"
THEME_NAMES = {"rpg": "A RPGウィンドウ", "console": "B ファミコン本体", "crt": "C ブラウン管"}
OFFSET_NAMES = {0: "ch1〜5(ふつう)", 5: "ch6〜10", 10: "ch11〜15"}


class Bridge:
    def __init__(self, app: App):
        self._app = app
        self._ready = threading.Event()
        self._dispatch = None
        self._window = None
        app.chord_listeners.append(
            lambda st: self._js(f"window.onChordState && onChordState({json.dumps(st, ensure_ascii=False)})"))

    # ---------- 初期表示 ----------
    def init(self):
        self._ready.set()
        a = self._app
        return {"state": a.state(), "side": a.side_list(a.place), "ports": a.ports(),
                "themes": [[k, THEME_NAMES[k]] for k in THEMES], "offsets": [[k, OFFSET_NAMES[k]] for k in OFFSETS],
                "channels": [[ch, CH_NAMES[ch]] for ch in range(1, 6)],
                "notes": a.notes, "other_apps": single.other_midi_apps()}

    def state(self):
        return self._app.state()

    # ---------- 接続・設定 ----------
    def ports(self):
        return self._app.ports()

    def connect(self, out_name, in_name):
        r = self._app.connect(out_name, in_name or None)
        return {**r, "state": self._app.state()}

    def disconnect(self):
        self._app.disconnect()
        return self._app.state()

    def toggle_virtual(self):
        r = self._app.toggle_virtual()
        return {**r, "state": self._app.state()}

    def vfc_defaults(self):
        """仮想ファミコンの音源が使う、各 CC の初期値(実装表)"""
        return {str(p["cc"]): p["default"] for p in self._app.spec.data["params"] if p.get("default") is not None}

    def set_theme(self, theme):
        return self._app.set_theme(theme)

    def set_offset(self, offset):
        return self._app.set_offset(int(offset))

    # ---------- 場所・左の一覧 ----------
    def set_place(self, place):
        st = self._app.set_place(place)
        return {"state": st, "side": self._app.side_list(self._app.place)}

    def side(self):
        return self._app.side_list(self._app.place)

    def _with_side(self, st):
        if isinstance(st, dict) and "error" in st:
            return st
        return {"state": st, "side": self._app.side_list(self._app.place), "selected": st.get("selected")}

    def load_performance(self, pid):
        return self._with_side(self._app.load_performance(pid))

    def save_performance_new(self, name):
        return self._with_side(self._app.save_performance_new(name))

    def overwrite_performance(self, pid):
        return self._with_side(self._app.overwrite_performance(pid))

    def rename_performance(self, pid, name):
        return self._with_side(self._app.rename_performance(pid, name))

    def delete_performance(self, pid):
        return self._with_side(self._app.delete_performance(pid))

    def put_tone(self, ch, tid):
        return self._with_side(self._app.put_tone(ch, tid))

    def save_tone_new(self, ch, name):
        return self._with_side(self._app.save_tone_new(ch, name))

    def overwrite_tone(self, ch, tid):
        return self._with_side(self._app.overwrite_tone(ch, tid))

    def rename_tone(self, tid, name):
        return self._with_side(self._app.rename_tone(tid, name))

    def delete_tone(self, tid):
        return self._with_side(self._app.delete_tone(tid))

    def reset_tone(self, ch):
        return self._with_side(self._app.reset_tone(ch))

    # ---------- 音色をつくる ----------
    def tone_view(self, ch):
        return self._app.tone_view(ch)

    def tone_set(self, ch, key, action, x):
        return self._app.tone_set(ch, key, action, x)

    def tone_env(self, ch, updates):
        return self._app.tone_env(ch, updates)

    def set_wave(self, samples):
        return self._app.set_wave(samples)

    # ---------- 演奏セット ----------
    def toggle_link12(self):
        return self._with_side(self._app.toggle_link12())

    def set_chord_active(self, on):
        return self._app.set_chord_active(bool(on))

    def set_keyboard(self, d):
        return self._with_side(self._app.set_keyboard(d))

    def apply_template(self, name):
        return self._with_side(self._app.apply_template(name))

    def set_controls(self, d):
        return self._app.set_controls(d)

    def resend(self):
        return self._app.resend()

    # ---------- コードモード ----------
    def chord_view(self):
        return self._app.chord_view()

    def set_chord_settings(self, d):
        return self._app.set_chord_settings(d)

    def chord_song(self, i):
        return self._app.chord_song(i)

    def chord_next_song(self, d):
        return self._app.chord_next_song(d)

    def chord_key(self, k=None, delta=None):
        return self._app.chord_key(k, delta)

    def set_kb_follow(self, on):
        return self._app.set_kb_follow(on)

    def chord_set_next(self, i):
        return self._app.chord_set_next(i)

    def chord_hold(self):
        return self._app.chord_hold()

    def chord_stop(self):
        return self._app.chord_stop()

    def chord_play(self, row, off, on, vel=100):
        return self._app.chord_play(row, off, on, vel)

    def save_song(self, i, name, key, text):
        return self._app.save_song(i, name, key, text)

    def save_common(self, symbols):
        return self._app.save_common(symbols)

    def import_chordbook(self):
        """OtamaChord Studio のコードセット(.json)を選んで取り込む"""
        path = self._open_dialog(("コードセット (*.json)", "すべて (*.*)"))
        if not path:
            return None
        try:
            data = json.loads(Path(path).read_text(encoding="utf-8"))
        except (OSError, ValueError) as e:
            return {"error": f"読めませんでした: {e}"}
        return self._app.import_chordbook(data)

    def import_chordwiki(self, i):
        """保存した ChordWiki のページ(.html)を選んで、曲 i に取り込む"""
        path = self._open_dialog(("ChordWiki のページ (*.html;*.htm)", "すべて (*.*)"))
        if not path:
            return None
        raw = Path(path).read_bytes()
        for enc in ("utf-8", "cp932", "euc-jp"):
            try:
                page = raw.decode(enc)
                break
            except UnicodeDecodeError:
                continue
        else:
            return {"error": "文字コードが分からないファイルです"}
        return self._app.import_chordwiki(int(i), page, source=str(path))

    def export_chordbook(self):
        """曲(コードセット)を JSON に書き出す(オタマで読める形)"""
        import webview
        if not self._window:
            return None
        r = self._window.create_file_dialog(webview.SAVE_DIALOG, save_filename="chordset.json",
                                            file_types=("コードセット (*.json)",))
        if not r:
            return None
        path = r if isinstance(r, str) else r[0]
        Path(path).write_text(json.dumps(self._app.chordbook.to_dict(), ensure_ascii=False, indent=1), encoding="utf-8")
        return {"path": path}

    def _open_dialog(self, types):
        import webview
        if not self._window:
            return None
        r = self._window.create_file_dialog(webview.OPEN_DIALOG, file_types=types)
        return r[0] if r else None

    # ---------- カートリッジ ----------
    def cart_view(self):
        return self._app.cart_view()

    def cart_plan(self, kind, args=None):
        return self._app.cart_plan(kind, args)

    def cart_run(self, token):
        def progress(i, n, text):
            self._js(f"window.onWriteProgress && onWriteProgress({i}, {n}, {json.dumps(text, ensure_ascii=False)})")

        def done(ok, message):
            self._js(f"window.onWriteDone && onWriteDone({json.dumps(ok)}, {json.dumps(message, ensure_ascii=False)})")
        return self._app.cart_run(token, progress, done)

    def write_overdue(self):
        return self._app.write_overdue()

    def cart_call(self, place, ch=1):
        return self._app.cart_call(place, ch)

    # ---------- 実機の確認モード ----------
    def check_list(self):
        return {"checks": self._app.check_list(), "other_apps": single.other_midi_apps(),
                "state": self._app.check_state()}

    def check_start(self, name):
        return self._app.check_start(name)

    def check_answer(self, answer):
        return self._app.check_answer(answer)

    def check_again(self):
        return self._app.check_again()

    def check_stop(self):
        return self._app.check_stop()

    # ---------- 演奏 ----------
    def note(self, note, vel, on):
        return self._app.screen_note(note, vel, bool(on))

    def panic(self):
        return self._app.panic()

    # ---------- 内部 ----------
    def _js(self, code):
        if self._dispatch:
            self._dispatch.post(code)


class JsDispatcher:
    """Python → 画面の知らせを、1本のスレッドで順番に evaluate_js する"""

    def __init__(self, window, ready: threading.Event):
        self._window, self._ready = window, ready
        self._q = queue.Queue()
        threading.Thread(target=self._run, name="js", daemon=True).start()

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
            except Exception:  # noqa: BLE001 — 閉じる途中などは無視
                pass


def pump_virtual(app: App, dispatch: JsDispatcher, ready: threading.Event, stop: threading.Event):
    """仮想ファミコンへ送ったメッセージを、画面の音源(web/vfc.js)へまとめて渡す(5ms ごと)"""
    ready.wait()
    while not stop.is_set():
        items = app.virtual.take()
        if items:
            dispatch.post(f"window.vfcFeed && vfcFeed({json.dumps(items)})")
        time.sleep(0.005)


def pump_log(app: App, dispatch: JsDispatcher, ready: threading.Event, stop: threading.Event):
    """送信ログを画面へ流す(100ms ごとにまとめて)"""
    ready.wait()
    while not stop.is_set():
        lines = []
        try:
            while len(lines) < 300:
                lines.append(app.log.lines.get_nowait())
        except queue.Empty:
            pass
        if lines:
            dispatch.post(f"window.onLog && window.onLog({json.dumps(lines, ensure_ascii=False)})")
        time.sleep(0.1)


def _message(text):
    ctypes.windll.user32.MessageBoxW(None, text, TITLE, 0x10)


def main():
    import webview
    if not single.acquire():          # 2つ同時に起動させない(鍵盤の演奏が二重に届く)
        return
    ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("Famimimidi.SoundEditor")
    try:
        app = App()
    except StoreError as e:
        _message(f"保存してあるデータを読めませんでした。\n{e}\n\nファイルは書き換えていません。Claude に伝えてください。")
        return
    bridge = Bridge(app)
    window = webview.create_window(TITLE, url=str(WEB / "index.html"), js_api=bridge, width=1360, height=900,
                                   min_size=(1100, 720), background_color="#000000")
    bridge._window = window
    dispatch = JsDispatcher(window, bridge._ready)
    bridge._dispatch = dispatch
    stop = threading.Event()

    def on_closing():
        if app.gate.writing:      # 書き込み中は閉じない(予定を大きく過ぎたら許す)
            if app.write_overdue():
                app.log.note("書き込みが予定の時間を大きく過ぎても終わらないため、閉じることを許しました(中身は不明として控えに残ります)")
                return True
            dispatch.post("window.toast && toast('カートリッジに書き込み中です。終わるまで閉じないでください。', 'danger')")
            return False
        return True

    def on_start():
        r = app.auto_connect()
        if r and not r["ok"]:
            dispatch.post(f"window.toast && toast({json.dumps(r['message'], ensure_ascii=False)}, 'danger')")
        dispatch.post("window.refresh && refresh()")
        threading.Thread(target=pump_log, args=(app, dispatch, bridge._ready, stop), daemon=True).start()
        threading.Thread(target=pump_virtual, args=(app, dispatch, bridge._ready, stop), daemon=True).start()

    window.events.closing += on_closing
    app.log.note("作り直し版の画面で起動")
    try:
        webview.start(on_start, http_server=True, icon=str(ICON))
    finally:
        stop.set()
        dispatch.stop()
        app.shutdown()
