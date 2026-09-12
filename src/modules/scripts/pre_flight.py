import shutil
from pathlib import Path
from modules.utils import SYSTEM, ADB


def _check_adb():
    """Verify ADB is available."""
    # Check system PATH or local bin folder
    if shutil.which("adb") == ADB.as_posix():
        return True

    # Check custom bin directory
    if ADB.exists():
        return True

    return False


def _check_driver():
    """Verify system driver (Platform specific)."""
    if SYSTEM == "Windows":
        # Interception typically doesn't have a simple 'which' check.
        # Instead, we can attempt to create an Interception context to verify driver access.
        from interception.interception import Interception

        return Interception().valid

    elif SYSTEM == "Linux":
        # Check if user has permission to read uinput
        return Path("/dev/uinput").exists()

    return False


def run():
    """Execute all checks. Returns False if any check fails."""
    checks = {"ADB": _check_adb(), "Driver": _check_driver()}

    failed = [name for name, status in checks.items() if not status]

    if failed:
        print(f"[!] Pre-flight failed:")
        if "ADB" in failed:
            print("    - ADB not found. Run 'touch2key-setup' to download it.")
        if SYSTEM == "Windows" and "Driver" in failed:
            print(
                "    - Driver not found. Run 'touch2key-setup' to configure environment or restart the system if the driver is installed."
            )
        elif SYSTEM == "Linux" and "Driver" in failed:
            print(
                "    - Driver not found. Run 'sudo touch2key-setup' to configure environment."
            )
        return False

    print("[+] Pre-flight checks passed.")
    return True


if __name__ == "__main__":
    run()
