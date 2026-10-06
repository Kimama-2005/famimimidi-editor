"""カートリッジの対応表(user_data/cartridge.json)と、書き込み手順の組み立て・実行。

カートリッジは読み出せない(CLAUDE.md 事実5)ので、何を書いたかはここで記録するしかない。
書き込み手順は実機で成功している T0 と同じ順番・待ち時間にする(docs/03)。
マクロはチャンネルを記録しない(事実12)ので、記録は常に「音源ch1」で行う。
"""
import json
import os
import threading
import time
from dataclasses import asdict, dataclass, field

from .library import EXCLUDED_CCS, now_iso
from .spec import ROOT

CART_PATH = ROOT / "user_data" / "cartridge.json"
MACROS = range(1, 41)
PCS = range(89, 129)            # 1始まりの表記。送信値は pc - 1
CHANNELS = range(1, 6)
MAX_CCS = 10                    # 事実1
NEUTRAL_MACRO = 19              # 音量最大。空きPCの既定の割り当て先
RESERVED = {19: "空きPCの割り当て先(音量最大のはずだが空の疑い)", 20: "テスト用: 無音"}

# 待ち時間(ms)。実績のある T0 の値
GAP, CC_GAP, AFTER_STOP, AFTER_EXEC, AFTER_ASSIGN = 600, 75, 1800, 900, 600


@dataclass
class MacroSlot:
    cc: list | None = None      # 記録した CC。None = 中身不明
    label: str = "未使用(中身不明)"
    certain: bool = False       # 中身が送信記録で裏付けられているか
    patch_id: str = ""
    written: str = ""


@dataclass
class CartState:
    macros: dict = field(default_factory=dict)    # int -> MacroSlot
    pc_map: dict = field(default_factory=dict)    # int(PC 1始まり) -> マクロ番号 / None(不明)
    startup: dict = field(default_factory=dict)   # int(ch) -> マクロ番号 / None(不明・未設定)
    history: list = field(default_factory=list)
    waves: dict = field(default_factory=dict)     # int(PC61〜76) -> {"name", "samples", "written"}

    # ---------- 読み書き ----------
    @classmethod
    def load(cls, path=CART_PATH):
        if not path.exists():
            st = known_state()
            st.save(path)
            return st
        with open(path, encoding="utf-8") as f:
            d = json.load(f)
        return cls(macros={int(k): MacroSlot(**v) for k, v in d["macros"].items()},
                   pc_map={int(k): v for k, v in d["pc_map"].items()},
                   startup={int(k): v for k, v in d["startup"].items()},
                   history=d.get("history", []),
                   waves={int(k): v for k, v in d.get("waves", {}).items()})

    def save(self, path=CART_PATH):
        path.parent.mkdir(exist_ok=True)
        tmp = path.with_suffix(".tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump({"version": 1,
                       "note": "カートリッジに書いた内容のPC側の記録。カートリッジからは読み出せない",
                       "macros": {str(k): asdict(v) for k, v in sorted(self.macros.items())},
                       "pc_map": {str(k): v for k, v in sorted(self.pc_map.items())},
                       "startup": {str(k): v for k, v in sorted(self.startup.items())},
                       "waves": {str(k): v for k, v in sorted(self.waves.items())},
                       "history": self.history}, f, ensure_ascii=False, indent=2)
        os.replace(tmp, path)

    # ---------- 参照 ----------
    def slot(self, m) -> MacroSlot:
        return self.macros.setdefault(m, MacroSlot())

    def users(self, m):
        """マクロ m を使っている PC と電源ON ch"""
        return ([pc for pc, mm in sorted(self.pc_map.items()) if mm == m],
                [ch for ch, mm in sorted(self.startup.items()) if mm == m])

    def macro_text(self, m):
        s = self.slot(m)
        pcs, chs = self.users(m)
        use = []
        if pcs:
            use.append("PC" + ",".join(map(str, pcs)) if len(pcs) <= 4 else f"PC {len(pcs)}枠")
        if chs:
            use.append("電源ON ch" + ",".join(map(str, chs)))
        return f"{m}: {s.label}" + (f" [{' / '.join(use)}]" if use else "")

    def pc_text(self, pc):
        m = self.pc_map.get(pc)
        if m is None:
            return f"PC{pc}(送信値{pc - 1}): 不明"
        if m == NEUTRAL_MACRO:
            return f"PC{pc}(送信値{pc - 1}): 空き(マクロ19)"
        return f"PC{pc}(送信値{pc - 1}): マクロ{m} {self.slot(m).label}"

    def free_macros(self):
        """予約でなく、どの PC・電源ONからも使われていないマクロ。中身が不明な未使用番号を先に"""
        free = [m for m in MACROS if m not in RESERVED and not any(self.users(m))]
        return sorted(free, key=lambda m: (self.slot(m).label != "未使用(中身不明)", m))

    def macro_for_pc(self, pc):
        """かんたん保存用: PC に音色を入れるとき使うマクロ番号を自動で選ぶ。
        その PC だけが使っているマクロなら上書きして使い回す(ほかの PC に影響しない)。
        そうでなければ空きマクロを使う(マクロを共有すると、ほかの PC の音も変わるため F7)"""
        m = self.pc_map.get(pc)
        if m is not None and m not in RESERVED and self.users(m) == ([pc], []):
            return m
        free = self.free_macros()
        if not free:
            raise ValueError("空いている保存用の枠(マクロ)がありません。詳細な管理で整理してください")
        return free[0]

    def free_pcs(self):
        return [pc for pc in PCS if self.pc_map.get(pc) == NEUTRAL_MACRO]

    # ---------- 更新 ----------
    def record_done(self, m, ccs, label, patch_id, pc, startup_ch):
        self.macros[m] = MacroSlot(cc=[list(x) for x in ccs], label=label, certain=True,
                                   patch_id=patch_id, written=now_iso())
        self._assign_done(m, pc, startup_ch)
        self.history.append({"time": now_iso(), "action": "record", "macro": m, "label": label,
                             "cc": [list(x) for x in ccs], "pc": pc, "startup_ch": startup_ch})

    def assign_done(self, m, pc, startup_ch):
        self._assign_done(m, pc, startup_ch)
        self.history.append({"time": now_iso(), "action": "assign", "macro": m,
                             "pc": pc, "startup_ch": startup_ch})

    def wave_done(self, pc, samples, name):
        self.waves[pc] = {"name": name, "samples": list(samples), "written": now_iso()}
        self.history.append({"time": now_iso(), "action": "wave", "pc": pc, "name": name,
                             "samples": list(samples)})

    def wave_failed(self, pc, error):
        self.waves[pc] = {"name": "登録途中で失敗(中身不明)", "samples": None, "written": now_iso()}
        self.history.append({"time": now_iso(), "action": "failed", "wave_pc": pc, "error": str(error)})

    def assign_many_done(self, assignments):
        self.pc_map.update(assignments)
        self.history.append({"time": now_iso(), "action": "assign_many",
                             "pc_map": {str(k): v for k, v in sorted(assignments.items())}})

    def assign_many_failed(self, assignments, error):
        for pc in assignments:
            self.pc_map[pc] = None
        self.history.append({"time": now_iso(), "action": "failed", "pcs": sorted(assignments),
                             "error": str(error)})

    def _assign_done(self, m, pc, startup_ch):
        if pc:
            self.pc_map[pc] = m
        if startup_ch:
            self.startup[startup_ch] = m

    def failed(self, m, pc, startup_ch, recorded, error):
        """途中で失敗したとき、影響したかもしれない所を「不明」にする"""
        if recorded:
            self.macros[m] = MacroSlot(cc=None, label="書き込み途中で失敗(中身不明)", written=now_iso())
        if pc:
            self.pc_map[pc] = None
        if startup_ch:
            self.startup[startup_ch] = None
        self.history.append({"time": now_iso(), "action": "failed", "macro": m, "pc": pc,
                             "startup_ch": startup_ch, "error": str(error)})


def known_state():
    """2026-09-29 の第3回テスト後の状態(docs/03「カートリッジの現在の状態」)"""
    jpop = {
        11: ("J-POP リード 標準", [[70, 48], [79, 104], [75, 16], [72, 20], [1, 64], [78, 46], [73, 0], [65, 0]]),
        12: ("J-POP リード バラード", [[70, 80], [79, 127], [75, 0], [72, 42], [1, 72], [78, 54], [73, 16], [65, 127]]),
        13: ("J-POP リード サビ", [[70, 16], [79, 116], [75, 10], [72, 14], [1, 80], [78, 34], [73, 0], [65, 0]]),
    }
    st = CartState()
    for m in MACROS:
        st.macros[m] = MacroSlot()
    for m in (1, 2):
        st.macros[m] = MacroSlot(cc=[[70, 16]], label="過去テストの残骸(CC#70=16、推定)")
    for m in list(range(5, 10)) + list(range(21, 27)) + list(range(31, 38)):
        st.macros[m] = MacroSlot(label="容量テストの残骸(中身不明)")
    for m, (label, cc) in jpop.items():
        st.macros[m] = MacroSlot(cc=cc, label=label, certain=True, patch_id={11: "jpop_v1_standard", 12: "jpop_v2_ballad", 13: "jpop_v3_chorus"}[m])
    st.macros[10] = MacroSlot(cc=[[70, 16], [7, 0]], label="T2b(実行したchが無音になる)", certain=True)
    st.macros[14] = MacroSlot(cc=[[7, 0]], label="T9 無音", certain=True)
    st.macros[15] = MacroSlot(cc=[[7, 0]], label="T9 無音(ch4宛てで記録)", certain=True)
    st.macros[16] = MacroSlot(cc=[[7, 0], [7, 0]], label="T9 無音", certain=True)
    st.macros[19] = MacroSlot(cc=[[7, 127], [11, 127]], label="音量最大(テスト用・空き枠の既定)", certain=True)
    st.macros[20] = MacroSlot(cc=[[7, 0], [11, 0]], label="無音(テスト用)", certain=True)
    # T5 で全部を無音(20)にした後、T0 による復旧は PC 割り当てには効いていなかった(PCチェック U15)。
    # 個別に割り当て直した PC89(R2)・PC90(R3)だけがマクロ19
    for pc in PCS:
        st.pc_map[pc] = 20
    st.pc_map.update({89: NEUTRAL_MACRO, 90: NEUTRAL_MACRO})
    st.startup = {1: 11, 2: None, 3: None, 4: None, 5: None}
    st.history.append({"time": now_iso(), "action": "init",
                       "note": "docs/03 の 2026-09-29 時点の状態(本ソフトで書き込む前)で初期化"})
    return st


# 音色の違いに効く順(docs/05「重要度の目安」)。かんたん保存はこの順で先頭10個を選ぶ
IMPORTANCE = [70, 23, 24,                    # デューティ、アルペジエーター ON/OFF と速さ(音の性格が大きく変わる)
              79, 75, 72, 1, 78, 73, 65, 12, 92,
              25, 26, 27,                    # アルペジエーターの細かい設定
              76, 77, 86, 87, 5, 81, 85, 88, 89, 80, 84, 83, 21, 22, 9, 13, 14, 15, 16, 30, 3, 2]


def by_importance(ccs):
    """重要度順に並べ替える(表に無いものは元の順で後ろ)"""
    rank = {c: i for i, c in enumerate(IMPORTANCE)}
    return [x for _, x in sorted(enumerate(ccs), key=lambda e: (rank.get(e[1][0], len(rank)), e[0]))]


def macro_candidates(patch_cc, params):
    """音色の CC → (マクロ候補, 既定値と同じなので外したもの)。順序は音色の順(= 優先順)を保つ。
    共通の土台(既定値と同じ値)をマクロに入れると、10枠が無駄になる(docs/03 F8 の教訓)"""
    cand, same = [], []
    for c, v in patch_cc:
        if c in EXCLUDED_CCS:
            continue
        p = params.get(c)
        (same if p is not None and p.default == v else cand).append([c, v])
    return cand, same


# ---------- 送信手順 ----------
@dataclass
class Step:
    wait_ms: int        # この送信の前に待つ時間
    msg: bytes
    text: str
    role: str = ""      # "record_start" / "record_stop" / "assign_pc" / "startup" など


def _cc(ch0, n, v):
    return bytes([0xB0 | ch0, n, v])


def validate(m, ccs, pc, startup_ch):
    if m not in MACROS:
        raise ValueError(f"マクロ番号は 1〜40: {m}")
    if pc is not None and pc not in PCS:
        raise ValueError(f"PC は 89〜128: {pc}")
    if startup_ch is not None and startup_ch not in CHANNELS:
        raise ValueError(f"電源ONマクロの ch は 1〜5: {startup_ch}")
    if ccs is not None:
        if not 1 <= len(ccs) <= MAX_CCS:
            raise ValueError(f"マクロに入れる CC は 1〜{MAX_CCS} 個: {len(ccs)} 個")
        for c, v in ccs:
            if c in EXCLUDED_CCS or not (0 <= c <= 127 and 0 <= v <= 127):
                raise ValueError(f"マクロに入れられない CC: CC#{c}={v}")


def plan_record(m, ccs, ch0, pc=None, startup_ch=None):
    """音色をマクロ m に記録し、実行し、PC / 電源ON に割り当てる。ch0 は記録に使う MIDI ch(0始まり)"""
    validate(m, ccs, pc, startup_ch)
    steps = [Step(0, _cc(ch0, 49, 47), "マクロ切り替え = ユーザー"),
             Step(GAP, _cc(ch0, 45, m), f"マクロ{m} の記録開始", "record_start")]
    for i, (c, v) in enumerate(ccs):
        steps.append(Step(GAP if i == 0 else CC_GAP, _cc(ch0, c, v), f"記録 {i + 1}/{len(ccs)}: CC#{c}={v}"))
    steps.append(Step(GAP, _cc(ch0, 45, 0), f"記録停止+保存", "record_stop"))
    steps.append(Step(AFTER_STOP, _cc(ch0, 47, m), f"マクロ{m} を実行(割り当ての対象にする)"))
    return steps + _assign_steps(m, ch0, pc, startup_ch)


def plan_assign(m, ch0, pc=None, startup_ch=None):
    """記録済みのマクロ m を PC / 電源ON に割り当てる(マクロの中身は変えない)"""
    validate(m, None, pc, startup_ch)
    if not pc and not startup_ch:
        raise ValueError("PC か電源ON ch のどちらかを指定してください")
    return [Step(0, _cc(ch0, 49, 47), "マクロ切り替え = ユーザー"),
            Step(GAP, _cc(ch0, 47, m), f"マクロ{m} を実行(割り当ての対象にする)")] + \
        _assign_steps(m, ch0, pc, startup_ch)


def plan_assign_many(assignments, ch0):
    """複数の PC をまとめて割り当てる。assignments: {pc: マクロ番号}。
    マクロごとに「実行 → CC#51 を並べる」(T0/T5 と同じ形、CC#51 の間隔 0.6秒)"""
    if not assignments:
        raise ValueError("割り当てる PC がありません")
    groups = {}
    for pc, m in sorted(assignments.items()):
        validate(m, None, pc, None)
        groups.setdefault(m, []).append(pc)
    steps = [Step(0, _cc(ch0, 49, 47), "マクロ切り替え = ユーザー")]
    for i, (m, pcs) in enumerate(groups.items()):
        steps.append(Step(GAP if i == 0 else AFTER_ASSIGN, _cc(ch0, 47, m), f"マクロ{m} を実行(割り当ての対象にする)"))
        for j, pc in enumerate(pcs):
            steps.append(Step(AFTER_EXEC if j == 0 else AFTER_ASSIGN, _cc(ch0, 51, pc - 1),
                              f"PC{pc}(送信値{pc - 1})← マクロ{m}", "assign_pc"))
    steps.append(Step(AFTER_ASSIGN, b"", "待ち(保存の完了を待つ)"))
    return steps


def _assign_steps(m, ch0, pc, startup_ch):
    steps = []
    if pc:
        steps.append(Step(AFTER_EXEC, _cc(ch0, 51, pc - 1), f"PC{pc}(送信値{pc - 1})← マクロ{m}", "assign_pc"))
    if startup_ch:
        steps.append(Step(AFTER_EXEC if not steps else AFTER_ASSIGN, _cc(ch0, 50, startup_ch),
                          f"ch{startup_ch} の電源ONマクロ ← マクロ{m}", "startup"))
    steps.append(Step(AFTER_ASSIGN, b"", "待ち(保存の完了を待つ)"))
    return steps


def plan_text(steps):
    t, lines = 0, []
    for s in steps:
        t += s.wait_ms
        if s.msg:
            lines.append(f"{t / 1000:6.2f}秒  {s.msg.hex(' ').upper():<9} {s.text}")
    lines.append(f"合計 約{t / 1000:.1f}秒")
    return "\n".join(lines)


class WriteJob:
    """手順を別スレッドで送る。途中で止める手段は用意しない(記録を途中で止めると中身が不明になるため)。
    on_done(ok, error, recorded) は別スレッドから呼ばれる"""

    def __init__(self, engine, steps, on_done, on_progress=None):
        self.engine, self.steps, self.on_done, self.on_progress = engine, steps, on_done, on_progress
        self.thread = threading.Thread(target=self._run, daemon=True)

    def start(self):
        self.thread.start()

    def _run(self):
        recorded = False
        ok, error = True, None
        self.engine.begin_write()
        try:
            for i, s in enumerate(self.steps):
                time.sleep(s.wait_ms / 1000)
                if not s.msg:
                    continue
                if s.role == "record_start":
                    recorded = True
                if not self.engine.send(s.msg, "書き込み", write_ok=True):
                    ok, error = False, f"送信できませんでした: {s.text}(ログを確認してください)"
                    if recorded:   # 記録モードのまま残さないよう、停止だけは試みる
                        self.engine.send(bytes([s.msg[0], 45, 0]), "書き込み", write_ok=True)
                    break
                if self.on_progress:
                    self.on_progress(i + 1, len(self.steps), s.text)
        finally:
            self.engine.end_write()
        self.on_done(ok, error, recorded)
