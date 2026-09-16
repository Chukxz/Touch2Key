"""
GUI entry point with environment validation and optional cProfile tracing.
"""

from __future__ import annotations

import argparse
import cProfile
import multiprocessing
import sys
from typing import TYPE_CHECKING

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

from modules.database import store
from modules.gui.main_window import MainWindow
from modules.platforms import check_single_instance
from modules.scripts.pre_flight import run as pre_flight_run
from modules.utils import DIAGNOSTICS_FOLDER, SYSTEM
from modules.log_manager import AppLogManager

if TYPE_CHECKING:
    from cProfile import Profile

GUI_APP_NAME = "Touch2Key_GUI"
gui_profiler: Profile | None = None


def profiler_cleanup(prof: Profile | None, filename: str = "touch2key_gui.prof") -> None:
    if prof:
        prof.disable()
        DIAGNOSTICS_FOLDER.mkdir(parents=True, exist_ok=True)
        dump_path = DIAGNOSTICS_FOLDER / filename
        prof.dump_stats(dump_path)
        print(f"[+] Profiling data saved to: {dump_path}")


def run(parser: argparse.ArgumentParser | None = None) -> None:
    global gui_profiler

    # -----------------------------------------------------------------------
    # 0. OS & Environment Validation
    # -----------------------------------------------------------------------
    if SYSTEM == "Linux":
        from modules.platforms.linux import check_display_protocol
        if not check_display_protocol():
            sys.exit(1)
    elif SYSTEM != "Windows":
        print(f"[!] Unsupported OS: {SYSTEM}")
        sys.exit(1)

    # Initialize GUI logging (no terminal spam + buffers file output)
    AppLogManager.setup_logging(is_gui=True, log_prefix="touch2key_gui")

    # -----------------------------------------------------------------------
    # 1. CLI Argument Parsing
    # -----------------------------------------------------------------------
    if parser is None:
        parser = argparse.ArgumentParser(description="Touch2Key GUI Application")

    parser.add_argument(
        "--profile",
        action="store_true",
        default=False,
        help="Enable cProfile execution tracing",
    )

    args, _ = parser.parse_known_args()

    if args.profile:
        gui_profiler = cProfile.Profile()
        gui_profiler.enable()

    # -----------------------------------------------------------------------
    # 2. Boot Sequence
    # -----------------------------------------------------------------------
    try:
        multiprocessing.set_start_method("spawn", force=True)
    except RuntimeError:
        pass

    if not pre_flight_run():
        profiler_cleanup(gui_profiler)
        sys.exit(1)

    success, _ = check_single_instance(GUI_APP_NAME)
    if not success:
        profiler_cleanup(gui_profiler)
        sys.exit(0)

    # -----------------------------------------------------------------------
    # 3. Application Execution
    # -----------------------------------------------------------------------
    QApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
    )

    app = QApplication.instance() or QApplication(sys.argv)
    app.setApplicationName("Touch2Key")
    app.setQuitOnLastWindowClosed(True)

    window = MainWindow()
    window.show()

    exit_code = 0
    try:
        exit_code = app.exec()
    finally:
        store.close()
        profiler_cleanup(gui_profiler)

    sys.exit(exit_code)


if __name__ == "__main__":
    run()
