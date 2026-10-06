import tempfile
import threading
import unittest
from pathlib import Path

from famimimidi import cartridge as C
from famimimidi.engine import MidiEngine, SendLog
from famimimidi.spec import load_spec
from tests.test_engine import FakeOut

JPOP_STD = [[70, 48], [79, 104], [75, 16], [72, 20], [1, 64], [78, 46], [73, 0], [65, 0]]


class PlanTest(unittest.TestCase):
    def test_record_matches_proven_t0_sequence(self):
        """T0(実機で成功)のマクロ11 部分と同じバイト列・同じ間隔"""
        steps = C.plan_record(11, JPOP_STD, 0, pc=93)
        msgs = [s.msg for s in steps if s.msg]
        expected = [bytes([0xB0, 49, 47]), bytes([0xB0, 45, 11])] + \
            [bytes([0xB0, c, v]) for c, v in JPOP_STD] + \
            [bytes([0xB0, 45, 0]), bytes([0xB0, 47, 11]), bytes([0xB0, 51, 92])]
        self.assertEqual(msgs, expected)
        waits = [s.wait_ms for s in steps]
        self.assertEqual(waits[:4], [0, 600, 600, 75])
        stop = next(i for i, s in enumerate(steps) if s.role == "record_stop")
        self.assertEqual(steps[stop + 1].wait_ms, 1800)    # 停止 → 実行 1.8秒
        self.assertEqual(steps[stop + 2].wait_ms, 900)     # 実行 → CC#51 0.9秒

    def test_pc_is_sent_as_data_byte(self):
        steps = C.plan_assign(19, 0, pc=89)
        self.assertIn(bytes([0xB0, 51, 88]), [s.msg for s in steps])

    def test_startup_and_offset(self):
        steps = C.plan_assign(11, 5, startup_ch=1)    # 音源が ch6-10 で起動している場合
        self.assertIn(bytes([0xB5, 50, 1]), [s.msg for s in steps])

    def test_validation(self):
        with self.assertRaises(ValueError):
            C.plan_record(11, [[70, 1]] * 11, 0)          # 11個は入らない
        with self.assertRaises(ValueError):
            C.plan_record(41, [[70, 1]], 0)
        with self.assertRaises(ValueError):
            C.plan_record(11, [[121, 0]], 0)              # リセットはマクロに入れない
        with self.assertRaises(ValueError):
            C.plan_assign(11, 0, pc=88)                   # 工場プリセットには割り当てられない
        with self.assertRaises(ValueError):
            C.plan_assign(11, 0)

    def test_by_importance(self):
        self.assertEqual(C.by_importance([[3, 0], [99, 1], [79, 104], [70, 48], [24, 4]]),
                         [[70, 48], [24, 4], [79, 104], [3, 0], [99, 1]])

    def test_candidates_drop_defaults_keep_order(self):
        _, params = load_spec()
        cand, same = C.macro_candidates([[23, 0], [70, 48], [7, 127], [79, 104], [121, 0]], params)
        self.assertEqual(cand, [[70, 48], [79, 104]])
        self.assertEqual(same, [[23, 0], [7, 127]])


class StateTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "cart.json"

    def tearDown(self):
        self.tmp.cleanup()

    def test_known_state(self):
        st = C.CartState.load(self.path)
        self.assertEqual(st.pc_map[89], 19)
        self.assertEqual(st.pc_map[93], 20)          # T5 の無音が残っている(PCチェック)
        self.assertEqual(st.startup[1], 11)
        self.assertNotIn(19, st.free_macros())
        self.assertNotIn(11, st.free_macros())         # ch1 の電源ONマクロとして使用中
        self.assertIn(17, st.free_macros())
        self.assertEqual(st.free_pcs(), [89, 90])
        self.assertEqual(st.free_macros()[0], 3)     # 一度も使っていない番号を先に

    def test_macro_for_pc(self):
        st = C.CartState.load(self.path)
        self.assertEqual(st.macro_for_pc(91), 3)          # 空き(マクロ19の共有)→ 空きマクロを使う
        st.record_done(3, [[70, 16]], "a", "p", 91, None)
        self.assertEqual(st.macro_for_pc(91), 3)          # その PC 専用なら使い回す
        st.assign_done(3, 92, None)                       # 同じマクロを別の PC でも使う
        self.assertNotEqual(st.macro_for_pc(91), 3)       # 共有中は上書きしない
        st.startup[1] = 4
        self.assertNotEqual(st.macro_for_pc(93), 4)       # 電源ONで使っているマクロも避ける

    def test_assign_many_plan_groups_by_macro(self):
        steps = C.plan_assign_many({93: 11, 91: 19, 92: 19, 94: 12}, 0)
        msgs = [s.msg for s in steps if s.msg]
        # PC 番号の小さい順に、同じマクロのものをまとめる
        self.assertEqual(msgs, [bytes([0xB0, 49, 47]),
                                bytes([0xB0, 47, 19]), bytes([0xB0, 51, 90]), bytes([0xB0, 51, 91]),
                                bytes([0xB0, 47, 11]), bytes([0xB0, 51, 92]),
                                bytes([0xB0, 47, 12]), bytes([0xB0, 51, 93])])
        with self.assertRaises(ValueError):
            C.plan_assign_many({88: 19}, 0)
        st = C.CartState.load(self.path)
        st.assign_many_done({91: 19, 93: 11})
        self.assertEqual((st.pc_map[91], st.pc_map[93]), (19, 11))

    def test_record_and_reload(self):
        st = C.CartState.load(self.path)
        st.record_done(17, [[7, 0]], "テスト", "p1", 97, None)
        st.save(self.path)
        st2 = C.CartState.load(self.path)
        self.assertEqual(st2.pc_map[97], 17)
        self.assertEqual(st2.slot(17).cc, [[7, 0]])
        self.assertEqual(st2.users(17), ([97], []))

    def test_failure_marks_unknown(self):
        st = C.CartState.load(self.path)
        st.failed(17, 97, 2, recorded=True, error="x")
        self.assertIsNone(st.slot(17).cc)
        self.assertIsNone(st.pc_map[97])
        self.assertIsNone(st.startup[2])


class JobTest(unittest.TestCase):
    def setUp(self):
        _, params = load_spec()
        self.eng = MidiEngine(SendLog(log_dir=None), params)
        self.out = FakeOut()
        self.eng.set_output(self.out)

    def tearDown(self):
        self.eng.shutdown()

    def run_job(self, steps):
        done = threading.Event()
        result = {}

        def on_done(ok, err, recorded):
            result.update(ok=ok, err=err, recorded=recorded)
            done.set()
        for s in steps:
            s.wait_ms = 1        # テストでは待たない
        C.WriteJob(self.eng, steps, on_done).start()
        self.assertTrue(done.wait(5))
        return result

    def test_job_sends_write_ccs(self):
        r = self.run_job(C.plan_record(17, [[7, 0]], 0, pc=97))
        self.assertTrue(r["ok"])
        self.assertIn(bytes([0xB0, 45, 17]), self.out.sent)
        self.assertIn(bytes([0xB0, 51, 96]), self.out.sent)
        self.assertFalse(self.eng.writing)

    def test_other_sends_blocked_while_writing(self):
        self.eng.begin_write()
        self.assertFalse(self.eng.send(bytes([0x90, 60, 100]), "試聴"))
        self.eng.handle_input(bytes([0xB0, 1, 64]))       # 鍵盤のモジュレーション
        self.eng.set_cc(1, 70, 16)
        self.eng.flush_pending()
        self.assertEqual(self.out.sent, [])
        self.eng.end_write()
        self.eng.flush_pending()                          # 持ち越した CC は書き込み後に送る
        self.assertEqual(self.out.sent, [bytes([0xB0, 70, 16])])

    def test_write_ccs_still_blocked_without_write_ok(self):
        self.assertFalse(self.eng.send(bytes([0xB0, 45, 1])))
        # 決まった形(波形データ・波形登録)以外の SysEx は、書き込みジョブからでも送らない
        self.assertFalse(self.eng.send(bytes([0xF0, 0x7E, 0x7F, 0x09, 0x01, 0xF7]), write_ok=True))
        self.assertEqual(self.out.sent, [])

    def test_failure_tries_to_stop_recording(self):
        class Flaky(FakeOut):
            def send(self, msg):
                if msg[1] == 7:
                    raise OSError("unplugged")
                super().send(msg)
        self.eng.set_output(Flaky())
        out = self.eng._out
        r = self.run_job(C.plan_record(17, [[7, 0]], 0, pc=97))
        self.assertFalse(r["ok"])
        self.assertTrue(r["recorded"])
        self.assertEqual(out.sent[-1], bytes([0xB0, 45, 0]))   # 記録停止だけは送る
        self.assertNotIn(bytes([0xB0, 51, 96]), out.sent)


if __name__ == "__main__":
    unittest.main()
