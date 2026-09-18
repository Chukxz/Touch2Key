"""
Pre-flight environment and dependency checks.
Outputs via logging / QMessageBox in GUI mode and standard print in CLI mode.
"""

from __future__ import annotations

import logging
import shutil
from pathlib import Path
from PySide6.QtWidgets import QApplication, QMessageBox

from modules.utils import SYSTEM, ADB

logger = logging.getLogger("modules.scripts.pre_flight")


def check_adb() -> bool:
    """Verify ADB binary is available in project bin folder or system PATH."""
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


def run(verbose: bool = True, parent=None) -> bool:
    """
    Executes pre-flight checks.
    Returns True if all pass, False otherwise.
    """
    is_gui = QApplication.instance() is not None

    checks = {
        "ADB": check_adb(),
        "Driver": check_driver(),
    }

    failed = [name for name, status in checks.items() if not status]

    if failed:
        err_lines = []
        if "ADB" in failed:
            err_lines.append(
                "• ADB binary not found. Run setup to download platform-tools."
            )
        if SYSTEM == "Windows" and "Driver" in failed:
            err_lines.append(
                "• Interception driver not accessible. Run setup or restart your PC."
            )
        elif SYSTEM == "Linux" and "Driver" in failed:
            err_lines.append(
                "• /dev/uinput access missing. Run 'sudo setup' to configure udev rules."
            )

        err_msg = "\n".join(err_lines)

        if is_gui:
            logger.error("Pre-flight checks failed:\n%s", err_msg)
            if verbose:
                QMessageBox.warning(
                    parent,
                    "Pre-flight Checks Failed",
                    f"System checks did not pass:\n\n{err_msg}",
                )
        else:
            if verbose:
                print("[!] Pre-flight checks failed:")
                for line in err_lines:
                    print(f"    {line}")
        return False

    if is_gui:
        logger.info("Pre-flight checks passed successfully.")
    elif verbose:
        print("[+] Pre-flight checks passed.")

    return True


if __name__ == "__main__":
    run()
