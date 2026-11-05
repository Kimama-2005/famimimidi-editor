"""ch5 波形メモリの SysEx(実装表 ファミコン版)。

    波形データ  F0 00 70 7F d0 … d15 F7   その場で ch5 の波形メモリに効く。カートリッジには保存されない(F32)
    波形の登録  F0 00 71 7F NN F7          NN = 60〜75 → 61〜76 に登録。**保存される(F33)**
"""
POINTS = 16
LEVELS = 16
WAVE_SLOTS = range(61, 77)


def check_samples(samples):
    if samples is None or len(samples) != POINTS or any(not (0 <= int(v) < LEVELS) for v in samples):
        raise ValueError(f"波形は 0〜{LEVELS - 1} の値が {POINTS} 個必要です")
    return [int(v) for v in samples]


def wave_data(samples) -> bytes:
    return bytes([0xF0, 0x00, 0x70, 0x7F] + check_samples(samples) + [0xF7])


def wave_register(slot) -> bytes:
    if slot not in WAVE_SLOTS:
        raise ValueError("波形の登録先は 61〜76 です")
    return bytes([0xF0, 0x00, 0x71, 0x7F, slot - 1, 0xF7])


def classify(msg: bytes):
    """"data"(波形データ)/ "register"(波形の登録)/ None(このソフトが送る形ではない)"""
    if len(msg) == 21 and msg[0] == 0xF0 and msg[-1] == 0xF7 and msg[1] <= 0x7D and msg[2:4] == b"\x70\x7F" \
            and all(b < LEVELS for b in msg[4:20]):
        return "data"
    if len(msg) == 6 and msg[0] == 0xF0 and msg[-1] == 0xF7 and msg[1] <= 0x7D and msg[2:4] == b"\x71\x7F" \
            and 60 <= msg[4] <= 75:
        return "register"
    return None
