"""鍵盤の弾き方: 外部の鍵盤(スルー)の演奏を、どの音源 ch へ送るかを決める。

ふぁみみみっでぃは各 ch が単音(Mode4 固定)なので、同時に鳴らすには ch を分けるしかない。
鍵盤の割り当てはカートリッジに保存できない(ふぁみみみっでぃは届いた ch の音源で鳴らすだけ)ので、アプリが受け持つ。

mode
    "tab"     開いているタブの ch へ(音色づくり用)
    "map"     割り当て表で鳴らす
    "through" 鍵盤が送ってきた ch のまま
割り当て表(map)
    parts[ch] = {"on", "lo", "hi", "shift", "ctl"}
        鍵域 lo〜hi に入るノートを、shift 半音ずらしてその ch へ。1つのノートは鍵域に入る全部の ch で鳴る
        (鍵域を重ねれば重なり、ずらせば分かれる)。ctl = ホイール・ピッチベンドなどノート以外を受ける
    pair(ch1 と ch2 の組み方)
        "off"   別々(それぞれの鍵域で)
        "poly"  2音: ch1 の鍵域を ch1・ch2 の空いている方へ1音ずつ(3音目は一番古い音を止める)
        "layer" 重ねる: ch1 の鍵域を ch1・ch2 の両方へ
        poly / layer のとき ch2 の設定は ch1 に従う

ノートオンのときに決めた送り先を覚えておき、ノートオフは必ず同じ ch・ノートへ送る
(押したまま設定やタブを変えても音が残らないように)。
画面からも engine からも独立した計算だけ。送るのは engine。
"""
import copy

MODES = ("tab", "map", "through")
PAIRS = ("off", "poly", "layer")
POLY_CHS = (1, 2)
CHS = (1, 2, 3, 4, 5)
NAMES = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]


def default_part(ch):
    return {"on": ch == 1, "lo": 0, "hi": 127, "shift": 0, "ctl": ch in POLY_CHS}


def default_map():
    return {"parts": {ch: default_part(ch) for ch in CHS}, "pair": "off"}


DEFAULT = {"mode": "tab", **default_map()}


def _from_old(cfg):
    """フェーズD の設定(upper / split …)→ 割り当て表"""
    upper = cfg.get("upper", "tab")
    split = bool(cfg.get("split"))
    if upper in ("poly", "layer") or (split and upper != "through"):
        mode = "map"
    else:
        mode = "through" if upper == "through" else "tab"
    out = {"mode": mode, **default_map()}
    if upper in ("poly", "layer"):
        out["pair"] = upper
    if split:
        sp, low = int(cfg.get("split_note", 60)), int(cfg.get("lower_ch", 3))
        out["parts"][1].update(lo=sp)
        if low != 1:
            out["parts"][low].update(on=True, lo=0, hi=sp - 1, shift=int(cfg.get("lower_shift", 0)), ctl=False)
    return out


def normalize(cfg):
    """設定の値を正しい範囲にそろえる(以前の形式も受け付ける)"""
    cfg = copy.deepcopy(cfg or {})
    if "parts" not in cfg and {"upper", "split", "split_note", "lower_ch", "lower_shift"} & set(cfg):
        cfg = _from_old(cfg)
    c = {"mode": cfg.get("mode") if cfg.get("mode") in MODES else "tab",
         "pair": cfg.get("pair") if cfg.get("pair") in PAIRS else "off", "parts": {}}
    given = {int(k): v for k, v in (cfg.get("parts") or {}).items()}
    for ch in CHS:
        p = default_part(ch)
        p.update({k: v for k, v in (given.get(ch) or {}).items() if k in p})
        lo, hi = sorted((max(0, min(127, int(p["lo"]))), max(0, min(127, int(p["hi"])))))
        c["parts"][ch] = {"on": bool(p["on"]), "lo": lo, "hi": hi,
                          "shift": max(-24, min(24, int(p["shift"]) // 12 * 12)), "ctl": bool(p["ctl"])}
    return c


def to_json(cfg):
    """JSON 用(キーを文字列に)"""
    return {**cfg, "parts": {str(ch): dict(p) for ch, p in cfg["parts"].items()}}


def note_name(n):
    """60 → C4(画面の鍵盤と同じ C4=60)"""
    return f"{NAMES[n % 12]}{n // 12 - 1}"


def describe_map(cfg):
    """割り当て表の一言(例: ch1+2(2音) C4〜 / ch3 〜B3(-1oct))"""
    parts, pair = cfg["parts"], cfg["pair"]
    out = []
    for ch in CHS:
        p = parts[ch]
        if not p["on"] or (ch == 2 and pair != "off"):
            continue
        name = f"ch1+2({'2音' if pair == 'poly' else '重ね'})" if ch == 1 and pair != "off" else f"ch{ch}"
        lo, hi = p["lo"], p["hi"]
        if (lo, hi) == (0, 127):
            rng = ""
        elif hi == 127:
            rng = f" {note_name(lo)}〜"
        elif lo == 0:
            rng = f" 〜{note_name(hi)}"
        else:
            rng = f" {note_name(lo)}〜{note_name(hi)}"
        out.append(name + rng + (f"({p['shift'] // 12:+d}oct)" if p["shift"] else ""))
    return " / ".join(out) or "(どの ch も使わない)"


class PlayRouter:
    def __init__(self, cfg=None):
        self.cfg = normalize(cfg)
        self._held = {}         # (入力ch0, ノート) -> [(出力ch0, 出力ノート), …]
        self._voices = {}       # 2音の出力ch0 -> (入力ch0, ノート)  … 今鳴らしている音
        self._stolen = set()    # 3音目のために止めた音(あとで届くノートオフは捨てる)
        self._stamp = 0
        self._started = {}      # 出力ch0 -> 鳴らし始めた順番
        self._released = {}     # 出力ch0 -> 離した順番(空いている ch が2つあれば、長く空いている方を使う)

    def configure(self, cfg):
        """設定を変える。→ 鳴っている音を止めるメッセージの列(押したまま変えても音が残らないように)"""
        offs = self.release_all()
        self.cfg = normalize(cfg)
        return offs

    def release_all(self):
        offs = [bytes([0x80 | c0, n, 0]) for dests in self._held.values() for c0, n in dests]
        self._held.clear()
        self._voices.clear()
        self._stolen.clear()
        return offs

    @property
    def linked(self):
        """2音のときは ch1 と ch2 を同じ音色にする"""
        return self.cfg["mode"] == "map" and self.cfg["pair"] == "poly" and self.cfg["parts"][1]["on"]

    def describe(self, tab_ch=None):
        """画面に出す一言"""
        mode = self.cfg["mode"]
        if mode == "tab":
            return f"開いているタブ(ch{tab_ch})" if tab_ch else "開いているタブ"
        if mode == "through":
            return "鍵盤のchのまま"
        return describe_map(self.cfg)

    # ---------- 送り先 ----------
    def _targets(self, note):
        """割り当て表: このノートを鳴らす [(ch の列, ずらし, 2音か)]。2音でなければ ch の列の全部へ"""
        parts, pair, out = self.cfg["parts"], self.cfg["pair"], []
        for ch in CHS:
            p = parts[ch]
            if ch == 2 and pair != "off":
                continue
            if p["on"] and p["lo"] <= note <= p["hi"]:
                chs = POLY_CHS if ch == 1 and pair != "off" else (ch,)
                out.append((chs, p["shift"], ch == 1 and pair == "poly"))
        return out

    def _ctl_chs(self, in_ch0, tab_ch, to_ch0):
        """ノート以外を送る ch0 の列"""
        mode = self.cfg["mode"]
        if mode == "tab" and tab_ch:
            return [to_ch0(tab_ch)]
        if mode != "map":
            return [in_ch0]
        parts, pair, out = self.cfg["parts"], self.cfg["pair"], []
        for ch in CHS:
            src = parts[1] if ch == 2 and pair != "off" else parts[ch]
            if src["on"] and src["ctl"]:
                out.append(to_ch0(ch))
        return out

    def _plain(self, key, tab_ch, to_ch0):
        """割り当て表を使わないとき(tab / through)の送り先"""
        if self.cfg["mode"] == "tab" and tab_ch:
            return to_ch0(tab_ch)
        return key[0]

    # ---------- 振り分け ----------
    def route(self, msg: bytes, tab_ch, to_ch0):
        """入力1つ → 送るメッセージの列。tab_ch は開いているタブ(1〜5、無ければ None)、
        to_ch0 は音源の ch(1〜5)→ 送信する MIDI ch(0始まり)"""
        st = msg[0]
        if not 0x80 <= st < 0xF0:
            return [msg]
        kind, in_ch0 = st & 0xF0, st & 0x0F
        if kind in (0x80, 0x90) and len(msg) >= 3:
            key = (in_ch0, msg[1])
            if kind == 0x90 and msg[2] > 0:
                return self._note_on(key, msg[2], tab_ch, to_ch0)
            return self._note_off(key, tab_ch, to_ch0)
        if kind == 0xA0 and len(msg) >= 3:          # ポリフォニック・キープレッシャー: その音の送り先へ
            return [bytes([0xA0 | c0, n, msg[2]]) for c0, n in self._held.get((in_ch0, msg[1]), [])]
        return [bytes([kind | c0]) + msg[1:] for c0 in self._ctl_chs(in_ch0, tab_ch, to_ch0)]

    def _note_on(self, key, vel, tab_ch, to_ch0):
        if key in self._held:                       # 離さずにもう一度届いた: 同じ所で鳴らし直す
            return [bytes([0x90 | c0, n, vel]) for c0, n in self._held[key]]
        self._stolen.discard(key)
        self._stamp += 1
        if self.cfg["mode"] != "map":
            c0 = self._plain(key, tab_ch, to_ch0)
            self._held[key] = [(c0, key[1])]
            return [bytes([0x90 | c0, key[1], vel])]
        out, dests = [], []
        for chs, shift, poly in self._targets(key[1]):
            n = max(0, min(127, key[1] + shift))
            c0s = [to_ch0(c) for c in chs]
            if poly:
                c0 = self._allocate(c0s, out)
                self._voices[c0] = key
                self._started[c0] = self._stamp
                c0s = [c0]
            dests += [(c0, n) for c0 in c0s]       # 単音の ch: 重なりは音源に任せる(後から押した音が鳴る)
        if dests:
            self._held[key] = dests
        return out + [bytes([0x90 | c0, n, vel]) for c0, n in dests]

    def _allocate(self, c0s, out):
        """2音: 空いている ch(長く空いている方)。全部ふさがっていれば一番古い音を止めて使う"""
        free = [c for c in c0s if c not in self._voices]
        if free:
            return min(free, key=lambda c: self._released.get(c, 0))
        c0 = min(c0s, key=lambda c: self._started.get(c, 0))
        old = self._voices.pop(c0)
        rest = []
        for oc0, on in self._held.pop(old, []):
            if oc0 == c0:
                out.append(bytes([0x80 | oc0, on, 0]))
            else:
                rest.append((oc0, on))          # 同じ鍵で鳴らしているほかの ch(重ねたベースなど)はそのまま
        if rest:
            self._held[old] = rest
        else:
            self._stolen.add(old)
        return c0

    def _note_off(self, key, tab_ch, to_ch0):
        if key in self._stolen:
            self._stolen.discard(key)
            return []
        if key in self._held:
            dests = self._held.pop(key)
            for c0, _ in dests:
                if self._voices.get(c0) == key:
                    del self._voices[c0]
                    self._stamp += 1
                    self._released[c0] = self._stamp
            return [bytes([0x80 | c0, n, 0]) for c0, n in dests]
        # 覚えていない音(接続前に押した など): 鳴りうる所すべてに送る
        if self.cfg["mode"] != "map":
            return [bytes([0x80 | self._plain(key, tab_ch, to_ch0), key[1], 0])]
        return [bytes([0x80 | to_ch0(c), max(0, min(127, key[1] + shift)), 0])
                for chs, shift, _ in self._targets(key[1]) for c in chs]


# 割り当て表のひな形(画面の「ひな形」)
TEMPLATES = {
    "single": ("ch1 だけ", {"pair": "off", "parts": {1: {"on": True}}}),
    "poly": ("ch1+ch2 で2音", {"pair": "poly", "parts": {1: {"on": True}}}),
    "layer": ("ch1+ch2 で重ねる", {"pair": "layer", "parts": {1: {"on": True}}}),
    "bass": ("下 ch3 ベース / 上 ch1 メロディ",
             {"pair": "off", "parts": {1: {"on": True, "lo": 60}, 3: {"on": True, "hi": 59, "ctl": False}}}),
    "bass_poly": ("下 ch3 ベース / 上 ch1+ch2 で2音",
                  {"pair": "poly", "parts": {1: {"on": True, "lo": 60}, 3: {"on": True, "hi": 59, "ctl": False}}}),
    "bass_layer": ("下 ch3 ベース / 上 ch1+ch2 で重ねる",
                   {"pair": "layer", "parts": {1: {"on": True, "lo": 60}, 3: {"on": True, "hi": 59, "ctl": False}}}),
}


def template(key):
    """ひな形 → 割り当て表(mode は含めない)"""
    _, t = TEMPLATES[key]
    parts = {ch: dict(default_part(ch), on=False) for ch in CHS}
    for ch, p in t["parts"].items():
        parts[ch].update(p)
    return {"pair": t["pair"], "parts": parts}
