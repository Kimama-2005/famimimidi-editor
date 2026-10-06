"""新しい画面の音色エディタ用のデータ(画面から独立)。easy.py のまとまりを JSON にし、操作を CC の変更に直す。

画面(JS)は「どう見せるか」だけを担当し、表示・非表示の判定や値の変換は Python 側で行う
(同じ判定を JS と Python に二重に書かないため)。
"""
import json

from .easy import GROUPS, choices_of, current_choice, groups_for
from .spec import ROOT, editable_params

CONTROLS = {c.key: c for g in GROUPS for c in g.controls}
PRESETS_PATH = ROOT / "data" / "easy_presets.json"


def load_presets():
    with open(PRESETS_PATH, encoding="utf-8") as f:
        return json.load(f)["presets"]


def spec(ch, params):
    """画面の組み立て用(値に関係なく決まる部分)"""
    groups = []
    for g in groups_for(ch, params):
        cs = []
        for c in g.controls:
            d = {"key": c.key, "label": c.label, "help": c.help, "kind": c.kind, "cc": c.cc}
            if c.kind == "choice":
                d["choices"] = [label for label, _ in choices_of(c, params)]
            elif c.kind == "steps":
                d["steps"] = params[c.cc].step_labels()
            elif c.kind == "slider":
                d.update(lo=c.lo, hi=c.hi, left=c.left, right=c.right)
            cs.append(d)
        groups.append({"key": g.key, "title": g.title, "help": g.help, "controls": cs})
    detail = [{"cc": p.cc, "name": p.name_ja, "kind": p.kind, "hint": p.hint(),
               "labels": _detail_labels(p)} for p in sorted(editable_params(params, ch), key=lambda p: p.cc)]
    return {"groups": groups, "detail": detail}


def _detail_labels(p):
    if p.kind == "steps":
        return p.step_labels()
    if p.kind == "enum":
        return p.enum_labels()
    if p.kind == "switch":
        return p.switch_labels()
    return None


def state(ch, values, params):
    """いまの値に合わせた表示(各項目の値・選択位置・オン/オフ・表示するか)"""
    out = {}
    for g in groups_for(ch, params):
        for c in g.controls:
            s = {"show": bool(c.show(values))}
            if c.kind == "toggle":
                s["on"] = bool(c.get(values))
            elif c.kind == "choice":
                s["index"] = current_choice(c, params, values.get(c.cc, 0))
            elif c.kind == "steps":
                s["index"] = params[c.cc].step_index(values.get(c.cc, 0))
            else:
                s["value"] = values.get(c.cc, 0)
            out[c.key] = s
    detail = {}
    for p in editable_params(params, ch):
        v = values.get(p.cc)
        if v is None:
            continue
        idx = None
        if p.kind == "steps":
            idx = p.step_index(v)
        elif p.kind == "enum" and p.enum_labels():
            idx = min(v, len(p.enum_labels()) - 1)
        elif p.kind == "switch":
            idx = 1 if v >= 64 else 0
        detail[str(p.cc)] = {"value": v, "index": idx}
    return {"controls": out, "values": {str(k): v for k, v in values.items()}, "detail": detail}


def updates_for(key, action, x, values, params):
    """画面の操作 → {cc: 値}。action: "toggle"(x=bool)/ "index"(x=選択位置)/ "value"(x=0〜127)"""
    c = CONTROLS[key]
    if action == "toggle":
        return c.set(values, bool(x))
    if action == "index":
        if c.kind == "steps":
            return {c.cc: params[c.cc].step_value(int(x))}
        opts = choices_of(c, params)
        return {c.cc: opts[int(x)][1]}
    return {c.cc: max(c.lo, min(c.hi, int(x)))}


def detail_update(cc, action, x, params):
    """詳細表示の操作 → {cc: 値}"""
    p = params[int(cc)]
    if action == "index":
        i = int(x)
        if p.kind == "steps":
            return {p.cc: p.step_value(i)}
        if p.kind == "switch":
            return {p.cc: 127 if i else 0}
        return {p.cc: i}
    return {p.cc: max(0, min(127, int(x)))}
