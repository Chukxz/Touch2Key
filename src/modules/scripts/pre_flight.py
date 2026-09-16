"""
Pre-flight environment and dependency checks.
Callable by both the CLI bootstrap and GUI startup workers.
"""

from __future__ import annotations

import shutil
from pathlib import Path
from modules.utils import SYSTEM, ADB


def check_adb() -> bool:
    """Verify ADB binary is available in PATH or project bin folder."""
    if ADB.exists():
        return True

    system_adb = shutil.which("adb")
    if system_adb and Path(system_adb).exists():
        return True

    return False


def check_driver() -> bool:
    """Verify low-level driver or kernel subsystem access."""
    if SYSTEM == "Windows":
        try:
            from interception.interception import Interception
            return Interception().valid
        except Exception:
            return False

    elif SYSTEM == "Linux":
        return Path("/dev/uinput").exists()

    return False


def run(verbose: bool = True) -> bool:
    """Executes pre-flight checks. Returns True if all pass, False otherwise."""
    checks = {
        "ADB": check_adb(),
        "Driver": check_driver(),
    }

    failed = [name for name, status in checks.items() if not status]

    if failed:
        if verbose:
            print("[!] Pre-flight failed:")
            if "ADB" in failed:
                print("    - ADB not found. Run setup to download it.")
            if SYSTEM == "Windows" and "Driver" in failed:
                print(
                    "    - Interception driver not found. Run setup or restart PC if recently installed."
                )
            elif SYSTEM == "Linux" and "Driver" in failed:
                print("    - uinput permissions missing. Run 'sudo setup' to configure udev rules.")
        return False

    if verbose:
        print("[+] Pre-flight checks passed.")
    return True


if __name__ == "__main__":
    run()
