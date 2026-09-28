# ---------------------------------------------------------------------------
# Linux: one-shot raw key capture via python-evdev
# ---------------------------------------------------------------------------

from evdev import InputDevice, categorize, ecodes, list_devices
from modules.platforms.linux.ecodes_map import LINUX_KEY_MAP_INV


def capture_one_key_linux(timeout_s: float | None = None) -> int | None:
    """Blocks until the next physical key-down on any /dev/input keyboard
    device, then returns it as this module's PS/2-style scancode via the
    LINUX_KEY_MAP_INV (evdev ecode -> PS/2 scancode). Returns None on timeout.
    """
    import select

    devices = [InputDevice(path) for path in list_devices()]
    keyboards = [
        d for d in devices if ecodes.EV_KEY in d.capabilities().get(ecodes.EV_KEY, [])
    ]
    if not keyboards:
        return None

    fd_to_dev = {d.fd: d for d in keyboards}

    try:
        r, _, _ = select.select(fd_to_dev.keys(), [], [], timeout_s)
        for fd in r:
            dev = fd_to_dev[fd]
            for event in dev.read():
                if event.type == ecodes.EV_KEY:
                    key_event = categorize(event)
                    if key_event.keystate == key_event.key_down:
                        return LINUX_KEY_MAP_INV.get(event.code)
        return None
    finally:
        for d in keyboards:
            d.close()
