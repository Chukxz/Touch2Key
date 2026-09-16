#!/usr/bin/env python3
"""
Touch2Key Driver, Rules, and Data Uninstaller.
Supports interactive prompt or non-interactive flag execution (-y / --purge).
"""

from __future__ import annotations

import argparse
import ctypes
import os
import shutil
import subprocess
import sys
from pathlib import Path

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


def _is_admin() -> bool:
    """Checks if script is running with elevated privileges."""
    if SYSTEM == "Windows":
        try:
            return ctypes.windll.shell32.IsUserAnAdmin() != 0
        except Exception:
            return False
    return os.geteuid() == 0


def _request_elevation() -> None:
    """Restarts the script with admin privileges in the current working directory."""
    if SYSTEM == "Windows":
        script = Path(__file__).resolve()
        params = " ".join(sys.argv[1:])
        ctypes.windll.shell32.ShellExecuteW(
            None, "runas", sys.executable, f'"{script}" {params}', os.getcwd(), 1
        )
    else:
        print("[!] Please run this uninstaller with 'sudo'.")


def _kill_adb() -> None:
    print("[+] Checking for running ADB processes...")
    cmd = (
        ["taskkill", "/F", "/IM", "adb.exe", "/T"]
        if SYSTEM == "Windows"
        else ["pkill", "-f", "adb"]
    )
    try:
        subprocess.run(cmd, capture_output=True, check=False)
        print("[+] ADB cleanup finished.")
    except Exception as e:
        print(f"[!] Note: ADB process cleanup skipped: {e}")


def run() -> None:
    parser = argparse.ArgumentParser(description="Touch2Key Driver/Rules and Data Uninstaller")
    parser.add_argument("-y", "--yes", action="store_true", help="Skip confirmation prompt")
    parser.add_argument("--purge", action="store_true", help="Purge database, profiles, and images")
    parser.add_argument("--no-restart", action="store_true", help="Do not prompt to restart Windows")
    args = parser.parse_args()

    # Elevation check
    if not _is_admin():
        print("[!] This uninstaller requires Administrator/Root privileges.")
        _request_elevation()
        return

    # Interactive confirmation if -y is not passed
    if not args.yes:
        confirm = input("Are you sure you want to uninstall Touch2Key drivers/rules? (y/N): ").strip().lower()
        if confirm != "y":
            print("[!] Uninstallation cancelled.")
            return

    # Close active database connections
    try:
        store.close()
    except Exception:
        pass

    # Stop background ADB instances
    _kill_adb()

    # Platform Driver Removal
    if SYSTEM == "Windows":
        print("\n--- Uninstalling Interception Driver ---")
        installer_exe = (
            BIN_DIR
            / "Interception"
            / "command line installer"
            / "install-interception.exe"
        )
        if installer_exe.exists():
            subprocess.run([str(installer_exe), "/uninstall"], capture_output=True)
            print("[+] Driver removed.")

            if not args.no_restart:
                print("\n" + "=" * 55)
                print("!!! SYSTEM RESTART REQUIRED !!!".center(55))
                print("=" * 55)
                choice = input("Restart PC now? (y/N): ").strip().lower()
                if choice == "y":
                    subprocess.run(
                        ["shutdown", "/r", "/t", "5", "/c", "Touch2Key driver uninstallation complete."]
                    )
                    return
        else:
            print("[!] Interception installer binary not found. Driver may require manual removal.")

    elif SYSTEM == "Linux":
        print("\n--- Removing Udev Rules ---")
        if UDEV_RULE_PATH.exists():
            UDEV_RULE_PATH.unlink()
            subprocess.run(["udevadm", "control", "--reload-rules"])
            print("[+] Udev rules removed.")
        else:
            print("[!] Udev rule file not found.")

    # Remove Downloaded Binaries
    if BIN_DIR.exists():
        shutil.rmtree(BIN_DIR, ignore_errors=True)
        print("    - Local binaries deleted.")

    # Purge Database and User Assets
    if args.purge:
        if IMAGES_FOLDER.exists():
            shutil.rmtree(IMAGES_FOLDER, ignore_errors=True)
        if JSONS_FOLDER.exists():
            shutil.rmtree(JSONS_FOLDER, ignore_errors=True)

        # Remove SQLite DB and WAL artifacts
        for ext in ("", "-wal", "-shm"):
            db_file = Path(f"{DB_PATH}{ext}")
            if db_file.exists():
                try:
                    db_file.unlink()
                except Exception:
                    pass
        print("    - Database, images, and user data purged.")

    print("\n[+] Uninstallation complete.")


if __name__ == "__main__":
    run()
