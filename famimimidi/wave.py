"""ch5 波形メモリ: 16点 × 4bit(0〜15)の波形と、その SysEx。

実装表(ファミコン版):
  波形データ設定  F0 00 70 7F d0 … d15 F7   (d = 00〜0F、2バイト目は任意ID 00〜7D)
  PC 登録        F0 00 71 7F NN F7          (NN = 60〜75 → PC61〜76。-1に注意。**セーブあり**)
データ設定の方は「セーブあり」と書かれていない(未確認)。登録は取り消せないので確認ダイアログを通す。
"""
import math

POINTS = 16
LEVELS = 16
PCS = range(61, 77)          # 登録先 PC61〜76(1始まり)

PRESETS = {
    "のこぎり": list(range(16)),
    "三角": [0, 2, 4, 6, 8, 10, 12, 14, 15, 13, 11, 9, 7, 5, 3, 1],
    "サイン": [round(7.5 + 7.5 * math.sin(2 * math.pi * i / 16)) for i in range(16)],
    "矩形 50%": [15] * 8 + [0] * 8,
    "矩形 25%": [15] * 4 + [0] * 12,
    "矩形 12.5%": [15] * 2 + [0] * 14,
    "平ら(無音)": [8] * 16,
}


def check_samples(samples):
    if len(samples) != POINTS or any(not (0 <= int(v) < LEVELS) for v in samples):
        raise ValueError(f"波形は 0〜{LEVELS - 1} の値が {POINTS} 個必要です")
    return [int(v) for v in samples]


def data_sysex(samples):
    return bytes([0xF0, 0x00, 0x70, 0x7F] + check_samples(samples) + [0xF7])


def register_sysex(pc):
    if pc not in PCS:
        raise ValueError("登録先は PC61〜76 です")
    return bytes([0xF0, 0x00, 0x71, 0x7F, pc - 1, 0xF7])


def classify_sysex(msg: bytes):
    """"data" / "register" / None(本ソフトが送ってよい形ではない)"""
    if len(msg) == 21 and msg[0] == 0xF0 and msg[-1] == 0xF7 and msg[1] <= 0x7D and msg[2:4] == b"\x70\x7F" \
            and all(b < LEVELS for b in msg[4:20]):
        return "data"
    if len(msg) == 6 and msg[0] == 0xF0 and msg[-1] == 0xF7 and msg[1] <= 0x7D and msg[2:4] == b"\x71\x7F" \
            and 60 <= msg[4] <= 75:
        return "register"
    return None


def plan_register(samples, pc):
    """波形データを送ってから PC に登録する手順(書き込み)"""
    from .cartridge import AFTER_ASSIGN, Step
    return [Step(0, data_sysex(samples), "波形データを送る"),
            Step(150, register_sysex(pc), f"PC{pc}(送信値{pc - 1})に波形を登録", "wave_register"),
            Step(AFTER_ASSIGN, b"", "待ち(保存の完了を待つ)")]
