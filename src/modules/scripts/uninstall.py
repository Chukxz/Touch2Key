"""
Driver, Rules, and Data Uninstaller (GUI & CLI compatible).
Supports Windows (Interception driver) and Linux (udev rules with pkexec/sudo fallback).
"""

from __future__ import annotations

import argparse
import ctypes
import logging
import os
import shutil
import subprocess
import sys
from pathlib import Path

from PySide6.QtWidgets import QApplication, QMessageBox

from modules.database import store
from modules.log_manager import AppLogManager
from modules.utils import (
    BIN_FOLDER,
    DATA_FOLDER,
    DIAGNOSTICS_FOLDER,
    LOGS_FOLDER,
    PROJECT_ROOT,
    UDEV_RULE_PATH,
)

logger = logging.getLogger("modules.scripts.uninstall")


def _is_admin() -> bool:
    """Checks if current process has elevated privileges."""
    if sys.platform == "win32":
        try:
            return ctypes.windll.shell32.IsUserAnAdmin() != 0
        except Exception:
            return False
    return os.geteuid() == 0


def _request_windows_elevation() -> None:
    """Triggers Windows UAC prompt to relaunch uninstaller as Administrator."""
    script = Path(__file__).resolve()
    params = " ".join(sys.argv[1:])
    ctypes.windll.shell32.ShellExecuteW(
        None, "runas", sys.executable, f'"{script}" {params}', os.getcwd(), 1
    )


def _kill_adb() -> None:
    """Terminates active adb daemon instances across platforms."""
    cmd = (
        ["taskkill", "/F", "/IM", "adb.exe", "/T"]
        if sys.platform == "win32"
        else ["pkill", "-f", "adb"]
    )
    try:
        subprocess.run(cmd, capture_output=True, check=False)
    except Exception:
        pass


def _remove_linux_udev_rules(is_gui: bool) -> bool:
    """
    Removes the udev rule file and reloads udevadm.
    Elevates via pkexec in GUI mode or sudo in CLI mode if unprivileged.
    """
    rule_path = Path(UDEV_RULE_PATH)
    if not rule_path.exists():
        logger.info("No udev rule found at %s. Skipping removal.", rule_path)
        return True

    if _is_admin():
        try:
            rule_path.unlink()
            subprocess.run(["udevadm", "control", "--reload-rules"], check=True)
            subprocess.run(["udevadm", "trigger"], check=True)
            logger.info("Udev rule removed and subsystem reloaded as root.")
            return True
        except Exception as exc:
            logger.error("Failed to remove udev rule as root: %s", exc)
            return False

    cmd_str = f"rm -f {rule_path} && udevadm control --reload-rules && udevadm trigger"

    if is_gui and shutil.which("pkexec"):
        logger.info("Invoking PolicyKit (pkexec) to remove udev rule...")
        res = subprocess.run(["pkexec", "sh", "-c", cmd_str], capture_output=True)
        if res.returncode == 0:
            logger.info("Udev rule removed successfully via PolicyKit.")
            return True
        logger.warning("pkexec authentication canceled or failed.")
        return False

    if shutil.which("sudo"):
        logger.warning("Sudo authentication required to delete /etc/udev/rules.d rule...")
        print("[!] Sudo authentication required to delete /etc/udev/rules.d rule...")
        res = subprocess.run(["sudo", "sh", "-c", cmd_str])
        if res.returncode == 0:
            logger.info("Udev rule removed via sudo.")
            return True
        logger.error("Sudo authentication failed.")
        return False

    return False


def purge_data() -> None:
    """Deletes entire data directory (database, profiles, images, jsons, settings.toml)."""
    if DATA_FOLDER.exists():
        shutil.rmtree(DATA_FOLDER, ignore_errors=True)
    logger.info("Purged data directory: %s", DATA_FOLDER)


def purge_diagnostics() -> None:
    """Deletes diagnostics/ and any stray .prof profiling files in the project root."""
    if DIAGNOSTICS_FOLDER.exists():
        shutil.rmtree(DIAGNOSTICS_FOLDER, ignore_errors=True)

    for prof_file in PROJECT_ROOT.glob("*.prof"):
        prof_file.unlink(missing_ok=True)

    logger.info("Purged diagnostics folder and root profiling files.")


def purge_logs() -> None:
    """Deletes logs/ and any root session log files."""
    if LOGS_FOLDER.exists():
        shutil.rmtree(LOGS_FOLDER, ignore_errors=True)

    for log_file in PROJECT_ROOT.glob("*.log"):
        log_file.unlink(missing_ok=True)

    logger.info("Purged logs directory: %s", LOGS_FOLDER)


def run(parent=None) -> bool:
    is_gui = QApplication.instance() is not None

    parser = argparse.ArgumentParser(description="Touch2Key Uninstaller")
    parser.add_argument(
        "-y", "--yes", action="store_true", help="Skip confirmation prompt"
    )
    parser.add_argument(
        "--purge",
        action="store_true",
        help="Delete data directory (database, profiles, images, jsons, settings.toml)",
    )
    parser.add_argument(
        "--purge-all",
        action="store_true",
        help="Delete data directory, diagnostics/profiling files, and session logs",
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

    if sys.platform == "win32" and not _is_admin():
        msg = "Administrator privileges are required to uninstall the Interception driver."
        logger.error(msg)
        if is_gui:
            QMessageBox.critical(parent, "Elevation Required", msg)
        else:
            _request_windows_elevation()
        return False

    if not args.yes:
        confirm_text = (
            "Are you sure you want to remove the driver/rules and clean binaries?"
        )
        if is_gui:
            res = QMessageBox.question(
                parent,
                "Confirm Uninstall",
                confirm_text,
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if res != QMessageBox.StandardButton.Yes:
                return False
        else:
            confirm = input(f"{confirm_text} (y/N): ").strip().lower()
            if confirm != "y":
                print("[!] Aborted.")
                return False

    try:
        store.close()
    except Exception:
        pass
    _kill_adb()

    needs_reboot = False
    if sys.platform == "win32":
        installer_exe = (
            BIN_FOLDER
            / "Interception"
            / "command line installer"
            / "install-interception.exe"
        )
        if installer_exe.exists():
            res = subprocess.run(
                [str(installer_exe), "/uninstall"], capture_output=True
            )
            if res.returncode == 0:
                needs_reboot = True
                logger.info("Interception driver uninstalled.")
            else:
                logger.warning("Interception driver uninstall command failed.")
        else:
            logger.warning("Interception installer binary not found in bin/.")

    elif sys.platform == "linux":
        success = _remove_linux_udev_rules(is_gui=is_gui)
        if not success:
            err_msg = (
                "Could not remove udev rules due to lack of administrative permissions."
            )
            if is_gui:
                QMessageBox.critical(parent, "Permission Denied", err_msg)
            else:
                logger.error(err_msg)
            return False

    if BIN_FOLDER.exists():
        shutil.rmtree(BIN_FOLDER, ignore_errors=True)
        logger.info("Local platform binaries deleted.")

    if args.purge or args.purge_all:
        purge_data()

    if args.purge_all:
        purge_diagnostics()
        purge_logs()

    logger.info("Uninstall completed successfully.")

    if is_gui:
        if sys.platform == "win32" and needs_reboot and not args.no_restart:
            res = QMessageBox.question(
                parent,
                "Restart Required",
                "Driver removal requires a reboot. Restart now in 5 seconds?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            )
            if res == QMessageBox.StandardButton.Yes:
                subprocess.run(
                    ["shutdown", "/r", "/t", "5", "/c", "Uninstall complete."]
                )
                return True
        else:
            QMessageBox.information(
                parent, "Uninstall Complete", "Uninstallation finished successfully."
            )
    else:
        if sys.platform == "win32":
            if needs_reboot and not args.no_restart:
                print("\n" + "=" * 55)
                print(" SYSTEM RESTART REQUIRED ".center(55, "="))
                print("=" * 55)
                choice = input("Restart PC now in 5 seconds? (y/N): ").strip().lower()
                if choice == "y":
                    subprocess.run(
                        [
                            "shutdown",
                            "/r",
                            "/t",
                            "5",
                            "/c",
                            "Touch2Key driver uninstallation complete.",
                        ]
                    )
                    return True
                else:
                    print(
                        "[!] Please restart your computer manually to finalize removal."
                    )
            input("\nPress Enter to exit...")

    return True


def main() -> None:
    """Dedicated entry point for touch2key-uninstall script execution."""
    is_gui = QApplication.instance() is not None or "--gui" in sys.argv
    AppLogManager.setup_logging(is_gui=is_gui, log_prefix="touch2key_uninstall")
    
    if not run():
        sys.exit(1)


if __name__ == "__main__":
    main()
