from __future__ import annotations

import sys
import multiprocessing
import argparse
import cProfile
import datetime
import signal
import logging
from typing import TYPE_CHECKING, cast

from modules.engine import Engine, shutdown_engine_process
from modules.platforms import check_single_instance
from modules.scripts.preflight import run as run_preflight
from modules.utils import APP_NAME, DIAGNOSTICS_FOLDER, ICONS_FOLDER
from modules.log_manager import AppLogManager, initialize_cleanup

from PySide6.QtCore import QTimer, QCoreApplication
from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QIcon

if TYPE_CHECKING:
    from cProfile import Profile
    
logger = logging.getLogger("modules.main")

cli_profiler: Profile | None = None


def profiler_cleanup(prof: Profile | None, filename: str = "touch2key_cli") -> None:
    if prof:
        prof.disable()
        DIAGNOSTICS_FOLDER.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        dump_file_path = DIAGNOSTICS_FOLDER / f"{filename}_{timestamp}.prof"
        prof.dump_stats(dump_file_path)
        logger.info(f"[+] Profiling data saved to: {dump_file_path}")


def run(parser: argparse.ArgumentParser | None = None) -> None:
    global cli_profiler
    AppLogManager.setup_logging(log_prefix="touch2key_cli")

    # -----------------------------------------------------------------------
    # OS & Environment Validation
    # -----------------------------------------------------------------------
    if sys.platform == "linux":
        from modules.platforms.linux import check_display_protocol

        if not check_display_protocol():
            sys.exit(1)
    elif sys.platform != "win32":
        logger.info(f"[!] Unsupported OS: {sys.platform}")
        sys.exit(1)

    # -----------------------------------------------------------------------
    # CLI Argument Parsing
    # -----------------------------------------------------------------------
    if parser is None:
        parser = argparse.ArgumentParser(description="Touch2Key CLI Application")

    parser.add_argument(
        "--profile",
        action="store_true",
        help="Enable cProfile execution tracing",
    )

    parser.add_argument(
        "--use-gui",
        action="store_true",
        help="Initialize QApplication context",
    )

    parser.add_argument(
        "--config",
        type=str,
        help="One-line comma-separated config: 'window_id,toggle_key,slogger.info_key,rate_cap,pps,k_device,m_device', use empty strings or omit commas for defaults/database values, e.g. ',,,100,50,,'",
    )

    args = parser.parse_args()

    if args.profile:
        cli_profiler = cProfile.Profile()
        cli_profiler.enable()
        logger.info(f"[+] Profiling started.")

    # -----------------------------------------------------------------------
    # Boot Sequence
    # -----------------------------------------------------------------------
    if args.use_gui:
        app = cast(QApplication, QApplication.instance() or QApplication(sys.argv))
        app.setApplicationName(APP_NAME)

        app_icon_path = ICONS_FOLDER / "app.png"
        if app_icon_path.exists():
            app.setWindowIcon(QIcon(str(app_icon_path)))

        # Allow Python signals to be processed periodically by running a dummy timer
        timer = QTimer()
        timer.start(500)
        timer.timeout.connect(lambda: None)  # Kickstarts the Python interpreter loop

        # Handle Ctrl+C cleanly
        signal.signal(signal.SIGINT, lambda *_: QCoreApplication.quit())

    if not run_preflight():
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

    initialize_cleanup()

    # -----------------------------------------------------------------------
    # Application Execution
    # -----------------------------------------------------------------------
    # headless explicitly kept false
    engine = Engine(headless=False)

    try:
        if args.config:
            engine._start(config_str=args.config)
        else:
            engine._start()
    except KeyboardInterrupt:
        logger.info("Engine received shutdown signal, exiting cleanly.")
        engine._shutdown()
    finally:
        engine._shutdown()
        profiler_cleanup(cli_profiler)


def main() -> None:
    """Dedicated entry point for touch2key script execution."""
    run()


if __name__ == "__main__":
    main()
