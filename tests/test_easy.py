import json
import unittest

from famimimidi.easy import GROUPS, choices_of, current_choice, groups_for
from famimimidi.library import EXCLUDED_CCS
from famimimidi.spec import ROOT, load_spec


class EasyTest(unittest.TestCase):
    def setUp(self):
        _, self.params = load_spec()

    def keys(self, ch):
        return {c.key for g in groups_for(ch, self.params) for c in g.controls}

    def test_channel_filtering(self):
        self.assertIn("duty", self.keys(1))
        self.assertNotIn("duty", self.keys(3))          # 三角波にデューティは無い
        self.assertNotIn("vibon", self.keys(4))         # ch4 の CC#1 はビブラートではない
        self.assertIn("tremon", self.keys(4))
        self.assertIn("noiseorder", self.keys(4))
        self.assertNotIn("noiseorder", self.keys(1))
        self.assertIn("wavemode", self.keys(5))
        self.assertNotIn("sweepon", self.keys(3))

    def test_every_cc_exists_and_is_not_dangerous(self):
        for g in GROUPS:
            for c in g.controls:
                for cc in c.needs():
                    self.assertIn(cc, self.params, c.key)
                    self.assertNotIn(cc, EXCLUDED_CCS, c.key)
                    self.assertTrue(c.help and c.label, c.key)

    def control(self, key):
        return next(c for g in GROUPS for c in g.controls if c.key == key)

    def test_vibrato_toggle(self):
        c = self.control("vibon")
        self.assertFalse(c.get({1: 0, 81: 20}))
        self.assertEqual(c.set({1: 0, 81: 20}, True), {1: 64})
        self.assertTrue(c.get({1: 64, 81: 20}))
        self.assertEqual(c.set({1: 64, 81: 70}, True), {1: 71})   # 無効区間より必ず大きく
        self.assertEqual(c.set({1: 64}, False), {1: 0})

    def test_hidden_when_unused(self):
        self.assertFalse(self.control("arptime").show({23: 0}))
        self.assertTrue(self.control("arptime").show({23: 2}))
        self.assertFalse(self.control("dec").show({79: 127}))    # サスティン最大ならディケイは効かない
        self.assertFalse(self.control("atklv").show({73: 0}))

    def test_choices(self):
        duty = self.control("duty")
        self.assertEqual(current_choice(duty, self.params, 64), 2)   # 既定値 64 = 50%
        arp = self.control("arptype")
        self.assertEqual([v for _, v in choices_of(arp, self.params)], [0, 1, 2])

    def test_presets_are_valid(self):
        with open(ROOT / "data" / "easy_presets.json", encoding="utf-8") as f:
            presets = json.load(f)["presets"]
        ids = set()
        for p in presets:
            self.assertNotIn(p["id"], ids)
            ids.add(p["id"])
            for cc, v in p["cc"]:
                self.assertIn(p["channel"], self.params[cc].channels, (p["name"], cc))
                self.assertTrue(0 <= v <= 127)
                self.assertNotIn(cc, EXCLUDED_CCS)


if __name__ == "__main__":
    unittest.main()
