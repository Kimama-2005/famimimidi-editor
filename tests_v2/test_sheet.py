"""進行の欄の譜面(行・小節線・見出し)と、ChordWiki の歌詞を表示するときだけ読むこと(SPEC_v2 6.5)のテスト。"""
import os
import tempfile
import unittest
from pathlib import Path

from famimimidi2.music import chords as cd

from .test_app import AppTestBase

PAGE = ('<h1 class="title">ウィキの曲(テスト主題歌)</h1><p class="key">Key: C</p>'
        '<p class="line"><span class="wordtop">まえがき</span></p>'
        '<p class="line comment"><strong>Aメロ</strong></p>'
        '<p class="line"><span class="chord">C</span><span class="word">あいう</span>'
        '<span class="chord">Am7</span><span class="word">えお|</span><span class="chord">F</span><span class="word">かき</span></p>'
        '<p class="line comment"><strong>サビ</strong></p>'
        '<p class="line"><span class="chord">G7</span><span class="word">くけこ</span><span class="chord">N.C.</span>'
        '<span class="chord">Xyz</span><span class="word">さし</span><span class="chord">C</span></p>')
LYRICS = ("まえがき", "あいう", "えお", "かき", "くけこ", "さし")


class SheetTest(unittest.TestCase):
    def test_from_chordwiki(self):
        sheet = cd.sheet_from_chordwiki(PAGE)
        kinds = [ln["kind"] for ln in sheet]
        self.assertEqual(kinds, ["line", "comment", "line", "comment", "line"])
        self.assertEqual(sheet[1]["text"], "Aメロ")
        segs = sheet[2]["segs"]
        self.assertEqual([(s["chord"], s["ci"], s["lyric"]) for s in segs],
                         [("C", 0, "あいう"), ("Am7", 1, "えお|"), ("F", 2, "かき")])
        last = sheet[4]["segs"]
        self.assertEqual([s["ci"] for s in last], [3, None, 4])                # 読めない Xyz は進行に入らない
        self.assertEqual(sheet[0]["segs"][0]["lyric"], "まえがき")             # コードの無い行も出す

    def test_same_order_as_import(self):
        song, _ = cd.from_chordwiki(PAGE)
        self.assertEqual(cd.sheet_chords(cd.sheet_from_chordwiki(PAGE)), cd.parse_progression(song["text"])[0])

    def test_from_text(self):
        sheet = cd.sheet_from_text("C Am7 | F\n\nG7 Xyz C")
        self.assertEqual(len(sheet), 2)
        self.assertEqual([(s["chord"], s["ci"], s["bar"]) for s in sheet[0]["segs"]],
                         [("C", 0, False), ("Am7", 1, False), (None, None, True), ("F", 2, False)])
        self.assertEqual([s["ci"] for s in sheet[1]["segs"]], [3, None, 4])


class LyricsDisplayOnlyTest(AppTestBase):
    def setUp(self):
        super().setUp()
        fd, name = tempfile.mkstemp(suffix=".html")
        os.write(fd, PAGE.encode("utf-8"))
        os.close(fd)
        self.page_path = Path(name)
        self.addCleanup(lambda: self.page_path.unlink(missing_ok=True))

    def import_song(self):
        r = self.app.import_chordwiki(0, PAGE, source=str(self.page_path))
        self.app.chord.select_song(0)
        return r

    def lyrics_in(self, sheet):
        return "".join(s["lyric"] for ln in sheet if ln["kind"] == "line" for s in ln["segs"])

    def test_lyrics_shown_but_never_saved(self):
        self.import_song()
        v = self.app.chord_view()
        self.assertIn("あいう", self.lyrics_in(v["sheet"]))
        self.assertEqual(v["sheet_note"], "")
        self.assertEqual(self.app.chordbook.songs[0].source, str(self.page_path))
        for f in Path(self.app.store.user_dir).rglob("*.json"):              # どの保存ファイルにも歌詞は無い
            text = f.read_text(encoding="utf-8")
            for word in LYRICS:
                self.assertNotIn(word, text, f.name)

    def test_transposed_names_follow_key(self):
        self.import_song()
        self.app.chord_key(None, 2)
        v = self.app.chord_view()
        self.assertEqual(v["sheet"][2]["segs"][0]["chord"], "D")

    def test_edited_text_hides_lyrics(self):
        self.import_song()
        self.app.save_song(0, "ウィキの曲", 0, "C F G")
        v = self.app.chord_view()
        self.assertEqual(self.lyrics_in(v["sheet"]), "")
        self.assertIn("編集", v["sheet_note"])
        self.assertEqual(self.app.chordbook.songs[0].source, str(self.page_path))  # 場所は覚えたまま

    def test_missing_page(self):
        self.import_song()
        self.page_path.unlink()
        v = self.app.chord_view()
        self.assertEqual(self.lyrics_in(v["sheet"]), "")
        self.assertIn("見つからない", v["sheet_note"])
        self.assertEqual(len(v["sheet"]), 2)                                  # 行と小節線の流れは出す

    def test_song_without_source(self):
        self.app.save_song(1, "手入力", 0, "C | F G")
        self.app.chord.select_song(1)
        v = self.app.chord_view()
        self.assertEqual(v["sheet_note"], "")
        self.assertEqual(len(v["sheet"]), 1)
