"""FAMIMIMIDI SOUND EDITOR(作り直し版、docs/SPEC_v2.md)。

今の版(famimimidi/)とは別のパッケージとして作り、全段がそろったら入れ替える。

層(上の層は下の層だけを使う。SPEC_v2 4.1):
    web / bridge   … 画面
    app            … 状態の持ち主
    performance / cartridge / music
    model          … データ型と JSON(送信しない)
    device         … MIDI ポート、送信の関所、送信ログ
"""
