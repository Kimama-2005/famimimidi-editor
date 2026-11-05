"""送信の関所(SPEC_v2 6.1)のテスト。偽のポートに送って、送った/止めたを確かめる。"""
import tempfile
import unittest
from pathlib import Path

from famimimidi2.device import sysex
from famimimidi2.device.gate import Gate, SendLog, Source
from famimimidi2.music.spec import load_spec


class FakePort:
    name = "偽のポート"

    def __init__(self):
        self.sent = []
        self.closed = False

    def send(self, msg):
        self.sent.append(bytes(msg))

    def close(self):
        self.closed = True


def cc(ch, n, v):
    return bytes([0xB0 | (ch - 1), n, v])


class GateTest(unittest.TestCase):
    def setUp(self):
        self.silent = set()
        self.log = SendLog(None)
        self.gate = Gate(self.log, load_spec(), is_silent=lambda ch: ch in self.silent)
        self.port = FakePort()
        self.gate.set_output(self.port)

    def lines(self):
        out = []
        while not self.log.lines.empty():
            out.append(self.log.lines.get())
        return out

    def test_plain_cc_is_sent_and_logged(self):
        self.assertTrue(self.gate.send(cc(1, 70, 48), Source.EDITOR))
        self.assertEqual(self.port.sent, [cc(1, 70, 48)])
        last = self.lines()[-1]
        self.assertIn("OUT", last)
        self.assertIn("B0 46 30", last)
        self.assertIn("デューティ比", last)
        self.assertIn("[エディタ]", last)

    def test_write_ccs_need_write_ok(self):
        for n in (45, 50, 51):
            self.assertFalse(self.gate.send(cc(1, n, 3)))
        self.assertEqual(self.port.sent, [])
        self.assertTrue(all("遮断" in line for line in self.lines()[-3:]))
        for n in (45, 50, 51):
            self.assertTrue(self.gate.send(cc(1, n, 3), Source.WRITE, write_ok=True))
        self.assertEqual(len(self.port.sent), 3)

    def test_cc121_is_never_sent(self):
        self.assertFalse(self.gate.send(cc(1, 121, 0)))
        self.assertFalse(self.gate.send(cc(1, 121, 0), Source.WRITE, write_ok=True))
        self.assertEqual(self.port.sent, [])

    def test_sysex(self):
        data = sysex.wave_data([0] * 8 + [15] * 8)
        reg = sysex.wave_register(61)
        self.assertTrue(self.gate.send(data, Source.AUDITION))
        self.assertFalse(self.gate.send(reg))
        self.assertTrue(self.gate.send(reg, Source.WRITE, write_ok=True))
        self.assertFalse(self.gate.send(bytes([0xF0, 0x41, 0x10, 0xF7]), Source.WRITE, write_ok=True))
        self.assertEqual(self.port.sent, [data, reg])

    def test_writing_blocks_everything_else(self):
        self.gate.begin_write()
        self.assertFalse(self.gate.send(cc(1, 7, 100)))
        self.assertFalse(self.gate.send(bytes([0x90, 60, 100]), Source.THRU))
        self.assertTrue(self.gate.send(cc(1, 45, 11), Source.WRITE, write_ok=True))
        self.gate.end_write()
        self.assertTrue(self.gate.send(cc(1, 7, 100)))
        self.assertEqual(self.port.sent, [cc(1, 45, 11), cc(1, 7, 100)])

    def test_note_on_to_silent_ch_is_skipped(self):
        self.silent.add(2)
        self.assertFalse(self.gate.send(bytes([0x91, 60, 127]), Source.THRU))
        self.assertIn("省略", self.lines()[-1])
        self.assertTrue(self.gate.send(bytes([0x91, 60, 0])))       # ノートオフ(強さ0)は送る
        self.assertTrue(self.gate.send(bytes([0x81, 60, 0])))
        self.assertTrue(self.gate.send(bytes([0x90, 60, 127])))     # ch1 は音量あり
        self.assertEqual(len(self.port.sent), 3)

    def test_silent_check_uses_screen_ch_with_offset(self):
        self.gate.ch_offset = 5
        self.silent.add(1)
        self.assertFalse(self.gate.send(bytes([0x95, 60, 100])))     # MIDI ch6 = 画面の ch1
        self.assertTrue(self.gate.send(bytes([0x90, 60, 100])))      # MIDI ch1 は範囲外(ずれ5のとき)
        self.assertEqual(self.gate.midi_ch0(1), 5)

    def test_throttle_keeps_latest_value(self):
        for v in range(0, 128, 8):
            self.gate.queue_cc(1, 7, v)
        self.gate.queue_cc(2, 7, 50)
        self.assertEqual(self.gate.flush(), 2)
        self.assertEqual(sorted(self.port.sent), sorted([cc(1, 7, 120), cc(2, 7, 50)]))

    def test_throttle_held_while_writing(self):
        self.gate.queue_cc(1, 70, 16)
        self.gate.begin_write()
        self.assertEqual(self.gate.flush(), 0)
        self.assertEqual(self.port.sent, [])
        self.gate.end_write()
        self.assertEqual(self.gate.flush(), 1)
        self.assertEqual(self.port.sent, [cc(1, 70, 16)])

    def test_panic_order(self):
        self.gate.queue_cc(1, 7, 3)
        self.gate.panic()
        self.assertEqual(self.port.sent, [cc(ch, 123, 0) for ch in range(1, 6)] + [cc(ch, 120, 0) for ch in range(1, 6)])
        self.assertEqual(self.gate.pending(), {})

    def test_not_connected(self):
        self.gate.set_output(None)
        self.assertTrue(self.port.closed)
        self.assertFalse(self.gate.send(cc(1, 7, 1)))
        self.assertIn("未送信", self.lines()[-1])

    def test_input_filter(self):
        self.assertFalse(Gate.accept_input(bytes([0xF8])))
        self.assertFalse(Gate.accept_input(bytes([0xFE])))
        self.assertTrue(Gate.accept_input(bytes([0x90, 60, 1])))

    def test_log_file(self):
        with tempfile.TemporaryDirectory() as d:
            log = SendLog(Path(d))
            g = Gate(log, load_spec())
            g.set_output(FakePort())
            g.send(cc(1, 7, 0), Source.CHORD)
            g.send(cc(1, 50, 1))
            log.close()
            text = log.path.read_text(encoding="utf-8")
            self.assertIn("B0 07 00", text)
            self.assertIn("[コード]", text)
            self.assertIn("遮断", text)


if __name__ == "__main__":
    unittest.main()
