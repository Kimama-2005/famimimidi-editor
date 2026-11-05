"""整える(SPEC_v2 6.6.4): 同じ ch の音色どうしで切り替えても、前の音色の設定が残らないようにする。以前の版の famimimidi/sets.py から移した。

- 保存場所1か所に入るのは10項目まで。呼び出したとき、入っていない設定は「前の状態のまま」になる
- 前の状態 = 電源 ON の値(実装表の既定値)+ 土台 + 直前に呼び出した音色が変えた設定
- 音色 P の10項目には「P と違う値になっている可能性がある設定」をすべて入れる:
    ・P の値が「既定値+土台」と違う設定
    ・同じ ch のほかの音色が(保存した10項目で)P と違う値にする設定(切り替えの後始末)
- 土台 = その ch のすべての音色で同じ値、かつ既定値と違う設定。電源ONマクロとして保存する
"""
import copy
from dataclasses import dataclass, field

from ..model.tone import IMPORTANCE, MACRO_CAPACITY, Tone
from ..music.spec import CH_KIND, Spec
from . import mirror

MAX = MACRO_CAPACITY


def base_role(ch):
    return f"base:{ch}"


def relevant(full):
    """この音色で「効いている」設定(使っていない機能の細かい設定は、どんな値でも音が変わらない)。
    ブレス・アフタータッチのタイプは無視(鍵盤から送らない想定)"""
    r = set(full) - {3, 30}
    if full.get(23, 0) == 0:
        r -= {24, 25, 26, 27}
    if full.get(65, 0) < 64:
        r -= {5}
    if full.get(1, 0) <= full.get(81, 20):
        r -= {76, 77, 78, 80, 81}
    if full.get(92, 0) <= full.get(89, 20):
        r -= {86, 87, 88, 89}
    if full.get(79, 127) >= 120:
        r -= {75}
    return r


def importance_key(cc):
    return IMPORTANCE.index(cc) if cc in IMPORTANCE else len(IMPORTANCE) + cc


def compute_base(fulls, spec: Spec):
    if not fulls:
        return {}
    common = {}
    for c in set().union(*fulls):
        vals = {f[c] for f in fulls if c in f and c in relevant(f)}
        if len(vals) == 1:
            v = vals.pop()
            if spec.default(c) != v:
                common[c] = v
    keep = sorted(common, key=importance_key)[:MAX]
    return {c: common[c] for c in keep}


def needed(full, others_saved, base, spec: Spec):
    need = {}
    rel = relevant(full)
    for c, v in full.items():
        if c not in rel:
            continue
        before = base.get(c, spec.default(c))
        if v != before or any(o.get(c, v) != v for o in others_saved):
            need[c] = v
    return need


def _fill(chosen, full, spec: Spec):
    """必要な設定のあと、余りがあれば音色自身の「既定値と違う設定」で埋める(エディタで変えたあとでも呼び出しで戻せる)"""
    out = dict(chosen)
    extra = sorted((c for c, v in full.items() if c not in out and v != spec.default(c)), key=importance_key)
    for c in extra[:MAX - len(out)]:
        out[c] = full[c]
    return [[c, v] for c, v in sorted(out.items(), key=lambda kv: importance_key(kv[0]))]


@dataclass
class Plan:
    ch: int
    base: dict = field(default_factory=dict)
    slots: dict = field(default_factory=dict)      # pc -> [[cc, v]]
    dropped: dict = field(default_factory=dict)    # pc -> [cc] 入りきらない設定


def plan_channel(sounds: dict, spec: Spec, ch):
    fulls = {pc: t.values(spec) for pc, t in sounds.items()}
    base = compute_base(list(fulls.values()), spec)
    saved = {pc: {c: v for c, v in f.items() if v != base.get(c, spec.default(c))} for pc, f in fulls.items()}
    plan = Plan(ch=ch, base=base)
    for _ in range(5):                      # ほかの音色の10項目に依存するので、収まるまで数回くり返す
        new = {}
        for pc, f in fulls.items():
            others = [s for q, s in saved.items() if q != pc]
            need = needed(f, others, base, spec)
            order = sorted(need, key=importance_key)
            new[pc] = {c: need[c] for c in order[:MAX]}
            plan.dropped[pc] = order[MAX:]
        if new == saved:
            break
        saved = new
    plan.slots = {pc: _fill(saved[pc], fulls[pc], spec) for pc in saved}
    return plan


def sounds_on_cart(cart, library, ch):
    """カートリッジに入っている、この ch の種類の音色 {pc: Tone}(土台・空き・不明は除く)"""
    kind = CH_KIND[ch]
    out = {}
    for pc, m in sorted(cart.pc_map.items()):
        if m is None or m in mirror.RESERVED:
            continue
        if mirror.tone_kind(cart, m, library) != kind:
            continue
        r = mirror.record(cart, m)
        t = library.tone(r.from_) if r.from_ else None
        if t is None:                        # ライブラリから消した音色: 書いた中身を音色とみなす
            if r.params is None:
                continue
            t = Tone(name=r.label, kind=kind, params=[list(x) for x in r.params])
        out[pc] = t
    return out


def current_base(cart, ch):
    m = cart.startup.get(ch)
    if m is None:
        return {}
    r = mirror.record(cart, m)
    return {c: v for c, v in r.params} if r.role == base_role(ch) and r.params else {}


def saved_params(cart, pc):
    m = cart.pc_map.get(pc)
    r = mirror.record(cart, m) if m is not None else None
    return (r.params or []) if r else []


def params_for_single(cart, library, spec: Spec, tone: Tone, pc, ch):
    """1か所だけ入れるときの10項目(ほかの音色から切り替えても残らないように)→ (入れる [[cc, v]], 入りきらない [cc])"""
    others = [dict(map(tuple, saved_params(cart, q))) for q in sounds_on_cart(cart, library, ch) if q != pc]
    full = tone.values(spec)
    need = needed(full, others, current_base(cart, ch), spec)
    order = sorted(need, key=importance_key)
    return _fill({c: need[c] for c in order[:MAX]}, full, spec), order[MAX:]


@dataclass
class Status:
    count: int
    to_rewrite: list
    base_ok: bool
    unavoidable: dict

    @property
    def needed(self):
        return bool(self.to_rewrite) or not self.base_ok


def status(cart, library, spec: Spec, ch):
    sounds = sounds_on_cart(cart, library, ch)
    if not sounds:
        return Status(0, [], True, {})
    plan = plan_channel(sounds, spec, ch)
    to_rewrite = [pc for pc in sounds if [list(x) for x in saved_params(cart, pc)] != plan.slots[pc]]
    return Status(len(sounds), to_rewrite, plan.base == current_base(cart, ch),
                  {pc: d for pc, d in plan.dropped.items() if d})


@dataclass
class TidyResult:
    plan: Plan
    ops: list            # [(種類, 引数)] plans.Write の手順の材料
    rewrites: list
    base_changed: bool
    old_startup: int | None


def build(cart, library, spec: Spec, ch):
    """ch を整えるのに必要な書き込み(手順は plans が組み立てる)。変える所が無ければ ops は空"""
    sounds = sounds_on_cart(cart, library, ch)
    plan = plan_channel(sounds, spec, ch)
    sim = copy.deepcopy(cart)
    ops, rewrites = [], []
    old_base = current_base(cart, ch)
    base_changed = plan.base != old_base
    if base_changed:
        items = [[c, v] for c, v in plan.base.items()]
        if items:
            m = cart.startup.get(ch)
            r = mirror.record(cart, m) if m is not None else None
            if not (r and r.role == base_role(ch) and mirror.users(sim, m) == ([], [ch])):
                free = mirror.free_macros(sim)
                if not free:
                    raise ValueError("空いている保存用の枠がありません")
                m = free[0]
            op = ("record", dict(m=m, params=items, label=f"ch{ch} の土台", from_="", kind=None, pc=None,
                                 startup_ch=ch, role=base_role(ch)))
        else:
            op = ("assign", dict(m=mirror.NEUTRAL_MACRO, pc=None, startup_ch=ch))
        _apply(sim, op)
        ops.append(op)
    for pc, t in sounds.items():
        want = plan.slots[pc]
        if [list(x) for x in saved_params(cart, pc)] == want:
            continue
        rewrites.append(pc)
        if want:
            m = mirror.macro_for_pc(sim, pc)
            op = ("record", dict(m=m, params=want, label=t.name, from_=t.id, kind=t.kind, pc=pc, startup_ch=None))
        else:
            op = ("assign", dict(m=mirror.NEUTRAL_MACRO, pc=pc, startup_ch=None))
        _apply(sim, op)
        ops.append(op)
    return TidyResult(plan, ops, rewrites, base_changed, cart.startup.get(ch))


def _apply(cart, op):
    kind, a = op
    if kind == "record":
        mirror.record_done(cart, **a)
    else:
        mirror.assign_done(cart, **a)
