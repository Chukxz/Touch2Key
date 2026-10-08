"""
Standalone Layout Studio entry point.
"""

from __future__ import annotations

import sys
from typing import cast

from PySide6.QtGui import QCloseEvent, QIcon
from PySide6.QtWidgets import QApplication, QMainWindow

from modules.utils import ICONS_FOLDER
from modules.database import store
from modules.gui.layout_studio_page import LayoutStudioPage
from modules.log_manager import AppLogManager


class LayoutStudioWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Touch2Key - Layout Studio (Standalone)")
        
        # Increased default size slightly to accommodate the 3-pane IDE comfortably
        self.resize(1300, 800)
        
        # Initialize the unified Studio Page (dispatcher is None in standalone mode)
        self.studio = LayoutStudioPage(dispatcher=None, parent=self)
        self.setCentralWidget(self.studio)
        
        # Trigger the lifecycle method to load profiles and canvas data immediately
        self.studio.on_page_shown()

    def closeEvent(self, event: QCloseEvent) -> None:
        store.close()
        super().closeEvent(event)


def run() -> None:
    # Initialize logging for the studio GUI
    AppLogManager.setup_logging(is_gui=True, log_prefix="touch2key_studio")

    app = cast(QApplication, QApplication.instance() or QApplication(sys.argv))
    app_icon_path = ICONS_FOLDER / "app.png"
    if app_icon_path.exists():
        app.setWindowIcon(QIcon(str(app_icon_path)))

    window = LayoutStudioWindow()
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
