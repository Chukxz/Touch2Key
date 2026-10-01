"""
Platform setup and driver configuration bootstrap.
Executable in both interactive CLI and GUI application modes.
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path
import subprocess

from modules import AppLogManager

from PySide6.QtWidgets import QApplication, QMessageBox
from modules.utils import PROJECT_ROOT, ICONS_FOLDER

logger = logging.getLogger("modules.scripts.setup")


def create_desktop_shortcut() -> None:
    desktop = Path.home() / "Desktop"
    if not desktop.exists():
        return  # Headless or containerized environment without a desktop

    if sys.platform == "win32":
        shortcut_path = desktop / "Touch2Key.lnk"
        target_script = PROJECT_ROOT / "src" / "modules" / "gui" / "app.py"
        icon_path = ICONS_FOLDER / "app.ico"

        ps_script = f"""
        $WshShell = New-Object -ComObject WScript.Shell
        $Shortcut = $WshShell.CreateShortcut("{shortcut_path}")
        $Shortcut.TargetPath = "pythonw.exe"
        $Shortcut.Arguments = '"{target_script}"'
        $Shortcut.WorkingDirectory = "{PROJECT_ROOT}"
        $Shortcut.IconLocation = "{icon_path}"
        $Shortcut.Save()
        """
        subprocess.run(["powershell", "-Command", ps_script], capture_output=True)

    elif sys.platform == "linux":
        desktop_file = desktop / "touch2key.desktop"
        exec_path = (
            f"{sys.executable} {PROJECT_ROOT / 'src' / 'modules' / 'gui' / 'app.py'}"
        )
        icon_path = ICONS_FOLDER / "app.png"

        content = f"""[Desktop Entry]
Type=Application
Name=Touch2Key
Exec={exec_path}
Path={PROJECT_ROOT}
Icon={icon_path}
Terminal=false
Categories=Utility;Application;
"""
        desktop_file.write_text(content.strip())
        desktop_file.chmod(0o755)

    logger.info("Desktop shortcuts created at %s", desktop)


def run(parent=None) -> bool:
    is_gui = QApplication.instance() is not None

    parser = argparse.ArgumentParser(description="Touch2Key Setup Utility")
    parser.add_argument(
        "-y",
        "--yes",
        action="store_true",
        help="Skip confirmation prompt / non-interactive mode",
    )
    parser.add_argument(
        "--no-restart",
        action="store_true",
        help="Skip system reboot prompt (Windows only, safely ignored on Linux)",
    )

    if is_gui:
        args, _ = parser.parse_known_args()
    else:
        args = parser.parse_args()

    # If --yes is passed, force interactive to False so scripts don't block
    interactive_mode = not is_gui and not args.yes

    logger.info("Starting automated platform configuration for %s", sys.platform)

    create_desktop_shortcut()

    try:
        needs_reboot = False

        if sys.platform == "win32":
            from modules.platforms.windows import setup_windows

            needs_reboot = setup_windows(
                interactive=interactive_mode, no_restart=args.no_restart
            )

        elif sys.platform == "linux":
            from modules.platforms.linux import setup_linux

            needs_reboot = setup_linux(
                interactive=interactive_mode, no_restart=args.no_restart
            )

        else:
            msg = f"Unsupported Operating System: {sys.platform}"
            logger.error(msg)
            if is_gui:
                QMessageBox.critical(parent, "Setup Error", msg)
            return False

        logger.info("Setup finished successfully (reboot required: %s)", needs_reboot)

        if is_gui:
            if needs_reboot and not args.no_restart:
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


def main() -> None:
    """Dedicated entry point for CLI and pyproject.toml execution."""
    # 1. Initialize logging right at the entry boundary
    AppLogManager.setup_logging(is_gui=False, log_prefix="touch2key_setup")

    # 2. Run the script logic
    success = run()
    if not success:
        sys.exit(1)


# Allows running directly
if __name__ == "__main__":
    main()
