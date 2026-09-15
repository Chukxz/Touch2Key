"""
GUI entry point. Intended to be wired as a `touch2key-gui` console
script in pyproject.toml's [project.scripts], parallel to the existing
`touch2key = "modules.engine:run"` CLI entry.
"""

from __future__ import annotations

import multiprocessing
import sys

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

from modules.database import store
from modules.gui.main_window import MainWindow
from modules.platforms import check_single_instance
from modules.scripts.pre_flight import run as pre_flight_run

GUI_APP_NAME = "Touch2Key_GUI"


def run() -> None:
    # 1. Multiprocessing safety for spawned bridge worker processes
    try:
        multiprocessing.set_start_method("spawn", force=True)
    except RuntimeError:
        pass

    # 2. Run system checks (Interception driver / udev / ADB)
    if not pre_flight_run():
        sys.exit(1)

    # 3. Guard against duplicate running GUI instances
    success, _ = check_single_instance(GUI_APP_NAME)
    if not success:
        sys.exit(0)

    # 4. Enable High-DPI scaling before QApplication construction
    QApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
    )

    app = QApplication.instance() or QApplication(sys.argv)
    app.setApplicationName("Touch2Key")
    app.setQuitOnLastWindowClosed(True)

    # 5. Launch Main Window
    window = MainWindow()
    window.show()

    exit_code = app.exec()

    # 6. Clean database connection shutdown on exit
    store.close()
    sys.exit(exit_code)


if __name__ == "__main__":
    run()