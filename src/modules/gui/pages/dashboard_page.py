from __future__ import annotations

from PySide6.QtWidgets import QLabel, QPushButton, QHBoxLayout

from .base_page import BasePage


class DashboardPage(BasePage):
    title = "Dashboard"

    def __init__(self, parent=None):
        super().__init__(parent)

        self.status_label = QLabel("Engine stopped.")
        self.content_layout().addWidget(self.status_label)

        btn_row = QHBoxLayout()
        self.start_btn = QPushButton("Start engine")
        self.stop_btn = QPushButton("Stop engine")
        self.stop_btn.setEnabled(False)
        btn_row.addWidget(self.start_btn)
        btn_row.addWidget(self.stop_btn)
        self.content_layout().addLayout(btn_row)
        self.content_layout().addStretch()

        # main_window.py wires start_btn/stop_btn.clicked to Engine
        # lifecycle calls and calls set_running() to reflect state here.

    def set_running(self, running: bool) -> None:
        self.start_btn.setEnabled(not running)
        self.stop_btn.setEnabled(running)
        self.status_label.setText("Engine running." if running else "Engine stopped.")
