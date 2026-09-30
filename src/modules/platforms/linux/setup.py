from __future__ import annotations

import os
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

import requests

from modules.utils import BIN_FOLDER, UDEV_RULE_PATH

ADB_URL = "https://dl.google.com/android/repository/platform-tools-latest-linux.zip"


def is_root() -> bool:
    """Checks if the script possesses root/superuser privileges."""
    return os.geteuid() == 0


def kill_adb() -> None:
    """Terminates active adb daemon instances."""
    print("[+] Checking for active ADB instances...")
    try:
        subprocess.run(["pkill", "-f", "adb"], capture_output=True, check=False)
        print("[+] ADB process cleanup complete.")
    except Exception as exc:
        print(f"[!] Warning during ADB termination: {exc}")


def download_adb() -> None:
    """Downloads and extracts Android platform-tools for Linux."""
    print("[+] Checking ADB installation...")
    BIN_FOLDER.mkdir(parents=True, exist_ok=True)

    platform_tools_dir = BIN_FOLDER / "platform-tools"
    zip_path = BIN_FOLDER / "adb.zip"

    if (platform_tools_dir / "adb").exists():
        print("[+] ADB binary present.")
        return

    print("[+] Downloading ADB tools...")
    try:
        if zip_path.exists():
            zip_path.unlink()
        if platform_tools_dir.exists():
            shutil.rmtree(platform_tools_dir)

        response = requests.get(ADB_URL, timeout=60)
        response.raise_for_status()

        with open(zip_path, "wb") as f:
            f.write(response.content)

        if not zipfile.is_zipfile(zip_path):
            raise ValueError("Downloaded archive is not a valid ZIP file.")

        print("[+] Extracting platform tools...")
        with zipfile.ZipFile(zip_path, "r") as z:
            z.extractall(BIN_FOLDER)

        (platform_tools_dir / "adb").chmod(0o755)
        print("[+] ADB installed with execution permissions.")

    except Exception as exc:
        if platform_tools_dir.exists():
            shutil.rmtree(platform_tools_dir)
        raise RuntimeError(f"Failed to install ADB: {exc}") from exc
    finally:
        if zip_path.exists():
            zip_path.unlink(missing_ok=True)


def setup_udev_rules(interactive: bool = True) -> None:
    """Applies udev rules for unprivileged access to input event nodes."""
    print("[+] Setting up udev rules for input devices...")
    rule_content = 'SUBSYSTEM=="input", GROUP="input", MODE="0660"\n'
    rule_path = Path(UDEV_RULE_PATH)

    if is_root():
        rule_path.parent.mkdir(parents=True, exist_ok=True)
        rule_path.write_text(rule_content)
        subprocess.run(["udevadm", "control", "--reload-rules"], check=True)
        subprocess.run(["udevadm", "trigger"], check=True)
        print("[+] Udev rules deployed and reloaded.")
        return

    # Escalate privileges when running unprivileged
    print("[!] Root permissions required to configure /etc/udev/rules.d.")

    # Try GUI PolicyKit agent if interactive GUI or pkexec is available
    if not interactive and shutil.which("pkexec"):
        cmd = [
            "pkexec",
            "sh",
            "-c",
            f"printf '{rule_content}' > {rule_path} && udevadm control --reload-rules && udevadm trigger",
        ]
        res = subprocess.run(cmd, capture_output=True)
        if res.returncode != 0:
            raise PermissionError("PolicyKit privilege escalation declined or failed.")
        print("[+] Udev rules applied successfully via PolicyKit.")
        return

    # Fallback to standard sudo for CLI
    if shutil.which("sudo"):
        cmd = [
            "sudo",
            "sh",
            "-c",
            f"printf '{rule_content}' > {rule_path} && udevadm control --reload-rules && udevadm trigger",
        ]
        res = subprocess.run(cmd)
        if res.returncode != 0:
            raise PermissionError("Sudo authentication failed.")
        print("[+] Udev rules deployed via sudo.")
        return

    raise PermissionError(
        "Could not elevate permissions. Run with 'sudo' or install 'pkexec'."
    )


def setup_linux(interactive: bool = True, no_restart: bool = False) -> bool:
    """
    Executes full platform setup for Linux.
    Returns False as Linux does not enforce a full system restart for udev reloads.
    (no_restart is accepted for cross-platform signature symmetry with Windows).
    """
    print("--- Linux Platform Setup ---")

    kill_adb()
    download_adb()
    setup_udev_rules(interactive=interactive)

    if interactive:
        print("\n[+] Linux setup finished successfully.")
        input("\nPress Enter to exit...")

    return False


if __name__ == "__main__":
    setup_linux(interactive=True)
