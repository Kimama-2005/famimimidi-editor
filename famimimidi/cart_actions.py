"""カートリッジへの書き込みの「計画」を作る(画面から独立)。新しい画面(webapp)が使う。

計画 = 確認画面に出す文と、送る手順と、成功/失敗したときの対応表の更新。
実行は Core.run_write()(前後のパニック、書き込み中の送信停止、対応表の保存)で行う。
言葉は「保存場所」「呼び出し番号」「電源を入れたときの音色」(CLAUDE.md: PC・マクロという言葉を出さない)。
"""
from dataclasses import dataclass, field
from typing import Callable

from .cartridge import (MACROS, MAX_CCS, NEUTRAL_MACRO, PCS, RESERVED, plan_assign, plan_assign_many, plan_record,
                        validate)
from .sets import apply_ops, base_id, build_tidy, cc_for_single_save, full_values, status
from .wave import PCS as WAVE_PCS, plan_register


def place_of(pc):
    return pc - PCS[0] + 1


@dataclass
class WritePlan:
    title: str
    lines: list
    steps: list
    on_success: Callable
    on_failure: Callable
    done_message: str
    ok_text: str = "保存する"
    after: list = field(default_factory=list)      # 成功後に画面へ伝えたいこと(例: 整えるのがおすすめ)


def name_of(cart, pc):
    m = cart.pc_map.get(pc)
    if m is None:
        return "(不明 — 呼び出して確かめてください)"
    if m == NEUTRAL_MACRO:
        return "(空き)"
    return cart.slot(m).label


def places(core):
    """保存場所 40 か所の一覧"""
    out = []
    for pc in PCS:
        m = core.cart.pc_map.get(pc)
        pid = core.cart.slot(m).patch_id if m is not None else ""
        p = core.lib.get(pid) if pid else None
        out.append({"pc": pc, "place": place_of(pc), "name": name_of(core.cart, pc),
                    "empty": m == NEUTRAL_MACRO, "channel": p.channel if p else None})
    return out


def startup_rows(core):
    st = core.cart
    rows = []
    for ch in range(1, 6):
        m = st.startup.get(ch)
        if m is None:
            text = "わからない(設定していない)"
        elif m == NEUTRAL_MACRO:
            text = "ふつう(何も変えない)"
        elif st.slot(m).patch_id == base_id(ch):
            text = f"ch{ch} の土台(共通の設定)"
        else:
            pcs = st.users(m)[0]
            text = (f"場所 {place_of(pcs[0])}: " if pcs else "") + st.slot(m).label
        rows.append({"ch": ch, "text": text})
    return rows


def tidy_rows(core):
    rows = []
    for ch in range(1, 6):
        s = status(core.cart, core.lib, core.params, ch)
        if s.count == 0:
            text, kind = "このチャンネル用の音色は入っていません", "none"
        elif s.tidy_needed:
            parts = []
            if s.to_rewrite:
                parts.append("、".join(f"場所{place_of(pc)}" for pc in s.to_rewrite) + " で前の音色の設定が残る可能性")
            if not s.base_ok:
                parts.append("土台が最新ではありません")
            text, kind = f"音色 {s.count} 個: " + " / ".join(parts) + " → 整えてください", "warn"
        elif s.unavoidable:
            text = (f"整っています(音色 {s.count} 個)。ただし " + "、".join(f"場所{place_of(pc)}" for pc in s.unavoidable)
                    + " は10項目に入りきらない設定があり、切り替えで残ることがあります")
            kind = "ok"
        else:
            text, kind = f"整っています(音色 {s.count} 個)", "ok"
        rows.append({"ch": ch, "text": text, "kind": kind})
    return rows


def _names(core, ccs):
    return "、".join(core.params[c].name_ja for c in ccs if c in core.params)


def plan_save(core, pc, patch):
    st = core.cart
    ccs, dropped = cc_for_single_save(st, core.lib, core.params, patch, pc)
    if not ccs:
        raise ValueError("この音色は初期設定と同じなので、保存する内容がありません。")
    m = st.macro_for_pc(pc)
    lines = [f"場所 {place_of(pc)} に「{patch.name}」を入れます。"]
    old = name_of(st, pc)
    if old != "(空き)":
        lines.append(f"※ いま入っている「{old}」は消えます。")
    if dropped:
        lines.append(f"※ 1か所に入るのは{MAX_CCS}項目までなので、次の設定は入りません"
                     f"(切り替えたときに前の音色の値が残ることがあります): {_names(core, dropped)}")
    lines.append(f"※ 保存が終わると、呼び出し番号 {pc} でこの音色になります。")
    ch = patch.channel

    def ok(s):
        s.record_done(m, ccs, patch.name, patch.id, pc, None)

    plan = WritePlan("音色を入れる", lines, plan_record(m, ccs, core.engine.midi_ch0(1), pc=pc), ok,
                     lambda s, e, r: s.failed(m, pc, None, r, e),
                     f"場所 {place_of(pc)} に「{patch.name}」を保存しました。\n"
                     "ファミコンの電源を入れ直してから、「呼び出して鳴らす」で確かめてください。")
    plan.after.append(("tidy_check", ch))
    return plan


def plan_clear(core, pc):
    st = core.cart
    if name_of(st, pc) == "(空き)":
        raise ValueError("この場所はもう空いています。")
    return WritePlan("空にする", [f"場所 {place_of(pc)} を空にします。",
                                 f"※ いま入っている「{name_of(st, pc)}」は、この場所からは呼び出せなくなります。"],
                     plan_assign(NEUTRAL_MACRO, core.engine.midi_ch0(1), pc=pc),
                     lambda s: s.assign_done(NEUTRAL_MACRO, pc, None),
                     lambda s, e, r: s.failed(NEUTRAL_MACRO, pc, None, False, e),
                     f"場所 {place_of(pc)} を空にしました。", ok_text="空にする")


def plan_startup(core, ch, pc):
    st = core.cart
    m = st.pc_map.get(pc)
    if m is None or m == NEUTRAL_MACRO:
        raise ValueError("音色の入っている場所を選んでください。")
    return WritePlan("電源を入れたときの音色",
                     [f"電源を入れたときの ch{ch} の音色を、場所 {place_of(pc)}「{name_of(st, pc)}」にします。",
                      "※ 設定の途中で、ch1 の音が一時的にこの音色に変わります。"],
                     plan_assign(m, core.engine.midi_ch0(1), startup_ch=ch),
                     lambda s: s.assign_done(m, None, ch), lambda s, e, r: s.failed(m, None, ch, False, e),
                     f"電源を入れたときの ch{ch} の音色を設定しました。電源を入れ直すと確かめられます。", ok_text="設定する")


def plan_startup_reset(core, ch):
    return WritePlan("電源を入れたときの音色", [f"電源を入れたときの ch{ch} の音色を、ふつう(何も変えない)に戻します。"],
                     plan_assign(NEUTRAL_MACRO, core.engine.midi_ch0(1), startup_ch=ch),
                     lambda s: s.assign_done(NEUTRAL_MACRO, None, ch),
                     lambda s, e, r: s.failed(NEUTRAL_MACRO, None, ch, False, e),
                     f"電源を入れたときの ch{ch} の音色を、ふつうに戻しました。", ok_text="戻す")


def plan_tidy(core, ch):
    st = core.cart
    t = build_tidy(st, core.lib, core.params, ch, core.engine.midi_ch0(1))
    if not t.steps:
        raise ValueError(f"ch{ch} はもう整っています。")
    lines = [f"ch{ch} の音色を整えます(保存し直す場所 {len(t.rewrites)} か所)。"]
    if t.rewrites:
        lines.append("保存し直す場所: " + "、".join(f"場所{place_of(pc)}「{name_of(st, pc)}」" for pc in t.rewrites))
    if t.base_changed:
        if t.plan.base:
            lines.append(f"土台(どの音色にも共通の設定): {_names(core, t.plan.base)}")
            old = t.old_startup
            if old is not None and old != NEUTRAL_MACRO and st.slot(old).patch_id != base_id(ch):
                lines.append(f"※ 電源を入れたときの ch{ch} は「{st.slot(old).label}」から「ch{ch} の土台」に変わります。"
                             "音色は呼び出し番号で選んでください。")
        else:
            lines.append(f"※ 共通の設定が無くなったので、電源を入れたときの ch{ch} を「ふつう」に戻します。")
    for pc, d in t.plan.dropped.items():
        if d:
            lines.append(f"※ 場所{place_of(pc)} は{MAX_CCS}項目に入りきらないため、次の設定は切り替えで残ることがあります: "
                         f"{_names(core, d)}")

    def fail(s, e, r):
        for name, args in t.ops:
            m, pc, sch = (args[0], args[4], args[5]) if name == "record_done" else args
            s.failed(m, pc, sch, name == "record_done", e)

    return WritePlan(f"ch{ch} を整える", lines, t.steps, lambda s: apply_ops(s, t.ops), fail,
                     f"ch{ch} を整えました。ファミコンの電源を入れ直してから、各場所を「呼び出して鳴らす」で確かめてください。",
                     ok_text="整える")


# ---------- 詳細な管理(上級者向け。マクロ・PC という言葉を使ってよい場所) ----------
def tables(core):
    """内部の対応表: マクロ1〜40、PC89〜128、電源ONマクロ"""
    st = core.cart
    macros = []
    for m in MACROS:
        s = st.slot(m)
        pcs, chs = st.users(m)
        use = []
        if pcs:
            use.append("PC" + ",".join(map(str, pcs)) if len(pcs) <= 4 else f"PC {len(pcs)}枠")
        if chs:
            use.append("電源ON ch" + ",".join(map(str, chs)))
        macros.append({"m": m, "label": s.label, "count": None if s.cc is None else len(s.cc), "certain": s.certain,
                       "use": " / ".join(use), "written": s.written[:16].replace("T", " "),
                       "cc": [[core.params[c].name_ja if c in core.params else f"CC#{c}", v] for c, v in (s.cc or [])],
                       "reserved": m in RESERVED})
    pcs = [{"pc": pc, "m": st.pc_map.get(pc), "label": name_of(st, pc)} for pc in PCS]
    return {"macros": macros, "pcs": pcs, "startup": startup_rows(core),
            "free": st.free_macros()}


def candidates(core, patch, pc):
    """くわしく設定して入れる: 10項目の候補(並び順=自動で選ぶときの優先順)と、自動で選ぶ内部番号"""
    ccs, dropped = cc_for_single_save(core.cart, core.lib, core.params, patch, pc)
    full = full_values(patch, core.params, patch.channel)
    rows = [[c, v] for c, v in ccs] + [[c, full[c]] for c in dropped if c in full]
    try:
        auto = core.cart.macro_for_pc(pc)
    except ValueError:
        auto = None
    return {"rows": [[c, v, core.params[c].name_ja, core.params[c].format_value(v)] for c, v in rows],
            "auto_macro": auto}


def plan_advanced(core, patch, m, ccs, pc=None, startup_ch=None):
    """10項目と内部番号を自分で決めて書き込む"""
    st = core.cart
    ccs = [[int(c), int(v)] for c, v in ccs][:MAX_CCS]
    validate(int(m), ccs, pc, startup_ch)
    m = int(m)
    lines = [f"マクロ{m} に「{patch.name}」の {len(ccs)} 項目を記録します。",
             f"※ いまのマクロ{m}: {st.slot(m).label}"]
    pcs, chs = st.users(m)
    others = [p for p in pcs if p != pc]
    if others or chs:
        lines.append(f"※ マクロ{m} は {'PC' + ','.join(map(str, others)) if others else ''}"
                     f"{' 電源ON ch' + ','.join(map(str, chs)) if chs else ''} でも使われています。それらの音もすべて変わります")
    if m in RESERVED:
        lines.append(f"※ マクロ{m} はテスト用に予約している番号です({RESERVED[m]})")
    if pc:
        lines.append(f"PC{pc}(送信値{pc - 1}、場所{place_of(pc)})→ マクロ{m}")
    if startup_ch:
        lines.append(f"ch{startup_ch} の電源ONマクロ → マクロ{m}")
    return WritePlan("くわしく設定して書き込む", lines, plan_record(m, ccs, core.engine.midi_ch0(1), pc, startup_ch),
                     lambda s: s.record_done(m, ccs, patch.name, patch.id, pc, startup_ch),
                     lambda s, e, r: s.failed(m, pc, startup_ch, r, e),
                     f"マクロ{m} に「{patch.name}」を書き込みました。電源を入れ直してから確かめてください。", ok_text="書き込む")


def plan_assign_existing(core, m, pc=None, startup_ch=None):
    """記録済みのマクロ m を、PC や電源ONに割り当てる(マクロの中身は変えない)"""
    st = core.cart
    m = int(m)
    steps = plan_assign(m, core.engine.midi_ch0(1), pc, startup_ch)      # PC も電源ONも無ければ ValueError
    lines = [f"マクロ{m}({st.slot(m).label})を割り当てます。"]
    if pc:
        lines.append(f"PC{pc}(送信値{pc - 1}、場所{place_of(pc)})→ マクロ{m}")
        if st.pc_map.get(pc) not in (NEUTRAL_MACRO, None, m):
            lines.append(f"※ PC{pc} の今の割り当て(マクロ{st.pc_map[pc]} {name_of(st, pc)})を上書きします")
    if startup_ch:
        lines.append(f"ch{startup_ch} の電源ONマクロ → マクロ{m}")
        if st.startup.get(startup_ch) not in (None, m):
            lines.append(f"※ ch{startup_ch} の電源ONマクロ(今はマクロ{st.startup[startup_ch]})を上書きします")
    if st.slot(m).cc is None:
        lines.append(f"※ マクロ{m} の中身は不明です")
    lines.append(f"※ 割り当てのためにマクロ{m} を一度実行するので、ch1 の音が変わります")
    return WritePlan("記録済みのマクロを割り当てる", lines, steps, lambda s: s.assign_done(m, pc, startup_ch),
                     lambda s, e, r: s.failed(m, pc, startup_ch, False, e),
                     "割り当てました。電源を入れ直してから確かめてください。", ok_text="割り当てる")


def plan_assign_many_pcs(core, mapping):
    """複数の PC をまとめて割り当てる。mapping: {pc: マクロ番号}"""
    st = core.cart
    mapping = {int(pc): int(m) for pc, m in mapping.items()}
    changed = [pc for pc, m in mapping.items() if st.pc_map.get(pc) != m]
    groups = {}
    for pc, m in sorted(mapping.items()):
        groups.setdefault(m, []).append(pc)
    lines = [f"{len(mapping)} 個の PC を割り当てます(対応表と違うもの {len(changed)} 個)。"]
    for m, pcs in groups.items():
        lines.append(f"マクロ{m}({st.slot(m).label})← PC" + ",".join(map(str, pcs)))
    lines.append("※ 割り当てのために各マクロを一度実行するので、ch1 の音が変わります。終わったら電源を入れ直してください")
    return WritePlan("まとめて割り当て", lines, plan_assign_many(mapping, core.engine.midi_ch0(1)),
                     lambda s: s.assign_many_done(mapping), lambda s, e, r: s.assign_many_failed(mapping, e),
                     f"{len(mapping)} 個の PC を割り当てました。電源を入れ直してから「1つずつ試す」で確かめられます。",
                     ok_text="割り当てる")


def plan_wave(core, pc, samples, name):
    if pc not in WAVE_PCS:
        raise ValueError("登録先は PC61〜76 です")
    old = core.cart.waves.get(pc)
    return WritePlan("波形を登録",
                     [f"波形「{name}」を PC{pc} に登録します。",
                      "※ " + (f"いま登録されている「{old['name']}」は消えます。" if old else
                              "この場所に以前なにが登録されていたかは、このソフトでは分かりません(上書きされます)。"),
                      f"※ 登録後は、ch5 を波形メモリにして PC{pc} を送ると、この波形になります。"],
                     plan_register(samples, pc), lambda s: s.wave_done(pc, samples, name),
                     lambda s, e, r: s.wave_failed(pc, e),
                     f"PC{pc} に「{name}」を登録しました。電源を入れ直してから、呼び出して確かめてください。", ok_text="登録する")
