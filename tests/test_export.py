import tempfile
import unittest
from pathlib import Path

import mido

from famimimidi import cartridge as C
from famimimidi.export import export_set, patch_events
from famimimidi.library import Patch
from famimimidi.spec import editable_params, load_spec


class ExportTest(unittest.TestCase):
    def setUp(self):
        _, self.params = load_spec()
        self.lead = Patch(id="lead", name="リード", channel=1, cc=[[70, 16], [23, 127]])
        self.noise = Patch(id="nz", name="ノイズ", channel=4, cc=[[75, 14], [70, 16]])   # ch4 にデューティは無い

    def read(self, data):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "x.mid"
            p.write_bytes(data)
            return mido.MidiFile(p)

    def test_full_mode_sends_every_param_once_without_reset(self):
        ev, _ = patch_events(self.lead, 1, self.params, "full")
        ccs = [m[1] for _, m in ev]
        self.assertEqual(sorted(ccs), sorted(p.cc for p in editable_params(self.params, 1) if p.default is not None))
        self.assertNotIn(121, ccs)
        vals = {m[1]: m[2] for _, m in ev}
        self.assertEqual((vals[70], vals[23], vals[7]), (16, 127, 127))
        self.assertEqual([t for t, _ in ev], list(range(len(ev))))    # 1tick ずつ

    def test_diff_mode_skips_params_not_on_channel(self):
        ev, note = patch_events(self.noise, 4, self.params, "diff")
        self.assertEqual([bytes(m) for _, m in ev], [bytes([0xB3, 75, 14])])
        self.assertIn("#70", note)

    def test_recall_uses_cartridge_pc_or_falls_back(self):
        st = C.known_state()
        st.record_done(3, [[70, 16]], "リード", "lead", 101, None)
        ev, note = patch_events(self.lead, 1, self.params, "recall", st)
        self.assertEqual(ev, [(0, bytes([0xC0, 100]))])
        ev, note = patch_events(self.noise, 4, self.params, "recall", st)
        self.assertGreater(len(ev), 1)
        self.assertIn("保存されていない", note)

    def test_file_has_one_track_per_channel(self):
        data, _ = export_set({1: self.lead, 4: self.noise}, self.params, "full", ch_offset=5)
        mf = self.read(data)
        self.assertEqual(mf.type, 1)
        chans = [{m.channel for m in t if hasattr(m, "channel")} for t in mf.tracks]
        self.assertEqual(chans, [set(), {5}, {8}])      # オフセット ch6〜10
        raw = mf.tracks[1].name.encode("latin-1").decode("cp932")   # mido は latin-1 で読むので戻す
        self.assertIn("リード", raw)


if __name__ == "__main__":
    unittest.main()
