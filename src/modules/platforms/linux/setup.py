import os
import sys
import subprocess
import shutil
import requests
import zipfile
from mapper_module.utils import PROJECT_ROOT, UDEV_RULE_PATH

# --- Configuration ---
BIN_DIR = PROJECT_ROOT / "bin"
ADB_URL = "https://dl.google.com/android/repository/platform-tools-latest-linux.zip"


def _is_root() -> bool:
    """Checks if the script is running with root privileges."""
    return os.geteuid() == 0


def _kill_adb():
    """Force terminates ADB processes on Linux."""
    print("[+] Checking for running ADB processes...")
    try:
        subprocess.run(["pkill", "-f", "adb"], capture_output=True, check=False)
        print("[+] ADB cleanup finished.")
    except Exception as e:
        print(f"[!] Warning: Could not kill ADB: {e}")


def _download_adb():
    """Downloads and extracts Android platform-tools for Linux."""
    print("[+] Checking if ADB is available...")
    BIN_DIR.mkdir(parents=True, exist_ok=True)

    platform_tools_dir = BIN_DIR / "platform-tools"
    zip_path = BIN_DIR / "adb.zip"

    if (platform_tools_dir / "adb").exists():
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

        # Ensure adb is executable on Linux
        (platform_tools_dir / "adb").chmod(0o755)
        print("[+] ADB setup complete.")

    except Exception as e:
        print(f"\n[!] Error during ADB setup: {e}")
        if platform_tools_dir.exists():
            shutil.rmtree(platform_tools_dir)
        sys.exit(1)
    finally:
        if zip_path.exists():
            os.remove(zip_path)


def _setup_udev_rules():
    """Applies udev rules for input device access."""
    if not _is_root():
        print("[!] Udev rule setup requires root. Please run with 'sudo'.")
        sys.exit(1)

    print("[+] Applying udev rules...")
    # This rule grants read/write access to input devices for all users
    # Adjust the ID/Vendor if you need more security
    rule_content = 'SUBSYSTEM=="input", GROUP="input", MODE="0660"\n'

    try:
        with open(UDEV_RULE_PATH, "w") as f:
            f.write(rule_content)
        subprocess.run(["udevadm", "control", "--reload-rules"], check=True)
        subprocess.run(["udevadm", "trigger"], check=True)
        print("[+] Udev rules applied successfully.")
    except Exception as e:
        print(f"[!] Failed to apply udev rules: {e}")


def setup_linux():
    print("--- Touch2Key Linux Setup Wizard ---")

    # Prepare Environment
    _kill_adb()
    _download_adb()

    # Setup Linux-specific permissions
    _setup_udev_rules()

    print("\n[+] Setup complete! You are ready to use Touch2Key.")
    input("\nPress Enter to exit...")


if __name__ == "__main__":
    setup_linux()
