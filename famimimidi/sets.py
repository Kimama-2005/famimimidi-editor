"""チャンネルごとの「音色セット」の整え: 共通の土台(A+B2 の B2)と、切り替えの後始末(A)。

考え方:
- 保存場所1か所に入るのは10項目まで(事実1)。呼び出したとき、入っていない設定は「前の状態のまま」になる
- 前の状態 = 電源ON時の値(実装表の既定値)+ 土台 + 直前に呼び出した音色が変えた設定
- だから音色 P の10項目には、次の「P と違う値になっている可能性がある設定」をすべて入れる必要がある
    ・P の値が「既定値+土台」と違う設定
    ・同じセットのほかの音色が(保存した10項目で)P と違う値にする設定   ← 切り替えの後始末(A)
- 土台(B2) = セットのすべての音色で同じ値、かつ既定値と違う設定。電源ONマクロとして保存する
  (土台に入れた設定は各音色の10項目から外せるので、枠が空く)
"""
import copy
from dataclasses import dataclass, field

from .cartridge import IMPORTANCE, MAX_CCS, NEUTRAL_MACRO, plan_assign, plan_record
from .library import EXCLUDED_CCS
from .spec import editable_params

BASE_TAG = "__base_ch"      # 土台マクロの patch_id(例: "__base_ch1")


def base_id(ch):
    return f"{BASE_TAG}{ch}"


def full_values(patch, params, ch):
    """この ch で意味のある全設定の、音色としての値(音色に無いものは既定値)"""
    vals = patch.cc_dict()
    out = {}
    for p in editable_params(params, ch):
        if p.cc in EXCLUDED_CCS:
            continue
        v = vals.get(p.cc, p.default)
        if v is not None:
            out[p.cc] = v
    return out


def relevant(full):
    """この音色で「効いている」設定。使っていない機能の細かい設定は、どんな値でも音が変わらないので気にしない。
    (前提: 鍵盤からモジュレーション/トレモロを手で足さない。ブレスコントローラー(CC#2)と
     アフタータッチは使わない ― KROSS2 / microKEY2 はどちらも送らない想定。CC#81・#89 の無効区間の解釈は docs/04 による)"""
    r = set(full) - {3, 30}                         # ブレス・コントロール・タイプ、アフタータッチ・タイプ
    if full.get(23, 0) == 0:                        # アルペジエーター OFF
        r -= {24, 25, 26, 27}
    if full.get(65, 0) < 64:                        # ポルタメント OFF
        r -= {5, 84}
    if full.get(1, 0) <= full.get(81, 20):          # モジュレーション量が無効区間以下 = ビブラート無し
        r -= {76, 77, 78, 80, 81}
    if full.get(92, 0) <= full.get(89, 20):         # トレモロ量が無効区間以下 = トレモロ無し
        r -= {86, 87, 88, 89}
    if full.get(79, 127) >= 120:                    # サスティン・レベル最大 = 減衰しない(docs/04)
        r -= {75}
    return r


def importance_key(cc):
    return IMPORTANCE.index(cc) if cc in IMPORTANCE else len(IMPORTANCE) + cc


def compute_base(fulls, params):
    """全員で同じ値かつ既定値と違う設定 → 土台(重要度順に最大10)。fulls: [dict]"""
    if not fulls:
        return {}
    common = {}
    for c in set().union(*fulls):
        # その設定が効いている音色だけで比べる(効いていない音色には、土台の値が入っても影響しない)
        vals = {f[c] for f in fulls if c in f and c in relevant(f)}
        if len(vals) == 1:
            v = vals.pop()
            if params[c].default != v:
                common[c] = v
    keep = sorted(common, key=importance_key)[:MAX_CCS]
    return {c: common[c] for c in keep}


def needed(full, others_saved, base, params):
    """音色 full を呼び出したときに、確実にその値にするため10項目に入れるべき設定。
    others_saved: ほかの音色が保存(予定)している {cc: 値} のリスト"""
    need = {}
    rel = relevant(full)
    for c, v in full.items():
        if c not in rel:
            continue
        before = base.get(c, params[c].default)
        if v != before or any(o.get(c, v) != v for o in others_saved):
            need[c] = v
    return need


@dataclass
class Plan:
    """1チャンネル分の整え方"""
    ch: int
    base: dict = field(default_factory=dict)
    slots: dict = field(default_factory=dict)      # pc -> [[cc, v]](重要度順、最大10)
    dropped: dict = field(default_factory=dict)    # pc -> [cc](入りきらず、切り替えで残る可能性がある設定)


def plan_channel(sounds, params, ch):
    """sounds: {pc: patch}。→ Plan
    各音色の10項目は、ほかの音色の10項目に依存するので、収まるまで数回くり返して決める"""
    fulls = {pc: full_values(p, params, ch) for pc, p in sounds.items()}
    base = compute_base(list(fulls.values()), params)
    # 最初は「既定値+土台との差」だけで仮決め
    saved = {pc: {c: v for c, v in f.items() if v != base.get(c, params[c].default)} for pc, f in fulls.items()}
    plan = Plan(ch=ch, base=base)
    for _ in range(5):
        new = {}
        for pc, f in fulls.items():
            others = [s for q, s in saved.items() if q != pc]
            need = needed(f, others, base, params)
            order = sorted(need, key=importance_key)
            new[pc] = {c: need[c] for c in order[:MAX_CCS]}
            plan.dropped[pc] = order[MAX_CCS:]
        if new == saved:
            break
        saved = new
    plan.slots = {pc: _fill(saved[pc], fulls[pc], params) for pc in saved}
    return plan


def _fill(chosen, full, params):
    """必要な設定のあと、10項目に余りがあれば音色自身の「既定値と違う設定」で埋める。
    埋めるのは土台と同じ値の設定なので、ほかの音色とぶつからない。
    こうしておくと、エディタで音を変えたあとでも呼び出し番号でこの音色に戻せる"""
    out = dict(chosen)
    extra = sorted((c for c, v in full.items() if c not in out and v != params[c].default), key=importance_key)
    for c in extra[:MAX_CCS - len(out)]:
        out[c] = full[c]
    return [[c, v] for c, v in sorted(out.items(), key=lambda kv: importance_key(kv[0]))]


def sounds_on_cart(cart, lib, ch):
    """カートリッジに入っている、この ch 用の音色 {pc: patch}(テスト用・土台・空きは除く)"""
    out = {}
    for pc, m in sorted(cart.pc_map.items()):
        if m is None or m == NEUTRAL_MACRO:
            continue
        pid = cart.slot(m).patch_id
        p = lib.get(pid) if pid and not pid.startswith(BASE_TAG) else None
        if p is not None and p.channel == ch:
            out[pc] = p
    return out


def current_base(cart, ch):
    """いまカートリッジに入っている ch の土台 {cc: 値}(無ければ空)"""
    m = cart.startup.get(ch)
    if m is None:
        return {}
    s = cart.slot(m)
    return dict(map(tuple, s.cc)) if s.patch_id == base_id(ch) and s.cc else {}


def saved_cc(cart, pc):
    m = cart.pc_map.get(pc)
    return (cart.slot(m).cc or []) if m is not None else []


@dataclass
class Tidy:
    """「整える」の送信手順と、成功したときの対応表の更新"""
    plan: Plan
    steps: list
    ops: list            # [(関数名, 引数)] CartState に順に適用する
    rewrites: list       # 保存し直す pc
    base_changed: bool
    old_startup: int | None


def build_tidy(cart, lib, params, ch, ch0):
    """ch の音色セットを整える手順。変更が無ければ steps は空"""
    sounds = sounds_on_cart(cart, lib, ch)
    plan = plan_channel(sounds, params, ch)
    sim = copy.deepcopy(cart)
    steps, ops, rewrites = [], [], []
    old_base = current_base(cart, ch)
    base_changed = plan.base != old_base
    if base_changed:
        items = [[c, v] for c, v in plan.base.items()]
        if items:
            m = cart.startup.get(ch)
            if not (m is not None and cart.slot(m).patch_id == base_id(ch) and sim.users(m) == ([], [ch])):
                m = sim.free_macros()[0] if sim.free_macros() else None
            if m is None:
                raise ValueError("空いている保存用の枠がありません")
            steps += plan_record(m, items, ch0, startup_ch=ch)
            op = ("record_done", (m, items, f"ch{ch} の土台", base_id(ch), None, ch))
        else:   # 土台が要らなくなった: 電源ONを「ふつう」に戻す
            steps += plan_assign(NEUTRAL_MACRO, ch0, startup_ch=ch)
            op = ("assign_done", (NEUTRAL_MACRO, None, ch))
        getattr(sim, op[0])(*op[1])
        ops.append(op)
    for pc, patch in sounds.items():
        want = plan.slots[pc]
        if [list(x) for x in saved_cc(cart, pc)] == want:
            continue
        rewrites.append(pc)
        if want:
            m = sim.macro_for_pc(pc)
            steps += plan_record(m, want, ch0, pc=pc)
            op = ("record_done", (m, want, patch.name, patch.id, pc, None))
        else:   # 変える設定が1つも無い(土台と既定値だけで済む)
            steps += plan_assign(NEUTRAL_MACRO, ch0, pc=pc)
            op = ("assign_done", (NEUTRAL_MACRO, pc, None))
        getattr(sim, op[0])(*op[1])
        ops.append(op)
    return Tidy(plan, steps, ops, rewrites, base_changed, cart.startup.get(ch))


@dataclass
class Status:
    count: int                  # この ch 用の音色の数
    to_rewrite: list            # 「整える」で保存し直せば直る場所
    base_ok: bool               # 土台が計画どおりか
    unavoidable: dict           # {pc: [cc]} 整えても10項目に入りきらない設定

    @property
    def tidy_needed(self):
        return bool(self.to_rewrite) or not self.base_ok


def status(cart, lib, params, ch):
    sounds = sounds_on_cart(cart, lib, ch)
    if not sounds:
        return Status(0, [], True, {})
    plan = plan_channel(sounds, params, ch)
    to_rewrite = [pc for pc in sounds if [list(x) for x in saved_cc(cart, pc)] != plan.slots[pc]]
    return Status(len(sounds), to_rewrite, plan.base == current_base(cart, ch),
                  {pc: d for pc, d in plan.dropped.items() if d})


def cc_for_single_save(cart, lib, params, patch, pc):
    """1か所だけ保存するときの10項目(A: ほかの音色から切り替えても残らないように)。
    → (入れる [[cc, v]], 入りきらない [cc])"""
    ch = patch.channel
    others = [dict(map(tuple, saved_cc(cart, q))) for q in sounds_on_cart(cart, lib, ch) if q != pc]
    full = full_values(patch, params, ch)
    need = needed(full, others, current_base(cart, ch), params)
    order = sorted(need, key=importance_key)
    return _fill({c: need[c] for c in order[:MAX_CCS]}, full, params), order[MAX_CCS:]


def apply_ops(cart, ops):
    for name, args in ops:
        getattr(cart, name)(*args)


def check_saved(sounds, saved_cc, params, ch, base):
    """いま保存されている中身で、切り替えたときに設定が残る所を調べる。
    saved_cc: {pc: [[cc, v]]}。→ {pc: [残る可能性のある cc]}"""
    fulls = {pc: full_values(p, params, ch) for pc, p in sounds.items()}
    saved = {pc: dict(map(tuple, saved_cc[pc])) for pc in sounds}
    problems = {}
    for pc, f in fulls.items():
        others = [s for q, s in saved.items() if q != pc]
        need = needed(f, others, base, params)
        bad = [c for c, v in need.items() if saved[pc].get(c) != v]
        if bad:
            problems[pc] = sorted(bad, key=importance_key)
    return problems
