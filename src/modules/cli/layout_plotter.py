"""
Standalone HUD Layout Editor and Plotter entry point.
"""

from __future__ import annotations

import sys
from PySide6.QtGui import QCloseEvent
from PySide6.QtWidgets import QApplication, QMainWindow

from modules.database import store
from modules.gui.widgets.layouts_plotter_widget import LayoutsPlotterWidget
from modules.log_manager import AppLogManager


class PlotterWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Touch2Key - HUD Layout Editor (Standalone)")
        self.resize(1100, 700)
        self.plotter = LayoutsPlotterWidget(self, standalone=True)
        self.setCentralWidget(self.plotter)

    def closeEvent(self, event: QCloseEvent) -> None:
        store.close()
        super().closeEvent(event)


def run() -> None:
    # Initialize logging for the plotter GUI
    AppLogManager.setup_logging(is_gui=True, log_prefix="touch2key_plot")

    app = QApplication.instance() or QApplication(sys.argv)
    window = PlotterWindow()
    window.show()

    exit_code = 0
    try:
        exit_code = app.exec()
    finally:
        store.close()

    sys.exit(exit_code)


def main() -> None:
    """Dedicated entry point for pyproject.toml scripts."""
    run()


if __name__ == "__main__":
    main()
