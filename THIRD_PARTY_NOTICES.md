# 同梱しているもの(第三者のソフトウェア・素材)

このリポジトリの MIT ライセンス(`LICENSE`)は、下の第三者のものには適用されません。それぞれのライセンスに従います。

## フォント
| 名前 | 場所 | ライセンス |
|---|---|---|
| DotGothic16(Fontworks) | `famimimidi/web/fonts/DotGothic16-Regular.ttf` | SIL Open Font License 1.1(全文: `famimimidi/web/fonts/OFL.txt`) |

## Python の部品(`vendor/wheels/`)
オフラインで入れられるように、配布されているファイル(wheel)をそのまま同梱しています。各ファイルの中にライセンス全文が入っています。

| 名前 | 版 | ライセンス |
|---|---|---|
| pywebview | 6.2.1 | BSD-3-Clause |
| pythonnet | 3.2.0 | MIT |
| clr_loader | 0.3.1 | MIT |
| cffi | 2.1.1 | MIT-0 |
| pycparser | 3.0 | BSD-3-Clause |
| bottle | 0.13.4 | MIT |
| proxy_tools | 0.1.0 | MIT |
| typing_extensions | 4.16.0 | PSF-2.0 |

## ふぁみみみっでぃの仕様について
`data/famimimidi_spec.json` は、このソフトを動かすために必要な MIDI 実装の事実(CC 番号・値の範囲・チャンネルごとの対応など)を、開発者が JSON に書き起こしたものです。
ふぁみみみっでぃの実装表そのもの(PDF)は同梱していません。作者さんの公式サイト http://famimimidi.dojin.com で公開されている資料を参照してください。
