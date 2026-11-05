"""仮想ファミコン(device/virtual.py と App の切り替え・書き込みの遮断)のテスト。"""
import json
import unittest
from pathlib import Path

from famimimidi2.cartridge import mirror
from famimimidi2.device import sysex, virtual
from famimimidi2.model.cartmirror import CartMirror, MacroRecord

from .test_app import AppTestBase


class VirtualOutTest(unittest.TestCase):
    def test_passes_notes_and_ccs(self):
        v = virtual.VirtualOut()
        v.send(bytes([0x90, 60, 100]))
        v.send(bytes([0xB1, 70, 16]))
        v.send(bytes([0xE0, 0, 64]))
        self.assertEqual(v.take(), [[0x90, 60, 100], [0xB1, 70, 16], [0xE0, 0, 64]])
        self.assertEqual(v.take(), [])

    def test_ignores_write_ccs(self):
        v = virtual.VirtualOut()
        for cc in (45, 47, 49, 50, 51):
            v.send(bytes([0xB0, cc, 5]))
        self.assertEqual(v.take(), [])

    def test_wave_data(self):
        v = virtual.VirtualOut()
        v.send(sysex.wave_data(list(range(16))))
        self.assertEqual(v.take(), [{"wave": list(range(16))}])

    def test_program_change_plays_saved_tone(self):
        v = virtual.VirtualOut(lookup=lambda pc: [[70, 16], [51, 3], [7, 90]] if pc == 93 else None)
        v.send(bytes([0xC1, 92]))                            # 呼び出し番号93 → 控えの CC を ch2 に(書き込み系は除く)
        self.assertEqual(v.take(), [[0xB1, 70, 16], [0xB1, 7, 90]])
        v.send(bytes([0xC0, 100]))
        self.assertEqual(v.take(), [])


class VirtualAppTest(AppTestBase):
    def test_listed_and_connects_without_port(self):
        self.assertIn(virtual.NAME, self.app.ports()["out"])
        r = self.app.connect(virtual.NAME, None)
        self.assertTrue(r["ok"])
        self.assertTrue(self.app.is_virtual)
        self.assertTrue(self.app.state()["connection"]["virtual"])
        self.assertTrue(self.app.virtual.take())              # 作業中の演奏が仮想ファミコンに送られた
        self.assertEqual(self.midi.take(), [])                # 本物のポートには何も行かない
        self.app.screen_note(60, 100, True)
        self.assertIn([0x90, 60, 100], self.app.virtual.take())

    def test_toggle_back_to_real_port(self):
        self.connect()
        self.app.toggle_virtual()
        self.assertTrue(self.app.is_virtual)
        self.app.toggle_virtual()
        self.assertFalse(self.app.is_virtual)
        self.assertEqual(self.app.gate.output_name, "USB MIDI Interface")
        self.assertEqual(self.app.prefs.out_name, "USB MIDI Interface")

    def test_cartridge_writes_and_checks_blocked(self):
        self.app.connect(virtual.NAME, None)
        before = json.dumps(self.app.cart.to_dict(), sort_keys=True)
        for kind, args in (("save", {"place": 40, "ch": 1}), ("clear", {"place": 5}), ("startup", {"ch": 1})):
            self.assertIn("仮想ファミコン", self.app.cart_plan(kind, args)["error"])
        self.assertIn("error", self.app.cart_run("anything"))
        self.assertIn("error", self.app.check_start("basic"))
        self.assertEqual(json.dumps(self.app.cart.to_dict(), sort_keys=True), before)   # 控えは変わらない

    def test_pc_params_from_mirror(self):
        self.app.cart = CartMirror()
        self.app.cart.pc_map = {pc: mirror.NEUTRAL_MACRO for pc in range(89, 129)}
        self.app.cart.pc_map[95] = 7
        self.app.cart.macros[7] = MacroRecord([[72, 6]], "ベース", True, "", "tone", "", {"kind": "triangle"})
        self.assertEqual(self.app._pc_params(95), [[72, 6]])
