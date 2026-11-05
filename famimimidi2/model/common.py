"""データの層で共通の小さな道具(SPEC_v2 5.1)。"""
import re
import uuid
from datetime import datetime

from ..music.spec import CH_KIND, CHS, KINDS  # noqa: F401 — ほかのモジュールがここから使う


def now_iso():
    """タイムゾーン付きの ISO 8601"""
    return datetime.now().astimezone().isoformat(timespec="seconds")


def new_id(name, prefix="tone"):
    """名前の英数字から作り、重ならないように6桁の乱数を足す(日本語だけの名前なら prefix)"""
    base = re.sub(r"[^0-9A-Za-z]+", "_", name or "").strip("_").lower()[:24]
    return f"{base or prefix}_{uuid.uuid4().hex[:6]}"


def clamp(v, lo, hi):
    return max(lo, min(hi, int(v)))


def ch_keys(d):
    """{"1": x, 1: y} のどちらでも ch(int)→ 値 にする"""
    return {int(k): v for k, v in (d or {}).items()}
