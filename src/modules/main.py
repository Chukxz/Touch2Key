import sys
from mapper_module.utils import SYSTEM
import argparse
from mapper_module import engine

parser = argparse.ArgumentParser(description="Touch2Key Main")

parser.add_argument(
    "--profile", action="store_true", help="Generate profiling data."
)
    
def run():
    if SYSTEM == "Windows":
        engine.run(parser)

    elif SYSTEM == "Linux":
        from mapper_module.platforms.linux import check_display_protocol

        if check_display_protocol():
            engine.run(parser)
        else:
            sys.exit(1)

    else:
        print(f"[!] Unsupported OS: {SYSTEM}")
        sys.exit(1)


if __name__ == "__main__":
    run()
