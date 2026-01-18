import sys
import os

# Platform detection
IS_WINDOWS = sys.platform == "win32"
IS_LINUX = sys.platform.startswith("linux")

def get_input_bridge():
    """
    Factory to return the appropriate bridge.
    On Windows, it returns the existing InterceptionBridge.
    On Linux, it returns the new LinuxInputBridge.
    """
    if IS_WINDOWS:
        # Keep existing behavior for Windows
        from ..bridge import InterceptionBridge
        return InterceptionBridge()
    elif IS_LINUX:
        from .linux import LinuxInputBridge
        return LinuxInputBridge()
    else:
        raise NotImplementedError(f"Platform {sys.platform} is not supported yet.")

__all__ = ["IS_WINDOWS", "IS_LINUX", "get_input_bridge"]
