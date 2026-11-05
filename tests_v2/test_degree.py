"""コードモードの配置「度数+補足」(SPEC_v2 6.5.2)のテスト。"""
import json
import unittest

from famimimidi2.model.performance import ChordSettings
from famimimidi2.music import chords as cd
from famimimidi2.music import degree as dg

from .test_chord import Rig

# インスタコードで弾けるコードの種類(maj・m・7・m7・M7・mM7・6・m6・add9・madd9・sus4・dim7・aug・m7-5・分数コード)
INSTACHORD_TYPES = ["", "m", "7", "m7", "M7", "mM7", "6", "m6", "add9", "madd9", "sus4", "dim7", "aug", "m7b5"]


def on(n, v=100):
    return bytes([0x90, n, v])


def off(n):
    return bytes([0x80, n, 0])


def pcs_of(msgs):
    """鳴らした上声とベースの音名(ノートオンだけ)"""
    return {m[1] % 12 for m in msgs if m[0] & 0xF0 == 0x90 and m[2] > 0}


class DegreeTableTest(unittest.TestCase):
    def test_every_instachord_type_on_every_root_and_key(self):
        """どのキーでも、12のルートすべてで、インスタコードの14種類と分数コード(3rd・5th がベース)が弾ける"""
        for key in range(12):
            for root in range(12):
                for q in INSTACHORD_TYPES:
                    c = cd.Chord(root, cd.QUALITIES[q])
                    f = dg.find(key, c)
                    self.assertIsNotNone(f, f"key={key} {c.name()}")
                    self.assertTrue(f[2])
                    off_, mods, _ = f
                    self.assertEqual(dg.build(key, off_, frozenset(mods)), c)
                for ivs in (cd.MAJ, cd.MIN):
                    for b in (ivs[1], ivs[2]):
                        c = cd.Chord(root, ivs, (root + b) % 12)
                        self.assertTrue(dg.find(key, c)[2], f"key={key} {c.name()}")

    def test_diatonic_needs_one_key(self):
        for s, deg in (("C", 0), ("Dm", 2), ("Em", 4), ("F", 5), ("G", 7), ("Am", 9), ("Bm", 11), ("Bb", 10)):
            self.assertEqual(dg.find(0, cd.parse(s)), (deg, (), True))

    def test_combinations(self):
        self.assertEqual(dg.find(0, cd.parse("G7")), (7, ("7",), True))
        self.assertEqual(dg.find(0, cd.parse("E7"))[1], ("7", "swap"))         # Ⅲm を入れ替えて 7th
        self.assertEqual(dg.find(0, cd.parse("Bm7b5"))[1], ("7", "b5"))
        self.assertEqual(dg.find(0, cd.parse("G/B"))[1], ("on3",))
        self.assertEqual(dg.build(0, 7, frozenset({"7", "M7"})), cd.parse("G6"))   # 7 と M7 で 6th
        self.assertEqual(dg.build(0, 7, frozenset({"flat"})), cd.parse("Gb"))       # ♭ でコード全体が半音下がる
        self.assertEqual(dg.build(2, 0, frozenset()), cd.parse("D"))                # キー D の Ⅰ

    def test_bass_not_makeable_is_approximate(self):
        self.assertEqual(dg.find(0, cd.parse("G7/F")), (7, ("7",), False))

    def test_zones(self):
        self.assertEqual([dg.zone(n, "degree_r") for n in (48, 60, 72)], ["mod", "degree", "bass"])
        self.assertEqual([dg.zone(n, "degree_l") for n in (48, 60, 72)], ["degree", "bass", "mod"])
        self.assertEqual(dg.zone(36, "degree_r"), "mod")                          # C3 より下は C3〜B3 と同じ
        self.assertEqual(dg.zone(84, "degree_l"), "mod")                          # C6 から上は C5〜B5 と同じ
        self.assertEqual(dg.bass_key_note(7), 79)
        self.assertEqual((dg.degree_note(0, "degree_r"), dg.mod_note(0, "degree_r")), (60, 48))
        self.assertEqual((dg.degree_note(0, "degree_l"), dg.mod_note(0, "degree_l"), dg.bass_key_note(0, "degree_l")), (48, 72, 60))


class DegreeEngineTest(unittest.TestCase):
    def rig(self, hand="degree_r", text="C Am7 F G7"):
        return Rig(ChordSettings(layout=hand, style="organ", spread=0), text=text)

    def test_degree_key_alone(self):
        r = self.rig()
        r.e.handle(on(69))                                  # A4 = Ⅵm(右手)
        self.assertEqual(pcs_of(r.take()), {9, 0, 4})
        self.assertEqual(r.e.state()["chord"]["name"], "Am")

    def test_modifier_held_first(self):
        r = self.rig()
        r.e.handle(on(48))                                  # C3 = 7(左手)。補足だけでは鳴らない
        self.assertEqual(r.take(), [])
        r.e.handle(on(67))                                  # G4 = Ⅴ → G7
        self.assertEqual(r.e.state()["chord"]["name"], "G7")
        self.assertIn(5, pcs_of(r.take()))                  # F(7th)

    def test_modifier_added_and_released_while_holding(self):
        r = self.rig()
        r.e.handle(on(67))                                  # G
        r.take()
        r.e.handle(on(48))                                  # +7 → G7(その場で変わる)
        self.assertEqual(r.e.state()["chord"]["name"], "G7")
        r.e.handle(off(48))                                 # 離すと(猶予のあと)G に戻る
        self.assertEqual(r.e.state()["chord"]["name"], "G7")
        r.sched.advance(0.2)
        self.assertEqual(r.e.state()["chord"]["name"], "G")

    def test_below_c3_is_same_as_c3(self):
        r = self.rig()
        r.e.handle(on(36))                                  # C2 も 7(C3〜B3 と同じ)
        r.e.handle(on(67))
        self.assertEqual(r.e.state()["chord"]["name"], "G7")

    def test_release_together_does_not_flash(self):
        """補足と基本コードを少しずれて離しても、途中のコード(G)を鳴らさない"""
        r = self.rig()
        r.e.handle(on(48)); r.e.handle(on(67))              # G7
        r.take()
        r.e.handle(off(48))                                 # 補足を先に離す
        r.sched.advance(0.03)
        r.e.handle(off(67))                                 # 0.03秒後に基本コードも離す
        r.sched.advance(5)
        sent = r.take()
        self.assertFalse(any(m[0] & 0xF0 == 0x90 and m[2] > 0 for m in sent))   # G を鳴らし直していない
        self.assertIsNone(r.e.state()["chord"])

    def test_left_hand_degrees(self):
        r = self.rig("degree_l")
        r.e.handle(on(76))                                  # E5 = ～(右手の補足、C5〜B5)
        r.e.handle(on(48))                                  # C3 = Ⅰ → Cm
        self.assertEqual(r.e.state()["chord"]["name"], "Cm")

    def test_release_degree_stops(self):
        r = self.rig()
        r.e.handle(on(60))
        r.take()
        r.e.handle(off(60))
        r.sched.advance(5)
        self.assertTrue(any(m[0] & 0xF0 == 0x80 for m in r.take()))
        self.assertIsNone(r.e.state()["chord"])

    def test_assist_shows_degree_and_modifiers(self):
        r = self.rig()
        st = r.e.state()
        self.assertEqual(st["next"]["notes"], [60])         # 最初は C = Ⅰ だけ
        r.e.handle(on(60))
        r.e.handle(off(60))
        nxt = r.e.state()["next"]                           # 次は Am7 = Ⅵm + 7
        self.assertEqual(nxt["name"], "Am7")
        self.assertEqual(nxt["notes"], [69, 48])
        self.assertEqual(nxt["cells"], [[0, 9], [1, 0]])
        self.assertIn("Ⅵm", nxt["how"])

    def test_progression_advances_when_modifier_completes_next_chord(self):
        r = self.rig()
        r.e.handle(on(60)); r.e.handle(off(60))           # C(位置0)
        r.e.handle(on(69))                                  # Am(まだ次の Am7 ではない)
        self.assertEqual(r.e.state()["prog_pos"], 0)
        r.e.handle(on(48))                                  # +7 → Am7 = 次のコード → 進む
        self.assertEqual(r.e.state()["prog_pos"], 1)
        r.e.handle(off(48))                                 # 離して Am に戻っても戻らない・進まない
        self.assertEqual(r.e.state()["prog_pos"], 1)

    def test_view(self):
        r = self.rig()
        v = r.e.view()
        json.dumps(v, ensure_ascii=False)
        self.assertEqual([row["row"] for row in v["rows"]], [2, 0, 1])     # 上から ベース・基本コード・補足
        self.assertEqual(v["rows"][1]["cells"][9]["name"], "Am")
        self.assertEqual(v["rows"][2]["cells"][0]["name"], "7")
        self.assertEqual(v["rows"][2]["cells"][0]["note"], 48)

    def test_overflow_only_unmakeable(self):
        r = self.rig(text="C G7/F Am")
        self.assertEqual(r.e.state()["overflow"], [])        # ベースだけ違うものは弾ける(ベース抜き)

    def test_settings_accept_layouts(self):
        for k in ("degree_r", "degree_l"):
            self.assertEqual(ChordSettings(layout=k).normalized().layout, k)


class SlashChordTest(unittest.TestCase):
    """分数のベースの鍵(C5〜B5、度数の並び)を押しながら基本コードを弾くと分数コード"""

    def rig(self, hand="degree_r", text="C F/G Am7/G C"):
        return Rig(ChordSettings(layout=hand, style="organ", spread=0), text=text)

    def test_any_bass(self):
        for s in ("F/G", "Am/G", "C/B", "C/Bb", "Dm7/G", "D/F#", "Ab/C"):
            for key in range(12):
                c = cd.parse(s).transpose(key)
                h = dg.how(key, c)
                self.assertIsNotNone(h, f"{key} {s}")
                self.assertEqual(dg.build(key, h["off"], frozenset(h["mods"]), h["bass"]), c, f"{key} {s}")

    def test_bass_key_makes_slash(self):
        r = self.rig()
        r.e.handle(on(79))                                  # G5 = ベース Ⅴ(これだけでは鳴らない)
        self.assertEqual(r.take(), [])
        r.e.handle(on(65))                                  # F4 = Ⅳ → F/G
        self.assertEqual(r.e.state()["chord"]["name"], "F/G")
        notes = [m for m in r.take() if m[0] == 0x92 and m[2] > 0]
        self.assertEqual(notes[-1][1] % 12, 7)              # ベース(ch3)は G

    def test_bass_key_added_while_holding(self):
        r = self.rig()
        r.e.handle(on(65))                                  # F
        r.e.handle(on(79))                                  # 押さえたままベース G → F/G
        self.assertEqual(r.e.state()["chord"]["name"], "F/G")

    def test_two_degree_keys_are_not_slash(self):
        r = self.rig()
        r.e.handle(on(67)); r.e.handle(on(65))              # 基本コードを2つ押しても分数コードにはしない
        self.assertEqual(r.e.state()["chord"]["name"], "F")

    def test_left_hand_bass_is_c4(self):
        r = self.rig("degree_l", text="F/G C")
        self.assertEqual(sorted(r.e.state()["next"]["notes"]), [53, 67])    # 最初の F/G は F3 と G4
        r.e.handle(on(67)); r.e.handle(on(53))              # 左手: G4(ベース、C4〜B4)+ F3(Ⅳ)
        self.assertEqual(r.e.state()["chord"]["name"], "F/G")

    def test_release_together_stops_cleanly(self):
        r = self.rig()
        r.e.handle(on(79)); r.e.handle(on(65))              # F/G
        r.take()
        r.e.handle(off(65))                                 # 基本コードを先に離す → 止まる(ベースだけでは鳴らない)
        r.sched.advance(0.02)
        r.e.handle(off(79))
        r.sched.advance(5)
        self.assertFalse(any(m[0] & 0xF0 == 0x90 and m[2] > 0 for m in r.take()))
        self.assertIsNone(r.e.state()["chord"])

    def test_release_bass_returns_after_grace(self):
        r = self.rig()
        r.e.handle(on(79)); r.e.handle(on(65))
        r.e.handle(off(79))                                 # ベースだけ離して F を押さえ続ける
        self.assertEqual(r.e.state()["chord"]["name"], "F/G")
        r.sched.advance(0.2)
        self.assertEqual(r.e.state()["chord"]["name"], "F")

    def test_assist_shows_bass_key(self):
        r = self.rig()
        r.e.handle(on(60)); r.e.handle(off(60))           # C → 次は F/G
        r.sched.advance(1)
        nxt = r.e.state()["next"]
        self.assertEqual(nxt["name"], "F/G")
        self.assertEqual(nxt["notes"], [65, 79])            # F4(Ⅳ)と G5(ベース)
        self.assertEqual(nxt["cells"], [[0, 5], [2, 7]])
        self.assertIn("ベース Ⅴ", nxt["how"])
        r.e.handle(on(79)); r.e.handle(on(65))
        self.assertEqual(r.e.state()["prog_pos"], 1)
        r.e.handle(off(65)); r.e.handle(off(79))
        r.sched.advance(1)
        self.assertEqual(sorted(r.e.state()["next"]["notes"]), [48, 69, 79])   # Am7/G = A4 + 7(C3)+ ベース G5

    def test_view_has_bass_row(self):
        r = self.rig()
        v = r.e.view()
        self.assertEqual([row["row"] for row in v["rows"]], [2, 0, 1])
        self.assertEqual(v["rows"][0]["cells"][7]["name"], "/G")
        self.assertEqual(v["rows"][0]["cells"][10]["name"], "/B♭")
        self.assertEqual(v["rows"][0]["cells"][7]["note"], 79)
        self.assertEqual([row["row"] for row in self.rig("degree_l").e.view()["rows"]], [1, 2, 0])   # 上から 補足・ベース・基本コード
