"""送信の関所・MIDIスルー・送信ログ。

すべての送信はここを通る。
- 書き込み系(CC#45/50/51、SysEx の波形登録)は、確認ダイアログを通った書き込みジョブ(write_ok=True)以外は遮断する。
  SysEx は波形データ(試聴)と波形登録の2つの形だけを扱い、それ以外は常に遮断する
- 書き込みジョブの実行中は、それ以外の送信(エディタ・スルー・試聴・パニック)を止める。
  記録中に届いたCCはマクロに入ってしまうため(docs/03 F11, F20)
- スルーは鍵盤の弾き方(play.py)で送り先の ch を決める
- スライダー操作の CC は間引く(同じ ch・CC は最新値だけを 20ms ごとに送る)
- 送った全バイトをタイムスタンプ付きでログに残す(画面+ファイル)
"""
import queue
import threading
import time
from datetime import datetime
from pathlib import Path

from .play import PlayRouter
from .spec import ROOT, describe
from .wave import classify_sysex

WRITE_CCS = {45: "ユーザーマクロ記録", 50: "初期化マクロ設定", 51: "PCマクロ設定"}
THRU_IGNORE = {0xF8, 0xFE}   # クロック、アクティブ・センシング(本機は非対応。ログが埋まるので捨てる)
FLUSH_INTERVAL = 0.020
LOG_DIR = ROOT / "logs"


class SendLog:
    """画面(キュー経由)とファイルの両方に書く。どのスレッドから呼んでもよい"""

    def __init__(self, log_dir: Path | None = LOG_DIR):
        self.lines = queue.Queue()
        self._lock = threading.Lock()
        self._file = None
        if log_dir is not None:
            log_dir.mkdir(exist_ok=True)
            self.path = log_dir / f"{datetime.now():%Y-%m-%d}.log"
            self._file = open(self.path, "a", encoding="utf-8", buffering=1)
            self._file.write(f"\n===== 起動 {datetime.now():%Y-%m-%d %H:%M:%S} =====\n")
        else:
            self.path = None

    def write(self, direction, msg: bytes = b"", text="", source=""):
        ts = datetime.now().strftime("%H:%M:%S.%f")[:-3]
        hexs = msg.hex(" ").upper() if msg else ""
        line = f"{ts}  {direction:<4} {hexs:<9} {text}"
        if source:
            line += f"  [{source}]"
        with self._lock:
            if self._file:
                self._file.write(line + "\n")
        self.lines.put(line)

    def note(self, text):
        self.write("----", text=text)

    def close(self):
        with self._lock:
            if self._file:
                self._file.close()
                self._file = None


class MidiEngine:
    def __init__(self, log: SendLog, params=None):
        self.log = log
        self.params = params
        self.ch_offset = 0          # 0 / 5 / 10(電源ON時のボタンで ch6-10 / 11-15 になる)
        self.thru_enabled = True
        self.thru_channel = None    # 1〜5 なら、スルーの演奏をその音源chに付け替える(None = そのまま)
        self.router = PlayRouter()  # 鍵盤の弾き方(2音・鍵盤を分ける)。ノートオフを同じchへ送るための記録も持つ
        self._route_lock = threading.Lock()
        self._out = None
        self._in = None
        self._out_lock = threading.Lock()
        self._pending = {}          # (midi_ch0, cc) -> value
        self._pending_lock = threading.Lock()
        self._inbox = queue.Queue()
        self._writing = threading.Event()
        self._stop = threading.Event()
        self._threads = [threading.Thread(target=self._flush_loop, daemon=True),
                         threading.Thread(target=self._thru_loop, daemon=True)]
        for t in self._threads:
            t.start()

    # ---------- ポート ----------
    @property
    def output_name(self):
        return self._out.name if self._out else None

    @property
    def input_name(self):
        return self._in.name if self._in else None

    def set_output(self, port):
        """port は send(bytes)/close()/name を持つもの。None で切断"""
        with self._out_lock:
            if self._out:
                self._out.close()
                self.log.note(f"出力を切断: {self._out.name}")
            self._out = port
        if port:
            self.log.note(f"出力に接続: {port.name}")

    def set_input(self, port):
        if self._in:
            self._in.close()
            self.log.note(f"入力を切断: {self._in.name}")
        self._in = port
        if port:
            self.log.note(f"入力に接続: {port.name}")

    def on_input(self, msg: bytes):
        """入力ポートのコールバックから呼ばれる(winmm のスレッド)"""
        self._inbox.put(msg)

    # ---------- 送信 ----------
    def midi_ch0(self, ch):
        """画面上の ch(1〜5)→ 送信する MIDI チャンネル(0始まり)"""
        return ch - 1 + self.ch_offset

    def set_cc(self, ch, cc, value):
        """スライダー用。間引いて送る"""
        with self._pending_lock:
            self._pending[(self.midi_ch0(ch), cc)] = value

    def send_cc_now(self, ch, cc, value, source="エディタ"):
        return self.send(bytes([0xB0 | self.midi_ch0(ch), cc, value]), source)

    # ---------- 書き込み中モード ----------
    @property
    def writing(self):
        return self._writing.is_set()

    def begin_write(self):
        with self._out_lock:        # 送信中のメッセージが終わってから切り替える
            self._writing.set()
        self.log.note("===== 書き込み開始(ほかの送信を停止) =====")

    def end_write(self):
        self._writing.clear()
        self.log.note("===== 書き込み終了 =====")

    def send(self, msg: bytes, source="エディタ", write_ok=False):
        """関所。送れたら True。write_ok は書き込みジョブだけが使う"""
        if self._writing.is_set() and not write_ok:
            self.log.write("遮断", msg, f"{describe(msg, self.params, self.ch_offset)} … 書き込み中のため送りません", source)
            return False
        reason = self.blocked_reason(msg, write_ok)
        if reason:
            self.log.write("遮断", msg, f"{describe(msg, self.params, self.ch_offset)} … {reason}", source)
            return False
        with self._out_lock:
            if not self._out:
                self.log.write("未送信", msg, f"{describe(msg, self.params, self.ch_offset)} … 出力ポート未接続", source)
                return False
            try:
                self._out.send(msg)
            except Exception as e:  # noqa: BLE001 — 送信エラーはログに残して続行
                self.log.write("失敗", msg, f"{describe(msg, self.params, self.ch_offset)} … {e}", source)
                return False
            # ロックの中で書く(ログの順序 = 実際の送信順)
            self.log.write("OUT", msg, describe(msg, self.params, self.ch_offset), source)
        return True

    @staticmethod
    def blocked_reason(msg: bytes, write_ok=False):
        if not msg:
            return "空のメッセージ"
        if msg[0] == 0xF0:
            kind = classify_sysex(msg)
            if kind == "data":          # 波形データ(試聴用)。実装表に「セーブあり」の記載なし
                return None
            if kind == "register":      # PC61〜76 への登録はカートリッジに保存される
                return None if write_ok else "波形の登録はカートリッジへの書き込みのため、確認ダイアログ経由でしか送れません"
            return "このソフトが扱う形ではない SysEx なので送りません"
        if (msg[0] & 0xF0) == 0xB0 and len(msg) >= 2 and msg[1] in WRITE_CCS and not write_ok:
            return f"CC#{msg[1]}({WRITE_CCS[msg[1]]})はカートリッジへの書き込みのため、確認ダイアログ経由でしか送れません"
        return None

    def panic(self):
        """CC#123(オール・ノート・オフ)→ CC#120(オール・サウンド・オフ)を ch1〜5 に。CC#121 は使わない"""
        with self._pending_lock:
            self._pending.clear()
        for ch in range(1, 6):
            self.send_cc_now(ch, 123, 0, "パニック")
        for ch in range(1, 6):
            self.send_cc_now(ch, 120, 0, "パニック")

    # ---------- スレッド ----------
    def flush_pending(self):
        if self._writing.is_set():      # 書き込みが終わるまで持ち越す
            return
        with self._pending_lock:
            items = list(self._pending.items())
            self._pending.clear()
        for (c0, cc), v in items:
            self.send(bytes([0xB0 | c0, cc, v]), "エディタ")

    def _flush_loop(self):
        while not self._stop.is_set():
            time.sleep(FLUSH_INTERVAL)
            self.flush_pending()

    def handle_input(self, msg: bytes):
        if msg[0] in THRU_IGNORE:
            return
        if self.thru_enabled and self._out:
            for m in self.remap_thru(msg):
                self.send(m, "スルー")
        else:
            self.log.write("IN", msg, describe(msg, self.params, self.ch_offset),
                           "スルーOFF" if not self.thru_enabled else "出力未接続")

    def remap_thru(self, msg: bytes):
        """スルーの1メッセージ → 送るメッセージの列(鍵盤の弾き方 play.py で振り分け)"""
        with self._route_lock:
            return self.router.route(msg, self.thru_channel, self.midi_ch0)

    def set_play(self, cfg):
        """鍵盤の弾き方を変える。鳴っている音は止める"""
        with self._route_lock:
            offs = self.router.configure(cfg)
        for m in offs:
            self.send(m, "スルー")

    def _thru_loop(self):
        while not self._stop.is_set():
            try:
                msg = self._inbox.get(timeout=0.1)
            except queue.Empty:
                continue
            self.handle_input(msg)

    def shutdown(self):
        """終了時。何も送らずにポートを閉じる"""
        self._stop.set()
        for t in self._threads:
            t.join(timeout=1)
        self.set_input(None)
        self.set_output(None)
