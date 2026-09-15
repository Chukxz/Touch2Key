from __future__ import annotations

import logging
from typing import TYPE_CHECKING
from PySide6.QtWidgets import (
    QHBoxLayout,
    QInputDialog,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
)

from modules.database import store
from modules.utils import MapperEvent
from .base_page import BasePage

if TYPE_CHECKING:
    from modules.utils import MapperEventDispatcher

logger = logging.getLogger("modules.gui.profiles_page")


class ProfilesPage(BasePage):
    """Database-backed Profiles management page.
    Lists saved layout profiles, switches active layout, duplicates, and deletes rows.
    """

    title = "Profiles"

    def __init__(
        self,
        dispatcher: MapperEventDispatcher | None = None,
        parent=None,
    ):
        super().__init__(dispatcher, parent)

        self.profile_list = QListWidget()
        self.content_layout().addWidget(self.profile_list)

        btn_row = QHBoxLayout()
        self.activate_btn = QPushButton("Set active")
        self.duplicate_btn = QPushButton("Duplicate")
        self.delete_btn = QPushButton("Delete")
        self.refresh_btn = QPushButton("Refresh")

        btn_row.addWidget(self.activate_btn)
        btn_row.addWidget(self.duplicate_btn)
        btn_row.addWidget(self.delete_btn)
        btn_row.addWidget(self.refresh_btn)
        self.content_layout().addLayout(btn_row)

        self._wire_signals()
        self.load_profiles()

    def on_page_shown(self) -> None:
        self.load_profiles()

    def _wire_signals(self) -> None:
        self.activate_btn.clicked.connect(self._on_set_active)
        self.duplicate_btn.clicked.connect(self._on_duplicate)
        self.delete_btn.clicked.connect(self._on_delete)
        self.refresh_btn.clicked.connect(self.load_profiles)

    def load_profiles(self) -> None:
        self.profile_list.clear()
        layouts = store.layouts.list_all()
        active_layout = store.get_active_layout()
        active_id = active_layout.id if active_layout else None

        for layout in layouts:
            item = QListWidgetItem(layout.name)
            item.setData(1000, layout.id)
            if layout.id == active_id:
                item.setText(f"{layout.name} (Active)")
                font = item.font()
                font.setBold(True)
                item.setFont(font)
            self.profile_list.addItem(item)

    def _get_selected_layout_id(self) -> int | None:
        selected = self.profile_list.selectedItems()
        if not selected:
            QMessageBox.warning(self, "Selection Required", "Please select a profile from the list.")
            return None
        return selected[0].data(1000)

    def _on_set_active(self) -> None:
        layout_id = self._get_selected_layout_id()
        if layout_id is None:
            return

        store.settings.update(active_layout_id=layout_id)
        self.load_profiles()

        if self.dispatcher is not None:
            self.dispatcher.dispatch(MapperEvent(action="ON_LAYOUT_RELOAD"))
            self.dispatcher.dispatch(MapperEvent(action="ON_CONFIG_RELOAD"))

        QMessageBox.information(self, "Profile Activated", "Active profile updated and hot-reloaded.")

    def _on_duplicate(self) -> None:
        layout_id = self._get_selected_layout_id()
        if layout_id is None:
            return

        source = store.layouts.get(layout_id)
        if source is None:
            return

        new_name, ok = QInputDialog.getText(
            self, "Duplicate Profile", "New profile name:", text=f"{source.name}_copy"
        )
        if not ok or not new_name.strip():
            return

        try:
            store.layouts.duplicate(layout_id, new_name.strip())
            self.load_profiles()
        except Exception as e:
            logger.exception("Failed to duplicate profile")
            QMessageBox.critical(self, "Error", f"Could not duplicate profile:\n{e}")

    def _on_delete(self) -> None:
        layout_id = self._get_selected_layout_id()
        if layout_id is None:
            return

        confirm = QMessageBox.question(
            self,
            "Confirm Delete",
            "Are you sure you want to delete this profile? Associated touch zones will also be deleted.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if confirm != QMessageBox.StandardButton.Yes:
            return

        store.layouts.delete(layout_id)
        self.load_profiles()

        if self.dispatcher is not None:
            self.dispatcher.dispatch(MapperEvent(action="ON_LAYOUT_RELOAD"))