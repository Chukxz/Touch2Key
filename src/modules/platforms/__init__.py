from __future__ import annotations
from typing import TYPE_CHECKING, NamedTuple

from modules.utils import SYSTEM

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
    """Uses a named Mutex to prevent duplicate instances on Windows."""
    import ctypes

    mutex_name = f"Global\\{instance_name}"
    handle = ctypes.windll.kernel32.CreateMutexW(None, False, mutex_name)
    last_error = ctypes.windll.kernel32.GetLastError()
    if last_error == 183:  # ERROR_ALREADY_EXISTS
        return False, None
    if not handle:  # creation genuinely failed for another reason
        print(f"[UTILITY] - Mutex creation failed (error {last_error}).")
        return False, None
    return True, handle


def _check_single_instance_linux(instance_name: str) -> tuple[bool, object | None]:
    """Uses a lockfile to prevent duplicate Linux instances."""
    import fcntl

    lock_file = f"/tmp/{instance_name}.lock"
    try:
        # 'a' mode creates the file if it doesn't exist
        handle = open(lock_file, "a")
        fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        return True, handle
    except (IOError, OSError):
        return False, None


def check_single_instance(instance_name: str) -> tuple[bool, object | None]:
    """Wrapper to check if another instance is running."""
    if SYSTEM == "Windows":
        return _check_single_instance_windows(instance_name)
    elif SYSTEM == "Linux":
        return _check_single_instance_linux(instance_name)
    raise RuntimeError(f"Unsupported platform: {SYSTEM}")


def get_platform():
    """
    Returns the platform-specific modules.
    Imports are deferred inside the function to avoid circular imports.
    """
    if SYSTEM == "Windows":
        from .windows.bridge import InterceptionBridge as Bridge
        from .windows.window import WindowManager
        from .windows.system import SystemConfig
        from .windows.mapping import Mapping

        return PlatformModules(Bridge, WindowManager, SystemConfig, Mapping)

    elif SYSTEM == "Linux":
        from .linux.bridge import UInputBridge as Bridge
        from .linux.window import WindowManager
        from .linux.system import SystemConfig
        from .linux.mapping import Mapping

        return PlatformModules(Bridge, WindowManager, SystemConfig, Mapping)

    else:
        raise RuntimeError(f"Unsupported platform: {SYSTEM}")


def get_specific_mt_key(event):
    """
    Returns a specific string like 'lshift' or 'rshift'
    by inspecting the low-level Qt event in the Matplotlib event.
    """

    gui_event = event.guiEvent
    if not gui_event:
        return event.key

    # Cross-platform way to get the native scancode
    scan_code = gui_event.nativeScanCode()

    # Use the abstracted mapping layer for the translation
    mapped_key = get_platform().Mapping().get_key_from_scancode(scan_code)

    # Fallback to the standard key if it wasn't in our modifier map
    return mapped_key if mapped_key else event.key


def get_specific_qt_key(event):
    """
    Returns a specific string like 'lshift' or 'rshift'
    by inspecting the Qt event.
    """

    # Cross-platform way to get the native scancode
    scan_code = event.nativeScanCode()

    # Use the abstracted mapping layer for the translation
    mapped_key = get_platform().Mapping().get_key_from_scancode(scan_code)

    # Fallback to the standard key if it wasn't in our modifier map
    return mapped_key if mapped_key else event.text()


__all__ = ["check_single_instance", "get_platform"]
