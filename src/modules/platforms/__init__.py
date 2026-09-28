from __future__ import annotations

import sys
from typing import TYPE_CHECKING, NamedTuple

if TYPE_CHECKING:
    from .windows.bridge import InterceptionBridge
    from .windows.window import WindowManager as WindowsWindowManager
    from .windows.system import SystemConfig as WindowsSystemConfig
    from .windows.mapping import Mapping as WindowsMapping

    from .linux.bridge import UInputBridge
    from .linux.window import WindowManager as LinuxWindowManager
    from .linux.system import SystemConfig as LinuxSystemConfig
    from .linux.mapping import Mapping as LinuxMapping


class PlatformModules(NamedTuple):
    Bridge: type[InterceptionBridge] | type[UInputBridge]
    WindowManager: type[WindowsWindowManager] | type[LinuxWindowManager]
    SystemConfig: type[WindowsSystemConfig] | type[LinuxSystemConfig]
    Mapping: type[WindowsMapping] | type[LinuxMapping]


def _check_single_instance_windows(instance_name: str) -> tuple[bool, int | None]:
    if sys.platform == "win32":
        import ctypes

        mutex_name = f"Global\\{instance_name}"
        handle = ctypes.windll.kernel32.CreateMutexW(None, False, mutex_name)
        last_error = ctypes.windll.kernel32.GetLastError()
        if last_error == 183:  # ERROR_ALREADY_EXISTS
            return False, None
        if not handle:
            print(f"[UTILITY] - Mutex creation failed (error {last_error}).")
            return False, None
        return True, handle

    raise RuntimeError(f"Unsupported platform: {sys.platform}")


def _check_single_instance_linux(instance_name: str) -> tuple[bool, object | None]:
    if sys.platform == "linux":
        import fcntl

        lock_file = f"/tmp/{instance_name}.lock"
        try:
            handle = open(lock_file, "a")
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
            return True, handle
        except (IOError, OSError):
            return False, None

    raise RuntimeError(f"Unsupported platform: {sys.platform}")


def check_single_instance(instance_name: str) -> tuple[bool, object | None]:
    if sys.platform == "win32":
        return _check_single_instance_windows(instance_name)
    elif sys.platform == "linux":
        return _check_single_instance_linux(instance_name)

    raise RuntimeError(f"Unsupported platform: {sys.platform}")


def get_platform() -> PlatformModules:
    if sys.platform == "win32":
        from .windows.bridge import InterceptionBridge as Bridge
        from .windows.window import WindowManager
        from .windows.system import SystemConfig
        from .windows.mapping import Mapping

        return PlatformModules(Bridge, WindowManager, SystemConfig, Mapping)

    elif sys.platform == "linux":
        from .linux.bridge import UInputBridge as Bridge
        from .linux.window import WindowManager
        from .linux.system import SystemConfig
        from .linux.mapping import Mapping

        return PlatformModules(Bridge, WindowManager, SystemConfig, Mapping)

    else:
        raise RuntimeError(f"Unsupported platform: {SYSTEM}")


def get_specific_mt_key(event) -> str:
    """Safe mapping helper for Matplotlib canvas events."""
    gui_event = getattr(event, "guiEvent", None)
    if not gui_event or not hasattr(gui_event, "nativeScanCode"):
        return str(event.key)

    scan_code = gui_event.nativeScanCode()
    mapped_key = get_platform().Mapping().get_key_name_from_code(scan_code)
    return mapped_key if mapped_key else str(event.key)


def get_specific_qt_key(event) -> str:
    """Safe mapping helper for PySide6 key events."""
    if not hasattr(event, "nativeScanCode"):
        return getattr(event, "text", lambda: "")()

    scan_code = event.nativeScanCode()
    mapped_key = get_platform().Mapping().get_key_name_from_code(scan_code)
    return mapped_key if mapped_key else event.text()


def capture_one_key() -> int | None:
    """Cross-platform: blocks until the next physical key press, returns
    this module's PS/2-style scancode. Replaces the `keyboard` module for
    the 'press a key to bind' capture flow.
    """
    if sys.platform == "win32":
        from .windows.capture_one_key_windows import capture_one_key_windows
        return capture_one_key_windows()
    elif sys.platform == "linux":
        from .linux.capture_one_key_linux import capture_one_key_linux
        return capture_one_key_linux()
    else:
        return None


def get_lock_states() -> dict[str, bool] | None:
    """Cross-platform: current toggle state of CapsLock/NumLock/ScrollLock,
    keyed by the same names LOCK_KEYS uses ("caps_lock", "num_lock",
    "scroll_lock"). Unlike modifier state (transient, tracked live by the
    input stack), lock-key toggle state is a persistent OS/driver flag
    exposed via a direct query -- callers never need to track it themselves.
    """
    if sys.platform == "win32":
        from .windows.lock_state import get_lock_states_windows
        return get_lock_states_windows()
    elif sys.platform == "linux":
        from .linux.lock_state import get_lock_states_linux
        return get_lock_states_linux()
    else:
        return None


__all__ = [
    "check_single_instance",
    "get_platform",
    "get_specific_mt_key",
    "get_specific_qt_key",
]
