"""カートリッジへの書き込み(SPEC_v2 6.6)のテスト。偽のポートと、待たずに進む sleep で動かす。"""
import json
from pathlib import Path

from famimimidi2.cartridge import mirror, plans, tidy
from famimimidi2.model.cartmirror import CartMirror, MacroRecord
from famimimidi2.model.tone import Tone
from famimimidi2.music.spec import load_spec

from .test_app import AppTestBase

SPEC = load_spec()
NOSLEEP = {"sleep": lambda s: None}


class StepsTest(AppTestBase):
    def test_record_steps(self):
        steps = plans.steps_record(7, [[70, 16], [79, 0]], 0, pc=95, startup_ch=None)
        msgs = [s.msg for s in steps if s.msg]
        self.assertEqual(msgs, [bytes([0xB0, 49, 47]), bytes([0xB0, 45, 7]), bytes([0xB0, 70, 16]),
                                bytes([0xB0, 79, 0]), bytes([0xB0, 45, 0]), bytes([0xB0, 47, 7]),
                                bytes([0xB0, 51, 94])])                       # 呼び出し番号95 = 送信値94
        waits = [s.wait_ms for s in steps]
        self.assertEqual(waits[:5], [0, 600, 600, 75, 600])
        self.assertIn(1800, waits)
        with self.assertRaises(ValueError):
            plans.steps_record(7, [[70, 16]] * 11, 0)                         # 11個目は入らない

    def test_wave_steps(self):
        steps = plans.steps_wave([1] * 16, 61)
        self.assertEqual(steps[1].msg, bytes([0xF0, 0x00, 0x71, 0x7F, 60, 0xF7]))
        self.assertEqual(steps[1].wait_ms, 150)


class CartAppTest(AppTestBase):
    def setUp(self):
        super().setUp()
        self.app.cart = CartMirror()
        self.app.cart.pc_map = {pc: mirror.NEUTRAL_MACRO for pc in range(89, 129)}
        self.connect()
        self.lead = self.app.library.add_tone(Tone("リード", "pulse", [[70, 16], [79, 64], [75, 30], [1, 80]]))
        self.app.put_tone(1, self.lead.id)
        self.midi.take()

    def run_plan(self, kind, args):
        r = self.app.cart_plan(kind, args)
        self.assertNotIn("error", r, r)
        json.dumps(r, ensure_ascii=False)
        result = {}
        rr = self.app.cart_run(r["token"], on_done=lambda ok, msg: result.update(ok=ok, msg=msg), **NOSLEEP)
        self.assertEqual(rr.get("ok"), True, rr)
        return r, result

    def test_save_tone_to_place(self):
        r, result = self.run_plan("save", {"place": 3, "ch": 1})
        self.assertTrue(result["ok"])
        self.assertIn("保存場所 3", r["lines"][0])
        sent = self.midi.take()
        self.assertIn(bytes([0xB0, 51, 90]), sent)                             # 保存場所3 = 呼び出し番号91 = 送信値90
        self.assertTrue(any(m[1] == 45 and m[2] != 0 for m in sent if m[0] == 0xB0))
        m = self.app.cart.pc_map[91]
        rec = self.app.cart.macros[m]
        self.assertTrue(rec.certain)
        self.assertEqual(rec.from_, self.lead.id)
        self.assertEqual(rec.extra["kind"], "pulse")
        self.assertEqual(rec.params[0][0], 70)                                 # 重要度順
        self.assertNotIn(m, (19, 20))
        saved = json.loads((Path(self._tmp.name) / "user_data" / "cartridge.json").read_text(encoding="utf-8"))
        self.assertEqual(saved["pc_map"]["91"], m)
        self.assertTrue(saved["history"][-1]["ok"])

    def test_token_is_one_shot_and_needs_connection(self):
        r = self.app.cart_plan("clear", {"place": 1})
        self.assertIn("error", r)                                              # もう空き
        r = self.app.cart_plan("save", {"place": 1, "ch": 1})
        self.app.disconnect()
        self.assertIn("error", self.app.cart_run(r["token"], **NOSLEEP))
        self.assertIn("error", self.app.cart_run(r["token"], **NOSLEEP))       # 番号札は1回だけ
        self.assertIn("error", self.app.cart_run("でたらめ", **NOSLEEP))

    def test_other_sends_blocked_while_writing(self):
        r = self.app.cart_plan("save", {"place": 2, "ch": 1})
        seen = []

        def sleep(_):
            seen.append(self.app.gate.send(bytes([0x90, 60, 100])))           # 書き込みの途中の演奏
        self.app.cart_run(r["token"], sleep=sleep)
        self.assertTrue(seen)
        self.assertFalse(any(seen))

    def test_failure_marks_unknown(self):
        r = self.app.cart_plan("save", {"place": 4, "ch": 1})
        port = self.app.gate._out
        calls = {"n": 0}
        real = port.send

        def flaky(msg):
            calls["n"] += 1
            if calls["n"] == 16:                                             # パニック10個の後、記録の途中で失敗
                raise OSError("ケーブルが抜けた")
            real(msg)
        port.send = flaky
        result = {}
        self.app.cart_run(r["token"], on_done=lambda ok, msg: result.update(ok=ok, msg=msg), **NOSLEEP)
        self.assertFalse(result["ok"])
        self.assertIsNone(self.app.cart.pc_map[92])
        unknown = [rec for rec in self.app.cart.macros.values() if rec.params is None and "失敗" in rec.label]
        self.assertTrue(unknown)
        self.assertFalse(self.app.cart.history[-1]["ok"])
        self.assertIn(bytes([0xB0, 45, 0]), self.midi.sent)                  # 記録モードは止めようとした

    def test_clear_startup_wave(self):
        self.run_plan("save", {"place": 5, "ch": 1})
        _, res = self.run_plan("startup", {"ch": 1, "place": 5})
        self.assertEqual(self.app.cart.startup[1], self.app.cart.pc_map[93])
        self.run_plan("startup", {"ch": 1, "place": None})
        self.assertEqual(self.app.cart.startup[1], 19)
        self.run_plan("clear", {"place": 5})
        self.assertEqual(self.app.cart.pc_map[93], 19)
        self.assertIn("error", self.app.cart_plan("wave", {"slot": 61}))       # ch5 に波形が無い
        self.app.set_wave([0, 4, 8, 12, 15, 12, 8, 4] * 2)
        self.run_plan("wave", {"slot": 62, "name": "三角っぽい"})
        self.assertEqual(self.app.cart.waves[62]["name"], "三角っぽい")

    def test_tidy(self):
        a = self.app.library.add_tone(Tone("A", "pulse", [[70, 16], [77, 5], [1, 80], [5, 30], [65, 127]]))
        b = self.app.library.add_tone(Tone("B", "pulse", [[70, 80], [77, 5], [1, 80]]))
        self.app.put_tone(1, a.id)
        self.run_plan("save", {"place": 10, "ch": 1})
        self.app.put_tone(1, b.id)
        self.run_plan("save", {"place": 11, "ch": 1})
        st = tidy.status(self.app.cart, self.app.library, SPEC, 1)
        self.assertEqual(st.count, 2)
        if st.needed:
            r, res = self.run_plan("tidy", {"ch": 1})
            self.assertTrue(res["ok"])
        st = tidy.status(self.app.cart, self.app.library, SPEC, 1)
        self.assertFalse(st.needed)
        base = tidy.current_base(self.app.cart, 1)
        self.assertEqual(base.get(77), 5)                                      # 共通の設定は土台に
        self.assertIn("error", self.app.cart_plan("tidy", {"ch": 1}))          # もう整っている

    def test_perf_places_and_startup(self):
        self.app.put_tone(3, self.app.library.add_tone(Tone("ベース", "triangle", [[72, 20]])).id)
        r, res = self.run_plan("perf_places", {"places": {"1": 20, "3": 21}})
        self.assertTrue(res["ok"])
        self.assertEqual(mirror.tone_kind(self.app.cart, self.app.cart.pc_map[108]), "pulse")
        self.assertEqual(mirror.tone_kind(self.app.cart, self.app.cart.pc_map[109]), "triangle")
        r, res = self.run_plan("perf_startup", {})
        self.assertTrue(res["ok"])
        self.assertIsNotNone(self.app.cart.startup[1])
        self.assertIsNotNone(self.app.cart.startup[3])
        self.assertEqual(self.app.cart.macros[self.app.cart.startup[3]].role, "startup:3")

    def test_cart_view_json(self):
        v = self.app.cart_view()
        json.dumps(v, ensure_ascii=False)
        self.assertEqual(len(v["tiles"]), 40)
        self.assertTrue(all(t["empty"] for t in v["tiles"]))

    def test_call_sends_program_change(self):
        self.app.cart_call(3, 2)
        sent = self.midi.take()
        self.assertEqual(sent[0], bytes([0xC1, 90]))
        self.assertEqual(sent[1][0], 0x91)


class MirrorTest(AppTestBase):
    def test_macro_choice(self):
        c = CartMirror()
        c.pc_map = {89: 5, 90: 5, 91: 6}
        c.macros = {5: MacroRecord([[70, 16]], "共有", True), 6: MacroRecord([[70, 16]], "ひとり", True),
                    1: MacroRecord(None, "中身不明")}
        self.assertEqual(mirror.macro_for_pc(c, 91), 6)                       # その場所だけが使うなら使い回す
        self.assertEqual(mirror.macro_for_pc(c, 89), 1)                       # 共有なら空き(中身不明を先に)
        self.assertNotIn(19, mirror.free_macros(c))
        self.assertNotIn(20, mirror.free_macros(c))
