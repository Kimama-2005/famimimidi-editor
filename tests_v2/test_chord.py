"""コードモード(SPEC_v2 6.5)のテスト。時間は ManualScheduler で進める。"""
import json
import random
import unittest

from famimimidi2.model.chordbook import ChordBook, Song
from famimimidi2.model.performance import ChordSettings, Controls
from famimimidi2.music import chords as cd
from famimimidi2.performance.chordmode import ChordEngine, key_slot, slot_note
from famimimidi2.performance.scheduler import ManualScheduler

from .test_app import AppTestBase


class Rig:
    def __init__(self, settings=None, text="C F G C", key=0, controls=None, keep_song=False):
        self.sent, self.ccs, self.values = [], [], {}
        self.sched = ManualScheduler()
        self.e = ChordEngine(send=self.sent.append, to_ch0=lambda ch: ch - 1,
                             get_value=lambda ch, cc: self.values.get((ch, cc), 0),
                             set_cc=lambda ch, cc, v: self.ccs.append((ch, cc, v)), scheduler=self.sched,
                             rng=random.Random(1))
        book = ChordBook()
        book.songs[0] = Song("テスト", key, text)
        self.e.set_book(book)
        settings = settings or ChordSettings(style="organ", spread=0)
        if settings.layout == "song" and not keep_song:      # テストは並びが決まっている度数+補足(右手)で弾く
            settings = ChordSettings.from_dict({**settings.to_dict(), "layout": "degree_r"})
        self.e.configure(settings, controls or Controls())
        self.e.set_active(True)

    def take(self):
        out, self.sent[:] = list(self.sent), []
        return out

    def notes_on(self, msgs):
        return {(m[0] & 0x0F) + 1: m[1] for m in msgs if m[0] & 0xF0 == 0x90 and m[2] > 0}


class EngineTest(unittest.TestCase):
    def test_keys_and_slots(self):
        self.assertEqual(key_slot(48), (0, 0))
        self.assertEqual(key_slot(71), (1, 11))
        self.assertEqual(key_slot(83), (2, 11))
        self.assertEqual(key_slot(36), (cd.COMMON_ROW, 0))
        self.assertIsNone(key_slot(84))          # C6 はなにもしない
        self.assertEqual(slot_note(cd.COMMON_ROW, 3), 39)

    def test_split_voicing(self):
        r = Rig()
        self.assertIn((5, 18, 127), r.ccs)       # ボイス3は波形メモリ
        r.e.handle(bytes([0x90, 60, 100]))       # C4 = Ⅰ(C)
        on = r.notes_on(r.take())
        self.assertEqual(set(on), {1, 2, 3, 5})
        self.assertEqual(on[3], 36)              # ベースは C2 から
        self.assertEqual({on[1] % 12, on[2] % 12}, {4, 7})   # パルスは 3度・5度(大事な2音)
        self.assertEqual(on[5] % 12, 0)          # ルートは波形メモリ
        self.assertTrue(all(60 <= on[c] <= 84 for c in (1, 2, 5)))

    def test_release_after_grace(self):
        r = Rig()
        r.e.handle(bytes([0x90, 60, 100]))
        r.take()
        r.e.handle(bytes([0x80, 60, 0]))
        self.assertEqual(r.take(), [])           # 猶予(80ms)の間は鳴らし続ける
        r.sched.advance(0.1)
        offs = r.take()
        self.assertEqual(len([m for m in offs if m[0] & 0xF0 == 0x80]), 4)

    def test_change_within_grace_is_chord_change(self):
        r = Rig()
        r.e.handle(bytes([0x90, 60, 100]))
        r.e.handle(bytes([0x80, 60, 0]))
        r.take()
        r.sched.advance(0.04)
        r.e.handle(bytes([0x90, 65, 100]))       # F4 = Ⅳ(F)
        r.sched.advance(0.2)
        msgs = r.take()
        self.assertTrue(any(m[0] == 0x92 and m[1] == 41 for m in msgs))   # ベース F2
        self.assertFalse(any(m[0] & 0xF0 == 0x80 and m[0] & 0x0F == 2 and m[1] == 41 for m in msgs))

    def test_organ_keeps_common_notes_piano_retriggers(self):
        r = Rig(ChordSettings(style="organ", spread=0))
        r.e.handle(bytes([0x90, 60, 100]))
        r.take()
        r.e.handle(bytes([0x90, 69, 100]))       # A4 = Ⅵm(Am): C・E は共通
        organ = r.take()
        p = Rig(ChordSettings(style="piano", spread=0))
        p.values = {}
        p.e.handle(bytes([0x90, 60, 100]))
        p.take()
        p.e.handle(bytes([0x90, 69, 100]))
        piano = p.take()
        self.assertLess(len(organ), len(piano))  # ピアノは全部打ち直す
        self.assertEqual(len([m for m in piano if m[0] & 0xF0 == 0x90]), 4)

    def test_strum_spreads_notes(self):
        r = Rig(ChordSettings(style="organ", spread=90))
        r.e.handle(bytes([0x90, 60, 100]))
        first = r.take()
        self.assertEqual(len(first), 1)          # 一番下(ベース)がすぐ、ほかはずらして
        r.sched.advance(0.1)
        self.assertEqual(len(r.take()), 3)

    def test_sustain_and_hold(self):
        r = Rig()
        r.e.handle(bytes([0xB0, 64, 127]))
        r.e.handle(bytes([0x90, 60, 100]))
        r.e.handle(bytes([0x80, 60, 0]))
        r.take()
        r.sched.advance(0.5)
        self.assertEqual(r.take(), [])           # 踏んでいる間は保持
        r.e.handle(bytes([0xB0, 64, 0]))
        r.sched.advance(0.2)
        self.assertTrue(r.take())
        r.e.toggle_hold()
        r.e.handle(bytes([0x90, 60, 100]))
        r.e.handle(bytes([0x80, 60, 0]))
        r.take()
        r.sched.advance(0.5)
        self.assertEqual(r.take(), [])           # ホールド中も保持
        r.e.stop_all()
        self.assertTrue(r.take())

    def test_pedal_off(self):
        r = Rig(controls=Controls(pedal_use="off"))
        self.assertIn("使わない", r.e.handle(bytes([0xB0, 64, 127])))

    def test_key_shift(self):
        r = Rig()
        r.e.shift_key(2)
        r.e.handle(bytes([0x90, 60, 100]))
        self.assertEqual(r.notes_on(r.take())[3] % 12, 2)   # キー D のⅠ = D
        self.assertEqual(r.e.state()["chord"]["name"], "D")

    def test_bend_and_mod_go_to_voices(self):
        r = Rig(controls=Controls(bend_to=[1, 2], mod_to=[1, 2, 3], mod_use="duty"))
        r.e.handle(bytes([0xE0, 0, 80]))
        self.assertEqual(r.take(), [bytes([0xE0, 0, 80]), bytes([0xE1, 0, 80])])
        r.e.handle(bytes([0xB0, 1, 50]))
        self.assertEqual(r.take(), [bytes([0xB0, 70, 50]), bytes([0xB1, 70, 50])])    # デューティは ch1・2 だけ
        self.assertIsNotNone(r.e.handle(bytes([0xC0, 3])))                           # PC は使わない

    def test_arp_method(self):
        r = Rig(ChordSettings(method="arp", style="organ", spread=0))
        self.assertNotIn((5, 18, 127), r.ccs)
        self.assertIn((1, 23, 127), r.ccs)       # アルペジエーターが OFF なら ON に
        r.e.handle(bytes([0x90, 50, 100]))       # D3 = 補足 M7
        r.e.handle(bytes([0x90, 60, 100]))       # C4 = Ⅰ → CM7
        msgs = r.take()
        chs = {(m[0] & 0x0F) + 1 for m in msgs}
        self.assertEqual(chs, {1, 3})
        self.assertEqual(len([m for m in msgs if m[0] == 0x90]), 4)   # CM7 の4音を ch1 へ

    def test_leave_restores_tone_values(self):
        r = Rig()
        r.values[(5, 18)] = 0
        r.ccs.clear()
        r.e.set_active(False)
        self.assertIn((5, 18, 0), r.ccs)
        self.assertEqual(r.e.override_values(), {})

    def test_glide(self):
        r = Rig(ChordSettings(glide=True, style="piano"))
        self.assertIn((1, 65, 127), r.ccs)
        self.assertFalse(r.e.cfg["retrigger"])

    def test_progression_and_next(self):
        r = Rig(text="C F G C")
        st = r.e.state()
        self.assertEqual(st["next"]["name"], "C")
        r.e.handle(bytes([0x90, 60, 100]))
        st = r.e.state()
        self.assertEqual((st["prog_pos"], st["next"]["name"]), (0, "F"))
        self.assertEqual(st["next"]["note"], 65)           # 次に弾く鍵(F4 = Ⅳ)

    def test_view_json(self):
        r = Rig(text="C F G Am Em7 D7 Bb Ebdim")
        for layout in ("song", "degree_r", "degree_l"):
            r.e.configure(ChordSettings(layout=layout))
            v = r.e.view()
            json.dumps(v, ensure_ascii=False)
            self.assertEqual(len(v["rows"]), 3)
        self.assertEqual(ChordSettings(layout="otama").normalized().layout, "song")   # なくした配置は弾きやすさ重視に


class ChordAppTest(AppTestBase):
    def setUp(self):
        super().setUp()
        self.app.save_song(0, "テスト", 0, "C G Am F")

    def test_active_only_in_play_place(self):
        self.connect()
        self.app.set_chord_settings({"layout": "degree_r"})
        self.app.set_chord_active(True)
        self.assertTrue(self.app.chord.active)
        self.app.gate.flush()
        self.assertIn(bytes([0xB4, 18, 127]), self.midi.take())
        self.app.screen_note(60, 100, True)
        self.app.scheduler.advance(0.2)           # ピアノの奏法はずらして入る
        self.assertEqual({m[0] & 0x0F for m in self.midi.take() if m[0] & 0xF0 == 0x90}, {0, 1, 2, 4})
        self.app.set_place(5)                     # 音色づくりの場所ではコードモードは効かない
        self.assertFalse(self.app.chord.active)
        self.app.gate.flush()
        self.assertIn(bytes([0xB4, 18, 0]), self.midi.take())      # 音色の値に戻す
        self.app.set_place("play")
        self.assertTrue(self.app.chord.active)

    def test_override_wins_when_loading_performance(self):
        self.connect()
        self.app.set_chord_active(True)
        pid = self.app.save_performance_new("コード")["selected"]
        self.midi.take()
        self.app.load_performance(pid)
        self.app.gate.flush()
        sent = [m for m in self.midi.take() if m[0] == 0xB4 and m[1] == 18]
        self.assertEqual(sent[-1], bytes([0xB4, 18, 127]))       # 最後に届くのはコードモードの値

    def test_tone_edit_during_chord_does_not_send_override(self):
        self.connect()
        self.app.set_chord_active(True)
        self.app.gate.flush()
        self.midi.take()
        self.app._apply_updates(5, {18: 0})
        self.app.gate.flush()
        self.assertEqual([m for m in self.midi.take() if m[1] == 18], [])
        self.assertEqual(self.app.session.performance.tone(5).value(18, self.app.spec), 0)   # 作業中の演奏には入る

    def test_settings_and_book(self):
        v = self.app.set_chord_settings({"layout": "degree_l", "style": "pad", "spread": 120})
        json.dumps(v, ensure_ascii=False)
        self.assertEqual(v["settings"]["style"], "pad")
        self.assertEqual(self.app.session.performance.chord.layout, "degree_l")
        r = self.app.save_song(1, "2曲目", "auto", "Dm7 G7 CM7 Xyz")
        self.assertEqual(len(r["errors"]), 1)
        r = self.app.import_chordbook([{"name": "取り込み", "key": 2, "text": "D G A"}])
        self.assertEqual(self.app.chordbook.songs[0].name, "取り込み")
        page = ('<h1 class="title">ウィキの曲(テスト主題歌)</h1><p class="key">Key: G</p>'
                '<p class="line"><span class="chord">G</span><span class="word">うた|</span><span class="chord">D</span></p>')
        r = self.app.import_chordwiki(2, page)
        self.assertEqual(self.app.chordbook.songs[2].name, "ウィキの曲")
        self.assertEqual(self.app.chordbook.songs[2].text, "G | D")
        self.assertNotIn("うた", self.app.chordbook.songs[2].text)          # 歌詞は取り込まない
        self.assertIn("error", self.app.import_chordwiki(3, "<html></html>"))

    def test_keyboard_view_labels(self):
        self.app.set_chord_settings({"layout": "degree_r"})
        self.app.set_chord_active(True)
        kv = self.app.keyboard_view()
        self.assertEqual(kv["mode"], "chord")
        self.assertEqual(kv["labels"]["60"], "C")


if __name__ == "__main__":
    unittest.main()


class ProgressionNoSkipTest(unittest.TestCase):
    """アシスト(次に弾くコード)は飛ばさない"""

    def test_wrong_chord_does_not_jump_ahead(self):
        r = Rig(text="C F G C Am")
        r.e.handle(bytes([0x90, 60, 100]))          # C → 位置0
        r.e.handle(bytes([0x80, 60, 0]))
        st = r.e.state()
        self.assertEqual(st["prog_pos"], 0)
        a = r.e._slot_of(r.e.progression()[4])       # Am(5番目)を弾いても飛ばない
        r.e.play_slot(*a, on=True)
        r.e.play_slot(*a, on=False)
        self.assertEqual(r.e.state()["prog_pos"], 0)
        self.assertEqual(r.e.state()["next"]["name"], "F")

    def test_replaying_current_chord_does_not_advance(self):
        r = Rig(text="C F C G")
        for _ in range(3):
            r.e.handle(bytes([0x90, 60, 100]))
            r.e.handle(bytes([0x80, 60, 0]))
        self.assertEqual(r.e.state()["prog_pos"], 0)    # 前は C を弾き直すと3番目の C へ飛んでいた

    def test_returning_to_held_chord_does_not_advance(self):
        r = Rig(text="C G C G")
        r.e.handle(bytes([0x90, 60, 100]))           # C を押さえたまま
        g = r.e._slot_of(r.e.progression()[1])
        r.e.play_slot(*g, on=True)                   # G → 位置1
        r.e.play_slot(*g, on=False)                  # 離すと C に戻るが、進まない
        self.assertEqual(r.e.state()["prog_pos"], 1)

    def test_set_next(self):
        r = Rig(text="C F G C")
        r.e.set_next(2)
        self.assertEqual(r.e.state()["next"]["index"], 2)
        r.e.set_next(0)
        self.assertEqual(r.e.state()["prog_pos"], -1)


class SongLayoutTest(unittest.TestCase):
    def test_song_layout_plays_most_used_on_white_key(self):
        r = Rig(text="C F G C F C", keep_song=True)
        self.assertEqual(r.e.cfg["layout"], "song")
        row, off = r.e._slot_of(cd.parse("C"))
        self.assertIn(off, (0, 2, 4, 5, 7, 9, 11))               # いちばん使う C は白鍵
        r.e.play_slot(row, off, on=True)
        self.assertEqual(r.e.state()["chord"]["name"], "C")
