"""
Platform setup and driver configuration bootstrap.
"""

from __future__ import annotations

import logging
import sys
from PySide6.QtWidgets import QApplication, QMessageBox

from modules.utils import SYSTEM

logger = logging.getLogger("modules.scripts.setup")


def run(parent=None) -> bool:
    is_gui = QApplication.instance() is not None

    if is_gui:
        logger.info("Starting platform setup for: %s", SYSTEM)
    else:
        print(f"--- Setting up for {SYSTEM} ---")

    try:
        if SYSTEM == "Windows":
            from modules.platforms.windows import setup_windows
            setup_windows()

        elif SYSTEM == "Linux":
            from modules.platforms.linux import setup_linux
            setup_linux()

        else:
            msg = f"Unsupported Operating System: {SYSTEM}"
            if is_gui:
                logger.error(msg)
                QMessageBox.critical(parent, "Setup Error", msg)
            else:
                print(f"[!] {msg}")
            return False

        if is_gui:
            logger.info("Platform setup completed successfully.")
            QMessageBox.information(parent, "Setup Complete", f"Environment setup for {SYSTEM} finished.")
        else:
            print("[+] Setup complete.")
        return True

    except Exception as exc:
        if is_gui:
            logger.exception("Setup failed")
            QMessageBox.critical(parent, "Setup Failed", f"Setup encountered an error:\n{exc}")
        else:
            print(f"[!] Setup failed: {exc}")
        return False


if __name__ == "__main__":
    if not run():
        sys.exit(1)
