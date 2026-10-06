import unittest

from famimimidi import cartridge as C
from famimimidi.library import Patch
from famimimidi.sets import (apply_ops, base_id, build_tidy, cc_for_single_save, check_saved, compute_base,
                             current_base, full_values, plan_channel, status)
from famimimidi.spec import load_spec


class FakeLib:
    def __init__(self, patches):
        self.patches = patches

    def get(self, pid):
        return next((p for p in self.patches if p.id == pid), None)


# 2つともビブラートあり(モジュレーション64、揺れ幅1 = 共通・既定値と違う)。
# A はアルペジエーターON、B は OFF でデューティが違う
A = Patch(id="a", name="アルペジオ", channel=1, cc=[[70, 16], [23, 127], [24, 3], [1, 64], [77, 1]])
B = Patch(id="b", name="リード", channel=1, cc=[[70, 48], [1, 64], [77, 1]])


class SetsTest(unittest.TestCase):
    def setUp(self):
        _, self.params = load_spec()

    def test_base_is_common_non_default(self):
        fa, fb = full_values(A, self.params, 1), full_values(B, self.params, 1)
        # アルペジエーターの速さは A でしか効いていないので、土台に入れても B に影響しない
        self.assertEqual(compute_base([fa, fb], self.params), {1: 64, 77: 1, 24: 3})

    def test_irrelevant_settings_are_ignored(self):
        from famimimidi.sets import relevant
        self.assertNotIn(24, relevant(full_values(B, self.params, 1)))    # アルペジエーター OFF
        self.assertIn(24, relevant(full_values(A, self.params, 1)))
        self.assertNotIn(5, relevant(full_values(B, self.params, 1)))     # ポルタメント OFF
        self.assertNotIn(75, relevant(full_values(B, self.params, 1)))    # サスティン最大

    def test_plan_resets_arpeggiator_for_other_sound(self):
        plan = plan_channel({93: B, 101: A}, self.params, 1)
        b = dict(map(tuple, plan.slots[93]))
        self.assertEqual(b.get(23), 0)          # A から B に切り替えたらアルペジエーターを切る
        self.assertNotIn(24, b)                 # B ではアルペジエーターの速さは関係ない
        self.assertEqual(b[70], 48)
        self.assertEqual(b[77], 1)              # 土台と同じ値だが、余った枠で自分の設定も持つ
        self.assertEqual(plan.dropped[93], [])

    def test_single_sound_still_keeps_its_own_settings(self):
        plan = plan_channel({93: B}, self.params, 1)
        self.assertEqual(plan.base, {70: 48, 1: 64, 77: 1})   # 1つだけなら全部が「共通」
        self.assertEqual(plan.slots[93], [[70, 48], [1, 64], [77, 1]])   # 場所の中身は空にしない

    def make_cart(self):
        st = C.known_state()
        st.record_done(3, [[70, 16], [23, 127], [24, 3], [1, 64], [77, 1]], A.name, "a", 101, None)
        st.record_done(4, [[70, 48], [1, 64], [77, 1]], B.name, "b", 102, None)
        return st

    def test_status_detects_leftover_and_tidy_fixes_it(self):
        st, lib = self.make_cart(), FakeLib([A, B])
        s = status(st, lib, self.params, 1)
        self.assertEqual(s.count, 2)
        self.assertEqual(s.to_rewrite, [102])   # B の場所にはアルペジエーターOFF が入っていない
        self.assertFalse(s.base_ok)
        self.assertTrue(s.tidy_needed)
        self.assertIn(102, check_saved({101: A, 102: B}, {101: st.slot(3).cc, 102: st.slot(4).cc},
                                       self.params, 1, {}))
        t = build_tidy(st, lib, self.params, 1, 0)
        msgs = [s.msg for s in t.steps if s.msg]
        self.assertIn(bytes([0xB0, 50, 1]), msgs)        # 土台を ch1 の電源ONに
        self.assertEqual(t.rewrites, [102])     # A の場所はすでに計画どおりなので保存し直さない
        apply_ops(st, t.ops)
        self.assertEqual(current_base(st, 1), {1: 64, 77: 1, 24: 3})
        self.assertEqual(st.slot(st.startup[1]).patch_id, base_id(1))
        self.assertFalse(status(st, lib, self.params, 1).tidy_needed)
        self.assertEqual(build_tidy(st, lib, self.params, 1, 0).steps, [])   # もう整っている

    def test_tidy_does_not_touch_other_channels(self):
        st, lib = self.make_cart(), FakeLib([A, B])
        t = build_tidy(st, lib, self.params, 1, 0)
        apply_ops(st, t.ops)
        self.assertEqual(st.pc_map[98], C.known_state().pc_map[98])
        for ch in (2, 3, 4, 5):
            self.assertEqual(st.startup[ch], C.known_state().startup[ch])

    def test_single_save_includes_reset(self):
        st, lib = self.make_cart(), FakeLib([A, B])
        ccs, dropped = cc_for_single_save(st, lib, self.params, B, 102)
        d = dict(map(tuple, ccs))
        self.assertEqual((d[70], d[23], d[77]), (48, 0, 1))
        self.assertEqual(dropped, [])


if __name__ == "__main__":
    unittest.main()
