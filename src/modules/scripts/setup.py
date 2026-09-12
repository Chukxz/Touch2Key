import sys
from modules.utils import SYSTEM


def run():
    print(f"--- Setting up for {SYSTEM} ---")

    if SYSTEM == "Windows":
        from modules.platforms.windows import setup_windows

        setup_windows()

    elif SYSTEM == "Linux":
        from modules.platforms.linux import setup_linux

        setup_linux()

    else:
        print(f"[!] Unsupported OS: {SYSTEM}")
        sys.exit(1)


if __name__ == "__main__":
    run()
