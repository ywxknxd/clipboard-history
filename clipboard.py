"""剪贴板读写：直接调 Windows 的 API，不装任何第三方包。

为什么不用 tkinter 自带的 clipboard_get：那个要求窗口有焦点，
后台常驻的程序拿不到焦点时读出来是空的。
"""

import ctypes
import time
from ctypes import wintypes

user32 = ctypes.WinDLL("user32", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

CF_TEXT = 1
CF_UNICODETEXT = 13
GMEM_MOVEABLE = 0x0002

user32.OpenClipboard.argtypes = [wintypes.HWND]
user32.OpenClipboard.restype = wintypes.BOOL
user32.CloseClipboard.restype = wintypes.BOOL
user32.EmptyClipboard.restype = wintypes.BOOL
user32.GetClipboardData.argtypes = [wintypes.UINT]
user32.GetClipboardData.restype = wintypes.HANDLE
user32.SetClipboardData.argtypes = [wintypes.UINT, wintypes.HANDLE]
user32.SetClipboardData.restype = wintypes.HANDLE

kernel32.GlobalAlloc.argtypes = [wintypes.UINT, ctypes.c_size_t]
kernel32.GlobalAlloc.restype = wintypes.HANDLE
kernel32.GlobalLock.argtypes = [wintypes.HANDLE]
kernel32.GlobalLock.restype = ctypes.c_void_p
kernel32.GlobalUnlock.argtypes = [wintypes.HANDLE]
kernel32.GlobalFree.argtypes = [wintypes.HANDLE]


def _open(retries=5, wait=0.02):
    """别的程序可能正占着剪贴板，抢不到就短暂重试几次。

    不能无限等：抢占失败时程序会卡死，而这里每 0.4 秒就会来一次，错过这轮无所谓。
    """
    for _ in range(retries):
        if user32.OpenClipboard(None):
            return True
        time.sleep(wait)
    return False


def get_text():
    """读当前剪贴板里的文字。读不到（是图片、是文件、被占用）返回空字符串。"""
    if not _open():
        return ""
    try:
        for fmt in (CF_UNICODETEXT, CF_TEXT):
            handle = user32.GetClipboardData(fmt)
            if not handle:
                continue
            ptr = kernel32.GlobalLock(handle)
            if not ptr:
                continue
            try:
                if fmt == CF_UNICODETEXT:
                    return ctypes.wstring_at(ptr)
                raw = ctypes.string_at(ptr)
                # 老程序只放 ANSI 文本，用 GBK 解（中文 Windows 的默认编码）
                return raw.decode("gbk", "ignore")
            finally:
                kernel32.GlobalUnlock(handle)
        return ""
    finally:
        # 必须无条件关闭。漏掉这一句会让整个系统的复制粘贴全部失效。
        user32.CloseClipboard()


def set_text(text):
    """把文字放进剪贴板，成功返回 True。"""
    data = text.encode("utf-16-le") + b"\x00\x00"

    if not _open():
        return False
    try:
        user32.EmptyClipboard()
        handle = kernel32.GlobalAlloc(GMEM_MOVEABLE, len(data))
        if not handle:
            return False

        ptr = kernel32.GlobalLock(handle)
        if not ptr:
            kernel32.GlobalFree(handle)
            return False

        ctypes.memmove(ptr, data, len(data))
        kernel32.GlobalUnlock(handle)

        if not user32.SetClipboardData(CF_UNICODETEXT, handle):
            kernel32.GlobalFree(handle)
            return False
        # 成功后内存所有权归系统，这里不能再 GlobalFree，否则系统读到的是野指针
        return True
    finally:
        user32.CloseClipboard()
