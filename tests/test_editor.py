import json
import tempfile
import time
import unittest
from pathlib import Path

from famimimidi import cartridge as C, core as CORE, editor
from famimimidi.engine import SendLog
from famimimidi.library import Library, Patch
from tests.test_engine import FakeOut


class EditorTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        t = Path(self.tmp.name)
        self.core = CORE.Core(log=SendLog(log_dir=None), cart=C.CartState.load(t / "c.json"),
                              lib=Library(t / "l.json"), settings={})
        self.out = FakeOut()
        self.core.engine.set_output(self.out)
        self.p = self.core.params

    def tearDown(self):
        self.core.shutdown()
        self.tmp.cleanup()

    def sent(self):
        time.sleep(0.06)      # 間引き送信(20ms)を待つ
        return {m[1]: m[2] for m in self.out.sent if m[0] & 0xF0 == 0xB0}

    def test_spec_is_json_and_per_channel(self):
        s1, s3 = editor.spec(1, self.p), editor.spec(3, self.p)
        json.dumps(s1, ensure_ascii=False)
        self.assertIn("duty", [g["key"] for g in s1["groups"]])
        self.assertNotIn("duty", [g["key"] for g in s3["groups"]])
        self.assertIn(70, [d["cc"] for d in s1["detail"]])

    def test_state_visibility(self):
        v = self.core.values[1]
        st = editor.state(1, v, self.p)
        self.assertFalse(st["controls"]["vibrate"]["show"])      # 既定値ではビブラートなし
        self.assertEqual(st["controls"]["duty"]["index"], 2)      # 50%
        json.dumps(st)

    def test_toggle_and_index_send(self):
        c = self.core
        c.set_values(1, editor.updates_for("vibon", "toggle", True, c.values[1], self.p))
        c.set_values(1, editor.updates_for("duty", "index", 0, c.values[1], self.p))
        c.set_values(1, editor.updates_for("sus", "index", 5, c.values[1], self.p))
        sent = self.sent()
        self.assertEqual((sent[1], sent[70], sent[79]), (64, 16, 44))
        self.assertTrue(editor.state(1, c.values[1], self.p)["controls"]["vibrate"]["show"])

    def test_slider_is_clamped_to_control_range(self):
        c = self.core
        self.assertEqual(editor.updates_for("vibdepth", "value", 99, c.values[1], self.p), {77: 12})

    def test_apply_patch_resets_everything_without_121(self):
        c = self.core
        c.set_values(1, {23: 127})
        self.out.sent.clear()
        skipped = c.apply_patch(Patch(id="x", name="テスト", channel=1, cc=[[70, 16], [17, 127]]))
        sent = self.sent()
        self.assertEqual((sent[70], sent[23]), (16, 0))          # アルペジエーターは既定値(OFF)に戻る
        self.assertNotIn(121, sent)
        self.assertEqual(skipped, [17])                          # ch1 に無い CC
        self.assertEqual(c.loaded[1].name, "テスト")

    def test_save_new_and_overwrite_keep_order(self):
        c = self.core
        c.apply_patch(Patch(id="x", name="元", channel=1, cc=[[79, 40], [70, 16]]))
        c.set_values(1, {72: 30})
        p = c.save_new(1, "新しい")
        self.assertEqual(p.cc, [[79, 40], [70, 16], [72, 30]])     # 元の並び順を保ち、新しい設定は後ろ
        self.assertIs(c.loaded[1], p)
        c.set_values(1, {79: 127})                                  # 既定値に戻した設定は消える
        c.overwrite(p.id, 1)
        self.assertEqual(c.lib.get(p.id).cc, [[70, 16], [72, 30]])

    def test_detail_update(self):
        self.assertEqual(editor.detail_update(70, "index", 1, self.p), {70: 48})
        self.assertEqual(editor.detail_update(22, "index", 0, self.p), {22: 0})
        self.assertEqual(editor.detail_update(72, "value", 200, self.p), {72: 127})

    def test_values_ignore_other_channels_ccs(self):
        c = self.core
        c.set_values(3, {70: 16, 72: 30})       # 三角波にデューティは無い
        self.assertNotIn(70, c.values[3])
        self.assertEqual(c.values[3][72], 30)


if __name__ == "__main__":
    unittest.main()
