"""アプリ層と画面の窓口(Bridge)のテスト。偽の MIDI と一時フォルダで動かす(実際の user_data は使わない)。"""
import json
import tempfile
import unittest
from html.parser import HTMLParser
from pathlib import Path

from famimimidi2.app import App
from famimimidi2.bridge import WEB, Bridge
from famimimidi2.model.tone import Tone
from famimimidi2.paths import DATA_DIR

from .fakes import FakeMidi


class AppTestBase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        root = Path(self._tmp.name)
        self.midi = FakeMidi()
        self.app = App(user_dir=root / "user_data", log_dir=None, data_dir=DATA_DIR, midi=self.midi, threads=False)
        self.bridge = Bridge(self.app)

    def tearDown(self):
        self.app.shutdown()
        self._tmp.cleanup()

    def connect(self):
        r = self.app.connect("USB MIDI Interface", "microKEY2")
        self.assertTrue(r["ok"], r)
        return self.midi.take()


class ConnectTest(AppTestBase):
    def test_connect_sends_whole_session(self):
        sent = self.connect()
        chs = {m[0] & 0x0F for m in sent if m[0] & 0xF0 == 0xB0}
        self.assertEqual(chs, {0, 1, 2, 3, 4})
        self.assertFalse(any(m[0] == 0xB0 and m[1] == 121 for m in sent))     # CC#121 は使わない
        self.assertIn(bytes([0xB0, 82, 2]), sent)                              # ベンド幅は演奏セットから
        self.assertEqual(self.app.prefs.out_name, "USB MIDI Interface")
        self.assertTrue((Path(self._tmp.name) / "user_data" / "prefs.json").exists())

    def test_missing_port(self):
        r = self.app.connect("ない", None)
        self.assertFalse(r["ok"])

    def test_input_is_routed_by_place(self):
        self.connect()
        self.app.handle_input(bytes([0x90, 60, 100]))
        self.assertEqual(self.midi.take(), [bytes([0x90, 60, 100])])           # 割り当て表(ch1 だけ)
        self.app.handle_input(bytes([0x80, 60, 0]))
        self.app.set_place(4)
        self.midi.take()
        self.app.handle_input(bytes([0x90, 40, 100]))
        self.assertEqual(self.midi.take(), [bytes([0x93, 40, 100])])           # 4 のタブは ch4 だけ
        self.app.handle_input(bytes([0xC0, 3]))                                # プログラムチェンジは送らない
        self.assertEqual(self.midi.take(), [])

    def test_place_change_stops_notes(self):
        self.connect()
        self.app.screen_note(60, 100, True)
        self.midi.take()
        self.app.set_place(2)
        self.assertEqual(self.midi.take(), [bytes([0x80, 60, 0])])

    def test_silent_ch_note_is_skipped(self):
        self.connect()
        self.app.session.performance.set_param(1, 7, 0, self.app.spec)
        self.app.screen_note(60, 127, True)
        self.assertEqual(self.midi.take(), [])

    def test_offset_resends_on_shifted_chs(self):
        self.connect()
        self.app.set_offset(5)
        chs = {m[0] & 0x0F for m in self.midi.take() if m[0] & 0xF0 == 0xB0}
        self.assertEqual(chs, {5, 6, 7, 8, 9})


class LibraryOpsTest(AppTestBase):
    def test_put_tone_with_link(self):
        self.connect()
        lead = self.app.library.add_tone(Tone("リード", "pulse", [[70, 16]]))
        self.app.toggle_link12()
        self.midi.take()
        self.app.put_tone(1, lead.id)
        sent = self.midi.take()
        self.assertIn(bytes([0xB0, 70, 16]), sent)
        self.assertIn(bytes([0xB1, 70, 16]), sent)
        side = self.app.side_list(2)
        self.assertTrue(next(i for i in side["items"] if i["id"] == lead.id)["current"])
        self.assertTrue(self.app.session.dirty)

    def test_wave_is_sent_after_cc18(self):
        self.connect()
        w = self.app.library.add_tone(Tone("波", "dpcm_wave", [[18, 127]], wave=list(range(16))))
        self.app.put_tone(5, w.id)
        sent = self.midi.take()
        i18 = sent.index(bytes([0xB4, 18, 127]))
        iw = next(i for i, m in enumerate(sent) if m[0] == 0xF0)
        self.assertLess(i18, iw)

    def test_save_and_reload_performance(self):
        self.connect()
        self.app.session.performance.set_param(3, 72, 30, self.app.spec)
        st = self.app.save_performance_new("ライブ")
        pid = st["selected"]
        self.assertFalse(self.app.session.dirty)
        self.app.session.performance.set_param(3, 72, 99, self.app.spec)
        self.app.load_performance(pid)
        self.assertEqual(self.app.session.performance.tone(3).value(72, self.app.spec), 30)
        self.assertIn(bytes([0xB2, 72, 30]), self.midi.take())
        self.app.rename_performance(pid, "ライブ2")
        self.assertEqual(self.app.session.performance.name, "ライブ2")
        self.app.delete_performance(pid)
        self.assertEqual(self.app.session.loaded_from, "")

    def test_tone_save_overwrite_delete(self):
        st = self.app.save_tone_new(1, "マイ音色")
        tid = st["selected"]
        self.assertEqual(self.app.session.performance.slots[1].from_, tid)
        self.app.session.performance.set_param(1, 70, 16, self.app.spec)
        self.app.overwrite_tone(1, tid)
        self.assertEqual(self.app.library.tone(tid).params, [[70, 16]])
        self.assertIn("error", self.app.overwrite_tone(3, tid))                 # 種類が違う
        self.app.delete_tone(tid)
        self.assertEqual(self.app.session.performance.slots[1].from_, "")

    def test_session_is_saved(self):
        self.app.toggle_link12()
        self.app.save_session_now()
        d = json.loads((Path(self._tmp.name) / "user_data" / "session.json").read_text(encoding="utf-8"))
        self.assertTrue(d["performance"]["link12"])


class BridgeTest(AppTestBase):
    def test_init_and_answers_are_json(self):
        init = self.bridge.init()
        json.dumps(init, ensure_ascii=False)
        self.assertEqual(init["state"]["place"], "play")
        self.assertEqual(init["side"]["place"], "play")
        for place in (1, 2, 3, 4, 5, "play"):
            r = self.bridge.set_place(place)
            json.dumps(r, ensure_ascii=False)
            self.assertEqual(r["side"]["place"], place)
        json.dumps(self.bridge.toggle_link12(), ensure_ascii=False)

    def test_keyboard_view(self):
        self.app.session.performance.apply_template("bass_poly")
        self.app._sync_router()
        kv = self.app.keyboard_view()
        self.assertEqual(kv["mode"], "map")
        self.assertEqual(kv["zones"]["48"], [3])
        self.assertEqual(kv["zones"]["72"], [1, 2])
        self.app.set_place(3)
        self.assertEqual(self.app.keyboard_view()["mode"], "tone")

    def test_public_attributes_are_methods_only(self):
        """pywebview は公開属性をたどるので、中身は _ で隠す"""
        for name in dir(self.bridge):
            if not name.startswith("_"):
                self.assertTrue(callable(getattr(self.bridge, name)), name)


class TagBalance(HTMLParser):
    VOID = {"meta", "link", "img", "input", "br", "hr", "source"}

    def __init__(self):
        super().__init__()
        self.stack, self.errors, self.ids = [], [], []

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if "id" in a:
            self.ids.append(a["id"])
        if tag not in self.VOID:
            self.stack.append((tag, self.getpos()))

    def handle_endtag(self, tag):
        if not self.stack or self.stack[-1][0] != tag:
            self.errors.append(f"{self.getpos()}: </{tag}> と {self.stack[-1] if self.stack else '(なし)'}")
            return
        self.stack.pop()


class HtmlTest(unittest.TestCase):
    def test_tags_are_balanced(self):
        p = TagBalance()
        p.feed((WEB / "index.html").read_text(encoding="utf-8"))
        self.assertEqual(p.errors, [])
        self.assertEqual(p.stack, [])
        self.assertEqual(len(p.ids), len(set(p.ids)), "id が重なっている")

    def test_ids_used_by_js_exist(self):
        import re
        html = (WEB / "index.html").read_text(encoding="utf-8")
        js = (WEB / "app.js").read_text(encoding="utf-8")
        ids = set(re.findall(r'id="([^"]+)"', html))
        used = set(re.findall(r"\$\('([^']+)'\)", js))
        self.assertEqual(used - ids, set())

    def test_no_external_resources(self):
        html = (WEB / "index.html").read_text(encoding="utf-8")
        self.assertNotIn("http://", html.replace("http://famimimidi.dojin.com", ""))
        self.assertNotIn("https://", html)


if __name__ == "__main__":
    unittest.main()
