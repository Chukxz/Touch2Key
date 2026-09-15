from __future__ import annotations
import sys
from PySide6.QtWidgets import QApplication, QMainWindow
from modules.gui.widgets.layout_plotter_widget import LayoutPlotterWidget


class PlotterWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Touch2Key - HUD Layout Editor")
        self.plotter = LayoutPlotterWidget(self)
        self.setCentralWidget(self.plotter)
        self.showMaximized()


def run():
    app = QApplication.instance() or QApplication(sys.argv)
    window = PlotterWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    run()