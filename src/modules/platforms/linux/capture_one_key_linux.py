# ---------------------------------------------------------------------------
# Linux: one-shot raw key capture via python-evdev
# ---------------------------------------------------------------------------

from __future__ import annotations

import select
from evdev import InputDevice, categorize, ecodes, list_devices
from .ecodes_map import LINUX_KEY_MAP_INV


def capture_one_key_linux(timeout_s: float | None = None) -> int | None:
    """Blocks until the next physical key-down on any /dev/input keyboard
    device, then returns it as this module's PS/2-style scancode via the
    LINUX_KEY_MAP_INV (evdev ecode -> PS/2 scancode). Returns None on timeout.
    """
    devices = []
    try:
        devices = [InputDevice(path) for path in list_devices()]
    except Exception:
        return None

    # Filter strictly for keyboards by ensuring they support EV_KEY but not EV_REL (mice)
    keyboards = [
        d
        for d in devices
        if ecodes.EV_KEY in d.capabilities() and ecodes.EV_REL not in d.capabilities()
    ]

    # Fallback to any EV_KEY device if strict keyboard filtering returns empty
    if not keyboards:
        keyboards = [d for d in devices if ecodes.EV_KEY in d.capabilities()]

    if not keyboards:
        for d in devices:
            try:
                d.close()
            except Exception:
                pass
        return None

    fd_to_dev = {d.fd: d for d in keyboards}

    try:
        r, _, _ = select.select(fd_to_dev.keys(), [], [], timeout_s)
        for fd in r:
            dev = fd_to_dev[fd]
            try:
                for event in dev.read():
                    if event.type == ecodes.EV_KEY:
                        key_event = categorize(event)
                        if key_event.keystate == key_event.key_down:
                            return LINUX_KEY_MAP_INV.get(event.code)
            except Exception:
                continue
        return None
    finally:
        for d in devices:
            try:
                d.close()
            except Exception:
                pass


if __name__ == "__main__":
    print("Waiting for key press on Linux (10s timeout)...")
    code = capture_one_key_linux(timeout_s=10.0)
    print(f"Captured scancode: {hex(code) if code else None}")
