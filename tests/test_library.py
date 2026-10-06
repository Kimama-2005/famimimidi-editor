import tempfile
import time
import unittest
from pathlib import Path

from famimimidi.audition import PhrasePlayer
from famimimidi.engine import MidiEngine, SendLog
from famimimidi.library import Library, Patch, clean_cc, diff_from_defaults
from famimimidi.spec import load_spec
from tests.test_engine import FakeOut


class LibraryTest(unittest.TestCase):
    def setUp(self):
        _, self.params = load_spec()
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "library.json"

    def tearDown(self):
        self.tmp.cleanup()

    def test_seed_import_strips_reset_and_write_ccs(self):
        lib = Library(self.path)
        self.assertEqual(len(lib.patches), 13)
        for p in lib.patches:
            ccs = {c for c, _ in p.cc}
            self.assertFalse(ccs & {45, 46, 47, 48, 49, 50, 51, 120, 121, 123}, p.id)
        self.assertIn("CC#121", lib.get("follin_lead").notes)
        # 順序は元のまま(マクロ化の優先順)
        self.assertEqual(lib.get("jpop_v1_macro10").cc[0], [70, 48])

    def test_save_and_reload(self):
        lib = Library(self.path)
        lib.add(Patch(id="x", name="テスト", channel=2, cc=[[70, 16]]))
        lib2 = Library(self.path)
        self.assertEqual(lib2.get("x").name, "テスト")
        self.assertEqual(lib2.get("x").cc, [[70, 16]])

    def test_clean_cc_dedup_keeps_first_position_last_value(self):
        cc, removed = clean_cc([[70, 16], [121, 0], [79, 10], [70, 48]])
        self.assertEqual(cc, [[70, 48], [79, 10]])
        self.assertEqual(removed, [121])

    def test_diff_keeps_previous_order(self):
        vals = {c: p.default for c, p in self.params.items() if p.default is not None}
        vals.update({79: 104, 70: 48, 1: 64})
        self.assertEqual(diff_from_defaults(vals, self.params, previous_order=[70, 79]),
                         [[70, 48], [79, 104], [1, 64]])

    def test_import_file_does_not_overwrite_same_id(self):
        lib = Library(self.path)
        out = Path(self.tmp.name) / "exp.json"
        lib.export(out, [lib.get("tri_bass")])
        added = lib.import_file(out)
        self.assertEqual(len(added), 1)
        self.assertNotEqual(added[0].id, "tri_bass")
        self.assertEqual(len(lib.patches), 14)


class PhraseTest(unittest.TestCase):
    def setUp(self):
        _, params = load_spec()
        self.eng = MidiEngine(SendLog(log_dir=None), params)
        self.out = FakeOut()
        self.eng.set_output(self.out)

    def tearDown(self):
        self.eng.shutdown()

    def test_phrase_sends_on_off_pairs(self):
        pl = PhrasePlayer(self.eng)
        pl.play(3, 48, 100, [(0, 30, 0), (40, 30, 7)])
        time.sleep(0.3)
        self.assertEqual(self.out.sent, [bytes([0x92, 48, 100]), bytes([0x82, 48, 0]),
                                         bytes([0x92, 55, 100]), bytes([0x82, 55, 0])])

    def test_stop_releases_sounding_notes(self):
        pl = PhrasePlayer(self.eng)
        pl.play(1, 60, 100, [(0, 5000, 0)])
        time.sleep(0.1)
        pl.stop()
        self.assertEqual(self.out.sent, [bytes([0x90, 60, 100]), bytes([0x80, 60, 0])])


if __name__ == "__main__":
    unittest.main()
