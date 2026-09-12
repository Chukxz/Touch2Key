"""
GUI entry point. Intended to be wired as a `touch2key-gui` console
script in pyproject.toml's [project.scripts], parallel to the existing
`touch2key = "mapper_module.main:run"` CLI entry.
"""
from __future__ import annotations
import sys

from PySide6.QtWidgets import QApplication

from modules.gui.main_window import MainWindow


def run() -> None:
    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(True)
    window = MainWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    run()
