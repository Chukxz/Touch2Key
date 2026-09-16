from __future__ import annotations

import sys
from modules.utils import wireless_connect


def run() -> None:
    print("[PROCESS] Searching for ADB device to establish wireless connection...")
    print("[INFO] Polling continuously. Press Ctrl+C to cancel.")

    try:
        ret = wireless_connect(continuous=True)
        if ret:
            success, endpoint = ret
            if success:
                print(f"[SUCCESS] Connected wirelessly to: {endpoint}")
                sys.exit(0)

        print("[ERROR] Failed to establish wireless ADB connection.")
        sys.exit(1)

    except KeyboardInterrupt:
        print("\n[INFO] Wireless connection cancelled by user.")
        sys.exit(0)


if __name__ == "__main__":
    run()