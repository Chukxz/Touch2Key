import os
import sys
import ctypes
import subprocess
import shutil
import requests
import zipfile
import shlex
from pathlib import Path
from modules.utils import PROJECT_ROOT

# --- Configuration ---
BIN_DIR = PROJECT_ROOT / "bin"
ADB_URL = "https://dl.google.com/android/repository/platform-tools-latest-windows.zip"
INTERCEPTION_API_URL = (
    "https://api.github.com/repos/oblitum/Interception/releases/latest"
)
INTERCEPTION_EXE = (
    BIN_DIR / "Interception" / "command line installer" / "install-interception.exe"
)


def is_admin() -> bool:
    """Checks if the script is running with Windows Administrative privileges."""
    try:
        return ctypes.windll.shell32.IsUserAnAdmin() != 0
    except Exception:
        return False


def request_elevation():
    """Restarts the script with Windows UAC elevation."""
    script = Path(__file__).resolve()
    params = shlex.join(sys.argv[1:]) if sys.argv[1:] else ""
    ctypes.windll.shell32.ShellExecuteW(
        None, "runas", sys.executable, f'"{script}" {params}', str(script.parent), 1
    )


def _kill_adb():
    """Force terminates ADB processes on Windows."""
    print("[+] Terminating existing ADB processes...")
    subprocess.run(
        ["taskkill", "/F", "/IM", "adb.exe", "/T"], capture_output=True, check=False
    )


def _download_adb():
    """Downloads and extracts Android platform-tools for Windows."""
    print("[+] Checking if ADB is available...")
    BIN_DIR.mkdir(parents=True, exist_ok=True)

    platform_tools_dir = BIN_DIR / "platform-tools"
    zip_path = BIN_DIR / "adb.zip"

    if (platform_tools_dir / "adb.exe").exists():
        print("[+] ADB is already present.")
        return

    print("[+] Downloading ADB (this may take a moment)...")
    try:
        if zip_path.exists():
            os.remove(zip_path)
        if platform_tools_dir.exists():
            shutil.rmtree(platform_tools_dir)

        response = requests.get(ADB_URL, timeout=60)
        response.raise_for_status()

        with open(zip_path, "wb") as f:
            f.write(response.content)

        if not zipfile.is_zipfile(zip_path):
            raise ValueError("Downloaded file is not a valid ZIP structure.")

        print("[+] Extracting ADB...")
        with zipfile.ZipFile(zip_path, "r") as z:
            z.extractall(BIN_DIR)
        print("[+] ADB setup complete.")

    except Exception as e:
        print(f"\n[!] Error during ADB setup: {e}")
        if platform_tools_dir.exists():
            shutil.rmtree(platform_tools_dir)
        sys.exit(1)
    finally:
        if zip_path.exists():
            os.remove(zip_path)


def _download_interception():
    """Fetches and extracts the latest Interception release for Windows."""
    print("[+] Checking if Interception driver files are available...")
    interception_dir = BIN_DIR / "Interception"
    installer_exe = (
        interception_dir / "command line installer" / "install-interception.exe"
    )
    zip_path = BIN_DIR / "interception.zip"

    if installer_exe.exists():
        print("[+] Interception files are already present.")
        return

    print("[+] Querying GitHub for Interception release...")
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
            raise ValueError("Could not find a .zip asset in the latest release.")

        print(f"[+] Downloading Interception (this may take a moment)...")
        zip_response = requests.get(download_url, timeout=60)
        zip_response.raise_for_status()

        with open(zip_path, "wb") as f:
            f.write(zip_response.content)

        with zipfile.ZipFile(zip_path, "r") as z:
            z.extractall(BIN_DIR)

        print("[+] Interception download complete.")
    except Exception as e:
        print(f"\n[!] Error downloading Interception: {e}")
        sys.exit(1)
    finally:
        if zip_path.exists():
            os.remove(zip_path)


def _setup_driver():
    """Handles driver registration (requires Admin)."""
    if not is_admin():
        request_elevation()
        sys.exit(0)

    return _register_driver()


def _register_driver():
    try:
        print("[+] Registering Interception driver...")
        result = subprocess.run(
            [str(INTERCEPTION_EXE), "/install"], capture_output=True
        )

        if result.returncode == 0:
            print("[+] Driver registered successfully!")
            return True
        else:
            print(
                f"[!] Failed to register driver (driver may already be installed run 'touch2key-preflight' to confirm)."
            )
            return False

    except FileNotFoundError:
        print("[!] Error: The interception executable was not found.")
        return False
    except Exception as e:
        print(f"[!] An unexpected error occurred: {e}")
        return False


def setup_windows():
    print("--- Touch2Key Windows Setup Wizard ---")

    # Prepare Environment
    _kill_adb()
    _download_adb()
    _download_interception()

    # Setup Driver
    needs_reboot = _setup_driver()

    # Finalize
    if needs_reboot:
        print("\n" + "=" * 55)
        print("!!! SYSTEM RESTART REQUIRED !!!".center(55))
        print("=" * 55)
        choice = (
            input("Restart PC now (Will restart in 5 seconds)? (y/n): ").strip().lower()
        )
        if choice == "y":
            # os.system('shutdown /r /t 5 /c "Touch2Key driver installation complete."')
            subprocess.run(
                [
                    "shutdown",
                    "/r",
                    "/t",
                    "5",
                    "/c",
                    "Touch2Key driver installation complete.",
                ]
            )
        else:
            print(
                "\n[+] Please remember to restart your computer as soon as possible to complete the installation process."
            )
    else:
        print("\n[+] Setup complete! You are ready to use Touch2Key.")

    input("\nPress Enter to exit...")


if __name__ == "__main__":
    setup_windows()
