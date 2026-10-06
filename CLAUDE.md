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
- 技術方針(2026-09-29 合意): Python の Windows デスクトップアプリ。オフラインで動くこと。詳細は `docs/05_requirements.md` の「合意事項」。
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
17. **アプリは同時に1つしか動かさない**(`single.py`)。2つ動くと、両方が同じ鍵盤の演奏を受け取って二重に送る(Windows 11 は同じ MIDI 入力を複数のアプリで開ける)。報告とログが合わないときは、まず二重起動を疑う。

未確認事項(ファミコンのコントローラーでPC89〜128に届くか、など)は `docs/03_verified_findings.md` にある。**未確認の事柄を確定として扱わないこと。**

## 開発ルール

- 仕様の一次ソースは `data/famimimidi_spec.json`(実装表をJSON化したもの)と `docs/Famimimidi_implement_chart_v10.pdf`(ファミコン版、日本語。**作者さんの資料なので公開版には含めない**。手元の main の履歴にだけある)。NES版とは細部が違うので、ネットのNES版資料を鵜呑みにしない。
- 実機テストを設計するときは、**判定を二択にする**(鳴る/無音 など)。「細い/太い」のような聴感判定は取り違えが起きた。調べたいCCを**先頭**に置くこと(容量10個問題で痛い目を見た)。
- 何か送るたびに、送信バイトとタイムスタンプをログに残す。ユーザーの報告と突き合わせるため。
- Windowsの古いMIDIドライバは**1ポートを同時に1アプリしか開けない**ことがある。Domino/Cubaseを開いたままだとポートを掴めない。エラー時はそれを案内する。
- 書き込み系の機能を実装したら、ユーザーに実機で確かめてもらうまで「完成」と言わない。
- **新しい画面の見た目の確認に、デスクトップ全体のスクリーンショット(ImageGrab など)は使わない。** ユーザーの別のウィンドウが写り込む(実際に起きた)。動作は pywebview を偽ポートで開いて JS から確かめ、見た目は Bridge の答えを埋め込んだ1ファイルの HTML(`.preview/single.html`、履歴外)をアプリ内のブラウザ欄で見る。

## GitHub での公開(2026-10-06 ユーザーと合意)

- 公開リポジトリ。ライセンス MIT。ソフト名 FAMIMIMIDI SOUND EDITOR。README に「非公式」と作者さん(@hekekekun)への配慮を明記
- **手元の main は公開しない**(実装表 PDF が履歴に入っている)。公開用は main とつながらないブランチ `public` を `python tools/publish.py "メッセージ" --author "名前 <noreply メール>"` で作り、`git push origin public:main` で送る
- 作者さんの一次資料(実装表の PDF など)を公開側に入れない。`tools/publish.py` の EXCLUDE に足す

## コード構成

| パス | 内容 |
|---|---|
| `run.bat` | **新しい画面**(フェーズC、pywebview)を起動。フォルダに書き込めるか確かめ、使える `.venv` が無ければ `%LOCALAPPDATA%\FamimimidiEditor\venv` を `vendor/wheels` からオフラインで作る(別のパソコンへのコピー対策)。**cp932・CRLF で保存し、2行目の `chcp 932` を消さない**(日本語の行が壊れる) |
| `run_classic.bat` | 予備の tkinter 版(`python -m famimimidi`) |
| `famimimidi/core.py` / `settings.py` | 画面から独立した中身のまとめ役(接続・設定・ライブラリ・対応表) |
| `famimimidi/cart_actions.py` | カートリッジへの書き込みの計画(文言・手順・対応表の更新)。新しい画面が使う。実行は `Core.run_write` |
| `famimimidi/webapp.py` / `famimimidi/web/` | 新しい画面。`Bridge` が画面⇔Python の窓口(中身は `_` 付きで隠す)。画面は HTML/CSS/JS(外部 CDN なし)。テーマは CSS 変数(rpg/console/crt) |
| `famimimidi/winmm.py` | Windows MIDI API(winmm)の ctypes ラッパー |
| `famimimidi/engine.py` | **送信の関所**(書き込み系CCの遮断)、CCの間引き、MIDIスルー、送信ログ(`logs/日付.log`) |
| `famimimidi/play.py` | 鍵盤の弾き方: 外部鍵盤の演奏を ch に振り分ける。割り当て表(ch ごとの鍵域・オクターブ・ホイール、ch1+ch2 の 2音/重ねる)とひな形。engine のスルーが使う。**割り当てはカートリッジに保存できない** |
| `famimimidi/spec.py` | 仕様JSONの読み込み、段階値の変換、ログ用の日本語説明 |
| `famimimidi/app.py` | tkinter の画面(接続・chタブ・全体の配置) |
| `famimimidi/library.py` / `library_ui.py` | ライブラリ(`user_data/library.json`)。2階建て: 音色(Patch、1ch 分)と演奏セット(PerfSet、5ch の音色のコピー+割り当て表)。library_ui は tkinter 版(音色だけ) |
| `famimimidi/audition.py` | 試聴(画面鍵盤・テストフレーズ) |
| `famimimidi/wave.py` / `wave_ui.py` | ch5 波形メモリ(16点×4bit)の SysEx と、描いて試聴・PC61〜76 に登録する画面 |
| `famimimidi/compare.py` / `ab_ui.py` | 音色の A/B 比較(違う設定を影響の大きい順に。効いていない設定は灰色) |
| `famimimidi/easy.py` / `easy_ui.py` | 音色編集のかんたん表示(まとまり・「?」の説明・おまかせ `data/easy_presets.json`)。easy.py は画面から独立 |
| `famimimidi/smf.py` / `export.py` / `export_ui.py` | MIDIファイル書き出し(format 1、chごとにトラック、文字は cp932) |
| `famimimidi/sets.py` | 音色セットの「整える」: 共通の土台(電源ONマクロ)と切り替えの後始末の計算 |
| `famimimidi/simple_ui.py` | **かんたん保存**(ユーザー向けの標準の入口)。「保存場所1〜40」「呼び出し番号89〜128」だけで説明し、マクロ番号・10個の選別(重要度順)は自動 |
| `famimimidi/cartridge.py` / `cartridge_ui.py` | カートリッジ対応表(`user_data/cartridge.json`)、書き込み手順の組み立てと実行、確認ダイアログ |
| `tests/` | 実機なしのテスト(`python -m unittest discover tests`) |
| `tools/` | `make_icon.py`(アイコンを作る。Pillow が必要)、`publish.py`(公開用の履歴を作る) |
| `make_shortcut.bat` | デスクトップにアイコン付きのショートカットを作る |
| `famimimidi/icon.ico` / `web/icon.png` | アイコン(ファミコンのカセット+音符のドット絵) |
| `hw_tests/` | 実機テストの MIDI ファイル生成と手順書 |

送信は必ず `MidiEngine.send()` を通すこと(ログと遮断がそこにある)。

## ドキュメント

| ファイル | 内容 |
|---|---|
| `docs/01_environment.md` | 機材、接続、ユーザーのソフト環境 |
| `docs/02_midi_spec.md` | MIDI仕様の要点と、ファミコン版/NES版の差分 |
| `docs/03_verified_findings.md` | **実機検証ログ。確定/未確定、カートリッジの現在の状態、テスト手法** |
| `docs/04_sound_design.md` | 音作りのノウハウ(パラメーターの実際の効き方) |
| `docs/06_roadmap.md` | **今後の計画**(A〜D 完了。E: 演奏セット) |
| `docs/05_requirements.md` | ソフトの要件案、MVP、技術選択肢、マクロ書き込みアルゴリズム |
| `data/famimimidi_spec.json` | 全CC・PC・SysEx・ノートマップの機械可読定義 |
| `data/patches.json` | これまでに作った音色とドラムキット定義 |
| `reference/` | claude.ai 上で使ったPythonスクリプト(MIDIファイル生成、マクロ書き込み、検証用) |
