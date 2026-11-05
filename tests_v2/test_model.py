"""データ構造(音色・演奏セット・作業中の演奏・曲・設定)のテスト。"""
import unittest

from famimimidi2.model.chordbook import ChordBook
from famimimidi2.model.library import Library
from famimimidi2.model.performance import (ChordSettings, Controls, KeyboardMap, Performance)
from famimimidi2.model.prefs import Prefs
from famimimidi2.model.session import Session
from famimimidi2.model.tone import Tone, clean_params, load_messages
from famimimidi2.music.spec import load_spec

SPEC = load_spec()


class ToneTest(unittest.TestCase):
    def test_clean_params(self):
        pairs = [[70, 48], [82, 7], [20, 127], [2, 10], [64, 127], [84, 1], [45, 3], [121, 0],
                 [7, 127],            # 既定値と同じ → 外す
                 [18, 127],           # ch5 だけの項目 → パルスには入らない
                 [79, 0], [70, 16]]   # 同じ CC は位置が最初、値は後
        out, removed = clean_params(pairs, "pulse", SPEC)
        self.assertEqual(out, [[70, 16], [79, 0]])
        self.assertTrue({82, 20, 2, 64, 84, 45, 121, 18} <= set(removed))

    def test_values_and_load_messages(self):
        t = Tone("t", "dpcm_wave", [[18, 127], [7, 100]], wave=[1] * 16)
        vals = t.values(SPEC)
        self.assertEqual(vals[7], 100)
        self.assertEqual(vals[18], 127)
        self.assertEqual(vals[11], 127)
        self.assertNotIn(82, vals)
        self.assertNotIn(45, vals)
        msgs = load_messages(vals)
        self.assertEqual(msgs[0][0], 18)          # 波形メモリモードを先に
        self.assertEqual(len(msgs), len(SPEC.tone_ccs("dpcm_wave")))

    def test_set_param(self):
        t = Tone("t", "pulse")
        t.set_param(70, 16, SPEC)
        t.set_param(75, 40, SPEC)
        t.set_param(70, 32, SPEC)
        self.assertEqual(t.params, [[70, 32], [75, 40]])
        t.set_param(70, SPEC.default(70), SPEC)
        self.assertEqual(t.params, [[75, 40]])
        with self.assertRaises(ValueError):
            t.set_param(82, 12, SPEC)             # ベンド幅は演奏セットのもの

    def test_wave_only_for_ch5(self):
        with self.assertRaises(ValueError):
            Tone("t", "pulse", wave=[0] * 16)
        with self.assertRaises(ValueError):
            Tone("t", "dpcm_wave", wave=[0] * 15)
        with self.assertRaises(ValueError):
            Tone("t", "organ")

    def test_macro_params_order_and_capacity(self):
        params = [[3, 1], [13, 127], [12, 32], [70, 16], [5, 40], [23, 2], [92, 30], [77, 9], [86, 40],
                  [1, 80], [73, 10], [72, 20], [79, 64]]
        t = Tone("t", "pulse", params)
        picked, rest = t.macro_params(SPEC)
        self.assertEqual(len(picked), 10)
        self.assertEqual([c for c, _ in picked], [70, 23, 79, 72, 1, 73, 12, 92, 77, 86])
        self.assertEqual([c for c, _ in rest], [5, 13, 3])

    def test_round_trip(self):
        t = Tone("ピアノ", "pulse", [[70, 48]], category="lead", id="piano_abc123")
        self.assertEqual(Tone.from_dict(t.to_dict(), SPEC), t)


class PerformanceTest(unittest.TestCase):
    def setUp(self):
        self.p = Performance(name="テスト")
        self.lead = Tone("リード", "pulse", [[70, 16]], id="lead_1")
        self.soft = Tone("やわらか", "pulse", [[70, 80], [75, 30]], id="soft_1")

    def test_always_five_slots_and_kind_check(self):
        self.assertEqual(sorted(self.p.slots), [1, 2, 3, 4, 5])
        with self.assertRaises(ValueError):
            self.p.put_tone(3, self.lead)
        with self.assertRaises(ValueError):
            Performance.from_dict({"slots": {"3": {"tone": {"name": "x", "kind": "pulse"}}}})

    def test_put_tone_is_a_copy(self):
        self.p.put_tone(1, self.lead, "lead_1")
        self.lead.params.append([75, 10])
        self.assertEqual(self.p.tone(1).params, [[70, 16]])
        self.assertEqual(self.p.slots[1].from_, "lead_1")
        self.assertEqual(self.p.tone(1).id, "")

    def test_link_keeps_and_restores_ch2(self):
        self.p.put_tone(1, self.soft, "soft_1")
        self.p.put_tone(2, self.lead, "lead_1")
        self.assertEqual(self.p.set_link12(True), [2])
        self.assertEqual(self.p.tone(2).params, self.soft.params)
        self.assertEqual(self.p.slots[2].kept.tone.params, [[70, 16]])
        # 紐付け中の変更は両方に入る
        self.assertEqual(self.p.set_param(2, 79, 0, SPEC), [1, 2])
        self.assertEqual(self.p.tone(1).value(79, SPEC), 0)
        self.assertEqual(self.p.put_tone(1, Tone("x", "pulse", [[70, 48]])), [1, 2])
        self.assertEqual(self.p.tone(2).params, [[70, 48]])
        # 外すと保管していた音色に戻る。紐付け中の変更は ch1 にだけ残る
        self.assertEqual(self.p.set_link12(False), [2])
        self.assertEqual(self.p.tone(2).params, [[70, 16]])
        self.assertEqual(self.p.slots[2].from_, "lead_1")
        self.assertIsNone(self.p.slots[2].kept)
        self.assertEqual(self.p.tone(1).params, [[70, 48]])
        self.assertEqual(self.p.set_param(1, 79, 0, SPEC), [1])

    def test_unlink_without_kept_keeps_ch1_tone(self):
        d = self.p.to_dict()
        d["link12"] = True
        d["slots"]["2"] = {"tone": self.soft.to_dict(with_id=False), "from": ""}
        p = Performance.from_dict(d, SPEC)
        p.set_link12(False)
        self.assertEqual(p.tone(2).params, self.soft.params)

    def test_kept_survives_json(self):
        self.p.put_tone(2, self.lead)
        self.p.set_link12(True)
        p2 = Performance.from_dict(self.p.to_dict(), SPEC)
        self.assertEqual(p2.slots[2].kept.tone.params, [[70, 16]])
        p2.set_link12(False)
        self.assertEqual(p2.tone(2).params, [[70, 16]])

    def test_poly_links_automatically(self):
        self.p.put_tone(2, self.lead)
        self.p.apply_template("bass_poly")
        self.assertTrue(self.p.link12)
        self.assertEqual(self.p.slots[2].kept.tone.params, [[70, 16]])
        self.p.apply_template("bass_unison")       # ユニゾンでは自動で外さない
        self.assertTrue(self.p.link12)

    def test_templates(self):
        k = KeyboardMap.template("bass_melody")
        self.assertEqual(k.pair, "off")
        self.assertEqual((k.parts[1].on, k.parts[1].lo), (True, 60))
        self.assertEqual((k.parts[3].on, k.parts[3].hi), (True, 59))
        self.assertEqual(KeyboardMap.template("unison").pair, "layer")
        self.assertEqual(KeyboardMap.template("ch1").used_chs(), [1])
        self.assertEqual(KeyboardMap.template("bass_poly").used_chs(), [1, 2, 3])
        with self.assertRaises(ValueError):
            KeyboardMap.template("piano")

    def test_controls_defaults(self):
        c = Controls.defaults_for(KeyboardMap.template("bass_poly"))
        self.assertEqual(c.bend_to, [1, 2])
        self.assertEqual(c.mod_to, [1, 2])
        self.assertEqual(c.pedal_to, [1, 2, 3])
        c = Controls.defaults_for(KeyboardMap.template("bass_melody"), Controls(bend_range=12, mod_use="duty"))
        self.assertEqual((c.bend_to, c.bend_range, c.mod_use), ([1], 12, "duty"))
        self.p.controls.bend_range = 7
        self.p.apply_template("ch1")
        self.assertEqual(self.p.controls.bend_range, 7)

    def test_keyboard_normalize(self):
        k = KeyboardMap.from_dict({"pair": "weird", "parts": {"3": {"on": True, "lo": 90, "hi": 10, "shift": -13}}})
        self.assertEqual(k.pair, "off")
        self.assertEqual((k.parts[3].lo, k.parts[3].hi, k.parts[3].shift), (10, 90, -12))
        self.assertTrue(k.parts[1].on)

    def test_chord_settings(self):
        c = ChordSettings.from_dict({"style": "pad", "spread": 900, "bass": "mid", "layout": "x"})
        self.assertEqual((c.style, c.spread, c.bass, c.layout), ("pad", 500, "mid", "otama"))
        v = c.engine_values()
        self.assertEqual((v["release_ms"], v["bass_floor"], v["upper_lo"], v["grace_ms"]), (300, 48, 72, 80))
        self.assertFalse(ChordSettings(glide=True, style="piano").engine_values()["retrigger"])

    def test_round_trip(self):
        self.p.put_tone(5, Tone("波", "dpcm_wave", [[18, 127]], wave=list(range(16))))
        self.p.apply_template("bass_poly")
        self.p.chord.active = True
        p2 = Performance.from_dict(self.p.to_dict(), SPEC)
        self.assertEqual(p2.to_dict(), self.p.to_dict())


class SessionTest(unittest.TestCase):
    def test_load_is_a_copy_and_dirty(self):
        perf = Performance(name="A", id="a_1")
        s = Session()
        s.load(perf)
        self.assertEqual((s.loaded_from, s.dirty), ("a_1", False))
        s.performance.set_param(1, 70, 16, SPEC)
        s.changed([1])
        self.assertTrue(s.dirty)
        self.assertEqual(perf.tone(1).params, [])

    def test_is_silent(self):
        s = Session()
        self.assertFalse(s.is_silent(1, SPEC))
        s.performance.set_param(1, 7, 0, SPEC)
        s.performance.set_param(3, 11, 0, SPEC)
        self.assertTrue(s.is_silent(1, SPEC))
        self.assertTrue(s.is_silent(3, SPEC))
        self.assertFalse(s.is_silent(2, SPEC))

    def test_round_trip(self):
        s = Session(Performance(name="B"), "b", True)
        self.assertEqual(Session.from_dict(s.to_dict(), SPEC).to_dict(), s.to_dict())
        with self.assertRaises(ValueError):
            Session.from_dict({"format": "other"})


class LibraryTest(unittest.TestCase):
    def test_add_overwrite_rename_delete(self):
        lib = Library()
        t = lib.add_tone(Tone("やわらか", "pulse", [[70, 80]]))
        self.assertTrue(t.id.startswith("tone_"))
        self.assertTrue(t.created)
        t2 = lib.add_tone(t)                        # 同じ id でも別の id になる
        self.assertNotEqual(t.id, t2.id)
        lib.overwrite_tone(t.id, Tone("ちがう名前", "pulse", [[70, 16]]))
        self.assertEqual((lib.tone(t.id).name, lib.tone(t.id).params), ("やわらか", [[70, 16]]))
        with self.assertRaises(ValueError):
            lib.overwrite_tone(t.id, Tone("x", "noise"))
        lib.rename_tone(t.id, "新しい名前")
        self.assertEqual(lib.tone(t.id).name, "新しい名前")
        lib.delete_tone(t.id)
        self.assertIsNone(lib.tone(t.id))
        self.assertEqual(len(lib.tones_of("pulse")), 1)

    def test_performances_and_merge(self):
        lib = Library()
        p = lib.add_performance(Performance(), "ライブ")
        self.assertTrue(p.id.startswith("set_"))
        other = Library.from_dict(lib.to_dict(), SPEC)
        added = lib.merge(other)
        self.assertEqual(len(lib.performances), 2)
        self.assertNotEqual(added[0].id, p.id)


class SmallTypesTest(unittest.TestCase):
    def test_chordbook_always_12(self):
        b = ChordBook.from_dict({"format": "otamachord-set-v1", "songs": [{"name": "曲", "key": 14, "text": "C"}],
                                 "bass_floor": 40})
        self.assertEqual(len(b.songs), 12)
        self.assertEqual(b.songs[0].key, 2)
        self.assertIsNone(b.to_dict()["bass_floor"])

    def test_prefs(self):
        p = Prefs.from_dict({"ch_offset": 3, "theme": "neon", "out_name": "X"})
        self.assertEqual((p.ch_offset, p.theme, p.out_name), (0, "rpg", "X"))


if __name__ == "__main__":
    unittest.main()
