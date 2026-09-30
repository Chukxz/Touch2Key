from __future__ import annotations

import sys
import logging
from modules.log_manager import AppLogManager
from modules.utils import wireless_connect

logger = logging.getLogger("modules.scripts.wireless_connect")

def run() -> None:
    AppLogManager.setup_logging(is_gui=False, log_prefix="touch2key_wireless")
    
    logger.info("Searching for ADB device to establish wireless connection...")
    print("[INFO] Polling continuously. Press Ctrl+C to cancel.")

    try:
        ret = wireless_connect(continuous=True)
        if ret:
            success, endpoint = ret
            if success:
                logger.info("Connected wirelessly to: %s", endpoint)
                print(f"[SUCCESS] Connected wirelessly to: {endpoint}")
                sys.exit(0)

        logger.error("Failed to establish wireless ADB connection.")
        sys.exit(1)

    except KeyboardInterrupt:
        print("\n[INFO] Wireless connection cancelled by user.")
        sys.exit(0)

def main() -> None:
    """Dedicated entry point for touch2key-wireless script execution."""
    run()

if __name__ == "__main__":
    main()
