"""演奏セットの割り当て表・ひな形・ペダル・レバー(4段目)のアプリでのテスト。"""
import json

from .test_app import AppTestBase


class PlayTest(AppTestBase):
    def test_template_bass_poly_links_and_routes(self):
        self.connect()
        st = self.app.apply_template("bass_poly")
        json.dumps(st, ensure_ascii=False)
        s = st["session"]
        self.assertTrue(s["link12"])
        self.assertEqual(s["keyboard"]["pair"], "poly")
        self.assertEqual(s["controls"]["bend"]["to"], [1, 2])
        self.midi.take()
        self.app.handle_input(bytes([0x90, 40, 100]))
        self.app.handle_input(bytes([0x90, 72, 100]))
        self.app.handle_input(bytes([0x90, 76, 100]))
        sent = self.midi.take()
        self.assertEqual(sent[0], bytes([0x92, 40, 100]))                      # 下はベース(ch3)
        self.assertEqual({sent[1][0], sent[2][0]}, {0x90, 0x91})               # 上はポリ

    def test_set_keyboard_normalizes_and_resets_controls(self):
        st = self.app.set_keyboard({"pair": "off", "parts": {
            "1": {"on": True, "lo": 72, "hi": 127, "shift": 0},
            "4": {"on": True, "lo": 0, "hi": 47, "shift": 12},
            "3": {"on": True, "lo": 48, "hi": 71, "shift": -12}}})
        s = st["session"]
        self.assertEqual(s["controls"]["bend"]["to"], [1])
        self.assertEqual(s["controls"]["pedal"]["to"], [1, 3, 4])
        self.assertEqual(st["keyboard"]["zones"]["40"], [4])
        self.assertTrue(st["session"]["dirty"])

    def test_controls_send_bend_range_to_ch1_3_only(self):
        self.connect()
        self.app.set_controls({"pedal": {"to": [1], "use": "hold"}, "bend": {"to": [1, 3, 4], "range": 12},
                               "mod": {"to": [1], "use": "vibrato"}})
        sent = self.midi.take()
        self.assertIn(bytes([0xB0, 82, 12]), sent)
        self.assertIn(bytes([0xB2, 82, 12]), sent)
        self.assertFalse(any(m[0] == 0xB3 and m[1] == 82 for m in sent))
        self.app.handle_input(bytes([0xE0, 0, 100]))
        self.assertEqual(self.midi.take(), [bytes([0xE0, 0, 100]), bytes([0xE2, 0, 100]), bytes([0xE3, 0, 100])])

    def test_mod_lever_duty(self):
        self.connect()
        self.app.apply_template("unison")
        c = self.app.session.performance.controls.to_dict()
        c["mod"]["use"] = "duty"
        self.app.set_controls(c)
        self.midi.take()
        self.app.handle_input(bytes([0xB0, 1, 30]))
        self.assertEqual(self.midi.take(), [bytes([0xB0, 70, 30]), bytes([0xB1, 70, 30])])
        self.app.set_place(1)
        self.midi.take()
        self.app.handle_input(bytes([0xB0, 1, 30]))                             # 音色づくりではそのまま
        self.assertEqual(self.midi.take(), [bytes([0xB0, 1, 30])])

    def test_bad_template(self):
        self.assertIn("error", self.app.apply_template("piano"))

    def test_saved_with_performance(self):
        self.app.apply_template("bass_melody")
        pid = self.app.save_performance_new("ベースとメロディ")["selected"]
        self.app.apply_template("ch1")
        self.app.load_performance(pid)
        self.assertEqual(self.app.session.performance.keyboard.parts[3].on, True)
        self.assertEqual(self.app.router.keyboard.parts[3].on, True)          # 振り分けにも入る


class KbFollowAppTest(AppTestBase):
    def test_follow_in_tone_tab_and_saved_in_prefs(self):
        self.connect()
        self.app.apply_template("bass_melody")
        self.app.set_place(3)
        st = self.app.set_kb_follow(True)
        self.assertTrue(st["prefs"]["kb_follow"])
        self.assertTrue(self.app.store.load_prefs().kb_follow)                # 設定として残る
        self.midi.take()
        self.app.handle_input(bytes([0x90, 72, 100]))
        self.assertIn(bytes([0x90, 72, 100]), self.midi.take())               # 3 のタブでも ch1(メロディ)へ
        self.app.handle_input(bytes([0x80, 72, 0]))
        self.app.screen_note(72, 100, True)
        self.assertIn(bytes([0x92, 72, 100]), self.midi.take())               # 画面の鍵盤は ch3 だけ

    def test_chord_mode_works_in_tone_tab_when_following(self):
        self.connect()
        self.app.set_chord_active(True)
        self.app.set_place(1)
        self.assertFalse(self.app.chord.active)                                 # ふだんは 1〜5 のタブでコードは効かない
        self.app.set_kb_follow(True)
        self.assertTrue(self.app.chord.active)
        self.app.set_kb_follow(False)
        self.assertFalse(self.app.chord.active)
