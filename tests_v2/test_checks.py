"""実機の確認モード(SPEC_v2 8.2)のテスト。"""
import json
from pathlib import Path

from famimimidi2 import checks
from famimimidi2.cartridge import mirror
from famimimidi2.model.cartmirror import CartMirror, MacroRecord

from .test_app import AppTestBase


class ChecksTest(AppTestBase):
    def test_steps_are_binary_and_target_first(self):
        for c in (checks.basic_check(), checks.v0_check()):
            for s in c.steps:
                self.assertIn(s.expect, ("yes", "no", None))
                self.assertTrue(s.sends)
                self.assertIn("鳴", s.question)

    def test_run_basic_records_and_restores(self):
        self.connect()
        self.app.session.performance.set_param(2, 7, 0, self.app.spec)        # 作業中の演奏で ch2 は音量0
        st = self.app.check_start("basic")
        self.assertTrue(st["running"])
        self.assertEqual(st["n"], 8)
        self.app.scheduler.advance(1)
        first = self.midi.take()
        self.assertIn(bytes([0x90, 60, 100]), first)
        st = self.app.check_answer("yes")
        self.app.scheduler.advance(1)
        self.assertIn(bytes([0x91, 64, 100]), self.midi.take())               # 音量0の ch でも確認では鳴らす
        for _ in range(6):
            self.app.check_answer("yes")
        r = self.app.check_answer("yes")                                       # 最後は「鳴らないはず」に「鳴った」
        self.assertTrue(r["done"])
        self.assertEqual(r["unexpected"], 1)
        data = json.loads(Path(r["file"]).read_text(encoding="utf-8"))
        self.assertEqual(data["format"], "famimimidi-check-v1")
        self.assertEqual(len(data["answers"]), 8)
        self.assertFalse(data["stopped"])
        self.assertTrue(str(Path(r["file"]).parent).endswith("checks"))
        restored = self.midi.take()
        self.assertIn(bytes([0xB0, 7, 127]), restored)                         # 音量を送り直して元に戻す
        self.assertIn(bytes([0xB1, 7, 0]), restored)                           # ch2 は作業中の値(0)へ
        self.assertFalse(self.app.check_state()["running"])

    def test_stop_midway(self):
        self.connect()
        self.app.check_start("v0")
        self.app.check_answer("no")
        r = self.app.check_stop()
        self.assertTrue(r["stopped"])
        self.assertEqual(len(json.loads(Path(r["file"]).read_text(encoding="utf-8"))["answers"]), 1)

    def test_again_resends(self):
        self.connect()
        self.app.check_start("basic")
        self.app.scheduler.advance(1)
        self.midi.take()
        self.app.check_again()
        self.app.scheduler.advance(1)
        self.assertIn(bytes([0x90, 60, 100]), self.midi.take())

    def test_offset_applied(self):
        self.connect()
        self.app.set_offset(5)
        self.midi.take()
        self.app.check_start("basic")
        self.app.scheduler.advance(1)
        self.assertIn(bytes([0x95, 60, 100]), self.midi.take())

    def test_places_check(self):
        self.app.cart = CartMirror()
        self.app.cart.pc_map = {pc: mirror.NEUTRAL_MACRO for pc in range(89, 129)}
        self.app.cart.pc_map[95] = 7
        self.app.cart.macros[7] = MacroRecord([[72, 6]], "ベース", True, "", "tone", "", {"kind": "triangle"})
        lst = {c["name"]: c for c in self.app.check_list()}
        self.assertEqual(lst["places"]["steps"], 1)
        self.connect()
        self.app.check_start("places")
        self.app.scheduler.advance(1)
        sent = self.midi.take()
        self.assertIn(bytes([0xC2, 94]), sent)                                  # 三角波は ch3 で呼び出す
        self.assertTrue(any(m[0] == 0x92 for m in sent))

    def test_needs_connection(self):
        self.assertIn("error", self.app.check_start("basic"))

    def test_places_check_silent_tone_expects_no_and_restores_volume(self):
        self.app.cart = CartMirror()
        self.app.cart.pc_map = {pc: mirror.NEUTRAL_MACRO for pc in range(89, 129)}
        self.app.cart.pc_map[95] = 7
        self.app.cart.macros[7] = MacroRecord([[72, 6]], "ベース", True, "", "tone", "", {"kind": "triangle"})
        self.app.cart.pc_map[128] = 5
        self.app.cart.macros[5] = MacroRecord([[70, 64], [7, 0]], "書き込みテスト 無音", True, "", "tone", "", {"kind": "pulse"})
        c = checks.places_check(self.app.cart_view()["tiles"], {"pulse": 1, "triangle": 3, "noise": 4, "dpcm": 5, "wave": 5})
        self.assertEqual([s.expect for s in c.steps], ["yes", "no"])
        last = c.steps[-1].sends
        self.assertEqual(last[0][1], bytes([0xB0, 7, 127]))                   # 呼び出す前に音量を戻す
        self.assertEqual(last[2][1], bytes([0xC0, 127]))
