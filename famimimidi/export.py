"""音色を MIDI ファイルに書き出す(Cubase などの曲の頭に置く用)。

書き方:
  full   … 全項目(既定値+音色の値)。アプリの「読み込んで送る」と同じ内容。前の設定が残らない。CC#121 は使わない
  diff   … 音色に入っている設定だけ。短いが、前の音色の設定が残ることがある
  recall … カートリッジの呼び出し番号(PC)だけ。1つで済むが、保存した10項目しか変わらない
"""
from .smf import build
from .spec import CHANNEL_NAMES, editable_params

MODES = {"full": "設定を全部書く(おすすめ。前の音色の設定が残らない)",
         "diff": "音色の設定だけ書く(短い)",
         "recall": "カートリッジの呼び出し番号だけ書く(保存済みの音色のみ)"}
CC_SPACING = 1      # tick。同じ時刻に並べると順序を変えるソフトがあるので1tickずつずらす


def recall_pc(patch, cart):
    """この音色が入っているカートリッジの呼び出し番号(無ければ None)"""
    for pc, m in sorted(cart.pc_map.items()):
        if m is not None and cart.slot(m).patch_id == patch.id:
            return pc
    return None


def patch_events(patch, ch, params, mode, cart=None, ch_offset=0):
    """→ (events, 注意書き)。ch は音源ch(1〜5)"""
    c0 = ch - 1 + ch_offset
    note = ""
    if mode == "recall":
        pc = recall_pc(patch, cart) if cart else None
        if pc is not None:
            return [(0, bytes([0xC0 | c0, pc - 1]))], ""
        note = f"「{patch.name}」はカートリッジに保存されていないので、全項目で書きました"
        mode = "full"
    valid = {p.cc: p for p in editable_params(params, ch)}
    if mode == "full":
        vals = patch.cc_dict()
        pairs = [(c, vals.get(c, p.default)) for c, p in sorted(valid.items()) if vals.get(c, p.default) is not None]
    else:
        pairs = [(c, v) for c, v in patch.cc if c in valid]
    skipped = [c for c, _ in patch.cc if c not in valid]
    if skipped:
        note = (note + " / " if note else "") + f"ch{ch} では効かない設定を省きました(CC#{', #'.join(map(str, skipped))})"
    return [(i * CC_SPACING, bytes([0xB0 | c0, c, v])) for i, (c, v) in enumerate(pairs)], note


def export_set(assign, params, mode, cart=None, ch_offset=0, bpm=120):
    """assign: {ch: patch}。→ (SMF のバイト列, 注意書きのリスト)"""
    tracks, notes = [], []
    for ch in sorted(assign):
        patch = assign[ch]
        ev, note = patch_events(patch, ch, params, mode, cart, ch_offset)
        tracks.append((f"ch{ch} {CHANNEL_NAMES[ch]}: {patch.name}", ev))
        if note:
            notes.append(note)
    return build(tracks, title="famimimidi 音色設定", bpm=bpm), notes
