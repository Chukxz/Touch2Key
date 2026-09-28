import ctypes


def get_lock_states_windows() -> dict[str, bool]:

    VK_CAPITAL = 0x14
    VK_NUMLOCK = 0x90
    VK_SCROLL = 0x91
    return {
        "caps_lock": bool(ctypes.windll.user32.GetKeyState(VK_CAPITAL) & 1),
        "num_lock": bool(ctypes.windll.user32.GetKeyState(VK_NUMLOCK) & 1),
        "scroll_lock": bool(ctypes.windll.user32.GetKeyState(VK_SCROLL) & 1),
    }
