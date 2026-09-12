from __future__ import annotations

from PySide6.QtWidgets import QListWidget, QPushButton, QHBoxLayout

from .base_page import BasePage


class ProfilesPage(BasePage):
    """New page enabled by the sqlite migration: lists saved `layouts`
    rows and lets the user switch app_settings.active_layout_id,
    duplicate, or delete a profile. Replaces scripts/select_json.py's
    file-picker flow."""

    title = "Profiles"

    def __init__(self, parent=None):
        super().__init__(parent)

        self.profile_list = QListWidget()
        self.content_layout().addWidget(self.profile_list)

        btn_row = QHBoxLayout()
        self.activate_btn = QPushButton("Set active")
        self.duplicate_btn = QPushButton("Duplicate")
        self.delete_btn = QPushButton("Delete")
        btn_row.addWidget(self.activate_btn)
        btn_row.addWidget(self.duplicate_btn)
        btn_row.addWidget(self.delete_btn)
        self.content_layout().addLayout(btn_row)
