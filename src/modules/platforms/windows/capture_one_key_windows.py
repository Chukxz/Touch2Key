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

    user32 = ctypes.windll.user32

    # Configure explicit signatures for 64-bit safety (using LPARAM / c_ssize_t for pointer-sized results)
    user32.SetWindowsHookExW.argtypes = [
        ctypes.c_int,
        LowLevelKeyboardProc,
        wintypes.HMODULE,
        wintypes.DWORD,
    ]
    user32.SetWindowsHookExW.restype = wintypes.HHOOK

    user32.CallNextHookEx.argtypes = [
        wintypes.HHOOK,
        ctypes.c_int,
        wintypes.WPARAM,
        wintypes.LPARAM,
    ]
    user32.CallNextHookEx.restype = wintypes.LPARAM  # Pointer-sized signed integer

    user32.UnhookWindowsHookEx.argtypes = [wintypes.HHOOK]
    user32.UnhookWindowsHookEx.restype = wintypes.BOOL

    def _proc(nCode, wParam, lParam):
        if nCode == 0 and wParam in (WM_KEYDOWN, WM_SYSKEYDOWN):
            kb = ctypes.cast(lParam, ctypes.POINTER(KBDLLHOOKSTRUCT)).contents
            scan_byte = kb.scanCode & 0xFF
            is_extended = bool(kb.flags & LLKHF_EXTENDED)
            result["code"] = (0xE000 | scan_byte) if is_extended else scan_byte
            user32.PostQuitMessage(0)
        return user32.CallNextHookEx(None, nCode, wParam, lParam)

    proc = LowLevelKeyboardProc(_proc)

    # Pass None (0) for hMod to avoid error 126
    hook_id = user32.SetWindowsHookExW(WH_KEYBOARD_LL, proc, None, 0)
    if not hook_id:
        err = ctypes.windll.kernel32.GetLastError()
        raise OSError(f"SetWindowsHookExW failed with error code: {err}")

    try:
        if timeout_ms is not None:
            user32.SetTimer(None, 1, timeout_ms, None)

        msg = wintypes.MSG()
        while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
            user32.TranslateMessage(ctypes.byref(msg))
            user32.DispatchMessageW(ctypes.byref(msg))
            if result["code"] is not None:
                break
    finally:
        user32.UnhookWindowsHookEx(hook_id)

    return result["code"]


if __name__ == "__main__":
    key = capture_one_key_windows(timeout_ms=5000)
    print(f"Captured scancode: {hex(key) if key else None}")
