"""保存と、以前の版からの移行のテスト。実際の user_data は読むだけ(一時フォルダに写して試し、前後で md5 を比べる)。"""
import hashlib
import json
import shutil
import tempfile
import unittest
from pathlib import Path

from famimimidi2.model import migrate
from famimimidi2.model.store import Store, StoreError, write_json
from famimimidi2.music.spec import load_spec
from famimimidi2.paths import ROOT, USER_DIR

SPEC = load_spec()

OLD_LIBRARY = {
    "version": 2,
    "patches": [
        {"id": "lead_v1", "name": "リード", "channel": 1, "category": "lead",
         "cc": [[23, 0], [82, 2], [7, 127], [70, 48], [20, 0], [64, 0], [75, 16]], "notes": "メモ",
         "created": "2026-09-29T21:34:07+09:00", "updated": "2026-09-29T21:34:07+09:00", "source": "data/patches.json"},
        {"id": "bass_v1", "name": "ベース", "channel": 3, "category": "bass", "cc": [[72, 16], [70, 16]],
         "notes": "", "created": "", "updated": "", "source": ""},
        {"id": "wave_v1", "name": "波", "channel": 5, "category": "other", "cc": [[18, 127]], "notes": "",
         "created": "", "updated": "", "source": "", "wave": list(range(16))},
    ],
    "sets": [
        {"id": "piano", "name": "ピアノ伴奏",
         "parts": {"1": {"name": "上", "cc": [[70, 48], [82, 12], [20, 127]], "source": "lead_v1"},
                   "2": {"name": "中", "cc": [[70, 80]], "source": ""},
                   "3": {"name": "ベース", "cc": [[72, 16]], "source": ""},
                   "4": {"name": "", "cc": [], "source": ""},
                   "5": {"name": "下", "cc": [[79, 0]], "source": "", "wave": [0] * 8 + [15] * 8}},
         "play": {"pair": "poly", "parts": {"1": {"on": True, "lo": 60, "hi": 127, "shift": 0, "ctl": True},
                                            "3": {"on": True, "lo": 0, "hi": 59, "shift": 0, "ctl": False}}},
         "chord": {"method": "split", "strum_ms": 30, "strum_order": 0, "strum_change": True, "release_ms": 40,
                   "bass_floor": 36, "glide": False, "active": True, "layout": "regular"},
         "notes": "", "created": "", "updated": ""},
    ],
}
OLD_SETTINGS = {"out_name": "USB MIDI Interface", "in_name": "microKEY2", "thru": True, "ch_offset": 5,
                "view": "easy", "thru_remap": True, "theme": "crt", "layer_detune": 24,
                "play": {"mode": "map", "pair": "off",
                         "parts": {"1": {"on": True, "lo": 60, "hi": 127, "shift": 0, "ctl": True},
                                   "4": {"on": True, "lo": 0, "hi": 59, "shift": -12, "ctl": False}}},
                "chord": {"release_ms": 0, "strum_change": False, "bass_floor": 48, "layout": "song"}}
OLD_CART = {
    "version": 1, "note": "控え",
    "macros": {"4": {"cc": [[77, 1], [5, 5]], "label": "ch1 の土台", "certain": True, "patch_id": "__base_ch1",
                     "written": "2026-09-30T00:26:57+09:00"},
               "5": {"cc": None, "label": "不明", "certain": False, "patch_id": "", "written": ""},
               "11": {"cc": [[70, 48], [23, 0]], "label": "J-POP", "certain": True, "patch_id": "lead_v1",
                      "written": "2026-09-30T00:26:57+09:00", "memo": "知らない項目"},
               "19": {"cc": [[7, 127]], "label": "音量最大", "certain": True, "patch_id": "", "written": ""}},
    "pc_map": {"89": 19, "93": 11, "94": None},
    "startup": {"1": 4, "2": 19, "3": None},
    "waves": {"61": {"name": "矩形", "samples": [15] * 8 + [0] * 8, "written": "x"}},
    "history": [{"time": "t", "action": "record", "macro": 11, "cc": [[70, 48]], "pc": 93}],
}
OLD_CHORDS = {"format": "otamachord-set-v1", "name": "セット",
              "songs": [{"name": "曲", "key": 2, "text": "D | G A"}], "common_row": None, "bass_floor": 36}


def md5_tree(path: Path):
    h = {}
    for f in sorted(path.rglob("*")):
        if f.is_file():
            h[str(f.relative_to(path))] = hashlib.md5(f.read_bytes()).hexdigest()
    return h


class StoreTestBase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self._tmp.name) / "user_data"
        self.dir.mkdir()

    def tearDown(self):
        self._tmp.cleanup()

    def put(self, name, data):
        (self.dir / name).write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")


class MigrationTest(StoreTestBase):
    def setUp(self):
        super().setUp()
        self.put("library.json", OLD_LIBRARY)
        self.put("settings.json", OLD_SETTINGS)
        self.put("cartridge.json", OLD_CART)
        self.put("chords.json", OLD_CHORDS)
        self.loaded = Store(self.dir).load_all()

    def test_tones(self):
        lib = self.loaded.library
        lead = lib.tone("lead_v1")
        self.assertEqual(lead.kind, "pulse")
        self.assertEqual(lead.params, [[70, 48], [75, 16]])     # #82・#20・#64・既定値は外す
        self.assertEqual(lead.notes, "メモ")
        self.assertEqual(lib.tone("bass_v1").kind, "triangle")
        self.assertEqual(lib.tone("bass_v1").params, [[72, 16]])  # 三角波にデューティは無い
        self.assertEqual(lib.tone("wave_v1").wave, list(range(16)))

    def test_performance(self):
        p = self.loaded.library.performance("piano")
        self.assertFalse(p.link12)                               # ポリでも ch1 と ch2 が違う音なら紐付けない(選択 B)
        self.assertEqual(p.tone(2).params, [[70, 80]])           # ch2 は今の音のまま
        self.assertIsNone(p.slots[2].kept)
        self.assertEqual(p.slots[1].from_, "lead_v1")
        self.assertEqual(p.tone(5).wave, [0] * 8 + [15] * 8)
        self.assertEqual(p.keyboard.pair, "poly")
        self.assertEqual(p.controls.bend_range, 12)               # ch1 の CC#82
        self.assertEqual(p.controls.mod_use, "duty")               # ch1 の CC#20 = ON
        self.assertEqual(p.controls.bend_to, [1, 2])
        self.assertEqual((p.chord.active, p.chord.style, p.chord.spread, p.chord.layout),
                         (True, "piano", 30, "song"))

    def test_poly_with_same_sound_is_linked(self):
        s = json.loads(json.dumps(OLD_LIBRARY["sets"][0]))
        s["parts"]["2"]["cc"] = [[70, 48]]                       # ch1 と同じ音(#82・#20 は音色から外れる)
        p = migrate.performance_from_v1(s, SPEC)
        self.assertTrue(p.link12)
        self.assertEqual(p.tone(2).params, [[70, 48]])

    def test_session_and_prefs(self):
        s, prefs = self.loaded.session, self.loaded.prefs
        self.assertEqual(s.performance.keyboard.parts[4].shift, -12)
        self.assertTrue(s.performance.keyboard.parts[4].on)
        self.assertEqual(s.performance.chord.style, "organ")
        self.assertEqual(s.performance.chord.bass, "mid")
        self.assertEqual(s.performance.chord.layout, "song")
        self.assertTrue(all(s.performance.tone(ch).params == [] for ch in range(1, 6)))
        self.assertEqual((prefs.out_name, prefs.in_name, prefs.ch_offset, prefs.theme),
                         ("USB MIDI Interface", "microKEY2", 5, "crt"))
        self.assertNotIn("thru", prefs.to_dict())

    def test_cart_numbers_unchanged(self):
        c = self.loaded.cart
        for k, old in OLD_CART["macros"].items():
            self.assertEqual(c.macros[int(k)].params, old["cc"])
            self.assertEqual(c.macros[int(k)].certain, old["certain"])
            self.assertEqual(c.macros[int(k)].label, old["label"])
        self.assertEqual(c.macros[4].role, "base:1")
        self.assertEqual(c.macros[11].from_, "lead_v1")
        self.assertEqual(c.macros[11].extra, {"memo": "知らない項目"})
        self.assertEqual(c.macros[19].role, "neutral")
        self.assertEqual(c.pc_map, {89: 19, 93: 11, 94: None})
        self.assertEqual(c.startup, {1: 4, 2: 19, 3: None, 4: None, 5: None})
        self.assertEqual(c.waves[61]["samples"], [15] * 8 + [0] * 8)
        self.assertEqual(c.history, OLD_CART["history"])

    def test_chordbook(self):
        b = self.loaded.chordbook
        self.assertEqual(b.songs[0].text, "D | G A")
        self.assertEqual(len(b.songs), 12)
        self.assertTrue((self.dir / "chordbook.json").exists())

    def test_backups_and_new_files(self):
        old = self.dir / "old_v1"
        for name, data in (("library.json", OLD_LIBRARY), ("settings.json", OLD_SETTINGS),
                           ("cartridge.json", OLD_CART), ("chords.json", OLD_CHORDS)):
            self.assertEqual(json.loads((old / name).read_text(encoding="utf-8")), data)
        for name, fmt in (("library.json", "famimimidi-library-v1"), ("session.json", "famimimidi-session-v1"),
                          ("cartridge.json", "famimimidi-cart-v1"), ("prefs.json", "famimimidi-prefs-v1"),
                          ("chordbook.json", "otamachord-set-v1")):
            self.assertEqual(json.loads((self.dir / name).read_text(encoding="utf-8"))["format"], fmt)
        self.assertEqual(len(self.loaded.notes), 4)

    def test_second_load_is_stable(self):
        before = md5_tree(self.dir)
        again = Store(self.dir).load_all()
        self.assertEqual(again.notes, [])
        self.assertEqual(md5_tree(self.dir), before)
        self.assertEqual(again.library.to_dict(), self.loaded.library.to_dict())
        self.assertEqual(again.cart.to_dict(), self.loaded.cart.to_dict())
        self.assertEqual(again.session.to_dict(), self.loaded.session.to_dict())


class FreshAndErrorTest(StoreTestBase):
    def test_fresh_user_gets_seeds(self):
        loaded = Store(self.dir).load_all()
        self.assertGreater(len(loaded.library.tones), 5)
        self.assertTrue(any(p.id == "piano_accompaniment" for p in loaded.library.performances))
        self.assertTrue(all(t.created for t in loaded.library.tones))
        self.assertEqual(loaded.cart.macros, {})
        self.assertFalse((self.dir / "old_v1").exists())

    def test_broken_file_is_not_overwritten(self):
        (self.dir / "cartridge.json").write_text("{ こわれた", encoding="utf-8")
        with self.assertRaises(StoreError):
            Store(self.dir).load_cart()
        self.assertEqual((self.dir / "cartridge.json").read_text(encoding="utf-8"), "{ こわれた")

    def test_unknown_format_is_not_overwritten(self):
        self.put("library.json", {"format": "famimimidi-library-v9"})
        with self.assertRaises(StoreError):
            Store(self.dir).load_library()
        self.assertIn("v9", (self.dir / "library.json").read_text(encoding="utf-8"))

    def test_atomic_write_leaves_no_tmp(self):
        write_json(self.dir / "x.json", {"a": 1})
        self.assertEqual([f.name for f in self.dir.iterdir()], ["x.json"])

    def test_backup_never_overwrites_previous_backup(self):
        self.put("chords.json", OLD_CHORDS)
        (self.dir / "old_v1").mkdir()
        (self.dir / "old_v1" / "chords.json").write_text("前の控え", encoding="utf-8")
        Store(self.dir).load_chordbook()
        self.assertEqual((self.dir / "old_v1" / "chords.json").read_text(encoding="utf-8"), "前の控え")
        self.assertEqual(len(list((self.dir / "old_v1").glob("chords_*.json"))), 1)


@unittest.skipUnless((USER_DIR / "cartridge.json").exists(), "実際の user_data が無い")
class RealUserDataTest(unittest.TestCase):
    """実際の user_data を一時フォルダに写して移行する。元のファイルは1バイトも変えない"""

    def test_migrate_copy_of_real_data(self):
        before = md5_tree(USER_DIR)
        with tempfile.TemporaryDirectory() as d:
            work = Path(d) / "user_data"
            shutil.copytree(USER_DIR, work)
            old_cart = json.loads((USER_DIR / "cartridge.json").read_text(encoding="utf-8"))
            old_lib = json.loads((USER_DIR / "library.json").read_text(encoding="utf-8"))
            if not migrate.is_v1_cart(old_cart):
                self.skipTest("user_data はもう新しい形")
            loaded = Store(work, ROOT / "data").load_all()
            for k, m in old_cart["macros"].items():
                self.assertEqual(loaded.cart.macros[int(k)].params, m.get("cc"), f"マクロ {k}")
                self.assertEqual(loaded.cart.macros[int(k)].certain, m.get("certain"), f"マクロ {k}")
            self.assertEqual({str(k): v for k, v in loaded.cart.pc_map.items()}, old_cart["pc_map"])
            self.assertEqual({str(k): v for k, v in loaded.cart.startup.items() if str(k) in old_cart["startup"]},
                             old_cart["startup"])
            self.assertEqual(loaded.cart.history, old_cart["history"])
            self.assertEqual(len(loaded.library.tones), len(old_lib["patches"]))
            self.assertEqual(len(loaded.library.performances), len(old_lib["sets"]))
        self.assertEqual(md5_tree(USER_DIR), before)


if __name__ == "__main__":
    unittest.main()
