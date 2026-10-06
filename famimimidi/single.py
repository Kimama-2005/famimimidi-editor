"""アプリを同時に2つ起動させない(Windows の名前付きミューテックス)。

2つ同時に動くと、両方が同じ鍵盤の演奏を受け取って二重に送ったり(C5 の確認で実際に起きた:
microKEY2 の演奏が ch2 と ch1 の両方で鳴った)、両方がカートリッジの対応表を保存して記録が食い違ったりする。
新しい画面と予備の tkinter 版でも同じ名前を使い、どちらか1つだけにする。
"""
import ctypes
from ctypes import wintypes

MUTEX_NAME = "Local\\FamimimidiSoundEditor"
WINDOW_TITLES = ("FAMIMIMIDI SOUND EDITOR", "ふぁみみみっでぃ 音色エディタ(段階3)")
ERROR_ALREADY_EXISTS = 183

_k = ctypes.WinDLL("kernel32", use_last_error=True)
_k.CreateMutexW.argtypes = [wintypes.LPVOID, wintypes.BOOL, wintypes.LPCWSTR]
_k.CreateMutexW.restype = wintypes.HANDLE
_u = ctypes.WinDLL("user32")
_u.FindWindowW.argtypes = [wintypes.LPCWSTR, wintypes.LPCWSTR]
_u.FindWindowW.restype = wintypes.HWND
_u.MessageBoxW.argtypes = [wintypes.HWND, wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.UINT]
_handle = None       # プロセスが終わるまで持ち続ける(閉じると次の起動を止められない)


def acquire():
    """起動してよければ True。すでにほかが起動していれば、その画面を手前に出して知らせ、False"""
    global _handle
    _handle = _k.CreateMutexW(None, False, MUTEX_NAME)
    if ctypes.get_last_error() != ERROR_ALREADY_EXISTS:
        return True
    for title in WINDOW_TITLES:
        hwnd = _u.FindWindowW(None, title)
        if hwnd:
            _u.ShowWindow(hwnd, 9)          # SW_RESTORE
            _u.SetForegroundWindow(hwnd)
            break
    _u.MessageBoxW(None, "FAMIMIMIDI SOUND EDITOR はすでに起動しています。\n"
                         "2つ同時に動かすと、鍵盤の演奏が二重に送られるなどの問題が起きるため、開いている画面を使ってください。",
                   "FAMIMIMIDI SOUND EDITOR", 0x40)
    return False
