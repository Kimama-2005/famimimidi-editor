# ふぁみみみっでぃ 音色エディタ / ライブラリアン

ファミコン用MIDI音源カートリッジ「ふぁみみみっでぃ」(Famimimidi) 専用の、音色編集・管理ソフトを作るプロジェクト。
このリポジトリには、claude.ai での事前調査と実機検証の結果が入っている。作業を始める前に `docs/` を読むこと。

## ユーザーについて

- 日本語で話す。説明も日本語で。
- MIDIの専門家ではないが飲み込みが速く、実機テストを的確に報告してくれる。専門用語は初出で一言添える。
- **「PC」「マクロ」は分かりにくいと言われた(2026-09-29)。** ユーザー向けの画面・説明では「保存場所」「呼び出し番号」「電源を入れたときの音色」と言い換える。細かい操作は「詳細な管理」に置き、簡易版を標準の入口にする。
- 実機テストの手順が多いと、手順の抜けや取り違えが起きる。手作業はできるだけ減らし、ファイル再生やアプリの自動操作にする。
- 実機(ファミコン+カートリッジ)を持っているのはユーザーだけ。**Claudeは音を聴けない。** ハードウェアに関わる機能は、ユーザーが耳で判定できるテスト手順とセットで作ること。
- 使用環境: Windows、Domino(MIDIシーケンサー)、Cubase、KORG KROSS2、KORG microKEY、USB-MIDIインターフェース(IN/OUT各1)。詳細は `docs/01_environment.md`。
- 技術方針(2026-09-29 合意): Python の Windows デスクトップアプリ。オフラインで動くこと。画面は pywebview(HTML/CSS/JS、外部 CDN なし)。仕様は `docs/SPEC_v2.md`。
- 実機テスト用MIDIファイルは `hw_tests/make_tests.py` で生成する(出力 `hw_tests/out/`)。

## 絶対に守る事実(実機で確定済み)

1. **ユーザーマクロに記録できるのは先頭10個のCCまで。** 11個目以降はエラーも出さず捨てられる。マクロに入れるCCは重要度順に並べる。
2. **CC#51の値 v = プログラムチェンジのデータバイト v(0始まり)。** v=92 → PC93(1始まり表記)。UIでは両方の表記を併記する。
3. **CC#121(Reset All Controllers)は発音中の音を全部止める。** 音色のシームレス切替には使わない。
4. **記録中(CC#45=1〜40 の間)に送ったCCは、記録されると同時に実際の音にも反映される。**
5. **カートリッジの中身を読み出す方法は無い。** どのマクロ番号・PC番号に何を書いたかは、ソフト側で記録・管理するしかない。
6. **ユーザーマクロ(PC89〜128)への書き込み、CC#50、SysExの波形登録(PC61〜76)はカートリッジに保存される。** 書き込み操作は必ず確認ダイアログを出す。
7. MIDI DINは1バイト約0.32ms。CC1個≒0.96ms、PC1個≒0.64ms。32個のCCを送ると約30msかかり、拍の頭では遅れて聴こえる。
8. **ユーザーマクロとPC割り当ては電源を切っても残る。**
9. **CC#7=0 で消した音は、PCを変えても戻らない。** 無音テストで「戻る」を判定に使うなら、戻す側にも CC#7=127 を入れる。
10. **Domino は1トラックに複数チャンネルが混ざったMIDIファイルを読めない。** 書き出しは format 1、チャンネルごとに1トラック。
11. **CC#50(電源ONマクロ)は効く。** 現在 ch1 の電源ONマクロはマクロ11(J-POP 標準)なので、電源を入れた直後の ch1 は実装表の初期値ではない。
12. **ユーザーマクロはチャンネルを記録しない。** 記録中にどのchへ送ったCCも「CC番号と値」だけが残り、実行したchに効く。1マクロで複数chは変えられない。
13. **PCの切り替えは KROSS2・PC など MIDI 側で行う**(ユーザー判断)。ファミコンのコントローラーは使わない。
14. **PC→マクロの対応表は全chで共通。マクロは PC を受けたchだけに効く。**
15. **ch5 の DPCM には音量(CC#7)が効かない。** ch5 のテストに無音判定は使えない。
16. **「復旧用ファイルを再生した」という報告だけで状態を確定させない。** T0 の再生は PC 割り当てに効いていなかった(docs/03 F26)。書き込み後はアプリの「PCを1つずつ試す」で確かめる。
17. **アプリは同時に1つしか動かさない**(`single.py`)。2つ動くと、両方が同じ鍵盤の演奏を受け取って二重に送る(Windows 11 は同じ MIDI 入力を複数のアプリで開ける)。報告とログが合わないときは、まず二重起動を疑う。**Domino・Cubase などほかのソフトが同じ鍵盤を開いて ふぁみみみっでぃ へ直接流していることもある**(2026-11-04、ログに無い音が鳴った)。起動時に Domino/Cubase/KROSS2 Editor が動いていれば警告する(`single.other_midi_apps`)

未確認事項(ファミコンのコントローラーでPC89〜128に届くか、など)は `docs/03_verified_findings.md` にある。**未確認の事柄を確定として扱わないこと。**

## 開発ルール

- 仕様の一次ソースは `data/famimimidi_spec.json`(実装表をJSON化したもの)と `docs/Famimimidi_implement_chart_v10.pdf`(ファミコン版、日本語。**作者さんの資料なので公開版には含めない**。手元の main の履歴にだけある)。NES版とは細部が違うので、ネットのNES版資料を鵜呑みにしない。
- 実機テストを設計するときは、**判定を二択にする**(鳴る/無音 など)。「細い/太い」のような聴感判定は取り違えが起きた。調べたいCCを**先頭**に置くこと(容量10個問題で痛い目を見た)。
- 何か送るたびに、送信バイトとタイムスタンプをログに残す。ユーザーの報告と突き合わせるため。
- Windowsの古いMIDIドライバは**1ポートを同時に1アプリしか開けない**ことがある。Domino/Cubaseを開いたままだとポートを掴めない。エラー時はそれを案内する。
- 書き込み系の機能を実装したら、ユーザーに実機で確かめてもらうまで「完成」と言わない。
- **新しい画面の見た目の確認に、デスクトップ全体のスクリーンショット(ImageGrab など)は使わない。** ユーザーの別のウィンドウが写り込む(実際に起きた)。動作は pywebview を偽ポート・一時 user_data で隠して開き、JS から数字で確かめる(座標・送ったバイト・音源の波)。見た目は1ファイルの HTML(`.preview/`、履歴外)をアプリ内のブラウザ欄で見る。

## GitHub での公開(2026-10-06 ユーザーと合意)

- https://github.com/Kimama-2005/famimimidi-editor (2026-10-06 に公開 → 作者さんへの確認のため一時非公開 → **2026-10-10 作者さんに確認済み、公開**。クレジットは README と画面の「接続と設定」に入れている。作者さんとのやりとりの中身は公開側に書かない)。ライセンス MIT。ソフト名 FAMIMIMIDI SOUND EDITOR。README に「非公式」と作者さん(@hekekekun)への配慮を明記
- **手元の main は公開しない**(実装表 PDF が履歴に入っている)。公開用は main とつながらないブランチ `public` を `python tools/publish.py "メッセージ" --author "名前 <noreply メール>"` で作り、`git push origin public:main` で送る
- **リリース**(2026-11-06 に v2.0.0 を公開): 公開用の `public` から、起動に要るものだけの zip を作って添付する。`git archive --format=zip --prefix=famimimidi-editor/ -o FAMIMIMIDI-SOUND-EDITOR-vX.Y.Z.zip public run.bat make_shortcut.bat requirements.txt README.md LICENSE THIRD_PARTY_NOTICES.md famimimidi2 data vendor` → 展開して `vendor/wheels` から部品が入りアプリを読み込めるか確かめる → `gh release create vX.Y.Z <zip> --target <public の完全なコミット> --notes-file …`(短いコミット番号は断られる)。公開はユーザーの OK のあと
- 作者さんの一次資料(実装表の PDF など)を公開側に入れない。`tools/publish.py` の EXCLUDE に足す(フォルダも指定できる)

## コード構成

**2026-11-05 に作り直し版(`famimimidi2/`、仕様は `docs/SPEC_v2.md`)へ差し替え、2026-11-06 に以前の版(`famimimidi/`・`tests/`・旧画面の手順書など)を消した**(git の履歴にはある)。以前の版が書いたファイル(v1)を見つけたら、`model/migrate.py` が読むときに新しい形へ移す(`data/patches.json` も v1 の形)。

| パス | 内容 |
|---|---|
| `run.bat` | アプリを起動(`python -m famimimidi2`)。フォルダに書き込めるか確かめ、使える `.venv` が無ければ `%LOCALAPPDATA%\FamimimidiEditor\venv` を `vendor/wheels` からオフラインで作る(別のパソコンへのコピー対策)。**cp932・CRLF で保存し、2行目の `chcp 932` を消さない**(日本語の行が壊れる)。**Git Bash の `sed -i` で触ると CRLF が LF になる**ので、バイト単位で直す |
| `famimimidi2/device/` | 機器の層。`gate.py` = **送信の関所**(すべての送信はここ。書き込み系 CC#45/50/51 は `write_ok` のときだけ、CC#121 は送らない、CC の間引き、音量0の ch へのノートオンを省く、送信ログ `logs/日付.log`)。`winmm.py`(winmm の ctypes)、`single.py`(二重起動の防止とほかの MIDI ソフトの警告)、`sysex.py`(ch5 波形の SysEx) |
| `famimimidi2/device/virtual.py` / `famimimidi2/web/vfc.js` | **🎮 仮想ファミコン**: ふぁみみみっでぃ無しで試すための出力ポートの偽物と、画面の音源(WebAudio。実装表の値どおりにそれっぽく鳴らす)。仮想のときはカートリッジへの書き込みと実機の確認を止める(控えを守る) |
| `famimimidi2/model/` | データの層(送信しない)。`tone.py` 音色、`performance.py` 演奏セット(Part・KeyboardMap・Controls・ChordSettings)、`session.py` 作業中の演奏、`library.py`、`chordbook.py` 曲、`prefs.py` 設定、`cartmirror.py` カートリッジの控え、`store.py` 保存(一時ファイル→置き換え、読めないファイルは上書きしない)、`migrate.py` 以前の版からの移行(元は `user_data/old_v1/`) |
| `famimimidi2/music/` | 音楽の計算。`spec.py` 実装表、`tonecards.py` 音色づくりのカード、`chords.py` コード・鍵盤の配置(曲の弾きやすさ重視。もう1つの「度数+補足」は degree.py)・ボイシング・ChordWiki 取り込み(**歌詞は取り込まない**。歌詞は保存したページから表示するときだけ読む `sheet_from_chordwiki`。曲には場所 `source` だけ)、`waves.py` 波形の見本、`degree.py` コードモードの配置「度数+補足」(インスタコード風。基本コードの鍵+補足の鍵の同時押し、C4 で左右に分ける) |
| `famimimidi2/performance/` | 時間で動くもの。`router.py` 鍵盤の振り分け(**タブで決まる**: 1〜5 はその ch、♪ は割り当て表かコードモード)、`chordmode.py` コードモード、`scheduler.py` ただ1本のスケジューラ |
| `famimimidi2/cartridge/` | カートリッジへの書き込み。`plans.py` 計画(文言と手順)、`writer.py` 実行、`mirror.py` **控えを書き換えてよいのはここだけ**、`tidy.py` 整える(土台と後始末)。マクロの10項目は重要度順に自動で選ぶ |
| `famimimidi2/checks.py` | ✓ 実機の確認モード(アプリが鳴らし、答えはボタン。結果は `user_data/checks/`) |
| `famimimidi2/app.py` | アプリ本体(画面から独立)。接続・タブ・音色・演奏セット・コード・カートリッジ・確認の操作 |
| `famimimidi2/bridge.py` / `famimimidi2/web/` | 画面(pywebview)。`Bridge` が画面⇔Python の窓口(公開メソッドだけ)。`evaluate_js` を呼ぶのは JsDispatcher の1本だけ。画面は HTML/CSS/JS(外部 CDN なし)、テーマは CSS 変数(rpg/console/crt) |
| `tests_v2/` | 実機なしのテスト(`python -m unittest discover -s tests_v2 -t .`。`-t .` が要る)。実際の `user_data` は書き換えない(`paths.py` で一時フォルダへ) |
| `tools/` | `make_icon.py`(アイコンを作る。Pillow が必要)、`publish.py`(公開用の履歴を作る) |
| `make_shortcut.bat` | デスクトップにアイコン付きのショートカットを作る |
| `famimimidi2/icon.ico` / `web/icon.png` | アイコン(ファミコンのカセット+音符のドット絵) |
| `hw_tests/` | 実機テストの MIDI ファイル生成(`make_tests.py`)と、MIDI ファイルで試す手順書(ROUND2・ROUND3・V0)。アプリの機能の確認は「✓ 実機の確認」を使う |

送信は必ず `Gate.send()` を通すこと(ログと遮断がそこにある)。

## ドキュメント

| ファイル | 内容 |
|---|---|
| `docs/01_environment.md` | 機材、接続、ユーザーのソフト環境 |
| `docs/02_midi_spec.md` | MIDI仕様の要点と、ファミコン版/NES版の差分 |
| `docs/03_verified_findings.md` | **実機検証ログ。確定/未確定、カートリッジの現在の状態、テスト手法** |
| `docs/04_sound_design.md` | 音作りのノウハウ(パラメーターの実際の効き方) |
| `docs/SPEC_v2.md` | **作り直し用の仕様書**(2026-11-05)。データの置き場所(音色・演奏セット・作業中の演奏・曲・控え・設定)と振る舞いを厳密に定義。新しい版はこれを元に作る |
| `docs/06_roadmap.md` | **今後の計画**(A〜D 完了。E: 演奏セット、F: コードモード) |
| `data/famimimidi_spec.json` | 全CC・PC・SysEx・ノートマップの機械可読定義 |
| `data/patches.json` | これまでに作った音色とドラムキット定義 |
| `reference/` | claude.ai 上で使ったPythonスクリプト(MIDIファイル生成、マクロ書き込み、検証用) |
