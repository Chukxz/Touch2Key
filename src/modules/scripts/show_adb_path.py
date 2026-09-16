"""
Diagnostic utility to inspect resolved ADB path.
"""

from __future__ import annotations

import logging
import shutil
from pathlib import Path
from PySide6.QtWidgets import QApplication

from modules.utils import ADB

logger = logging.getLogger("modules.scripts.check_adb")


def run() -> str | None:
    is_gui = QApplication.instance() is not None

    resolved_path: Path | None = None

    if ADB.exists():
        resolved_path = ADB.resolve()
    else:
        system_adb = shutil.which("adb")
        if system_adb:
            resolved_path = Path(system_adb).resolve()

    if resolved_path:
        msg = f"ADB binary located at: {resolved_path}"
        if is_gui:
            logger.info(msg)
        else:
            print(f"[+] {msg}")
        return str(resolved_path)

    msg = "ADB binary not found in project bin directory or system PATH."
    if is_gui:
        logger.warning(msg)
    else:
        print(f"[!] {msg}")
    return None


if __name__ == "__main__":
    run()
