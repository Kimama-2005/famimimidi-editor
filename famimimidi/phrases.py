"""試聴フレーズ(画面から独立。tkinter 版と新しい画面の両方で使う)。送信はすべて engine.send を通す。"""
import threading

# (名前, [(開始ms, 長さms, 基準からの半音)]) 和音は同じ開始時刻に並べる(単音chなので後着優先)
PHRASES = [
    ("長い音(2秒押す)", [(0, 2000, 0)]),   # 離した後もリリース・タイムの分は鳴る
    ("短い音×4", [(i * 250, 120, 0) for i in range(4)]),
    ("上昇アルペジオ", [(i * 180, 160, n) for i, n in enumerate([0, 4, 7, 12, 16, 19, 24])]),
    ("和音(3音同時)", [(0, 1500, 0), (0, 1500, 4), (0, 1500, 7)]),
    ("レガート(つなげる)", [(i * 300, 320, n) for i, n in enumerate([0, 2, 4, 5, 7])]),
]


class PhrasePlayer:
    """1つのフレーズを別スレッドで鳴らす。stop() で即座に止めてノートオフを送る"""

    def __init__(self, engine):
        self.engine = engine
        self._stop = threading.Event()
        self._thread = None

    def play(self, ch, base, velocity, events):
        self.stop()
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, args=(ch, base, velocity, events, self._stop),
                                        daemon=True)
        self._thread.start()

    def _run(self, ch, base, vel, events, stop):
        c0 = self.engine.midi_ch0(ch)
        timeline = []
        for start, dur, off in events:
            n = max(0, min(127, base + off))
            timeline.append((start + dur, 0, bytes([0x80 | c0, n, 0])))
            timeline.append((start, 1, bytes([0x90 | c0, n, vel])))
        timeline.sort(key=lambda e: (e[0], e[1]))   # 同時刻ならノートオフを先に
        sounding = set()
        t0 = 0
        for t, _, msg in timeline:
            if stop.wait((t - t0) / 1000):
                break
            t0 = t
            self.engine.send(msg, "試聴")
            if msg[0] & 0xF0 == 0x90:
                sounding.add(msg[1])
            else:
                sounding.discard(msg[1])
        for n in sounding:   # 途中で止めたときの後始末
            self.engine.send(bytes([0x80 | c0, n, 0]), "試聴")

    def stop(self):
        self._stop.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=1)
