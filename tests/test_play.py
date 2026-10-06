"""鍵盤の弾き方(割り当て表: 2音・重ねる・鍵域)と演奏セットのテスト"""
import tempfile
import time
import unittest
from pathlib import Path

from famimimidi import cartridge as C, core as CORE
from famimimidi.engine import SendLog
from famimimidi.library import Library, Patch
from famimimidi.play import PlayRouter, describe_map, normalize, template
from tests.test_engine import FakeOut


def ch0(ch):
    return ch - 1


def on(n, v=100, c=0):
    return bytes([0x90 | c, n, v])


def off(n, c=0):
    return bytes([0x80 | c, n, 0])


def mapped(tpl, **parts):
    """ひな形 + ch ごとの上書き → mode=map の設定"""
    cfg = {"mode": "map", **template(tpl)}
    for ch, p in parts.items():
        cfg["parts"][int(ch[2:])].update(p)
    return cfg


class RouterTest(unittest.TestCase):
    def play(self, r, msgs, tab=1):
        out = []
        for m in msgs:
            out += r.route(m, tab, ch0)
        return out

    def test_tab_mode_is_same_as_before(self):
        r = PlayRouter()
        self.assertEqual(self.play(r, [on(60)], tab=2), [bytes([0x91, 60, 100])])
        self.assertEqual(self.play(r, [off(60), bytes([0xC0, 96])], tab=4),
                         [bytes([0x81, 60, 0]), bytes([0xC3, 96])])

    def test_through_keeps_channel(self):
        r = PlayRouter({"mode": "through"})
        self.assertEqual(self.play(r, [on(60, c=5)], tab=2), [on(60, c=5)])

    def test_poly_two_notes_go_to_ch1_and_ch2(self):
        r = PlayRouter(mapped("poly"))
        self.assertEqual(self.play(r, [on(60), on(64)]), [bytes([0x90, 60, 100]), bytes([0x91, 64, 100])])
        self.assertEqual(self.play(r, [off(60), off(64)]), [bytes([0x80, 60, 0]), bytes([0x81, 64, 0])])
        self.assertEqual(r._held, {})

    def test_poly_note_off_goes_where_note_on_went(self):
        r = PlayRouter(mapped("poly"))
        a = self.play(r, [on(60)])[0][0] & 0x0F
        b = self.play(r, [on(64)])[0][0] & 0x0F
        self.assertNotEqual(a, b)
        self.assertEqual(self.play(r, [off(64)]), [bytes([0x80 | b, 64, 0])])
        self.assertEqual(self.play(r, [off(60)]), [bytes([0x80 | a, 60, 0])])

    def test_poly_third_note_steals_oldest(self):
        r = PlayRouter(mapped("poly"))
        a = self.play(r, [on(60)])[0][0] & 0x0F
        self.play(r, [on(64)])
        out = self.play(r, [on(67)])
        self.assertEqual(out, [bytes([0x80 | a, 60, 0]), bytes([0x90 | a, 67, 100])])
        self.assertEqual(self.play(r, [off(60)]), [])          # 止めた音のノートオフは捨てる
        self.assertEqual(self.play(r, [off(67)]), [bytes([0x80 | a, 67, 0])])

    def test_poly_alternates_after_release(self):
        """1音ずつ弾くと ch1 と ch2 を交互に使う(前の音の余韻(リリース)を切らない)"""
        r = PlayRouter(mapped("poly"))
        chs = []
        for n in (60, 62, 64, 65):
            chs.append(self.play(r, [on(n)])[0][0] & 0x0F)
            self.play(r, [off(n)])
        self.assertEqual(chs, [0, 1, 0, 1])

    def test_split_low_to_lower_ch_with_shift(self):
        r = PlayRouter(mapped("bass", ch3={"shift": -12}))
        out = self.play(r, [on(48), on(72)])
        self.assertEqual(out, [bytes([0x92, 36, 100]), bytes([0x90, 72, 100])])
        self.assertEqual(self.play(r, [off(48), off(72)]), [bytes([0x82, 36, 0]), bytes([0x80, 72, 0])])

    def test_split_with_poly_gives_three_voices(self):
        r = PlayRouter(mapped("bass_poly"))
        out = self.play(r, [on(40), on(64), on(67)])
        self.assertEqual(sorted(m[0] for m in out), [0x90, 0x91, 0x92])

    def test_controls_go_to_ctl_parts(self):
        r = PlayRouter(mapped("bass_poly"))
        out = self.play(r, [bytes([0xE0, 0, 80]), bytes([0xB0, 1, 64])])
        self.assertEqual(out, [bytes([0xE0, 0, 80]), bytes([0xE1, 0, 80]), bytes([0xB0, 1, 64]), bytes([0xB1, 1, 64])])
        r = PlayRouter(mapped("bass", ch3={"ctl": True}))
        self.assertEqual(self.play(r, [bytes([0xE0, 0, 80])]), [bytes([0xE0, 0, 80]), bytes([0xE2, 0, 80])])

    def test_layer_sends_same_note_to_both(self):
        r = PlayRouter(mapped("layer"))
        self.assertEqual(self.play(r, [on(60)]), [bytes([0x90, 60, 100]), bytes([0x91, 60, 100])])
        self.assertEqual(self.play(r, [on(64)]), [bytes([0x90, 64, 100]), bytes([0x91, 64, 100])])  # 重ねるは1音ずつ(止めない)
        self.assertEqual(self.play(r, [off(60)]), [bytes([0x80, 60, 0]), bytes([0x81, 60, 0])])
        self.assertEqual(r.configure({}), [bytes([0x80, 64, 0]), bytes([0x81, 64, 0])])

    def test_layer_with_split(self):
        r = PlayRouter(mapped("bass_layer"))
        self.assertEqual(self.play(r, [on(40), on(70)]),
                         [bytes([0x92, 40, 100]), bytes([0x90, 70, 100]), bytes([0x91, 70, 100])])
        self.assertEqual(self.play(r, [off(40)]), [bytes([0x82, 40, 0])])

    def test_overlapping_ranges_play_all(self):
        """鍵域を重ねると、1つの鍵で複数の ch が鳴る(ch1 と ch3 を重ね、ch4 は別の鍵域)"""
        r = PlayRouter(mapped("single", ch3={"on": True, "shift": -12}, ch4={"on": True, "lo": 100}))
        self.assertEqual(self.play(r, [on(60)]), [bytes([0x90, 60, 100]), bytes([0x92, 48, 100])])
        self.assertEqual(self.play(r, [on(100)]),
                         [bytes([0x90, 100, 100]), bytes([0x92, 88, 100]), bytes([0x93, 100, 100])])

    def test_poly_steal_keeps_other_parts_of_same_key(self):
        """2音の古い音を止めても、同じ鍵で重ねて鳴らしている ch3 は止めない"""
        r = PlayRouter(mapped("poly", ch3={"on": True}))
        self.play(r, [on(60), on(64)])
        out = self.play(r, [on(67)])
        self.assertIn(bytes([0x80, 60, 0]), out)
        self.assertNotIn(bytes([0x82, 60, 0]), out)
        self.assertEqual(self.play(r, [off(60)]), [bytes([0x82, 60, 0])])

    def test_configure_releases_held_notes(self):
        r = PlayRouter(mapped("bass"))
        self.play(r, [on(40), on(70)])
        offs = r.configure(mapped("poly"))
        self.assertEqual(sorted(offs), sorted([bytes([0x82, 40, 0]), bytes([0x80, 70, 0])]))
        self.assertEqual(self.play(r, [off(40)]), [bytes([0x80, 40, 0]), bytes([0x81, 40, 0])])  # 覚えていない音は両方へ

    def test_normalize(self):
        c = normalize({"mode": "x", "pair": "y", "parts": {"3": {"on": True, "lo": 90, "hi": 20, "shift": 7, "bogus": 1}}})
        self.assertEqual((c["mode"], c["pair"]), ("tab", "off"))
        self.assertEqual(c["parts"][3], {"on": True, "lo": 20, "hi": 90, "shift": 0, "ctl": False})
        self.assertTrue(c["parts"][1]["on"])

    def test_old_settings_are_converted(self):
        """フェーズD の設定(upper / split)を割り当て表に直す"""
        c = normalize({"upper": "poly", "split": True, "split_note": 60, "lower_ch": 3, "lower_shift": -12})
        self.assertEqual((c["mode"], c["pair"]), ("map", "poly"))
        self.assertEqual((c["parts"][1]["lo"], c["parts"][3]["hi"], c["parts"][3]["shift"]), (60, 59, -12))
        self.assertTrue(c["parts"][3]["on"])
        self.assertEqual(normalize({"upper": "tab"})["mode"], "tab")
        self.assertEqual(normalize({"upper": "through"})["mode"], "through")

    def test_describe(self):
        self.assertEqual(describe_map(normalize(mapped("bass_poly", ch3={"shift": -12}))),
                         "ch1+2(2音) C4〜 / ch3 〜B3(-1oct)")


class CoreLinkTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        t = Path(self.tmp.name)
        self.core = CORE.Core(log=SendLog(log_dir=None), cart=C.CartState.load(t / "c.json"),
                              lib=Library(t / "l.json"), settings={})
        self.core.save_settings = lambda: None          # 本物の settings.json に書かない
        self.out = FakeOut()
        self.core.engine.set_output(self.out)

    def tearDown(self):
        self.core.shutdown()
        self.tmp.cleanup()

    def cc(self, ch):
        time.sleep(0.06)
        return {m[1]: m[2] for m in self.out.sent if m[0] == 0xB0 | (ch - 1)}

    def test_old_remap_setting_is_carried_over(self):
        core = CORE.Core(log=SendLog(log_dir=None), settings={"thru_remap": False})
        self.assertEqual(core.engine.router.cfg["mode"], "through")
        core.shutdown()

    def test_poly_copies_ch1_tone_to_ch2_and_links_edits(self):
        self.core.set_values(1, {70: 0})
        self.core.set_play(mapped("poly"))
        self.assertEqual(self.core.values[2], self.core.values[1])
        self.assertEqual(self.cc(2).get(70), 0)
        self.out.sent.clear()
        self.core.set_values(1, {70: 127})
        self.assertEqual(self.cc(2).get(70), 127)
        p = Patch(id="x", name="テスト", channel=1, cc=[[70, 64]])
        self.core.apply_patch(p)
        self.assertEqual(self.core.loaded[2].name, "テスト")

    def test_layer_does_not_link_but_copy_detunes_ch2(self):
        self.core.set_play(mapped("layer"))
        self.core.set_values(1, {70: 0, 85: 64})
        self.assertNotIn(70, self.cc(2))
        self.core.copy_for_layer()
        sent = self.cc(2)
        self.assertEqual(sent.get(70), 0)
        self.assertEqual(sent.get(85), 80)          # 初期値は「普通」(+16)
        self.core.copy_for_layer(8)
        self.assertEqual(self.cc(2).get(85), 72)
        self.core.copy_for_layer(99)                # 選択肢に無い値は「普通」
        self.assertEqual(self.core.values[2][85], 80)
        self.assertEqual(self.core.values[1][85], 64)

    def test_no_link_without_poly(self):
        self.core.set_values(1, {70: 0})
        self.assertNotIn(70, self.cc(2))


class PerfSetTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        t = Path(self.tmp.name)
        self.path = t / "l.json"
        self.core = CORE.Core(log=SendLog(log_dir=None), cart=C.CartState.load(t / "c.json"),
                              lib=Library(self.path), settings={})
        self.core.save_settings = lambda: None
        self.out = FakeOut()
        self.core.engine.set_output(self.out)

    def tearDown(self):
        self.core.shutdown()
        self.tmp.cleanup()

    def test_save_and_load_set_restores_tones_and_map(self):
        c = self.core
        lead = c.lib.patches[0]
        c.apply_patch(lead, 1)
        c.set_values(3, {7: 90})
        c.set_play(mapped("bass", ch3={"shift": -12}))
        ps = c.save_set("ベース+メロディ", "メモ")
        self.assertEqual(ps.parts["1"]["name"], lead.name)
        self.assertEqual(ps.parts["1"]["source"], lead.id)
        self.assertEqual(ps.parts["3"]["cc"], [[7, 90]])
        self.assertEqual(ps.play["parts"]["3"]["shift"], -12)
        # 別の状態にしてから読み込む
        c.reset_defaults(1)
        c.reset_defaults(3)
        c.set_play({"mode": "tab"})
        time.sleep(0.06)
        self.out.sent.clear()
        c.load_set(ps.id)
        self.assertEqual(c.engine.router.cfg["mode"], "map")
        self.assertEqual(c.engine.router.cfg["parts"][3]["shift"], -12)
        self.assertEqual(c.values[3][7], 90)
        self.assertEqual(c.loaded[1].name, lead.name)
        time.sleep(0.06)
        self.assertIn(bytes([0xB2, 7, 90]), self.out.sent)

    def test_set_is_a_copy(self):
        c = self.core
        lead = c.lib.patches[0]
        c.apply_patch(lead, 1)
        ps = c.save_set("コピー確認")
        lead.cc = [[70, 0]]
        c.lib.update(lead)
        self.assertNotEqual(c.lib.get_set(ps.id).parts["1"]["cc"], [[70, 0]])

    def test_edited_tone_is_marked(self):
        c = self.core
        lead = c.lib.patches[0]
        c.apply_patch(lead, 1)
        c.set_values(1, {7: 3})
        self.assertTrue(c.save_set("変更").parts["1"]["name"].endswith("(変更あり)"))

    def test_sets_persist_and_backup_roundtrip(self):
        c = self.core
        ps = c.save_set("保存")
        again = Library(self.path)
        self.assertEqual(again.get_set(ps.id).name, "保存")
        bk = Path(self.tmp.name) / "bk.json"
        again.export(bk)
        added = again.import_file(bk)                   # 同じ id は別 id にして追加
        self.assertEqual(len(again.sets), 2)
        self.assertTrue(any(getattr(a, "parts", None) is not None for a in added))

    def test_old_library_file_without_sets_loads(self):
        p = Path(self.tmp.name) / "old.json"
        p.write_text('{"version": 1, "patches": []}', encoding="utf-8")
        self.assertEqual(Library(p).sets, [])


if __name__ == "__main__":
    unittest.main()
