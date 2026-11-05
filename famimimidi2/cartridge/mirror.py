"""カートリッジの控え(CartMirror)の参照と更新。**控えを書き換えるのはここの関数だけ**(書き込みの成功・失敗のとき)。"""
from ..model.cartmirror import MACROS, NEUTRAL_MACRO, PCS, SILENT_MACRO, CartMirror, MacroRecord
from ..model.common import now_iso

RESERVED = {NEUTRAL_MACRO: "音量最大(空きの呼び出し番号の割り当て先)", SILENT_MACRO: "テスト用の無音(予約)"}


def place_of(pc):
    return pc - PCS[0] + 1


def pc_of(place):
    return PCS[0] + int(place) - 1


def record(cart: CartMirror, m) -> MacroRecord:
    return cart.macros.get(m) or MacroRecord()


def users(cart: CartMirror, m):
    """マクロ m を使っている 呼び出し番号 と 電源ON の ch"""
    return ([pc for pc, mm in sorted(cart.pc_map.items()) if mm == m],
            [ch for ch, mm in sorted(cart.startup.items()) if mm == m])


def free_macros(cart: CartMirror):
    """予約でなく、どこからも使われていないマクロ。中身の分からない番号を先に使う"""
    free = [m for m in MACROS if m not in RESERVED and not any(users(cart, m))]
    return sorted(free, key=lambda m: (record(cart, m).params is not None, m))


def macro_for_pc(cart: CartMirror, pc):
    """保存場所に音色を入れるときのマクロ: その場所だけが使っていれば使い回す(ほかの場所に影響しない)。そうでなければ空き"""
    m = cart.pc_map.get(pc)
    if m is not None and m not in RESERVED and users(cart, m) == ([pc], []):
        return m
    free = free_macros(cart)
    if not free:
        raise ValueError("空いている保存用の枠がありません。使っていない保存場所を空にしてください")
    return free[0]


def tone_kind(cart: CartMirror, m, library=None):
    """マクロに入っている音色の種類(分からなければ None)"""
    r = record(cart, m)
    if r.role != "tone":
        return None
    if r.extra.get("kind"):
        return r.extra["kind"]
    t = library.tone(r.from_) if library is not None and r.from_ else None
    return t.kind if t else None


# ---------------------------------------------------------------- 更新(書き込みの結果)
def record_done(cart: CartMirror, m, params, label, from_, kind, pc=None, startup_ch=None, role="tone"):
    extra = {"kind": kind} if kind else {}
    cart.macros[m] = MacroRecord([list(x) for x in params], label, True, from_ or "", role, now_iso(), extra)
    _assign(cart, m, pc, startup_ch)
    cart.history.append({"time": now_iso(), "action": "record", "macro": m, "label": label,
                         "params": [list(x) for x in params], "pc": pc, "startup_ch": startup_ch, "ok": True})


def assign_done(cart: CartMirror, m, pc=None, startup_ch=None):
    _assign(cart, m, pc, startup_ch)
    cart.history.append({"time": now_iso(), "action": "assign", "macro": m, "pc": pc, "startup_ch": startup_ch,
                         "ok": True})


def _assign(cart, m, pc, startup_ch):
    if pc:
        cart.pc_map[pc] = m
    if startup_ch:
        cart.startup[startup_ch] = m


def failed(cart: CartMirror, m, pc, startup_ch, recorded, error):
    """途中で失敗・応答なし: 影響したかもしれない所を「不明」にする"""
    if recorded and m is not None:
        cart.macros[m] = MacroRecord(None, "書き込み途中で失敗(中身不明)", False, "", "tone", now_iso())
    if pc:
        cart.pc_map[pc] = None
    if startup_ch:
        cart.startup[startup_ch] = None
    cart.history.append({"time": now_iso(), "action": "record" if recorded else "assign", "macro": m, "pc": pc,
                         "startup_ch": startup_ch, "ok": False, "note": str(error)})


def wave_done(cart: CartMirror, slot, samples, name):
    cart.waves[slot] = {"name": name, "samples": list(samples), "written": now_iso()}
    cart.history.append({"time": now_iso(), "action": "wave", "slot": slot, "name": name, "samples": list(samples),
                         "ok": True})


def wave_failed(cart: CartMirror, slot, error):
    cart.waves[slot] = {"name": "登録途中で失敗(中身不明)", "samples": None, "written": now_iso()}
    cart.history.append({"time": now_iso(), "action": "wave", "slot": slot, "ok": False, "note": str(error)})
