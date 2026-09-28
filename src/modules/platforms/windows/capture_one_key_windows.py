# ---------------------------------------------------------------------------
# Windows: one-shot raw key capture via WH_KEYBOARD_LL (ctypes)
# ---------------------------------------------------------------------------

import ctypes
import ctypes.wintypes as wintypes

WH_KEYBOARD_LL = 13
WM_KEYDOWN = 0x0100
WM_SYSKEYDOWN = 0x0104
LLKHF_EXTENDED = 0x01


class KBDLLHOOKSTRUCT(ctypes.Structure):
    _fields_ = [
        ("vkCode", wintypes.DWORD),
        ("scanCode", wintypes.DWORD),
        ("flags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ctypes.POINTER(wintypes.ULONG)),
    ]


LowLevelKeyboardProc = ctypes.WINFUNCTYPE(
    ctypes.c_int, ctypes.c_int, wintypes.WPARAM, wintypes.LPARAM
)


def capture_one_key_windows(timeout_ms: int | None = None) -> int | None:
    """Blocks until the next physical key-down, then returns it as this
    module's PS/2-style scancode (matching SCANCODES/SPECIAL_MAP's 0xE0xx
    convention for extended keys). Returns None on timeout.
    """
    result: dict[str, int | None] = {"code": None}

    def _proc(nCode, wParam, lParam):
        if nCode == 0 and wParam in (WM_KEYDOWN, WM_SYSKEYDOWN):
            kb = ctypes.cast(lParam, ctypes.POINTER(KBDLLHOOKSTRUCT)).contents
            scan_byte = kb.scanCode & 0xFF
            is_extended = bool(kb.flags & LLKHF_EXTENDED)
            result["code"] = (0xE000 | scan_byte) if is_extended else scan_byte
            ctypes.windll.user32.PostQuitMessage(0)
        return ctypes.windll.user32.CallNextHookEx(None, nCode, wParam, lParam)

    proc = LowLevelKeyboardProc(_proc)
    hook_id = ctypes.windll.user32.SetWindowsHookExW(
        WH_KEYBOARD_LL, proc, ctypes.windll.kernel32.GetModuleHandleW(None), 0
    )
    if not hook_id:
        raise OSError("SetWindowsHookExW failed")

    try:
        if timeout_ms is not None:
            ctypes.windll.user32.SetTimer(None, 1, timeout_ms, None)

        msg = wintypes.MSG()
        while ctypes.windll.user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
            ctypes.windll.user32.TranslateMessage(ctypes.byref(msg))
            ctypes.windll.user32.DispatchMessageW(ctypes.byref(msg))
            if result["code"] is not None:
                break
    finally:
        ctypes.windll.user32.UnhookWindowsHookEx(hook_id)

    return result["code"]
