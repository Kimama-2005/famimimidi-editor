"""実機なしで確かめられる部分のテスト。  python -m unittest discover tests"""
import time
import unittest

from famimimidi.engine import MidiEngine, SendLog
from famimimidi.spec import editable_params, load_spec


class FakeOut:
    name = "fake"

    def __init__(self):
        self.sent = []

    def send(self, msg):
        self.sent.append(bytes(msg))

    def close(self):
        pass


class EngineTest(unittest.TestCase):
    def setUp(self):
        _, self.params = load_spec()
        self.log = SendLog(log_dir=None)
        self.eng = MidiEngine(self.log, self.params)
        self.out = FakeOut()
        self.eng.set_output(self.out)

    def tearDown(self):
        self.eng.shutdown()

    def logged(self):
        lines = []
        while not self.log.lines.empty():
            lines.append(self.log.lines.get())
        return lines

    def test_write_ccs_are_blocked(self):
        for cc in (45, 50, 51):
            self.assertFalse(self.eng.send(bytes([0xB0, cc, 1])))
        self.assertFalse(self.eng.send(bytes([0xF0, 0x00, 0x71, 0x7F, 60, 0xF7])))
        self.assertEqual(self.out.sent, [])
        self.assertTrue(any("遮断" in l for l in self.logged()))

    def test_write_ccs_blocked_on_thru_too(self):
        self.eng.handle_input(bytes([0xB0, 51, 92]))
        self.eng.handle_input(bytes([0x90, 60, 100]))
        self.assertEqual(self.out.sent, [bytes([0x90, 60, 100])])

    def test_thru_ignores_active_sensing_and_clock(self):
        self.eng.handle_input(b"\xFE")
        self.eng.handle_input(b"\xF8")
        self.assertEqual(self.out.sent, [])

    def test_thru_remap_to_tab_channel_keeps_note_off_channel(self):
        self.eng.thru_channel = 2
        self.eng.handle_input(bytes([0x90, 60, 100]))     # 鍵盤は ch1 で送ってくる
        self.eng.thru_channel = 4                          # 押したままタブを変えた
        self.eng.handle_input(bytes([0x80, 60, 0]))
        self.eng.handle_input(bytes([0xC0, 96]))
        self.assertEqual(self.out.sent, [bytes([0x91, 60, 100]), bytes([0x81, 60, 0]), bytes([0xC3, 96])])

    def test_thru_off_does_not_send(self):
        self.eng.thru_enabled = False
        self.eng.handle_input(bytes([0x90, 60, 100]))
        self.assertEqual(self.out.sent, [])

    def test_cc_coalescing_sends_latest_only(self):
        for v in range(0, 100):
            self.eng.set_cc(1, 70, v)
        time.sleep(0.1)
        self.assertEqual(self.out.sent, [bytes([0xB0, 70, 99])])

    def test_channel_offset(self):
        self.eng.ch_offset = 5
        self.eng.send_cc_now(1, 7, 100)
        self.assertEqual(self.out.sent, [bytes([0xB5, 7, 100])])

    def test_panic_uses_123_then_120_never_121(self):
        self.eng.panic()
        ccs = [m[1] for m in self.out.sent]
        self.assertEqual(ccs, [123] * 5 + [120] * 5)
        self.assertEqual([m[0] for m in self.out.sent[:5]], [0xB0, 0xB1, 0xB2, 0xB3, 0xB4])

    def test_every_send_is_logged_with_bytes(self):
        self.eng.send_cc_now(1, 70, 48)
        lines = [l for l in self.logged() if "OUT" in l]
        self.assertEqual(len(lines), 1)
        self.assertIn("B0 46 30", lines[0])
        self.assertIn("デューティ比", lines[0])


class SpecTest(unittest.TestCase):
    def setUp(self):
        _, self.params = load_spec()

    def test_step_centers(self):
        duty = self.params[70]
        self.assertEqual([duty.step_value(k) for k in range(4)], [16, 48, 80, 112])
        self.assertEqual(duty.step_index(64), 2)   # 既定値 64 = 50%
        sus = self.params[79]
        self.assertEqual([sus.step_value(k) for k in range(16)][:3], [4, 12, 20])
        self.assertEqual(sus.step_value(15), 124)

    def test_editor_hides_write_and_macro_ccs(self):
        for ch in range(1, 6):
            ccs = {p.cc for p in editable_params(self.params, ch)}
            self.assertFalse(ccs & {45, 46, 47, 48, 49, 50, 51, 120, 121, 123})

    def test_duty_only_on_pulse_channels(self):
        self.assertIn(70, {p.cc for p in editable_params(self.params, 1)})
        self.assertNotIn(70, {p.cc for p in editable_params(self.params, 3)})


if __name__ == "__main__":
    unittest.main()
