"""Windows 標準の MIDI API(winmm.dll)を ctypes で直接呼ぶ。

python-rtmidi は Python 3.14 用の配布版が無いので使わない(docs/01)。
入力はコールバックで受け取り、キューに積むだけにする
(コールバック内から他の MIDI 関数を呼ぶのは Windows のドキュメント上非推奨)。
"""
import ctypes
import time
from ctypes import wintypes

_winmm = ctypes.WinDLL("winmm")

MMSYSERR_NOERROR = 0
MMSYSERR_BADDEVICEID = 2
MMSYSERR_ALLOCATED = 4
CALLBACK_FUNCTION = 0x00030000
MIM_DATA = 0x3C3

HMIDIOUT = wintypes.HANDLE
HMIDIIN = wintypes.HANDLE
DWORD_PTR = ctypes.c_size_t


class MIDIOUTCAPSW(ctypes.Structure):
    _fields_ = [("wMid", wintypes.WORD), ("wPid", wintypes.WORD),
                ("vDriverVersion", wintypes.UINT), ("szPname", wintypes.WCHAR * 32),
                ("wTechnology", wintypes.WORD), ("wVoices", wintypes.WORD),
                ("wNotes", wintypes.WORD), ("wChannelMask", wintypes.WORD),
                ("dwSupport", wintypes.DWORD)]


class MIDIINCAPSW(ctypes.Structure):
    _fields_ = [("wMid", wintypes.WORD), ("wPid", wintypes.WORD),
                ("vDriverVersion", wintypes.UINT), ("szPname", wintypes.WCHAR * 32),
                ("dwSupport", wintypes.DWORD)]


class MIDIHDR(ctypes.Structure):
    pass


MIDIHDR._fields_ = [("lpData", ctypes.c_void_p), ("dwBufferLength", wintypes.DWORD),
                    ("dwBytesRecorded", wintypes.DWORD), ("dwUser", DWORD_PTR),
                    ("dwFlags", wintypes.DWORD), ("lpNext", ctypes.POINTER(MIDIHDR)),
                    ("reserved", DWORD_PTR), ("dwOffset", wintypes.DWORD),
                    ("dwReserved", DWORD_PTR * 8)]
MHDR_DONE = 0x00000001
MIDIERR_STILLPLAYING = 65

MIDIINPROC = ctypes.WINFUNCTYPE(None, HMIDIIN, wintypes.UINT, DWORD_PTR, DWORD_PTR, DWORD_PTR)


def _sig(name, argtypes):
    f = getattr(_winmm, name)
    f.argtypes = argtypes
    f.restype = wintypes.UINT
    return f


midiOutGetNumDevs = _sig("midiOutGetNumDevs", [])
midiOutGetDevCapsW = _sig("midiOutGetDevCapsW", [DWORD_PTR, ctypes.POINTER(MIDIOUTCAPSW), wintypes.UINT])
midiOutOpen = _sig("midiOutOpen", [ctypes.POINTER(HMIDIOUT), wintypes.UINT, DWORD_PTR, DWORD_PTR, wintypes.DWORD])
midiOutShortMsg = _sig("midiOutShortMsg", [HMIDIOUT, wintypes.DWORD])
midiOutClose = _sig("midiOutClose", [HMIDIOUT])
midiOutPrepareHeader = _sig("midiOutPrepareHeader", [HMIDIOUT, ctypes.POINTER(MIDIHDR), wintypes.UINT])
midiOutUnprepareHeader = _sig("midiOutUnprepareHeader", [HMIDIOUT, ctypes.POINTER(MIDIHDR), wintypes.UINT])
midiOutLongMsg = _sig("midiOutLongMsg", [HMIDIOUT, ctypes.POINTER(MIDIHDR), wintypes.UINT])
midiOutGetErrorTextW = _sig("midiOutGetErrorTextW", [wintypes.UINT, wintypes.LPWSTR, wintypes.UINT])
midiInGetNumDevs = _sig("midiInGetNumDevs", [])
midiInGetDevCapsW = _sig("midiInGetDevCapsW", [DWORD_PTR, ctypes.POINTER(MIDIINCAPSW), wintypes.UINT])
midiInOpen = _sig("midiInOpen", [ctypes.POINTER(HMIDIIN), wintypes.UINT, MIDIINPROC, DWORD_PTR, wintypes.DWORD])
midiInStart = _sig("midiInStart", [HMIDIIN])
midiInStop = _sig("midiInStop", [HMIDIIN])
midiInReset = _sig("midiInReset", [HMIDIIN])
midiInClose = _sig("midiInClose", [HMIDIIN])


class MidiPortError(Exception):
    def __init__(self, code, action, port_name):
        self.code = code
        buf = ctypes.create_unicode_buffer(256)
        midiOutGetErrorTextW(code, buf, 256)
        detail = buf.value or f"エラーコード {code}"
        if code == MMSYSERR_ALLOCATED:
            msg = (f"「{port_name}」は他のアプリが使用中です。\n"
                   "Domino や Cubase を開いている場合は閉じてから、もう一度「接続」を押してください。\n"
                   "(Windows の MIDI ドライバは、1つのポートを同時に1つのアプリしか使えないことがあります)")
        elif code == MMSYSERR_BADDEVICEID:
            msg = f"「{port_name}」が見つかりません。USBケーブルを確認して「一覧を更新」を押してください。"
        else:
            msg = f"「{port_name}」を{action}できませんでした: {detail}"
        super().__init__(msg)


def list_outputs():
    names = []
    for i in range(midiOutGetNumDevs()):
        caps = MIDIOUTCAPSW()
        if midiOutGetDevCapsW(i, ctypes.byref(caps), ctypes.sizeof(caps)) == MMSYSERR_NOERROR:
            names.append(caps.szPname)
        else:
            names.append(f"(出力 {i})")
    return names


def list_inputs():
    names = []
    for i in range(midiInGetNumDevs()):
        caps = MIDIINCAPSW()
        if midiInGetDevCapsW(i, ctypes.byref(caps), ctypes.sizeof(caps)) == MMSYSERR_NOERROR:
            names.append(caps.szPname)
        else:
            names.append(f"(入力 {i})")
    return names


def message_length(status):
    if status < 0x80:
        return 0
    if status < 0xF0:
        return 2 if (status & 0xF0) in (0xC0, 0xD0) else 3
    return {0xF1: 2, 0xF2: 3, 0xF3: 2}.get(status, 1)


class OutputPort:
    def __init__(self, index, name):
        self.name = name
        self._h = HMIDIOUT()
        rc = midiOutOpen(ctypes.byref(self._h), index, 0, 0, 0)
        if rc != MMSYSERR_NOERROR:
            raise MidiPortError(rc, "開く", name)

    def send(self, msg: bytes):
        """チャンネルメッセージ(3バイト以下)または SysEx(F0 … F7)を送る"""
        if msg and msg[0] == 0xF0:
            self._send_long(msg)
            return
        packed = 0
        for i, b in enumerate(msg[:3]):
            packed |= b << (8 * i)
        rc = midiOutShortMsg(self._h, packed)
        if rc != MMSYSERR_NOERROR:
            raise MidiPortError(rc, "送信", self.name)

    def _send_long(self, msg: bytes):
        """SysEx を送り、送り終わるまで待つ(20バイト程度なら約7ms)"""
        buf = ctypes.create_string_buffer(bytes(msg), len(msg))
        hdr = MIDIHDR()
        hdr.lpData = ctypes.cast(buf, ctypes.c_void_p)
        hdr.dwBufferLength = hdr.dwBytesRecorded = len(msg)
        size = ctypes.sizeof(hdr)
        rc = midiOutPrepareHeader(self._h, ctypes.byref(hdr), size)
        if rc != MMSYSERR_NOERROR:
            raise MidiPortError(rc, "送信の準備", self.name)
        try:
            rc = midiOutLongMsg(self._h, ctypes.byref(hdr), size)
            if rc != MMSYSERR_NOERROR:
                raise MidiPortError(rc, "送信", self.name)
            deadline = time.monotonic() + 2.0
            while not hdr.dwFlags & MHDR_DONE and time.monotonic() < deadline:
                time.sleep(0.002)
        finally:
            for _ in range(100):   # 送信中なら少し待ってから解放する
                if midiOutUnprepareHeader(self._h, ctypes.byref(hdr), size) != MIDIERR_STILLPLAYING:
                    break
                time.sleep(0.01)

    def close(self):
        if self._h:
            midiOutClose(self._h)
            self._h = HMIDIOUT()


class InputPort:
    """on_message(bytes) は winmm のスレッドから呼ばれる。重い処理をしないこと。"""

    def __init__(self, index, name, on_message):
        self.name = name
        self._on_message = on_message
        self._cb = MIDIINPROC(self._callback)   # 参照を保持しないと GC で落ちる
        self._h = HMIDIIN()
        rc = midiInOpen(ctypes.byref(self._h), index, self._cb, 0, CALLBACK_FUNCTION)
        if rc != MMSYSERR_NOERROR:
            raise MidiPortError(rc, "開く", name)
        midiInStart(self._h)

    def _callback(self, h, msg, inst, p1, p2):
        if msg != MIM_DATA:
            return
        status = p1 & 0xFF
        n = message_length(status)
        if n:
            self._on_message(bytes((p1 >> (8 * i)) & 0xFF for i in range(n)))

    def close(self):
        if self._h:
            midiInStop(self._h)
            midiInReset(self._h)
            midiInClose(self._h)
            self._h = HMIDIIN()
