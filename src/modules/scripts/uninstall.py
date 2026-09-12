import os
import sys
import shutil
import argparse
import subprocess
import tkinter as tk
import ctypes
from tkinter import messagebox
from pathlib import Path

from mapper_module.utils import (
    PROJECT_ROOT,
    SYSTEM,
    IMAGES_FOLDER,
    JSONS_FOLDER,
    UDEV_RULE_PATH,
)

BIN_DIR = PROJECT_ROOT / "bin"


def _is_admin() -> bool:
    """Checks if script is running with elevated privileges."""
    if SYSTEM == "Windows":
        try:
            return ctypes.windll.shell32.IsUserAnAdmin() != 0
        except:
            return False
    return os.geteuid() == 0


def _request_elevation():
    """Restarts the script with admin privileges in the correct directory."""
    if SYSTEM == "Windows":
        script = Path(__file__).resolve()
        params = " ".join(sys.argv[1:])

        # 5th argument (os.getcwd()) ensures the new process starts
        # in the correct project folder instead of C:\Windows\System32
        ctypes.windll.shell32.ShellExecuteW(
            None, "runas", sys.executable, f'"{script}" {params}', os.getcwd(), 1
        )
    else:
        print("[!] Please run this script with 'sudo'.")


def _confirm_uninstall(message):
    root = None
    try:
        root = tk.Tk()
        root.withdraw()
        root.attributes("-topmost", True)
        return messagebox.askyesno("Touch2Key Uninstall", message, parent=root)
    except Exception:
        return input(f"{message} (y/n): ").lower() == "y"
    finally:
        if root:
            root.destroy()


def _kill_adb():
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
        print(f"[!] Note: Could not kill ADB (might not be running): {e}")


def run():
    # Admin Check First
    if not _is_admin():
        print("[!] This uninstaller requires Administrator/Root privileges.")
        _request_elevation()
        return

    parser = argparse.ArgumentParser(description="Touch2Key Driver/Rules Uninstaller")
    parser.add_argument("--purge", action="store_true", help="Delete JSON/Images.")
    args = parser.parse_args()

    # Confirm
    msg = "Are you sure you want to uninstall Touch2Key Driver/Rules?"
    if not _confirm_uninstall(msg):
        print("[!] Aborted.")

        if SYSTEM == "Windows":
            input("\nPress Enter to exit...")

        return

    # Cleanup
    _kill_adb()

    if SYSTEM == "Windows":
        print(f"\n--- Uninstalling Interception Driver ---")
        installer_exe = (
            BIN_DIR
            / "Interception"
            / "command line installer"
            / "install-interception.exe"
        )
        if installer_exe.exists():
            subprocess.run([str(installer_exe), "/uninstall"], capture_output=True)
            print("[+] Driver removed.")

            print("\n" + "=" * 55)
            print("!!! SYSTEM RESTART REQUIRED !!!".center(55))
            print("=" * 55)
            choice = (
                input("Restart PC now (Will restart in 5 seconds)? (y/n): ")
                .strip()
                .lower()
            )

            if choice == "y":
                # os.system(
                #     'shutdown /r /t 5 /c "Touch2Key driver uninstallation complete."'
                # )
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
            else:
                print(
                    "[!] Please remember to restart your computer to complete the uninstallation process."
                )
        else:
            print(
                "[!] Interception installer not found. Driver might need manual removal."
            )

    elif SYSTEM == "Linux":
        print(f"\n--- Removing Udev Rules ---")
        if UDEV_RULE_PATH.exists():
            UDEV_RULE_PATH.unlink()
            subprocess.run(["udevadm", "control", "--reload-rules"])
            print("[+] Udev rules removed.")
        else:
            print("[!] Udev rule file not found. Manual cleanup might be needed.")

    # Remove Files
    if BIN_DIR.exists():
        shutil.rmtree(BIN_DIR)
        print("    - Binaries deleted.")

    if args.purge:
        if IMAGES_FOLDER.exists():
            shutil.rmtree(IMAGES_FOLDER)
        if JSONS_FOLDER.exists():
            shutil.rmtree(JSONS_FOLDER)
        print("    - User data purged.")

    print("\n[+] Uninstall complete.")

    input("\nPress Enter to exit...")


if __name__ == "__main__":
    run()
