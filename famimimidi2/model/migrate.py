"""以前の版(v1 = famimimidi/ が書いたファイル)からの移行(SPEC_v2 9章)。純粋な変換だけ(ファイルは store が扱う)。

| 以前の版 | 作り直し後 |
|---|---|
| library.json v2 patches[] | tones[](channel → kind、cc → params。#82・#20・#2・#64・#84 と既定値は外す) |
| library.json v2 sets[] | performances[](parts → slots、play → keyboard、chord → 5.5 の形)。
  ポリでも ch1 と ch2 が違う音なら紐付けない(今の音のまま) |
| settings.json の play・chord | session.json の performance.keyboard・chord(5ch の音色は既定値) |
| settings.json のそのほか | prefs.json(thru・thru_remap・view・layer_detune は捨てる) |
| cartridge.json v1 | cartridge.json famimimidi-cart-v1(中身の数値は1つも変えない) |
| chords.json | chordbook.json(形は同じ) |
"""
from ..music.spec import CH_KIND, CHS, Spec
from .cartmirror import NEUTRAL_MACRO, SILENT_MACRO, CartMirror, MacroRecord
from .chordbook import ChordBook
from .library import Library
from .performance import (BEND_RANGES, ChordSettings, Controls, KeyboardMap, Part, Performance, Slot)
from .prefs import Prefs
from .session import Session
from .tone import Tone, blank_tone, clean_params

CHANNEL_KIND = CH_KIND


def is_v1_library(d):
    return "format" not in d and ("patches" in d or "sets" in d)


def is_v1_cart(d):
    return "format" not in d and "macros" in d


# ---------------------------------------------------------------- 音色
def tone_from_v1(p: dict, spec: Spec) -> Tone:
    """library.json の patches[] の1つ(または data/patches.json の1つ)→ Tone"""
    kind = CHANNEL_KIND[int(p.get("channel", 1))]
    params, _ = clean_params(p.get("cc") or [], kind, spec)
    notes = p.get("notes") if p.get("notes") is not None else p.get("desc", "")
    wave = p.get("wave") if kind == "dpcm_wave" else None
    return Tone(name=p.get("name", ""), kind=kind, params=params, wave=wave, category=p.get("category", "other"),
                notes=notes or "", source=p.get("source", ""), id=p.get("id", ""),
                created=p.get("created", ""), updated=p.get("updated", ""))


# ---------------------------------------------------------------- 割り当て表・コードモード
def keyboard_from_v1(play: dict | None) -> KeyboardMap:
    """play(pair / parts{on, lo, hi, shift, ctl} / mode)→ KeyboardMap。mode と ctl は捨てる"""
    play = play or {}
    if "parts" not in play:
        return KeyboardMap()
    parts = {}
    for ch in CHS:
        g = (play.get("parts") or {}).get(str(ch)) or (play.get("parts") or {}).get(ch) or {}
        parts[ch] = Part(**{k: g[k] for k in ("on", "lo", "hi", "shift") if k in g}) if g else Part(on=(ch == 1))
    return KeyboardMap(play.get("pair", "off"), parts).normalized()


def chord_from_v1(c: dict | None) -> ChordSettings:
    """以前の版のコードモードの15項目 → 6項目。細かい値は近い奏法プリセットへ"""
    c = c or {}
    if not c:
        return ChordSettings()
    release = int(c.get("release_ms", 0) or 0)
    if not c.get("strum_change", False) and release == 0:
        style = "organ"
    elif release >= 200:
        style = "pad"
    elif int(c.get("strum_order", 0) or 0) == 1:
        style = "strum"
    else:
        style = "piano"
    return ChordSettings(active=bool(c.get("active", False)), layout=c.get("layout", "song"),
                         method=c.get("method", "split"), style=style, spread=int(c.get("strum_ms", 30) or 0),
                         bass="mid" if int(c.get("bass_floor", 36) or 36) >= 48 else "low",
                         glide=bool(c.get("glide", False))).normalized()


# ---------------------------------------------------------------- 演奏セット
def performance_from_v1(s: dict, spec: Spec) -> Performance:
    parts = {int(k): v for k, v in (s.get("parts") or {}).items()}
    slots = {}
    for ch in CHS:
        part = parts.get(ch) or {}
        kind = CH_KIND[ch]
        params, _ = clean_params(part.get("cc") or [], kind, spec)
        tone = Tone(name=part.get("name", ""), kind=kind, params=params,
                    wave=part.get("wave") if kind == "dpcm_wave" else None)
        slots[ch] = Slot(tone, part.get("source", ""))
    keyboard = keyboard_from_v1(s.get("play"))
    controls = Controls.defaults_for(keyboard)
    ch1_cc = {int(c): int(v) for c, v in (parts.get(1) or {}).get("cc") or []}
    if 82 in ch1_cc:
        controls.bend_range = min(BEND_RANGES, key=lambda r: abs(r - ch1_cc[82]))
    if ch1_cc.get(20, 0) >= 64:
        controls.mod_use = "duty"
    perf = Performance(name=s.get("name", ""), id=s.get("id", ""), notes=s.get("notes", ""), slots=slots,
                       link12=False, keyboard=keyboard, controls=controls, chord=chord_from_v1(s.get("chord")),
                       created=s.get("created", ""), updated=s.get("updated", ""))
    if keyboard.pair == "poly" and _same_sound(slots[1].tone, slots[2].tone):
        # ch1 と ch2 が同じ音のときだけ紐付ける。違う音のセットは今の音のまま移す(2026-11-05 ユーザーの選択 B)
        perf.set_link12(True)
    return perf


def _same_sound(a: Tone, b: Tone):
    return sorted(map(tuple, a.params)) == sorted(map(tuple, b.params)) and a.wave == b.wave


def library_from_v1(d: dict, spec: Spec) -> Library:
    return Library([tone_from_v1(p, spec) for p in d.get("patches", [])],
                   [performance_from_v1(s, spec) for s in d.get("sets", [])])


# ---------------------------------------------------------------- settings.json
def session_from_v1(settings: dict, spec: Spec) -> Session:
    """以前の版では 5ch の音色はどこにも保存されていなかったので既定値。割り当て表とコードの設定だけ持ってくる"""
    keyboard = keyboard_from_v1(settings.get("play"))
    perf = Performance(name="", slots={ch: Slot(blank_tone(CH_KIND[ch])) for ch in CHS}, keyboard=keyboard,
                       controls=Controls.defaults_for(keyboard), chord=chord_from_v1(settings.get("chord")))
    if keyboard.pair == "poly":
        perf.set_link12(True)       # 5ch とも既定値なので ch1 と ch2 は同じ音
    return Session(perf, "", False)


def prefs_from_v1(settings: dict) -> Prefs:
    return Prefs(out_name=settings.get("out_name") or "", in_name=settings.get("in_name") or "",
                 ch_offset=settings.get("ch_offset", 0) or 0, theme=settings.get("theme") or "rpg")


# ---------------------------------------------------------------- cartridge.json
def _role(m, patch_id):
    if patch_id.startswith("__base_ch"):
        return "base:" + patch_id[len("__base_ch"):]
    if m in (NEUTRAL_MACRO, SILENT_MACRO):
        return "neutral"
    return "tone"


def cart_from_v1(d: dict) -> CartMirror:
    """中身の数値は1つも変えない(ユーザーのカートリッジの唯一の控え)。名前だけ直す"""
    macros = {}
    for k, r in (d.get("macros") or {}).items():
        m = int(k)
        pid = r.get("patch_id") or ""
        known = {"cc", "label", "certain", "patch_id", "written"}
        macros[m] = MacroRecord(params=r.get("cc"), label=r.get("label", ""), certain=bool(r.get("certain", False)),
                                from_="" if pid.startswith("__base_ch") else pid, role=_role(m, pid),
                                written=r.get("written", ""), extra={k2: v for k2, v in r.items() if k2 not in known})
    cart = CartMirror(macros, {int(pc): m for pc, m in (d.get("pc_map") or {}).items()},
                      {**{ch: None for ch in CHS}, **{int(ch): m for ch, m in (d.get("startup") or {}).items()}},
                      {int(n): w for n, w in (d.get("waves") or {}).items()}, list(d.get("history") or []))
    if d.get("note"):
        cart.note = d["note"]
    return cart


def chordbook_from_v1(d: dict) -> ChordBook:
    return ChordBook.from_dict({**d, "format": d.get("format") or "otamachord-set-v1"})
