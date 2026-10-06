import tempfile
import threading
import unittest
from pathlib import Path

from famimimidi import cart_actions as A, cartridge as C, core as CORE
from famimimidi.engine import SendLog
from famimimidi.library import Library, Patch
from tests.test_engine import FakeOut


class CartActionsTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        t = Path(self.tmp.name)
        self.core = CORE.Core(log=SendLog(log_dir=None), cart=C.CartState.load(t / "c.json"),
                              lib=Library(t / "l.json"), settings={})
        self.core.cart.save = lambda path=t / "c.json": C.CartState.save(self.core.cart, path)
        self.out = FakeOut()
        self.core.engine.set_output(self.out)

    def tearDown(self):
        self.core.shutdown()
        self.tmp.cleanup()

    def run_plan(self, plan):
        for s in plan.steps:
            s.wait_ms = 1
        done = threading.Event()
        result = {}
        err = self.core.run_write(plan, done=lambda ok, msg: (result.update(ok=ok, msg=msg), done.set()))
        self.assertIsNone(err)
        self.assertTrue(done.wait(5))
        return result

    def test_places_and_words(self):
        places = A.places(self.core)
        self.assertEqual(len(places), 40)
        self.assertEqual(places[0]["place"], 1)
        self.assertEqual(places[0]["pc"], 89)
        self.assertTrue(places[0]["empty"])                  # PC89 = 空き(マクロ19)
        self.assertEqual(len(A.startup_rows(self.core)), 5)
        self.assertEqual(len(A.tidy_rows(self.core)), 5)

    def test_save_plan_runs_and_updates_table(self):
        p = Patch(id="t1", name="テスト音", channel=1, cc=[[70, 16], [79, 40]])
        self.core.lib.add(p)
        plan = A.plan_save(self.core, 97, p)
        self.assertTrue(any("場所 9" in l for l in plan.lines))
        self.assertFalse(any("マクロ" in l for l in plan.lines))       # ユーザー向けの文に「マクロ」は出さない
        r = self.run_plan(plan)
        self.assertTrue(r["ok"])
        m = self.core.cart.pc_map[97]
        self.assertEqual(self.core.cart.slot(m).patch_id, "t1")
        self.assertIn(bytes([0xB0, 51, 96]), self.out.sent)
        self.assertFalse(self.core.engine.writing)

    def test_cannot_start_when_disconnected_or_busy(self):
        p = Patch(id="t1", name="x", channel=1, cc=[[70, 16]])
        plan = A.plan_save(self.core, 97, p)
        self.core.engine.set_output(None)
        self.assertIn("接続", self.core.run_write(plan))

    def test_clear_rejects_empty_place(self):
        with self.assertRaises(ValueError):
            A.plan_clear(self.core, 89)          # 空き


    def test_tables(self):
        t = A.tables(self.core)
        self.assertEqual(len(t["macros"]), 40)
        self.assertEqual(len(t["pcs"]), 40)
        self.assertTrue(t["macros"][18]["reserved"])          # マクロ19

    def test_advanced_plan_uses_given_order_and_macro(self):
        p = Patch(id="t2", name="並べ替え", channel=1, cc=[[70, 16], [79, 40], [72, 30]])
        self.core.lib.add(p)
        cand = A.candidates(self.core, p, 97)
        self.assertEqual([r[0] for r in cand["rows"]][:3], [70, 79, 72])
        plan = A.plan_advanced(self.core, p, 30, [[72, 30], [70, 16]], pc=97)
        msgs = [s.msg for s in plan.steps if s.msg]
        self.assertEqual(msgs[1:4], [bytes([0xB0, 45, 30]), bytes([0xB0, 72, 30]), bytes([0xB0, 70, 16])])
        self.assertTrue(self.run_plan(plan)["ok"])
        self.assertEqual(self.core.cart.pc_map[97], 30)

    def test_assign_many_plan(self):
        plan = A.plan_assign_many_pcs(self.core, {"91": 19, "92": 19})
        self.assertTrue(self.run_plan(plan)["ok"])
        self.assertEqual((self.core.cart.pc_map[91], self.core.cart.pc_map[92]), (19, 19))


    def test_assign_existing(self):
        plan = A.plan_assign_existing(self.core, 20, pc=None, startup_ch=2)
        self.assertTrue(self.run_plan(plan)["ok"])
        self.assertEqual(self.core.cart.startup[2], 20)
        with self.assertRaises(ValueError):
            A.plan_assign_existing(self.core, 20)              # PC も電源ONも無い


if __name__ == "__main__":
    unittest.main()
