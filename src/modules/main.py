import sys
from modules.utils import SYSTEM
import argparse
from modules import engine

parser = argparse.ArgumentParser(description="Touch2Key Main")

parser.add_argument(
    "--profile", action="store_true", help="Generate profiling data."
)
    
def run():
    if SYSTEM == "Windows":
        engine.run(parser)

    elif SYSTEM == "Linux":
        from modules.platforms.linux import check_display_protocol

        if check_display_protocol():
            engine.run(parser)
        else:
            sys.exit(1)

    else:
        print(f"[!] Unsupported OS: {SYSTEM}")
        sys.exit(1)


if __name__ == "__main__":
    run()
