"""標準MIDIファイル(SMF)の書き出し。標準ライブラリのみ。

Domino は1トラックに複数チャンネルが混ざったファイルを読めない(CLAUDE.md 事実10)ので、
format 1 で「トラック0 = テンポと名前」「以降 = チャンネルごとに1トラック」にする。
"""
import struct

TPQ = 480


def vlq(n):
    out = [n & 0x7F]
    n >>= 7
    while n:
        out.append((n & 0x7F) | 0x80)
        n >>= 7
    return bytes(reversed(out))


def _meta_text(kind, text):
    # 日本語版 Windows の Domino / Cubase は SMF 内の文字を Shift_JIS(cp932)として読む
    b = text.encode("cp932", errors="replace")
    return b"\xFF" + bytes([kind]) + vlq(len(b)) + b


def _track(events, name=None, tempo_us=None):
    """events: [(tick, bytes)] 同じ tick は並び順を保つ"""
    d = b""
    if name:
        d += vlq(0) + _meta_text(0x03, name)
    if tempo_us:
        d += vlq(0) + b"\xFF\x51\x03" + tempo_us.to_bytes(3, "big")
    last = 0
    for t, msg in sorted(events, key=lambda e: e[0]):   # sorted は安定なので同 tick の順序は保たれる
        d += vlq(t - last) + msg
        last = t
    d += vlq(0) + b"\xFF\x2F\x00"
    return b"MTrk" + struct.pack(">I", len(d)) + d


def build(tracks, title="", bpm=120):
    """tracks: [(トラック名, [(tick, bytes)])] → SMF のバイト列。各トラックは1チャンネルだけにすること"""
    for name, events in tracks:
        chans = {m[0] & 0x0F for _, m in events if m and m[0] < 0xF0}
        if len(chans) > 1:
            raise ValueError(f"トラック「{name}」に複数のチャンネルが混ざっています")
    body = [_track([], name=title or "famimimidi", tempo_us=60_000_000 // bpm)]
    body += [_track(ev, name=name) for name, ev in tracks]
    return b"MThd" + struct.pack(">IHHH", 6, 1, len(body), TPQ) + b"".join(body)
