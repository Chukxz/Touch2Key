"""
Diagnostic utility to inspect resolved ADB binary path.
"""

from __future__ import annotations

import shutil
from pathlib import Path
from modules.utils import ADB


def run() -> None:
    if ADB.exists():
        print(f"[+] ADB Executable found at: {ADB.resolve()}")
        return

    system_adb = shutil.which("adb")
    if system_adb:
        print(f"[+] ADB found in system PATH at: {Path(system_adb).resolve()}")
    else:
        print("[!] ADB Executable not found in project bin or system PATH.")


if __name__ == "__main__":
    run()
