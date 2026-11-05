"""送信の関所(SPEC_v2 6.1)。すべての送信はここを通る。ほかの道から送らない。

判定の順:
1. 書き込み中なら、書き込みジョブ(write_ok)以外は送らない(記録中に届いた CC はマクロに入ってしまう。F11・F20)
2. 書き込み系の CC(#45・#50・#51)と波形の登録 SysEx は、確認画面を通った書き込みジョブ以外は送らない。
   波形データの SysEx(試聴)は送ってよい。それ以外の SysEx は送らない。
   CC#121 は鳴っている音を全部止め、保存領域への影響も未確認(U11)なので、いつも送らない
3. 音量(CC#7)かエクスプレッション(CC#11)が 0 の ch へのノートオンは送らない
   (音量0でも強く弾くと鳴ることがあった。法則は未確認 = V0)。0 かどうかは is_silent(ch) で作業中の演奏に聞く
4. 送ったものは時刻・バイト列・日本語の説明・出どころをログに書く。送らなかったものも理由付きで書く

スライダーの CC は queue_cc で間引く(同じ ch・CC は 20ms ごとに最新の値だけ)。書き込み中は持ち越す。
"""
import queue
import threading
from datetime import datetime
from pathlib import Path

from ..music.spec import describe
from . import sysex

WRITE_CCS = {45: "ユーザーマクロ記録", 50: "電源を入れたときの音色の設定", 51: "呼び出し番号の設定"}
NEVER_CCS = {121: "鳴っている音を全部止める(リセット・オール・コントローラー)ので使いません"}
INPUT_IGNORE = frozenset({0xF8, 0xFE})     # クロック、アクティブ・センシング(ログが埋まるので捨てる)
FLUSH_INTERVAL = 0.020


class Source:
    """ログに書く出どころ"""
    EDITOR = "エディタ"
    THRU = "スルー"
    CHORD = "コード"
    SCREEN = "画面鍵盤"
    AUDITION = "試聴"
    WRITE = "書き込み"
    PANIC = "パニック"
    CHECK = "確認"
    RESEND = "送り直し"


class SendLog:
    """ファイル(logs/YYYY-MM-DD.log)と画面向けのキューの両方に書く。どのスレッドから呼んでもよい"""

    def __init__(self, log_dir: Path | None):
        self.lines = queue.Queue()
        self._lock = threading.Lock()
        self._file = None
        self.path = None
        if log_dir is not None:
            log_dir.mkdir(parents=True, exist_ok=True)
            self.path = log_dir / f"{datetime.now():%Y-%m-%d}.log"
            self._file = open(self.path, "a", encoding="utf-8", buffering=1)
            self._file.write(f"\n===== 起動(作り直し版) {datetime.now():%Y-%m-%d %H:%M:%S} =====\n")

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


class Gate:
    """port は send(bytes) / close() / name を持つもの(winmm の出力、テストでは偽物)"""

    def __init__(self, log: SendLog, spec=None, is_silent=None):
        self.log = log
        self.spec = spec
        self.ch_offset = 0              # 0 / 5 / 10(電源 ON のときのボタンで ch がずれる)
        self.is_silent = is_silent      # is_silent(ch 1〜5) -> bool。音量かエクスプレッションが 0 か
        self._out = None
        self._out_lock = threading.RLock()
        self._pending = {}              # (MIDI ch0, CC) -> 値
        self._pending_lock = threading.Lock()
        self._writing = threading.Event()
        self._stop = threading.Event()
        self._thread = None

    # ---------- ポート ----------
    @property
    def output_name(self):
        return self._out.name if self._out else None

    def set_output(self, port):
        with self._out_lock:
            if self._out:
                self._out.close()
                self.log.note(f"出力を切断: {self._out.name}")
            self._out = port
        if port:
            self.log.note(f"出力に接続: {port.name}")

    # ---------- ch ----------
    def midi_ch0(self, ch):
        """画面の ch(1〜5)→ 送る MIDI チャンネル(0始まり)"""
        return ch - 1 + self.ch_offset

    def screen_ch(self, ch0):
        """MIDI チャンネル(0始まり)→ 画面の ch(1〜5)。範囲外なら None"""
        ch = ch0 - self.ch_offset + 1
        return ch if 1 <= ch <= 5 else None

    def _describe(self, msg):
        return describe(msg, self.spec, self.ch_offset)

    # ---------- 書き込み中 ----------
    @property
    def writing(self):
        return self._writing.is_set()

    def begin_write(self):
        with self._out_lock:            # 送っている途中のメッセージが終わってから切り替える
            self._writing.set()
        self.log.note("===== 書き込み開始(ほかの送信を止める) =====")

    def end_write(self):
        self._writing.clear()
        self.log.note("===== 書き込み終了 =====")

    # ---------- 判定 ----------
    @staticmethod
    def blocked_reason(msg: bytes, write_ok=False):
        """送ってはいけない理由(送ってよければ None)。書き込み中かどうかと音量0は send で見る"""
        if not msg:
            return "空のメッセージ"
        if msg[0] == 0xF0:
            kind = sysex.classify(msg)
            if kind == "data":
                return None
            if kind == "register":
                return None if write_ok else "波形の登録はカートリッジへの書き込みなので、確認画面を通した書き込みでしか送りません"
            return "このソフトが扱う形ではない SysEx なので送りません"
        if (msg[0] & 0xF0) == 0xB0 and len(msg) >= 3:
            cc = msg[1]
            if cc in NEVER_CCS:
                return f"CC#{cc} は{NEVER_CCS[cc]}"
            if cc in WRITE_CCS and not write_ok:
                return f"CC#{cc}({WRITE_CCS[cc]})はカートリッジへの書き込みなので、確認画面を通した書き込みでしか送りません"
        return None

    def _silenced(self, msg):
        if not self.is_silent or len(msg) < 3 or (msg[0] & 0xF0) != 0x90 or msg[2] == 0:
            return False
        ch = self.screen_ch(msg[0] & 0x0F)
        return ch is not None and bool(self.is_silent(ch))

    # ---------- 送信 ----------
    def send(self, msg: bytes, source=Source.EDITOR, write_ok=False, skip_silent=False) -> bool:
        """関所。送れたら True。write_ok は確認画面を通った書き込みジョブだけが使う。
        skip_silent は実機の確認モードだけが使う(音量0の ch で鳴るかを調べるため。V0)"""
        msg = bytes(msg)
        if self._writing.is_set() and not write_ok:
            self.log.write("遮断", msg, f"{self._describe(msg)} … 書き込み中なので送りません", source)
            return False
        reason = self.blocked_reason(msg, write_ok)
        if reason:
            self.log.write("遮断", msg, f"{self._describe(msg)} … {reason}", source)
            return False
        if not skip_silent and self._silenced(msg):
            self.log.write("省略", msg, f"{self._describe(msg)} … 音量0の ch なので送りません", source)
            return False
        with self._out_lock:
            if not self._out:
                self.log.write("未送信", msg, f"{self._describe(msg)} … 出力ポートにつながっていません", source)
                return False
            try:
                self._out.send(msg)
            except Exception as e:  # noqa: BLE001 — 送信の失敗はログに残して続ける
                self.log.write("失敗", msg, f"{self._describe(msg)} … {e}", source)
                return False
            self.log.write("OUT", msg, self._describe(msg), source)   # ロックの中で書く(ログの順 = 送った順)
        return True

    def send_cc(self, ch, cc, value, source=Source.EDITOR, write_ok=False):
        return self.send(bytes([0xB0 | self.midi_ch0(ch), cc, value]), source, write_ok)

    # ---------- 間引き ----------
    def queue_cc(self, ch, cc, value):
        """スライダー・音色の読み込み用。同じ ch・CC は最新の値だけが残る(最後の値が勝つ)"""
        with self._pending_lock:
            self._pending[(self.midi_ch0(ch), cc)] = int(value)

    def pending(self):
        with self._pending_lock:
            return dict(self._pending)

    def flush(self, source=Source.EDITOR):
        """間引きの列を送る。書き込み中は持ち越す"""
        if self._writing.is_set():
            return 0
        with self._pending_lock:
            items = list(self._pending.items())
            self._pending.clear()
        for (c0, cc), v in items:
            self.send(bytes([0xB0 | c0, cc, v]), source)
        return len(items)

    def start(self):
        """20ms ごとに間引きの列を送るスレッドを動かす"""
        if self._thread:
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, name="gate-flush", daemon=True)
        self._thread.start()

    def _loop(self):
        while not self._stop.wait(FLUSH_INTERVAL):
            self.flush()

    # ---------- パニック ----------
    def panic(self, write_ok=False):
        """全 ch に CC#123(オール・ノート・オフ)→ CC#120(オール・サウンド・オフ)。CC#121 は使わない"""
        with self._pending_lock:
            self._pending.clear()
        for cc in (123, 120):
            for ch in range(1, 6):
                self.send_cc(ch, cc, 0, Source.PANIC, write_ok)

    # ---------- 入力 ----------
    @staticmethod
    def accept_input(msg: bytes) -> bool:
        """入力のクロック・アクティブセンシングは捨てる(ログにも書かない)"""
        return bool(msg) and msg[0] not in INPUT_IGNORE

    def shutdown(self):
        """終了時。何も送らずにポートを閉じる"""
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=1)
            self._thread = None
        self.set_output(None)
