#!/usr/bin/env python3
"""
Driver, Rules, and Data Uninstaller (GUI & CLI compatible).
Supports both Windows (Interception driver) and Linux (udev rules).
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
from modules.utils import (
    BIN_DIR,
    DATA_FOLDER,
    DIAGNOSTICS_FOLDER,
    LOGS_FOLDER,
    PROJECT_ROOT,
    SYSTEM,
    UDEV_RULE_PATH,
)

logger = logging.getLogger("modules.scripts.uninstall")


def _is_admin() -> bool:
    """Checks for Administrator (Windows) or root (Linux) privileges."""
    if SYSTEM == "Windows":
        try:
            return ctypes.windll.shell32.IsUserAnAdmin() != 0
        except Exception:
            return False
    return os.geteuid() == 0


def _request_elevation() -> None:
    """Requests elevation via Windows UAC or prints sudo warning on Linux."""
    if SYSTEM == "Windows":
        script = Path(__file__).resolve()
        params = " ".join(sys.argv[1:])
        ctypes.windll.shell32.ShellExecuteW(
            None, "runas", sys.executable, f'"{script}" {params}', os.getcwd(), 1
        )
    else:
        print("[!] Please re-run this script with 'sudo'.")


def _kill_adb() -> None:
    """Terminates active adb daemon instances across platforms."""
    cmd = (
        ["taskkill", "/F", "/IM", "adb.exe", "/T"]
        if SYSTEM == "Windows"
        else ["pkill", "-f", "adb"]
    )
    try:
        subprocess.run(cmd, capture_output=True, check=False)
    except Exception:
        pass


def purge_data(is_gui: bool) -> None:
    """Deletes entire data directory (database, profiles, images, jsons, settings.toml)."""
    if DATA_FOLDER.exists():
        shutil.rmtree(DATA_FOLDER, ignore_errors=True)

    if is_gui:
        logger.info("Purged data directory: %s", DATA_FOLDER)
    else:
        print(f"    - User data directory purged ({DATA_FOLDER}).")


def purge_diagnostics(is_gui: bool) -> None:
    """Deletes diagnostics/ and any stray .prof profiling files in the project root."""
    if DIAGNOSTICS_FOLDER.exists():
        shutil.rmtree(DIAGNOSTICS_FOLDER, ignore_errors=True)

    for prof_file in PROJECT_ROOT.glob("*.prof"):
        prof_file.unlink(missing_ok=True)

    if is_gui:
        logger.info("Purged diagnostics folder and root profiling files.")
    else:
        print("    - Diagnostics and profiling files purged.")


def purge_logs(is_gui: bool) -> None:
    """Deletes logs/ and any root session log files."""
    if LOGS_FOLDER.exists():
        shutil.rmtree(LOGS_FOLDER, ignore_errors=True)

    for log_file in PROJECT_ROOT.glob("*.log"):
        log_file.unlink(missing_ok=True)

    if is_gui:
        logger.info("Purged logs directory: %s", LOGS_FOLDER)
    else:
        print(f"    - Session logs purged ({LOGS_FOLDER}).")


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
        "--no-restart", action="store_true", help="Skip system reboot prompt on Windows"
    )

    if is_gui:
        args, _ = parser.parse_known_args()
    else:
        args = parser.parse_args()

    # 1. Privilege Check
    if not _is_admin():
        msg = (
            "Administrator privileges required (Windows)."
            if SYSTEM == "Windows"
            else "Root/Superuser privileges required (run with 'sudo')."
        )
        if is_gui:
            logger.error(msg)
            QMessageBox.critical(parent, "Elevation Required", msg)
        else:
            print(f"[!] {msg}")
            _request_elevation()
        return False

    # 2. Confirmation Prompt
    if not args.yes:
        confirm_text = "Are you sure you want to remove the driver/rules and clean binaries?"
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

    # 3. Teardown active handles and background processes
    try:
        store.close()
    except Exception:
        pass
    _kill_adb()

    # 4. OS-Specific Driver / Rules Removal
    needs_reboot = False
    if SYSTEM == "Windows":
        installer_exe = (
            BIN_DIR
            / "Interception"
            / "command line installer"
            / "install-interception.exe"
        )
        if installer_exe.exists():
            res = subprocess.run([str(installer_exe), "/uninstall"], capture_output=True)
            if res.returncode == 0:
                needs_reboot = True
                if is_gui:
                    logger.info("Interception driver uninstalled.")
                else:
                    print("[+] Interception driver uninstalled.")
            else:
                if is_gui:
                    logger.warning("Interception driver uninstall command failed.")
                else:
                    print("[!] Driver uninstallation reported a non-zero exit code.")
        else:
            msg = "Interception installer binary not found in bin/."
            if is_gui:
                logger.warning(msg)
            else:
                print(f"[!] {msg}")

    elif SYSTEM == "Linux":
        if UDEV_RULE_PATH.exists():
            UDEV_RULE_PATH.unlink(missing_ok=True)
            subprocess.run(["udevadm", "control", "--reload-rules"], check=False)
            subprocess.run(["udevadm", "trigger"], check=False)
            if is_gui:
                logger.info("Udev rule removed and subsystem reloaded.")
            else:
                print("[+] Udev rule removed and subsystem reloaded.")
        else:
            msg = f"Udev rule not found at {UDEV_RULE_PATH}."
            if is_gui:
                logger.warning(msg)
            else:
                print(f"[!] {msg}")

    # 5. Remove Platform Binaries
    if BIN_DIR.exists():
        shutil.rmtree(BIN_DIR, ignore_errors=True)
        if is_gui:
            logger.info("Local platform binaries deleted.")
        else:
            print("    - Local platform binaries deleted.")

    # 6. Purge Application Data
    if args.purge or args.purge_all:
        purge_data(is_gui=is_gui)

    if args.purge_all:
        purge_diagnostics(is_gui=is_gui)
        purge_logs(is_gui=is_gui)

    # 7. Final Notification / Reboot Workflow
    if is_gui:
        logger.info("Uninstall completed successfully.")
        if SYSTEM == "Windows" and needs_reboot and not args.no_restart:
            res = QMessageBox.question(
                parent,
                "Restart Required",
                "Driver removal requires a reboot. Restart now in 5 seconds?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            )
            if res == QMessageBox.StandardButton.Yes:
                subprocess.run(["shutdown", "/r", "/t", "5", "/c", "Uninstall complete."])
                return True
        else:
            QMessageBox.information(
                parent, "Uninstall Complete", "Uninstallation finished successfully."
            )
    else:
        print("\n[+] Uninstall complete.")
        if SYSTEM == "Windows":
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
                    print("[!] Please restart your computer manually to finalize removal.")
            input("\nPress Enter to exit...")

    return True


if __name__ == "__main__":
    if not run():
        sys.exit(1)
