"""
GUI entry point with environment validation and optional cProfile tracing.
"""

from __future__ import annotations

import argparse
import cProfile
import multiprocessing
import sys
from typing import TYPE_CHECKING, cast
import signal

from PySide6.QtCore import Qt, QCoreApplication, QTimer
from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QIcon

from modules.database import store
from modules.gui.main_window import MainWindow
from modules.platforms import check_single_instance
from modules.utils import APP_NAME, DIAGNOSTICS_FOLDER, ICONS_FOLDER
from modules.log_manager import AppLogManager

if TYPE_CHECKING:
    from cProfile import Profile

gui_profiler: Profile | None = None


def profiler_cleanup(
    prof: Profile | None, filename: str = "touch2key_gui.prof"
) -> None:
    if prof:
        prof.disable()
        DIAGNOSTICS_FOLDER.mkdir(parents=True, exist_ok=True)
        dump_path = DIAGNOSTICS_FOLDER / filename
        prof.dump_stats(dump_path)
        print(f"[+] Profiling data saved to: {dump_path}")


def run(parser: argparse.ArgumentParser | None = None) -> None:
    global gui_profiler
    # Initialize GUI logging (no terminal spam + buffers file output)
    AppLogManager.setup_logging(is_gui=True, log_prefix="touch2key_gui")

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

    # -----------------------------------------------------------------------
    # 1. GUI Argument Parsing
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
    # 2. Boot Sequence (Initialize Qt Application Early)
    # -----------------------------------------------------------------------
    QApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
    )

    app = cast(QApplication, QApplication.instance() or QApplication(sys.argv))
    app.setApplicationName(APP_NAME)
    app.setQuitOnLastWindowClosed(True)

    app_icon_path = ICONS_FOLDER / "app.png"
    if app_icon_path.exists():
        app.setWindowIcon(QIcon(str(app_icon_path)))

    # Allow Python signals to be processed periodically by running a dummy timer
    timer = QTimer()
    timer.start(500)
    timer.timeout.connect(lambda: None)  # Kickstarts the Python interpreter loop

    # Handle Ctrl+C cleanly
    signal.signal(signal.SIGINT, lambda *_: QCoreApplication.quit())

    try:
        multiprocessing.set_start_method("spawn", force=True)
    except RuntimeError:
        pass

    success, _ = check_single_instance(APP_NAME)
    if not success:
        profiler_cleanup(gui_profiler)
        sys.exit(0)

    # -----------------------------------------------------------------------
    # 3. Application Execution
    # -----------------------------------------------------------------------
    window = MainWindow()
    window.showMaximized()

    exit_code = 0
    try:
        exit_code = app.exec()
    finally:
        store.close()
        profiler_cleanup(gui_profiler)

    sys.exit(exit_code)


def main() -> None:
    """Dedicated entry point for pyproject.toml scripts and direct execution."""
    run()


if __name__ == "__main__":
    main()
