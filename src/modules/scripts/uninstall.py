#!/usr/bin/env python3
"""
Touch2Key Driver, Rules, and Data Uninstaller.
Uses PySide6 dialogs when invoked within a Qt application, otherwise standard CLI prompts.
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
from modules.database.connection import DB_PATH
from modules.utils import (
    BIN_DIR,
    IMAGES_FOLDER,
    JSONS_FOLDER,
    PROJECT_ROOT,
    SYSTEM,
    UDEV_RULE_PATH,
)

logger = logging.getLogger("modules.scripts.uninstall")


def _is_admin() -> bool:
    if SYSTEM == "Windows":
        try:
            return ctypes.windll.shell32.IsUserAnAdmin() != 0
        except Exception:
            return False
    return os.geteuid() == 0


def _request_elevation() -> None:
    if SYSTEM == "Windows":
        script = Path(__file__).resolve()
        params = " ".join(sys.argv[1:])
        ctypes.windll.shell32.ShellExecuteW(
            None, "runas", sys.executable, f'"{script}" {params}', os.getcwd(), 1
        )
    else:
        print("[!] Please execute this script with 'sudo'.")


def _kill_adb() -> None:
    cmd = (
        ["taskkill", "/F", "/IM", "adb.exe", "/T"]
        if SYSTEM == "Windows"
        else ["pkill", "-f", "adb"]
    )
    try:
        subprocess.run(cmd, capture_output=True, check=False)
    except Exception:
        pass


def run(parent=None) -> bool:
    is_gui = QApplication.instance() is not None

    parser = argparse.ArgumentParser(description="Touch2Key Uninstaller")
    parser.add_argument("-y", "--yes", action="store_true", help="Skip confirmation prompt")
    parser.add_argument("--purge", action="store_true", help="Delete database, profiles, and images")
    parser.add_argument("--no-restart", action="store_true", help="Skip system reboot prompt")

    # In GUI mode, ignore CLI argv parsing errors
    if is_gui:
        args, _ = parser.parse_known_args()
    else:
        args = parser.parse_args()

    # 1. Elevation Check
    if not _is_admin():
        msg = "Administrator / Root privileges are required to uninstall drivers and rules."
        if is_gui:
            logger.error(msg)
            QMessageBox.critical(parent, "Elevation Required", msg)
        else:
            print(f"[!] {msg}")
            _request_elevation()
        return False

    # 2. Confirmation Prompt
    if not args.yes:
        confirm_text = "Are you sure you want to remove the driver/rules?"
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

    # 3. Clean active database handles & stop ADB
    try:
        store.close()
    except Exception:
        pass
    _kill_adb()

    # 4. Driver / Rule Removal
    if SYSTEM == "Windows":
        installer_exe = (
            BIN_DIR
            / "Interception"
            / "command line installer"
            / "install-interception.exe"
        )
        if installer_exe.exists():
            subprocess.run([str(installer_exe), "/uninstall"], capture_output=True)
            if is_gui:
                logger.info("Interception driver uninstalled.")
            else:
                print("[+] Driver removed.")

            # Reboot Prompt
            if not args.no_restart:
                reboot_text = "System restart is required to complete driver uninstallation. Restart now?"
                reboot_now = False
                if is_gui:
                    res = QMessageBox.question(
                        parent,
                        "Restart Required",
                        reboot_text,
                        QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                    )
                    reboot_now = (res == QMessageBox.StandardButton.Yes)
                else:
                    print("\n" + "=" * 55)
                    print("!!! SYSTEM RESTART REQUIRED !!!".center(55))
                    print("=" * 55)
                    reboot_now = input("Restart PC now? (y/N): ").strip().lower() == "y"

                if reboot_now:
                    subprocess.run(
                        ["shutdown", "/r", "/t", "5", "/c", "Touch2Key driver uninstallation complete."]
                    )
                    return True
        else:
            msg = "Interception installer binary not found."
            if is_gui:
                logger.warning(msg)
            else:
                print(f"[!] {msg}")

    elif SYSTEM == "Linux":
        if UDEV_RULE_PATH.exists():
            UDEV_RULE_PATH.unlink()
            subprocess.run(["udevadm", "control", "--reload-rules"])
            if is_gui:
                logger.info("Udev rules removed and reloaded.")
            else:
                print("[+] Udev rules removed.")

    # 5. Remove Binaries
    if BIN_DIR.exists():
        shutil.rmtree(BIN_DIR, ignore_errors=True)

    # 6. Purge Database and Artifacts
    if args.purge:
        if IMAGES_FOLDER.exists():
            shutil.rmtree(IMAGES_FOLDER, ignore_errors=True)
        if JSONS_FOLDER.exists():
            shutil.rmtree(JSONS_FOLDER, ignore_errors=True)

        for ext in ("", "-wal", "-shm"):
            db_file = Path(f"{DB_PATH}{ext}")
            if db_file.exists():
                try:
                    db_file.unlink()
                except Exception:
                    pass

        if is_gui:
            logger.info("Purged user images, JSON profiles, and SQLite database.")
        else:
            print("[+] User data and SQLite database purged.")

    if is_gui:
        logger.info("Uninstall completed successfully.")
        QMessageBox.information(parent, "Uninstall Complete", "Uninstallation finished successfully.")
    else:
        print("[+] Uninstall complete.")

    return True


if __name__ == "__main__":
    run()
