"""
Platform setup and driver configuration bootstrap.
Executable in both interactive CLI and GUI application modes.
"""

from __future__ import annotations

import argparse
import ctypes
import logging
import sys
from pathlib import Path
import subprocess

from modules.log_manager import AppLogManager, modify_qt_logging_rules_on_win32

from PySide6.QtWidgets import QApplication, QMessageBox
from modules.utils import PROJECT_ROOT, ICONS_FOLDER

logger = logging.getLogger("modules.scripts.setup")


def create_desktop_shortcut() -> None:
    desktop = Path.home() / "Desktop"
    if not desktop.exists():
        return

    exe = Path(sys.executable)

    if sys.platform == "win32":
        shortcut_path = desktop / "Touch2Key.lnk"
        pythonw = exe.with_name("pythonw.exe")
        target = pythonw if pythonw.exists() else exe
        icon_path = ICONS_FOLDER / "app.ico"

        ps_script = f"""
        $WshShell = New-Object -ComObject WScript.Shell
        $Shortcut = $WshShell.CreateShortcut("{shortcut_path}")
        $Shortcut.TargetPath = "{target}"
        $Shortcut.Arguments = "-m modules.gui.app"
        $Shortcut.WorkingDirectory = "{PROJECT_ROOT}"
        $Shortcut.IconLocation = "{icon_path}"
        $Shortcut.Save()
        """
        subprocess.run(["powershell", "-Command", ps_script], capture_output=True)

    elif sys.platform == "linux":
        desktop_file = desktop / "touch2key.desktop"
        icon_path = ICONS_FOLDER / "app.png"

        content = f"""[Desktop Entry]
Type=Application
Name=Touch2Key
Exec="{exe}" -m modules.gui.app
Path={PROJECT_ROOT}
Icon={icon_path}
Terminal=false
Categories=Utility;Application;
"""
        desktop_file.write_text(content.strip())
        desktop_file.chmod(0o755)

    logger.info("Desktop shortcuts created at %s", desktop)


def _is_admin() -> bool:
    try:
        return ctypes.windll.shell32.IsUserAnAdmin() != 0
    except Exception:
        return False


def _relaunch_elevated() -> bool:
    params = subprocess.list2cmdline(["-m", "modules.scripts.setup", *sys.argv[1:]])
    res = ctypes.windll.shell32.ShellExecuteW(
        None, "runas", sys.executable, params, str(PROJECT_ROOT), 1
    )
    return res > 32


def run(parent=None) -> bool:
    is_gui = "--gui" in sys.argv or QApplication.instance() is not None

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
    parser.add_argument(
        "--gui",
        action="store_true",
        help="Use dialogs and graphical elevation",
    )

    args, _ = parser.parse_known_args()
    interactive_mode = not is_gui and not args.yes

    logger.info("Starting automated platform configuration for %s", sys.platform)

    create_desktop_shortcut()

    try:
        needs_reboot = False

        if sys.platform == "win32":
            from modules.platforms.windows import setup_windows

            if is_gui and not _is_admin():
                if _relaunch_elevated():
                    return True
                raise PermissionError("UAC elevation prompt was rejected.")

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
    gui = "--gui" in sys.argv[1:]
    console = "auto" if gui else "on"
    AppLogManager.setup_logging(log_prefix="touch2key_setup", console=console)

    modify_qt_logging_rules_on_win32()

    app = (
        QApplication(sys.argv[:1]) if gui and QApplication.instance() is None else None
    )
    try:
        run()
    finally:
        if app is not None:
            app.quit()


if __name__ == "__main__":
    main()
