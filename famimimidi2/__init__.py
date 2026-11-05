"""FAMIMIMIDI SOUND EDITOR(作り直し版、docs/SPEC_v2.md)。

以前の版(famimimidi/)と入れ替えた(以前の版は 2026-11-06 に消した。git の履歴にはある)。

層(上の層は下の層だけを使う。SPEC_v2 4.1):
    web / bridge   … 画面
    app            … 状態の持ち主
    performance / cartridge / music
    model          … データ型と JSON(送信しない)
    device         … MIDI ポート、送信の関所、送信ログ
"""
