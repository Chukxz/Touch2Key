from __future__ import annotations

import sys
from PySide6.QtGui import QCloseEvent
from PySide6.QtWidgets import QApplication, QMainWindow

from modules.database import store
from modules.gui.widgets.layout_plotter_widget import LayoutPlotterWidget


class PlotterWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Touch2Key - HUD Layout Editor (Standalone)")
        self.resize(1100, 700)
        self.plotter = LayoutPlotterWidget(self, standalone=True)
        self.setCentralWidget(self.plotter)

    def closeEvent(self, event: QCloseEvent) -> None:
        store.close()
        super().closeEvent(event)


def run() -> None:
    app = QApplication.instance() or QApplication(sys.argv)
    window = PlotterWindow()
    window.show()
    exit_code = app.exec()
    store.close()
    sys.exit(exit_code)


if __name__ == "__main__":
    run()