from __future__ import annotations

from typing import TYPE_CHECKING
from PySide6.QtCore import Signal
from PySide6.QtWidgets import QGroupBox, QHBoxLayout, QLabel, QPushButton, QVBoxLayout

from modules.database import store
from .base_page import BasePage

if TYPE_CHECKING:
    from modules.utils import MapperEventDispatcher


class DashboardPage(BasePage):
    """Primary overview dashboard displaying active layout, target window, and engine state."""

    title = "Dashboard"

    start_requested = Signal()
    stop_requested = Signal()

    def __init__(
        self,
        dispatcher: MapperEventDispatcher | None = None,
        parent=None,
    ):
        super().__init__(dispatcher, parent)

        info_box = QGroupBox("Active Session")
        info_layout = QVBoxLayout(info_box)

        self.status_label = QLabel("Engine: Stopped")
        self.status_label.setStyleSheet("font-weight: bold;")
        self.active_profile_label = QLabel("Active Profile: None")
        self.target_window_label = QLabel("Target Window: None")

        info_layout.addWidget(self.status_label)
        info_layout.addWidget(self.active_profile_label)
        info_layout.addWidget(self.target_window_label)
        self.content_layout().addWidget(info_box)

        btn_row = QHBoxLayout()
        self.start_btn = QPushButton("Start Engine")
        self.stop_btn = QPushButton("Stop Engine")
        self.stop_btn.setEnabled(False)

        # Wire up button clicks to signals
        self.start_btn.clicked.connect(self.start_requested.emit)
        self.stop_btn.clicked.connect(self.stop_requested.emit)

        btn_row.addWidget(self.start_btn)
        btn_row.addWidget(self.stop_btn)
        self.content_layout().addLayout(btn_row)
        self.content_layout().addStretch()

    def on_page_shown(self) -> None:
        active_layout = store.get_active_layout()
        if active_layout:
            self.active_profile_label.setText(
                f"Active Profile: {active_layout.name} (ID: {active_layout.id})"
            )
        else:
            self.active_profile_label.setText("Active Profile: None")

    def set_running(self, running: bool, window_title: str = "") -> None:
        self.start_btn.setEnabled(not running)
        self.stop_btn.setEnabled(running)
        self.status_label.setText("Engine: Running" if running else "Engine: Stopped")
        if window_title:
            self.target_window_label.setText(f"Target Window: {window_title}")
