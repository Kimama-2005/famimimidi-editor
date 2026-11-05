"""時間で動くもの(コードのずらし・つなぎの猶予)を動かす1本のスケジューラ(SPEC_v2 4.1)。

後から別の指示が来たら、予約を番号で取り消す(呼ばれる側が番号を見て、古ければ何もしない)。
テストでは ManualScheduler で時間を進めて確かめる。
"""
import heapq
import threading
import time


class Scheduler:
    """delay 秒後に fn() を呼ぶ(1本のスレッドで順番に)"""

    def __init__(self):
        self._q, self._n = [], 0
        self._cv = threading.Condition()
        self._stop = False
        threading.Thread(target=self._run, name="scheduler", daemon=True).start()

    def at(self, delay, fn):
        with self._cv:
            self._n += 1
            heapq.heappush(self._q, (time.monotonic() + max(0.0, delay), self._n, fn))
            self._cv.notify()

    def stop(self):
        with self._cv:
            self._stop = True
            self._cv.notify()

    def _run(self):
        while True:
            with self._cv:
                while not self._stop and (not self._q or self._q[0][0] > time.monotonic()):
                    self._cv.wait(None if not self._q else max(0.0, self._q[0][0] - time.monotonic()))
                if self._stop:
                    return
                _, _, fn = heapq.heappop(self._q)
            try:
                fn()
            except Exception:  # noqa: BLE001 — 1つの失敗で止めない(送信の失敗は関所がログに残す)
                pass


class ManualScheduler:
    """テスト用: advance(秒) で時間を進めた分だけ呼ぶ"""

    def __init__(self):
        self.now, self._q, self._n = 0.0, [], 0

    def at(self, delay, fn):
        self._n += 1
        heapq.heappush(self._q, (self.now + max(0.0, delay), self._n, fn))

    def advance(self, sec):
        end = self.now + sec
        while self._q and self._q[0][0] <= end:
            t, _, fn = heapq.heappop(self._q)
            self.now = t
            fn()
        self.now = end

    def stop(self):
        self._q.clear()
