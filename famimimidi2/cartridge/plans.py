"""カートリッジへの書き込みの計画(SPEC_v2 6.6.1〜6.6.3)。送らない。

計画 = 確認画面の文・送信手順(待ち時間付き)・成功/失敗したときの控えの更新(ops)。
言葉は「保存場所」「呼び出し番号」「電源を入れたときの音色」(PC・マクロという言葉を出さない)。
待ち時間は実機で成功している以前の版の値(docs/03)。記録に使う ch は ch1(ch は記録されない)。
"""
import copy
from dataclasses import dataclass, field

from ..device import sysex
from ..model.cartmirror import CHS, NEUTRAL_MACRO, PCS, WAVE_SLOTS
from ..model.performance import Performance
from ..model.tone import MACRO_CAPACITY, Tone
from ..music.spec import CH_KIND, Spec
from . import mirror, tidy

GAP, CC_GAP, AFTER_STOP, AFTER_EXEC, AFTER_ASSIGN, WAVE_GAP = 600, 75, 1800, 900, 600, 150
TAB = {1: "1 パルス", 2: "2 パルス", 3: "3 三角波", 4: "4 ノイズ", 5: "5 DPCM/波形"}


@dataclass
class Step:
    wait_ms: int        # この送信の前に待つ時間
    msg: bytes
    text: str
    role: str = ""      # "record_start" など


@dataclass
class WritePlan:
    title: str
    lines: list
    steps: list
    ops: list                                   # [("record"|"assign"|"wave", 引数)]
    done_message: str
    ok_text: str = "書き込む"
    after: list = field(default_factory=list)

    @property
    def seconds(self):
        return sum(s.wait_ms for s in self.steps) / 1000

    def text(self):
        t, out = 0, []
        for s in self.steps:
            t += s.wait_ms
            if s.msg:
                out.append(f"{t / 1000:6.2f}秒  {s.msg.hex(' ').upper():<9} {s.text}")
        out.append(f"合計 約{t / 1000:.1f}秒")
        return "\n".join(out)


def apply_success(cart, plan: WritePlan):
    for kind, a in plan.ops:
        if kind == "record":
            mirror.record_done(cart, **a)
        elif kind == "assign":
            mirror.assign_done(cart, **a)
        elif kind == "wave":
            mirror.wave_done(cart, a["slot"], a["samples"], a["name"])


def apply_failure(cart, plan: WritePlan, error):
    """失敗・途中で止まった: 影響したかもしれない所を全部「不明」にする(控えが実際より良く見えないように)"""
    for kind, a in plan.ops:
        if kind == "wave":
            mirror.wave_failed(cart, a["slot"], error)
        else:
            mirror.failed(cart, a["m"], a.get("pc"), a.get("startup_ch"), kind == "record", error)


# ---------------------------------------------------------------- 送信手順
def _cc(ch0, n, v):
    return bytes([0xB0 | ch0, n, v])


def steps_record(m, params, ch0, pc=None, startup_ch=None):
    if not 1 <= len(params) <= MACRO_CAPACITY:
        raise ValueError(f"1か所に入れられるのは 1〜{MACRO_CAPACITY} 項目です({len(params)} 項目)")
    steps = [Step(0, _cc(ch0, 49, 47), "マクロ切り替え = ユーザー"),
             Step(GAP, _cc(ch0, 45, m), f"マクロ{m} の記録開始", "record_start")]
    for i, (c, v) in enumerate(params):
        steps.append(Step(GAP if i == 0 else CC_GAP, _cc(ch0, c, v), f"記録 {i + 1}/{len(params)}: CC#{c}={v}"))
    steps.append(Step(GAP, _cc(ch0, 45, 0), "記録停止+保存", "record_stop"))
    steps.append(Step(AFTER_STOP, _cc(ch0, 47, m), f"マクロ{m} を実行"))
    return steps + _assign_tail(m, ch0, pc, startup_ch)


def steps_assign(m, ch0, pc=None, startup_ch=None):
    if not pc and not startup_ch:
        raise ValueError("割り当て先がありません")
    return [Step(0, _cc(ch0, 49, 47), "マクロ切り替え = ユーザー"),
            Step(GAP, _cc(ch0, 47, m), f"マクロ{m} を実行")] + _assign_tail(m, ch0, pc, startup_ch)


def _assign_tail(m, ch0, pc, startup_ch):
    steps = []
    if pc:
        steps.append(Step(AFTER_EXEC, _cc(ch0, 51, pc - 1), f"呼び出し番号{pc}(送信値{pc - 1})← マクロ{m}", "assign_pc"))
    if startup_ch:
        steps.append(Step(AFTER_EXEC if not steps else AFTER_ASSIGN, _cc(ch0, 50, startup_ch),
                          f"ch{startup_ch} の電源ONマクロ ← マクロ{m}", "startup"))
    steps.append(Step(AFTER_ASSIGN, b"", "待ち(保存の完了を待つ)"))
    return steps


def steps_wave(samples, slot):
    return [Step(0, sysex.wave_data(samples), "波形データを送る"),
            Step(WAVE_GAP, sysex.wave_register(slot), f"波形を {slot}(送信値{slot - 1})に登録", "wave_register"),
            Step(AFTER_ASSIGN, b"", "待ち(保存の完了を待つ)")]


def _steps_for(ops, ch0):
    steps = []
    for kind, a in ops:
        if kind == "record":
            steps += steps_record(a["m"], a["params"], ch0, a.get("pc"), a.get("startup_ch"))
        elif kind == "assign":
            steps += steps_assign(a["m"], ch0, a.get("pc"), a.get("startup_ch"))
    return steps


# ---------------------------------------------------------------- 画面の操作 → 計画
def name_at(cart, pc, library=None):
    m = cart.pc_map.get(pc)
    if m is None:
        return "(不明 ― 呼び出して確かめてください)"
    if m == NEUTRAL_MACRO:
        return "(空き)"
    return mirror.record(cart, m).label or f"(マクロ{m})"


def _names(spec, ccs):
    return "、".join(spec.name(c) for c in ccs)


def plan_save(cart, library, spec: Spec, tone: Tone, place, ch, ch0, from_id=None):
    """保存場所 place に音色を入れる(ch はどの ch の音色か = 切り替えの後始末を考える ch)。
    from_id は元の音色の id(作業中の演奏の音色はコピーなので id を持たない)"""
    pc = mirror.pc_of(place)
    if pc not in PCS:
        raise ValueError("保存場所は 1〜40 です")
    params, dropped = tidy.params_for_single(cart, library, spec, tone, pc, ch)
    if not params:
        raise ValueError("この音色は電源 ON のときと同じなので、入れる内容がありません")
    m = mirror.macro_for_pc(cart, pc)
    name = tone.name or f"{TAB[ch]} の音色"
    lines = [f"保存場所 {place} に「{name}」を入れます(呼び出し番号 {pc})。"]
    old = name_at(cart, pc)
    if old != "(空き)":
        lines.append(f"※ いま入っている「{old}」は消えます。")
    if dropped:
        lines.append(f"※ 1か所に入るのは{MACRO_CAPACITY}項目までなので、次の設定は入りません"
                     f"(切り替えたときに前の音色の値が残ることがあります): {_names(spec, dropped)}")
    lines.append("※ 記録の途中で、ch1 の音がこの音色に変わります。")
    ops = [("record", dict(m=m, params=params, label=name, from_=from_id if from_id is not None else tone.id,
                           kind=tone.kind, pc=pc, startup_ch=None))]
    return WritePlan("音色を入れる", lines, _steps_for(ops, ch0), ops,
                     f"保存場所 {place} に「{name}」を入れました。\nファミコンの電源を入れ直してから、「呼び出して鳴らす」で確かめてください。",
                     "入れる", after=[("tidy_check", ch)])


def plan_clear(cart, place, ch0):
    pc = mirror.pc_of(place)
    old = name_at(cart, pc)
    if old == "(空き)":
        raise ValueError("この保存場所はもう空いています")
    ops = [("assign", dict(m=NEUTRAL_MACRO, pc=pc, startup_ch=None))]
    return WritePlan("空にする", [f"保存場所 {place}(呼び出し番号 {pc})を空にします。",
                                 f"※ いま入っている「{old}」は、この場所からは呼び出せなくなります。"],
                     _steps_for(ops, ch0), ops, f"保存場所 {place} を空にしました。", "空にする")


def plan_startup(cart, ch, place, ch0):
    """電源を入れたときの ch の音色を、保存場所 place の音色にする(place=None で「ふつう」)"""
    if place is None:
        ops = [("assign", dict(m=NEUTRAL_MACRO, pc=None, startup_ch=ch))]
        return WritePlan("電源を入れたときの音色", [f"電源を入れたときの ch{ch} を、ふつう(何も変えない)に戻します。"],
                         _steps_for(ops, ch0), ops, f"電源を入れたときの ch{ch} を、ふつうに戻しました。", "戻す")
    pc = mirror.pc_of(place)
    m = cart.pc_map.get(pc)
    if m is None or m == NEUTRAL_MACRO:
        raise ValueError("音色の入っている保存場所を選んでください")
    ops = [("assign", dict(m=m, pc=None, startup_ch=ch))]
    return WritePlan("電源を入れたときの音色",
                     [f"電源を入れたときの ch{ch} を、保存場所 {place}「{name_at(cart, pc)}」の音色にします。",
                      "※ 設定の途中で、ch1 の音が一時的にこの音色に変わります。"],
                     _steps_for(ops, ch0), ops,
                     f"電源を入れたときの ch{ch} を設定しました。電源を入れ直すと確かめられます。", "設定する")


def plan_tidy(cart, library, spec: Spec, ch, ch0):
    t = tidy.build(cart, library, spec, ch)
    if not t.ops:
        raise ValueError(f"ch{ch} はもう整っています")
    lines = [f"ch{ch} の音色を整えます(保存し直す場所 {len(t.rewrites)} か所)。"]
    if t.rewrites:
        lines.append("保存し直す場所: " + "、".join(f"{mirror.place_of(pc)}「{name_at(cart, pc)}」" for pc in t.rewrites))
    if t.base_changed:
        if t.plan.base:
            lines.append(f"土台(どの音色にも共通の設定。電源を入れたときに入る): {_names(spec, t.plan.base)}")
            old = t.old_startup
            if old is not None and old != NEUTRAL_MACRO and mirror.record(cart, old).role != tidy.base_role(ch):
                lines.append(f"※ 電源を入れたときの ch{ch} は「{mirror.record(cart, old).label}」から「ch{ch} の土台」に変わります。")
        else:
            lines.append(f"※ 共通の設定が無くなったので、電源を入れたときの ch{ch} を「ふつう」に戻します。")
    for pc, d in t.plan.dropped.items():
        if d:
            lines.append(f"※ 保存場所 {mirror.place_of(pc)} は{MACRO_CAPACITY}項目に入りきらないため、次の設定は切り替えで残ることがあります: "
                         f"{_names(spec, d)}")
    return WritePlan(f"ch{ch} を整える", lines, _steps_for(t.ops, ch0), t.ops,
                     f"ch{ch} を整えました。電源を入れ直してから、各保存場所を「呼び出して鳴らす」で確かめてください。", "整える")


def plan_wave(cart, slot, samples, name):
    if slot not in WAVE_SLOTS:
        raise ValueError("波形の登録先は 61〜76 です")
    samples = sysex.check_samples(samples)
    old = cart.waves.get(slot)
    ops = [("wave", dict(slot=slot, samples=samples, name=name or "波形"))]
    return WritePlan("波形を登録",
                     [f"波形「{name or '波形'}」を {slot} に登録します。",
                      "※ " + (f"いま登録されている「{old['name']}」は消えます。" if old else
                              "この場所に以前なにが登録されていたかは、このソフトでは分かりません(上書きされます)。"),
                      f"※ 登録したあとは、ch5 を波形メモリにして呼び出し番号 {slot} を送ると、この波形になります。"],
                     steps_wave(samples, slot), ops,
                     f"{slot} に「{name or '波形'}」を登録しました。電源を入れ直してから、呼び出して確かめてください。", "登録する")


def perf_chs(perf: Performance):
    """演奏セットの音色を入れる ch(紐付け中の ch2 は ch1 と同じなので省く。既定値だけの ch も省く)"""
    out = []
    for ch in CHS:
        if ch == 2 and perf.link12:
            continue
        if perf.tone(ch).params:
            out.append(ch)
    return out


def plan_perf_places(cart, library, spec: Spec, perf: Performance, places: dict, ch0):
    """E2: 演奏セットの音色を、ch ごとに選んだ保存場所へまとめて入れる。places: {ch: 保存場所}"""
    sim = copy.deepcopy(cart)
    ops, lines = [], [f"演奏セット「{perf.name or '(名前なし)'}」の音色を保存場所に入れます。"]
    for ch in perf_chs(perf):
        place = places.get(ch) or places.get(str(ch))
        if not place:
            continue
        pc = mirror.pc_of(place)
        tone = perf.tone(ch)
        params, dropped = tidy.params_for_single(sim, library, spec, tone, pc, ch)
        if not params:
            continue
        m = mirror.macro_for_pc(sim, pc)
        name = tone.name or f"{perf.name} {TAB[ch]}"
        op = ("record", dict(m=m, params=params, label=name, from_=perf.slots[ch].from_, kind=tone.kind, pc=pc,
                             startup_ch=None))
        mirror.record_done(sim, **op[1])
        ops.append(op)
        old = name_at(cart, pc)
        lines.append(f"・{TAB[ch]}「{name}」→ 保存場所 {place}" + ("" if old == "(空き)" else f"(いまの「{old}」は消えます)")
                     + (f" ※入りきらない設定: {_names(spec, dropped)}" if dropped else ""))
    if not ops:
        raise ValueError("入れる音色がありません(保存場所を選んでください)")
    return WritePlan("演奏セットの音色を保存場所へ", lines, _steps_for(ops, ch0), ops,
                     "演奏セットの音色を保存場所に入れました。電源を入れ直してから「呼び出して鳴らす」で確かめてください。", "入れる")


def plan_perf_startup(cart, spec: Spec, perf: Performance, ch0):
    """E3: 電源を入れたときに、演奏セットの音色になるようにする(ch ごとに電源ONマクロへ記録)"""
    sim = copy.deepcopy(cart)
    ops = []
    lines = [f"電源を入れたときに、演奏セット「{perf.name or '(名前なし)'}」の音色になるようにします。"]
    for ch in CHS:
        tone = perf.tone(ch)
        params, rest = tone.macro_params(spec)
        if not params:
            continue
        m = sim.startup.get(ch)
        r = mirror.record(sim, m) if m is not None else None
        if not (r and r.role == f"startup:{ch}" and mirror.users(sim, m) == ([], [ch])):
            free = mirror.free_macros(sim)
            if not free:
                raise ValueError("空いている保存用の枠がありません")
            m = free[0]
        op = ("record", dict(m=m, params=params, label=f"電源ON ch{ch}: {tone.name or TAB[ch]}", from_="",
                             kind=CH_KIND[ch], pc=None, startup_ch=ch, role=f"startup:{ch}"))
        mirror.record_done(sim, **op[1])
        ops.append(op)
        lines.append(f"・ch{ch}「{tone.name or '(名前なし)'}」" + (f" ※入りきらない設定: {_names(spec, [c for c, _ in rest])}" if rest else ""))
    if not ops:
        raise ValueError("電源 ON のときと違う音色がありません")
    lines.append("※ 「整える」で作った土台があった ch は、土台の代わりにこの音色になります。")
    return WritePlan("電源を入れたときの音色を演奏セットに", lines, _steps_for(ops, ch0), ops,
                     "設定しました。ファミコンの電源を入れ直すと、演奏セットの音色で始まります。", "設定する")
