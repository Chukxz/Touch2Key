"""
Platform setup and driver configuration bootstrap.
Executable in both interactive CLI and GUI application modes.
"""

from __future__ import annotations

import logging
import sys

from PySide6.QtWidgets import QApplication, QMessageBox

logger = logging.getLogger("modules.scripts.setup")


def run(parent=None) -> bool:
    is_gui = QApplication.instance() is not None

    logger.info("Starting automated platform configuration for %s", sys.platform)

    try:
        needs_reboot = False

        if sys.platform == "win32":
            from modules.platforms.windows import setup_windows
            needs_reboot = setup_windows(interactive=not is_gui)

        elif sys.platform == "linux":
            from modules.platforms.linux import setup_linux
            needs_reboot = setup_linux(interactive=not is_gui)

        else:
            msg = f"Unsupported Operating System: {sys.platform}"
            logger.error(msg)
            if is_gui:
                QMessageBox.critical(parent, "Setup Error", msg)
            return False

        logger.info("Setup finished successfully (reboot required: %s)", needs_reboot)
        
        if is_gui:
            if needs_reboot:
                QMessageBox.information(
                    parent,
                    "Reboot Recommended",
                    f"Setup completed for {sys.platform}.\n\n"
                    "Please restart your PC to finalize driver registration.",
                )
            else:
                QMessageBox.information(
                    parent,
                    "Setup Complete",
                    f"Environment setup for {sys.platform} completed successfully.",
                )

        return True

    except Exception as exc:
        logger.exception("Platform setup execution halted with an error")
        if is_gui:
            QMessageBox.critical(
                parent,
                "Setup Failed",
                f"Platform configuration failed:\n\n{exc}",
            )
        return False


if __name__ == "__main__":
    success = run()
    if not success:
        sys.exit(1)
