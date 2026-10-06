import tempfile
import threading
import unittest
from pathlib import Path

from famimimidi import cartridge as C
from famimimidi.engine import MidiEngine, SendLog
from famimimidi.spec import describe, load_spec
from famimimidi.wave import PRESETS, classify_sysex, data_sysex, plan_register, register_sysex
from tests.test_engine import FakeOut


class WaveTest(unittest.TestCase):
    def setUp(self):
        _, params = load_spec()
        self.eng = MidiEngine(SendLog(log_dir=None), params)
        self.out = FakeOut()
        self.eng.set_output(self.out)

    def tearDown(self):
        self.eng.shutdown()

    def test_presets_are_valid(self):
        for name, s in PRESETS.items():
            self.assertEqual(classify_sysex(data_sysex(s)), "data", name)

    def test_saw_matches_implementation_chart_example(self):
        self.assertEqual(data_sysex(PRESETS["のこぎり"]).hex(" ").upper(),
                         "F0 00 70 7F 00 01 02 03 04 05 06 07 08 09 0A 0B 0C 0D 0E 0F F7")

    def test_register_is_pc_minus_one(self):
        self.assertEqual(register_sysex(61), bytes([0xF0, 0, 0x71, 0x7F, 60, 0xF7]))
        self.assertEqual(register_sysex(76)[4], 75)
        with self.assertRaises(ValueError):
            register_sysex(77)
        with self.assertRaises(ValueError):
            data_sysex([16] * 16)

    def test_gate(self):
        self.assertTrue(self.eng.send(data_sysex(PRESETS["三角"]), "試聴"))      # 試聴は通る
        self.assertFalse(self.eng.send(register_sysex(61)))                        # 登録は確認経由のみ
        self.assertFalse(self.eng.send(bytes([0xF0, 0x7E, 0x7F, 0x09, 0x01, 0xF7])))   # それ以外の SysEx
        self.assertTrue(self.eng.send(register_sysex(61), write_ok=True))
        self.assertEqual(len(self.out.sent), 2)

    def test_describe(self):
        self.assertIn("PC61", describe(register_sysex(61)))
        self.assertIn("波形データ", describe(data_sysex(PRESETS["三角"])))

    def test_register_job_and_state(self):
        steps = plan_register(PRESETS["矩形 50%"], 62)
        for s in steps:
            s.wait_ms = 1
        done = threading.Event()
        C.WriteJob(self.eng, steps, lambda ok, e, r: done.set()).start()
        self.assertTrue(done.wait(5))
        self.assertEqual(self.out.sent, [data_sysex(PRESETS["矩形 50%"]), register_sysex(62)])
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "c.json"
            st = C.CartState.load(path)
            st.wave_done(62, PRESETS["矩形 50%"], "矩形")
            st.save(path)
            self.assertEqual(C.CartState.load(path).waves[62]["samples"], PRESETS["矩形 50%"])


if __name__ == "__main__":
    unittest.main()
