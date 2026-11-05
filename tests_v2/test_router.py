"""鍵盤の振り分け(SPEC_v2 6.4)のテスト。"""
import unittest

from famimimidi2.model.performance import Controls, KeyboardMap
from famimimidi2.performance.router import NOT_USED, Router


def on(n, v=100, ch0=0):
    return bytes([0x90 | ch0, n, v])


def off(n, ch0=0):
    return bytes([0x80 | ch0, n, 0])


class RouterTest(unittest.TestCase):
    def setUp(self):
        self.r = Router()

    def test_tone_place_plays_only_that_ch(self):
        self.r.configure(place=3, keyboard=KeyboardMap.template("bass_poly"))
        out, _ = self.r.route(on(72))
        self.assertEqual(out, [bytes([0x92, 72, 100])])
        out, _ = self.r.route(bytes([0xE0, 0, 80]))
        self.assertEqual(out, [bytes([0xE2, 0, 80])])
        out, _ = self.r.route(bytes([0xB0, 1, 50]))
        self.assertEqual(out, [bytes([0xB2, 1, 50])])          # モジュレーションはそのまま

    def test_note_off_goes_where_note_on_went(self):
        self.r.configure(place=1)
        self.r.route(on(60))
        offs = self.r.configure(place=4)                       # 押したまま場所を変えた
        self.assertEqual(offs, [bytes([0x80, 60, 0])])
        out, _ = self.r.route(off(60))
        self.assertEqual(out, [])                              # もう止めたので送らない

    def test_map_split_and_shift(self):
        k = KeyboardMap.template("bass_melody")
        k.parts[3].shift = -12
        self.r.configure(place="play", keyboard=k)
        self.assertEqual(self.r.route(on(48))[0], [bytes([0x92, 36, 100])])
        self.assertEqual(self.r.route(on(72))[0], [bytes([0x90, 72, 100])])
        self.assertEqual(self.r.route(off(48))[0], [bytes([0x82, 36, 0])])

    def test_layer_sends_both(self):
        self.r.configure(place="play", keyboard=KeyboardMap.template("unison"))
        self.assertEqual(sorted(self.r.route(on(60))[0]), sorted([bytes([0x90, 60, 100]), bytes([0x91, 60, 100])]))

    def test_poly_allocates_and_steals_oldest(self):
        self.r.configure(place="play", keyboard=KeyboardMap.template("poly"))
        a, _ = self.r.route(on(60))
        b, _ = self.r.route(on(64))
        self.assertEqual({a[0][0], b[0][0]}, {0x90, 0x91})
        c, _ = self.r.route(on(67))                            # 3音目: 一番古い 60 を止めてその ch で
        self.assertEqual(c[0], bytes([0x80 | (a[0][0] & 0x0F), 60, 0]))
        self.assertEqual(c[1][0], a[0][0])
        self.assertEqual(self.r.route(off(60))[0], [])          # 止めた音のノートオフは捨てる

    def test_controls_in_play(self):
        k = KeyboardMap.template("bass_poly")
        c = Controls(pedal_to=[1, 2, 3], bend_to=[1, 2], mod_to=[1, 2, 3], mod_use="duty")
        self.r.configure(place="play", keyboard=k, controls=c)
        self.assertEqual(self.r.route(bytes([0xB0, 64, 127]))[0], [bytes([0xB0 | i, 64, 127]) for i in (0, 1, 2)])
        self.assertEqual(self.r.route(bytes([0xE0, 0, 90]))[0], [bytes([0xE0, 0, 90]), bytes([0xE1, 0, 90])])
        self.assertEqual(self.r.route(bytes([0xB0, 1, 99]))[0], [bytes([0xB0, 70, 99]), bytes([0xB1, 70, 99])])   # デューティは ch1・2 だけ
        c.mod_use = "expression"
        self.r.configure(controls=c)
        self.assertEqual(len(self.r.route(bytes([0xB0, 1, 99]))[0]), 3)
        c.pedal_use = "off"
        self.r.configure(controls=c)
        out, reason = self.r.route(bytes([0xB0, 64, 127]))
        self.assertEqual(out, [])
        self.assertIn("使わない", reason)

    def test_other_messages_are_not_used(self):
        for msg in (bytes([0xC0, 5]), bytes([0xB0, 7, 0]), bytes([0xB0, 45, 1]), bytes([0xF8])):
            out, reason = self.r.route(msg)
            self.assertEqual(out, [])
            self.assertEqual(reason, NOT_USED)

    def test_offset(self):
        r = Router(lambda ch: ch - 1 + 5)
        r.configure(place=2)
        self.assertEqual(r.route(on(60))[0], [bytes([0x96, 60, 100])])


if __name__ == "__main__":
    unittest.main()


class FollowTest(unittest.TestCase):
    """1〜5 のタブでも外部の鍵盤は割り当て表どおり(follow)。画面の鍵盤(solo)はタブの ch だけ"""

    def setUp(self):
        self.r = Router()
        self.r.configure(place=3, keyboard=KeyboardMap.template("bass_melody"), follow=True)

    def test_external_keyboard_follows_map(self):
        out, _ = self.r.route(on(72))                          # メロディの鍵域 → ch1
        self.assertEqual(out, [bytes([0x90, 72, 100])])

    def test_screen_keyboard_plays_tab_ch(self):
        out, _ = self.r.route(on(72), solo=True)
        self.assertEqual(out, [bytes([0x92, 72, 100])])
        out, _ = self.r.route(off(72), solo=True)
        self.assertEqual(out, [bytes([0x82, 72, 0])])
        out, _ = self.r.route(on(74))                          # solo は1回ごと。次の外部の鍵盤は割り当て表どおり
        self.assertEqual(out, [bytes([0x90, 74, 100])])

    def test_switching_releases_notes(self):
        self.r.route(on(72))
        self.assertEqual(self.r.configure(follow=False), [bytes([0x80, 72, 0])])
        out, _ = self.r.route(on(72))
        self.assertEqual(out, [bytes([0x92, 72, 100])])
