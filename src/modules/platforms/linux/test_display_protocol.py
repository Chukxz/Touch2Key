import os


def _get_display_protocol():
    session = os.environ.get("XDG_SESSION_TYPE", "").lower()
    if session == "wayland":
        if "DISPLAY" in os.environ:
            return "xwayland"
        return "wayland"
    if session == "x11" or "DISPLAY" in os.environ:
        return "x11"
    return None


def check_display_protocol():
    protocol = _get_display_protocol()
    if protocol is None:
        print("\n[!] - Display protocol not found.")
        return False
    elif not protocol == "x11":
        print("\n[!] - Ensure you are on X11.")
        return False
    else:
        return True
