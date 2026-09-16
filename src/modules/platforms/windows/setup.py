from __future__ import annotations

import ctypes
import os
import shlex
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

import requests

from modules.utils import PROJECT_ROOT

BIN_DIR = PROJECT_ROOT / "bin"
ADB_URL = "https://dl.google.com/android/repository/platform-tools-latest-windows.zip"
INTERCEPTION_API_URL = (
    "https://api.github.com/repos/oblitum/Interception/releases/latest"
)
INTERCEPTION_EXE = (
    BIN_DIR / "Interception" / "command line installer" / "install-interception.exe"
)


def is_admin() -> bool:
    """Checks if the process holds Windows Administrator privileges."""
    try:
        return ctypes.windll.shell32.IsUserAnAdmin() != 0
    except Exception:
        return False


def request_elevation() -> bool:
    """Prompts a Windows UAC elevation dialog to run the script as Admin."""
    script = Path(__file__).resolve()
    params = shlex.join(sys.argv[1:]) if sys.argv[1:] else ""
    res = ctypes.windll.shell32.ShellExecuteW(
        None, "runas", sys.executable, f'"{script}" {params}', str(script.parent), 1
    )
    return res > 32


def kill_adb() -> None:
    """Terminates running adb.exe processes."""
    print("[+] Terminating existing ADB processes...")
    subprocess.run(
        ["taskkill", "/F", "/IM", "adb.exe", "/T"],
        capture_output=True,
        check=False,
    )


def download_adb() -> None:
    """Downloads and unpacks Android platform-tools for Windows."""
    print("[+] Checking ADB installation...")
    BIN_DIR.mkdir(parents=True, exist_ok=True)

    platform_tools_dir = BIN_DIR / "platform-tools"
    zip_path = BIN_DIR / "adb.zip"

    if (platform_tools_dir / "adb.exe").exists():
        print("[+] ADB is already present.")
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
            raise ValueError("Downloaded ADB archive is not a valid ZIP file.")

        print("[+] Extracting ADB tools...")
        with zipfile.ZipFile(zip_path, "r") as z:
            z.extractall(BIN_DIR)
        print("[+] ADB setup complete.")

    except Exception as exc:
        if platform_tools_dir.exists():
            shutil.rmtree(platform_tools_dir)
        raise RuntimeError(f"Failed to install ADB: {exc}") from exc
    finally:
        if zip_path.exists():
            zip_path.unlink(missing_ok=True)


def download_interception() -> None:
    """Fetches and extracts the latest Interception driver bundle."""
    print("[+] Checking Interception driver files...")
    interception_dir = BIN_DIR / "Interception"
    installer_exe = (
        interception_dir / "command line installer" / "install-interception.exe"
    )
    zip_path = BIN_DIR / "interception.zip"

    if installer_exe.exists():
        print("[+] Interception binaries are already present.")
        return

    print("[+] Querying GitHub API for latest Interception release...")
    try:
        api_response = requests.get(INTERCEPTION_API_URL, timeout=30)
        api_response.raise_for_status()
        release_data = api_response.json()

        download_url = next(
            (
                asset["browser_download_url"]
                for asset in release_data.get("assets", [])
                if asset["name"].endswith(".zip")
            ),
            None,
        )

        if not download_url:
            raise ValueError("No valid .zip release asset found on GitHub.")

        print("[+] Downloading Interception bundle...")
        zip_response = requests.get(download_url, timeout=60)
        zip_response.raise_for_status()

        with open(zip_path, "wb") as f:
            f.write(zip_response.content)

        with zipfile.ZipFile(zip_path, "r") as z:
            z.extractall(BIN_DIR)

        print("[+] Interception download complete.")
    except Exception as exc:
        raise RuntimeError(f"Failed to fetch Interception driver: {exc}") from exc
    finally:
        if zip_path.exists():
            zip_path.unlink(missing_ok=True)


def register_driver() -> bool:
    """Registers the Interception driver with Windows."""
    if not INTERCEPTION_EXE.exists():
        raise FileNotFoundError(f"Missing installer executable: {INTERCEPTION_EXE}")

    print("[+] Registering Interception kernel driver...")
    result = subprocess.run(
        [str(INTERCEPTION_EXE), "/install"],
        capture_output=True,
        text=True,
    )

    if result.returncode == 0:
        print("[+] Interception driver registered successfully.")
        return True

    print(
        "[!] Interception driver registration returned non-zero. "
        "The driver might already be active. Run preflight to verify."
    )
    return False


def setup_windows(interactive: bool = True) -> bool:
    """
    Executes full platform setup for Windows.
    Returns True if a reboot is needed for the driver, otherwise False.
    """
    print("--- Windows Platform Setup ---")

    kill_adb()
    download_adb()
    download_interception()

    if not is_admin():
        if interactive:
            print("[!] Elevation required to install Interception driver.")
            if request_elevation():
                sys.exit(0)
            raise PermissionError("UAC elevation prompt was rejected.")
        else:
            raise PermissionError(
                "Driver registration requires Administrator privileges. "
                "Please restart the application as Administrator."
            )

    needs_reboot = register_driver()

    if interactive:
        if needs_reboot:
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
                        "Driver installation complete.",
                    ]
                )
            else:
                print("[+] Please reboot manually to finalize driver registration.")
        else:
            print("\n[+] Setup finished successfully.")

        input("\nPress Enter to exit...")

    return needs_reboot


if __name__ == "__main__":
    setup_windows(interactive=True)
