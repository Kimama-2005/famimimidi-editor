"""書き込みの実行(SPEC_v2 6.6.1-3)。確認画面を通った計画だけを、番号札で実行する。

- 前後にパニック。書き込み中は関所がほかの送信を止める(記録中に届いた CC はマクロに入ってしまう)
- 途中で止める手段は用意しない(記録を途中で止めると中身が不明になる)。送れなかったら記録モードだけは止めようとする
- 予定時間+20秒を過ぎたら「応答がない」(overdue)。画面は閉じることを許す
- 結果は控えに反映して保存する(成功: 書いた中身 / 失敗: 影響したかもしれない所を不明に)
"""
import threading
import time

from ..device.gate import Gate, Source
from . import plans

OVERDUE_MARGIN = 20.0


class WriteJob:
    def __init__(self, gate: Gate, plan: plans.WritePlan, on_done, on_progress=None, sleep=time.sleep):
        self.gate, self.plan, self.on_done, self.on_progress, self._sleep = gate, plan, on_done, on_progress, sleep
        self.deadline = time.monotonic() + plan.seconds + OVERDUE_MARGIN
        self.done = False
        self.ok = None

    def start(self):
        threading.Thread(target=self.run, name="write", daemon=True).start()

    @property
    def overdue(self):
        return not self.done and time.monotonic() > self.deadline

    def run(self):
        ok, error, recorded = True, None, False
        self.gate.panic()
        self.gate.begin_write()
        try:
            steps = self.plan.steps
            for i, s in enumerate(steps):
                if s.wait_ms:
                    self._sleep(s.wait_ms / 1000)
                if not s.msg:
                    continue
                if s.role == "record_start":
                    recorded = True
                if s.role == "record_stop":
                    recorded = False
                if not self.gate.send(s.msg, Source.WRITE, write_ok=True):
                    ok, error = False, f"送信できませんでした: {s.text}(送信ログを見てください)"
                    if recorded:                        # 記録モードのまま残さないよう、停止だけは試みる
                        self.gate.send(bytes([0xB0 | (s.msg[0] & 0x0F), 45, 0]), Source.WRITE, write_ok=True)
                    break
                if self.on_progress:
                    self.on_progress(i + 1, len(steps), s.text)
        finally:
            self.gate.end_write()
            self.gate.panic()
        self.done, self.ok = True, ok
        self.on_done(ok, error)
