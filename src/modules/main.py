from __future__ import annotations

import sys
import multiprocessing
import argparse
import cProfile
from typing import TYPE_CHECKING

from modules.engine import Engine
from modules.platforms import check_single_instance
from modules.scripts.preflight import run as pre_flight_run
from modules.utils import APP_NAME, DIAGNOSTICS_FOLDER
from modules.log_manager import AppLogManager

from PySide6.QtWidgets import QApplication

if TYPE_CHECKING:
    from cProfile import Profile

cli_profiler: Profile | None = None


def profiler_cleanup(
    prof: Profile | None, filename: str = "touch2key_cli.prof"
) -> None:
    if prof:
        prof.disable()
        DIAGNOSTICS_FOLDER.mkdir(parents=True, exist_ok=True)
        dump_path = DIAGNOSTICS_FOLDER / filename
        prof.dump_stats(dump_path)
        print(f"[+] Profiling data saved to: {dump_path}")


def run(parser: argparse.ArgumentParser | None = None) -> None:
    global cli_profiler

    # -----------------------------------------------------------------------
    # 0. OS & Environment Validation
    # -----------------------------------------------------------------------
    if sys.platform == "linux":
        from modules.platforms.linux import check_display_protocol

        if not check_display_protocol():
            sys.exit(1)
    elif sys.platform != "win32":
        print(f"[!] Unsupported OS: {sys.platform}")
        sys.exit(1)

    # Initialize CLI logging
    AppLogManager.setup_logging(is_gui=False, log_prefix="touch2key_cli")

    # -----------------------------------------------------------------------
    # 1. CLI Argument Parsing
    # -----------------------------------------------------------------------
    if parser is None:
        parser = argparse.ArgumentParser(description="Touch2Key CLI Application")

    parser.add_argument(
        "--profile",
        action="store_true",
        default=False,
        help="Enable cProfile execution tracing",
    )

    args = parser.parse_args()

    if args.profile:
        cli_profiler = cProfile.Profile()
        cli_profiler.enable()

    # -----------------------------------------------------------------------
    # 2. Boot Sequence
    # -----------------------------------------------------------------------
    # Initialize QApplication early so pre-flight knows if a GUI context exists
    # app = QApplication.instance() or QApplication(sys.argv)
    # app.setApplicationName(APP_NAME)

    if not pre_flight_run():
        profiler_cleanup(cli_profiler)
        sys.exit(1)

    try:
        multiprocessing.set_start_method("spawn", force=True)
    except RuntimeError:
        pass

    success, _ = check_single_instance(APP_NAME)
    if not success:
        profiler_cleanup(cli_profiler)
        sys.exit(0)

    # -----------------------------------------------------------------------
    # 3. Application Execution
    # -----------------------------------------------------------------------
    engine = Engine(headless=False)

    try:
        engine._start()
    except KeyboardInterrupt:
        pass
    finally:
        engine._shutdown()
        profiler_cleanup(cli_profiler)


def main() -> None:
    """Dedicated entry point for pyproject.toml scripts and direct execution."""
    run()


if __name__ == "__main__":
    main()
