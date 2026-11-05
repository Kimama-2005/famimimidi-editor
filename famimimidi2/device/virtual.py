"""仮想ファミコン: ふぁみみみっでぃが無くても試せるように、このパソコンで鳴らす出力ポート。

送信の関所(gate)からは本物のポートと同じに見える(send / close / name)。受け取ったメッセージは列にためるだけで、
画面の音源(web/vfc.js、WebAudio)へ bridge がまとめて渡す。音は「なんとなく似ている」程度(実装表の値どおりに
デューティ比・エンベロープ・音量・ビブラートなどを効かせる)。

- 書き込み系(CC#45/50/51)と SysEx の波形登録は何もしない(カートリッジは無い)。アプリ側でも書き込みを止める
- プログラムチェンジ 89〜128 は、カートリッジの控え(lookup)にある音色の CC を流す(「呼び出して鳴らす」を試せるように)
- 波形メモリの波形データの SysEx は {"wave": [16点]} にして渡す
"""
import threading
from collections import deque

from . import sysex

NAME = "仮想ファミコン(このパソコンで鳴らす)"
WRITE_CCS = (45, 46, 47, 48, 49, 50, 51)


class VirtualOut:
    def __init__(self, lookup=None):
        """lookup(pc) → その呼び出し番号に入っている音色の [[cc, v], …](無ければ None)"""
        self.name = NAME
        self._lookup = lookup or (lambda pc: None)
        self._q = deque()
        self._lock = threading.Lock()

    def send(self, msg):
        msg = bytes(msg)
        if not msg:
            return
        st = msg[0]
        if st == 0xF0:
            if sysex.classify(msg) == "data":
                self._put({"wave": list(msg[4:20])})
            return
        kind, ch0 = st & 0xF0, st & 0x0F
        if kind == 0xB0 and len(msg) >= 3 and msg[1] in WRITE_CCS:
            return
        if kind == 0xC0 and len(msg) >= 2:
            params = self._lookup(msg[1] + 1)
            for cc, v in params or []:
                if int(cc) not in WRITE_CCS:
                    self._put([0xB0 | ch0, int(cc) & 0x7F, int(v) & 0x7F])
            return
        self._put(list(msg))

    def _put(self, item):
        with self._lock:
            self._q.append(item)

    def take(self):
        """ためたメッセージを全部取り出す(bridge が画面へ渡す)"""
        with self._lock:
            out = list(self._q)
            self._q.clear()
        return out

    def close(self):
        with self._lock:
            self._q.clear()
            self._q.append([0xB0, 120, 0])          # 閉じるときは全部止める(画面の音源へ)
            for ch0 in range(1, 16):
                self._q.append([0xB0 | ch0, 120, 0])
