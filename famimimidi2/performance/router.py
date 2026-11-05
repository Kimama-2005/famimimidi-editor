"""鍵盤の振り分け(SPEC_v2 6.4)。**いる場所で決まる**(切り替えのスイッチは無い)。

| いる場所 | 鍵盤 |
|---|---|
| 「1」〜「5」のタブ(place = 1〜5) | その ch だけで鳴らす。ペダル・ベンド・モジュレーションもその ch へ |
| 「♪ 演奏セット」タブ(place = "play") | 割り当て表(5.4)どおり。ペダル・レバーは controls(5.3.5)どおり |

- 「外部の鍵盤: 演奏セットどおり」(follow = True)のときは、1〜5 のタブでも外部の鍵盤は ♪ と同じに鳴らす
  (割り当て表のまま音作りをする)。画面の鍵盤(solo)は、タブの ch だけを鳴らす

- 鍵盤から使うのは ノート・ピッチベンド・モジュレーション(CC#1)・サスティンペダル(CC#64)・アフタータッチだけ。
  プログラムチェンジ・そのほかの CC は送らない(理由を返すのでログに残す)
- ノートオンで決めた送り先を覚え、ノートオフは必ず同じ所へ送る(場所や設定を変えても音が残らない)
- ポリ(2音): ch1 の鍵域を ch1・ch2 に1音ずつ。空いている方(長く空いている方)を使い、3音目は一番古い音を止める
- コードモード(place = "play" で chord.active)は5段目。ここでは扱わない(アプリが先に受け取る)

送るのはアプリ(関所)。ここは「入力1つ → 送るメッセージの列」の計算だけ。
"""
from ..model.performance import MOD_CC, Controls, KeyboardMap

CHS = (1, 2, 3, 4, 5)
POLY_CHS = (1, 2)
NOT_USED = "鍵盤の操作は使いません(鍵盤は音を鳴らすことにだけ使う)"


class Router:
    def __init__(self, to_ch0=lambda ch: ch - 1):
        self.to_ch0 = to_ch0              # 画面の ch(1〜5)→ 送る MIDI ch(0始まり)
        self.place = "play"
        self.follow = False     # 1〜5 のタブでも割り当て表どおり
        self._solo = False      # いま振り分けているのは画面の鍵盤(タブの ch だけ)
        self.keyboard = KeyboardMap()
        self.controls = Controls()
        self._held = {}         # (入力ch0, 鍵) -> [(出力ch0, ノート), …]
        self._voices = {}       # ポリの出力ch0 -> 鳴らしている (入力ch0, 鍵)
        self._stolen = set()    # 3音目のために止めた音(あとで届くノートオフは捨てる)
        self._stamp = 0
        self._started = {}
        self._released = {}

    # ---------- 設定 ----------
    def configure(self, place=None, keyboard=None, controls=None, follow=None):
        """場所・割り当て表・ペダル・レバー・鍵盤の振る舞いを変える。→ 鳴っている音を止めるメッセージの列"""
        changed = (place is not None and place != self.place) or keyboard is not None             or (follow is not None and bool(follow) != self.follow)
        offs = self.release_all() if changed else []
        if place is not None:
            self.place = place
        if follow is not None:
            self.follow = bool(follow)
        if keyboard is not None:
            self.keyboard = keyboard.normalized()
        if controls is not None:
            self.controls = controls.normalized()
        return offs

    def release_all(self):
        offs = [bytes([0x80 | c0, n, 0]) for dests in self._held.values() for c0, n in dests]
        self._held.clear()
        self._voices.clear()
        self._stolen.clear()
        return offs

    @property
    def tone_ch(self):
        """タブの ch だけで鳴らすときのその ch。割り当て表どおりなら None"""
        if not isinstance(self.place, int):
            return None
        return self.place if self._solo or not self.follow else None

    def sounding(self):
        """鳴らしている音(画面の鍵盤を光らせる用)"""
        return [n for dests in self._held.values() for _, n in dests]

    # ---------- 振り分け ----------
    def route(self, msg: bytes, solo=False):
        """入力1つ → (送るメッセージの列, 送らなかった理由 or None)。solo = 画面の鍵盤(タブの ch だけ)"""
        self._solo = bool(solo)
        try:
            return self._route(msg)
        finally:
            self._solo = False

    def _route(self, msg: bytes):
        st = msg[0] if msg else 0
        if not 0x80 <= st < 0xF0:
            return [], NOT_USED
        kind, in_ch0 = st & 0xF0, st & 0x0F
        if kind in (0x80, 0x90) and len(msg) >= 3:
            key = (in_ch0, msg[1])
            if kind == 0x90 and msg[2] > 0:
                return self._note_on(key, msg[2]), None
            return self._note_off(key), None
        if kind == 0xA0 and len(msg) >= 3:          # キー別アフタータッチ: その音の送り先へ
            return [bytes([0xA0 | c0, n, msg[2]]) for c0, n in self._held.get((in_ch0, msg[1]), [])], None
        if kind == 0xE0 and len(msg) >= 3:
            return [bytes([0xE0 | self.to_ch0(ch)]) + msg[1:3] for ch in self._ctl_chs("bend")], None
        if kind == 0xD0 and len(msg) >= 2:
            return [bytes([0xD0 | self.to_ch0(ch), msg[1]]) for ch in self._ctl_chs("mod")], None
        if kind == 0xB0 and len(msg) >= 3:
            if msg[1] == 64:
                if self.tone_ch is None and self.controls.pedal_use == "off":
                    return [], "サスティンペダルは「使わない」にしてあります"
                return [bytes([0xB0 | self.to_ch0(ch), 64, msg[2]]) for ch in self._ctl_chs("pedal")], None
            if msg[1] == 1:
                return self._mod(msg[2]), None
        return [], NOT_USED

    def _ctl_chs(self, what):
        if self.tone_ch is not None:
            return [self.tone_ch]
        return list({"pedal": self.controls.pedal_to, "bend": self.controls.bend_to,
                     "mod": self.controls.mod_to}[what])

    def _mod(self, value):
        """モジュレーションレバー: 演奏セットでは働き(ビブラート CC#1 / デューティ比 CC#70 / エクスプレッション CC#11)に置き換える"""
        if self.tone_ch is not None:
            return [bytes([0xB0 | self.to_ch0(self.tone_ch), 1, value])]
        use = self.controls.mod_use
        cc = MOD_CC[use]
        chs = [ch for ch in self.controls.mod_to if use != "duty" or ch in POLY_CHS]   # デューティ比は ch1・ch2 だけ
        return [bytes([0xB0 | self.to_ch0(ch), cc, value]) for ch in chs]

    def _targets(self, note):
        """割り当て表: このノートを鳴らす [(ch の列, ずらし, ポリか)]"""
        kb, out = self.keyboard, []
        for ch in CHS:
            p = kb.parts[ch]
            if ch == 2 and kb.pair != "off":
                continue
            if p.on and p.lo <= note <= p.hi:
                chs = POLY_CHS if ch == 1 and kb.pair != "off" else (ch,)
                out.append((chs, p.shift, ch == 1 and kb.pair == "poly"))
        return out

    def _note_on(self, key, vel):
        if key in self._held:                       # 離さずにもう一度届いた: 同じ所で鳴らし直す
            return [bytes([0x90 | c0, n, vel]) for c0, n in self._held[key]]
        self._stolen.discard(key)
        self._stamp += 1
        if self.tone_ch is not None:
            c0 = self.to_ch0(self.tone_ch)
            self._held[key] = [(c0, key[1])]
            return [bytes([0x90 | c0, key[1], vel])]
        out, dests = [], []
        for chs, shift, poly in self._targets(key[1]):
            n = max(0, min(127, key[1] + shift))
            c0s = [self.to_ch0(c) for c in chs]
            if poly:
                c0 = self._allocate(c0s, out)
                self._voices[c0] = key
                self._started[c0] = self._stamp
                c0s = [c0]
            dests += [(c0, n) for c0 in c0s]
        if dests:
            self._held[key] = dests
        return out + [bytes([0x90 | c0, n, vel]) for c0, n in dests]

    def _allocate(self, c0s, out):
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
                rest.append((oc0, on))
        if rest:
            self._held[old] = rest
        else:
            self._stolen.add(old)
        return c0

    def _note_off(self, key):
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
        return []       # 覚えていない音(接続前に押したなど)は送らない。止めたいときはパニック
