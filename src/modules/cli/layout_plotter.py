"""
Standalone Layout Studio entry point for CLI usage.
Runs strictly using terminal logging (no GUI log dock).
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
        self.resize(1300, 800)
        
        # Instantiate the widget directly (dispatcher is None in standalone mode)
        self.studio = LayoutStudioPage(dispatcher=None, parent=self)
        self.setCentralWidget(self.studio)
        
        # Force the lifecycle hook to load the db profiles into the UI
        self.studio.on_page_shown()

    def closeEvent(self, event: QCloseEvent) -> None:
        store.close()
        super().closeEvent(event)


def run() -> None:
    # Initialize standard terminal logging (is_gui=False for CLI mode)
    AppLogManager.setup_logging(is_gui=False, log_prefix="touch2key_studio")

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
