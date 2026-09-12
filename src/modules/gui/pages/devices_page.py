from __future__ import annotations

from PySide6.QtWidgets import QListWidget, QPushButton, QHBoxLayout

from .base_page import BasePage


class DevicesPage(BasePage):
    """Replaces the modal window picker (core/list_windows.py's
    ListApp) and exposes ADB device / wireless-connect actions inline,
    instead of blocking dialogs run once during startup."""

    title = "Devices"

    def __init__(self, parent=None):
        super().__init__(parent)

        self.window_list = QListWidget()
        self.content_layout().addWidget(self.window_list)

        btn_row = QHBoxLayout()
        self.refresh_btn = QPushButton("Refresh windows")
        self.connect_wireless_btn = QPushButton("Connect wirelessly")
        btn_row.addWidget(self.refresh_btn)
        btn_row.addWidget(self.connect_wireless_btn)
        self.content_layout().addLayout(btn_row)

        # main_window.py should poll WindowManager.find_visible_windows()
        # on a QTimer (same ~1s cadence ListApp used) to repopulate
        # window_list, and treat a selected row as the active target
        # window instead of ListApp's one-shot _handle_enter().
