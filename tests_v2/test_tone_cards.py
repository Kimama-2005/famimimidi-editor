"""音色をつくる画面(SPEC_v2 7.3)のテスト: カードの組み立て・表示の判定・値の変換と、アプリでの送信。"""
import json
import unittest

from famimimidi2.music import tonecards
from famimimidi2.music.spec import load_spec

from .test_app import AppTestBase

SPEC = load_spec()


def keys(kind):
    return [c["key"] for c in tonecards.describe(kind, SPEC)]


class CardsTest(unittest.TestCase):
    def test_cards_per_kind(self):
        self.assertEqual(keys("pulse"), ["duty", "env", "basic", "vib", "trem", "arp", "porta", "sweep", "assign"])
        self.assertEqual(keys("triangle"), ["env", "basic", "vib", "arp", "porta", "assign"])
        self.assertEqual(keys("noise"), ["env", "basic", "noise", "trem", "arp", "assign"])
        self.assertEqual(keys("dpcm_wave"), ["wave", "env", "basic", "arp"])

    def test_no_performance_ccs_in_cards(self):
        """ベンド幅(#82)・#20・#2・#64・#84 は音色のカードに出さない"""
        for kind in ("pulse", "triangle", "noise", "dpcm_wave"):
            for card in tonecards.cards_for(kind, SPEC):
                for c in ([card.switch] if card.switch else []) + card.controls:
                    for cc in c.needs():
                        self.assertNotIn(cc, (82, 20, 2, 64, 84, 45, 50, 51, 121), (kind, c.key))

    def test_every_tone_cc_has_a_place(self):
        """今の版の詳細表示にしかなかった項目も、どこかのカードに行き先がある"""
        for kind in ("pulse", "triangle", "noise", "dpcm_wave"):
            placed = set()
            for card in tonecards.cards_for(kind, SPEC):
                for c in ([card.switch] if card.switch else []) + card.controls:
                    placed |= set(c.needs())
            missing = set(SPEC.tone_ccs(kind)) - placed
            self.assertEqual(missing, set(), kind)

    def test_json(self):
        for kind in ("pulse", "triangle", "noise", "dpcm_wave"):
            json.dumps(tonecards.describe(kind, SPEC), ensure_ascii=False)
            json.dumps(tonecards.state(kind, SPEC.tone_defaults(kind), SPEC), ensure_ascii=False)

    def test_state_shows_and_switches(self):
        v = SPEC.tone_defaults("pulse")
        st = tonecards.state("pulse", v, SPEC)
        self.assertFalse(st["cards"]["vib"]["on"])
        self.assertFalse(st["controls"]["dec"]["show"])         # サステイン最大ではディケイは効かない
        self.assertEqual(st["controls"]["duty"]["index"], 2)    # 既定 64 = 50%
        v[79] = 0
        v[1] = 80
        st = tonecards.state("pulse", v, SPEC)
        self.assertTrue(st["controls"]["dec"]["show"])
        self.assertTrue(st["cards"]["vib"]["on"])

    def test_updates(self):
        v = SPEC.tone_defaults("pulse")
        self.assertEqual(tonecards.updates_for("duty", "index", 0, v, SPEC), {70: 16})
        self.assertEqual(tonecards.updates_for("vibon", "toggle", True, v, SPEC), {1: 64})
        self.assertEqual(tonecards.updates_for("vibon", "toggle", False, v, SPEC), {1: 0})
        self.assertEqual(tonecards.updates_for("sus", "index", 15, v, SPEC), {79: 124})
        self.assertEqual(tonecards.updates_for("vibrate", "value", 99, v, SPEC), {76: 20})      # 範囲に収める
        self.assertEqual(tonecards.updates_for("hold", "value", 30, v, SPEC), {83: 30, 21: 0})  # 自動は OFF
        self.assertEqual(tonecards.updates_for("arpon", "toggle", True, v, SPEC), {23: 1})
        w = SPEC.tone_defaults("dpcm_wave")
        self.assertEqual(tonecards.updates_for("wavemode", "index", 0, w, SPEC), {18: 127})
        self.assertEqual(tonecards.state("dpcm_wave", w, SPEC)["controls"]["wavemode"]["index"], 1)   # 既定は DPCM
        with self.assertRaises(ValueError):
            tonecards.updates_for("bend", "value", 12, v, SPEC)

    def test_env_updates_filter(self):
        self.assertEqual(tonecards.env_updates({"73": 10, "82": 5, 79: 200}), {73: 10, 79: 127})


class ToneAppTest(AppTestBase):
    def test_tone_set_sends_and_links(self):
        self.connect()
        self.app.toggle_link12()
        self.midi.take()
        r = self.app.tone_set(1, "duty", "index", 0)
        json.dumps(r, ensure_ascii=False)
        self.assertEqual(r["tone"]["controls"]["duty"]["index"], 0)
        self.app.gate.flush()
        sent = self.midi.take()
        self.assertIn(bytes([0xB0, 70, 16]), sent)
        self.assertIn(bytes([0xB1, 70, 16]), sent)               # 紐付け中は ch2 にも
        self.assertEqual(self.app.session.performance.tone(2).value(70, self.app.spec), 16)
        self.assertTrue(r["state"]["session"]["dirty"])

    def test_slider_is_throttled(self):
        self.connect()
        for v in range(0, 100, 5):
            self.app.tone_set(3, "rel", "value", v)
        self.app.gate.flush()
        self.assertEqual([m for m in self.midi.take() if m[1] == 72], [bytes([0xB2, 72, 95])])

    def test_env(self):
        self.connect()
        r = self.app.tone_env(1, {"73": 20, "79": 60, "75": 30})
        self.assertEqual(r["tone"]["env"]["73"], 20)
        self.app.gate.flush()
        self.assertIn(bytes([0xB0, 73, 20]), self.midi.take())

    def test_wave(self):
        self.connect()
        r = self.app.set_wave([15] * 8 + [0] * 8)
        self.assertEqual(r["tone"]["wave"], [15] * 8 + [0] * 8)
        self.assertEqual(self.midi.take()[0][:4], bytes([0xF0, 0x00, 0x70, 0x7F]))
        with self.assertRaises(ValueError):
            self.app.set_wave([16] * 16)

    def test_presets_in_side_list_and_put(self):
        self.connect()
        side = self.app.side_list(1)
        presets = [i for i in side["items"] if i.get("preset")]
        self.assertTrue(presets)
        self.assertTrue(any(i.get("header") for i in side["items"]))
        self.assertFalse(any(i.get("preset") for i in self.app.side_list(3)["items"] if i.get("id", "").endswith("e_pico")))
        pid = presets[0]["id"]
        self.midi.take()
        st = self.app.put_tone(1, pid)
        self.assertNotIn("error", st)
        self.assertTrue(self.midi.take())
        self.assertIn("error", self.app.put_tone(3, pid))         # パルスの見本は三角波に入らない
        self.assertIn("error", self.app.delete_tone(pid))
        self.assertIn("error", self.app.rename_tone(pid, "x"))
        self.assertIn("error", self.app.overwrite_tone(1, pid))

    def test_tone_view_json(self):
        for ch in range(1, 6):
            json.dumps(self.app.tone_view(ch), ensure_ascii=False)


if __name__ == "__main__":
    unittest.main()
