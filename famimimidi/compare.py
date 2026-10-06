"""2つの音色の違い(A/B 比較)。画面から独立。"""
from dataclasses import dataclass

from .sets import full_values, importance_key, relevant


@dataclass
class DiffRow:
    cc: int
    name: str
    a: str
    b: str
    audible: bool     # どちらかの音色でこの設定が効いているか(効いていなければ音は変わらない)


def diff(pa, pb, params):
    """同じ ch の設定どうしで比べる。ch が違う場合は A の ch で比べる(ch に無い設定は出さない)"""
    ch = pa.channel
    fa, fb = full_values(pa, params, ch), full_values(pb, params, ch)
    ra, rb = relevant(fa), relevant(fb)
    rows = []
    for c in sorted(set(fa) | set(fb), key=importance_key):
        va, vb = fa.get(c), fb.get(c)
        p = params[c]
        if va == vb or (p.kind == "steps" and None not in (va, vb) and p.step_index(va) == p.step_index(vb)):
            continue   # 段階で選ぶ設定は、同じ段階なら同じ音
        rows.append(DiffRow(c, p.name_ja, p.format_value(va), p.format_value(vb), c in ra or c in rb))
    return rows
