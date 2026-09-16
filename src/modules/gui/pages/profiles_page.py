# src/modules/gui/pages/profiles_page.py

from __future__ import annotations

import logging
from typing import TYPE_CHECKING
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from modules.database import store
from modules.utils import MapperEvent
from .base_page import BasePage

if TYPE_CHECKING:
    from modules.utils import MapperEventDispatcher

logger = logging.getLogger("modules.gui.profiles_page")


class ProfilesPage(BasePage):
    """Database-backed Profiles management page.
    Manages layout lifecycles, zone associations, duplication, renaming, and activation.
    """

    title = "Profiles"

    def __init__(
        self,
        dispatcher: MapperEventDispatcher | None = None,
        parent: QWidget | None = None,
    ):
        super().__init__(dispatcher, parent)

        # Profile List & Metadata Header
        self.profile_list = QListWidget()
        self.content_layout().addWidget(self.profile_list)

        self.details_label = QLabel("Select a profile to view details.")
        self.details_label.setStyleSheet("color: palette(placeholder-text); padding: 4px;")
        self.content_layout().addWidget(self.details_label)

        # Action Buttons Layout
        btn_row_1 = QHBoxLayout()
        self.activate_btn = QPushButton("Set Active")
        self.new_btn = QPushButton("New Blank Profile")
        self.rename_btn = QPushButton("Rename")
        self.duplicate_btn = QPushButton("Duplicate")

        btn_row_1.addWidget(self.activate_btn)
        btn_row_1.addWidget(self.new_btn)
        btn_row_1.addWidget(self.rename_btn)
        btn_row_1.addWidget(self.duplicate_btn)
        self.content_layout().addLayout(btn_row_1)

        btn_row_2 = QHBoxLayout()
        self.clear_zones_btn = QPushButton("Clear Zones")
        self.delete_btn = QPushButton("Delete Profile")
        self.delete_btn.setStyleSheet("color: #d9534f;")
        self.refresh_btn = QPushButton("Refresh")

        btn_row_2.addWidget(self.clear_zones_btn)
        btn_row_2.addWidget(self.delete_btn)
        btn_row_2.addWidget(self.refresh_btn)
        self.content_layout().addLayout(btn_row_2)

        self._wire_signals()
        self.load_profiles()

    def on_page_shown(self) -> None:
        self.load_profiles()

    def _wire_signals(self) -> None:
        self.profile_list.itemSelectionChanged.connect(self._on_selection_changed)
        self.activate_btn.clicked.connect(self._on_set_active)
        self.new_btn.clicked.connect(self._on_new_profile)
        self.rename_btn.clicked.connect(self._on_rename)
        self.duplicate_btn.clicked.connect(self._on_duplicate)
        self.clear_zones_btn.clicked.connect(self._on_clear_zones)
        self.delete_btn.clicked.connect(self._on_delete)
        self.refresh_btn.clicked.connect(self.load_profiles)

    def load_profiles(self) -> None:
        self.profile_list.clear()
        layouts = store.layouts.list_all()
        active_layout = store.get_active_layout()
        active_id = active_layout.id if active_layout else None

        for layout in layouts:
            zones = store.zones.list_for_layout(layout.id)
            display_text = f"{layout.name}  [{len(zones)} zones]  ({layout.width}x{layout.height} @ {layout.dpi} DPI)"

            item = QListWidgetItem(display_text)
            item.setData(Qt.ItemDataRole.UserRole, layout.id)

            if layout.id == active_id:
                item.setText(f"★ {display_text} (Active)")
                font = item.font()
                font.setBold(True)
                item.setFont(font)

            self.profile_list.addItem(item)

        self._on_selection_changed()

    def _get_selected_layout_id(self) -> int | None:
        selected = self.profile_list.selectedItems()
        if not selected:
            QMessageBox.warning(self, "Selection Required", "Please select a profile from the list.")
            return None
        return selected[0].data(Qt.ItemDataRole.UserRole)

    def _on_selection_changed(self) -> None:
        selected = self.profile_list.selectedItems()
        if not selected:
            self.details_label.setText("Select a profile to view details.")
            return

        layout_id = selected[0].data(Qt.ItemDataRole.UserRole)
        layout = store.layouts.get(layout_id)
        if not layout:
            return

        zones = store.zones.list_for_layout(layout.id)
        img_info = layout.image_path if layout.image_path else "None"
        self.details_label.setText(
            f"ID: {layout.id} | Canvas: {layout.width}x{layout.height} ({layout.dpi} DPI) | "
            f"Zones: {len(zones)} | Image: {img_info}"
        )

    def _notify_reload(self) -> None:
        if self.dispatcher is not None:
            self.dispatcher.dispatch(MapperEvent(action="ON_LAYOUT_RELOAD"))
            self.dispatcher.dispatch(MapperEvent(action="ON_CONFIG_RELOAD"))

    def _on_set_active(self) -> None:
        layout_id = self._get_selected_layout_id()
        if layout_id is None:
            return

        store.settings.update(active_layout_id=layout_id)
        self.load_profiles()
        self._notify_reload()
        QMessageBox.information(self, "Profile Activated", "Active profile updated and hot-reloaded.")

    def _on_new_profile(self) -> None:
        name, ok = QInputDialog.getText(self, "New Profile", "Enter profile name:")
        if not ok or not name.strip():
            return

        name = name.strip()
        if store.layouts.get_by_name(name) is not None:
            QMessageBox.warning(self, "Name Conflict", f"Profile '{name}' already exists.")
            return

        settings = store.settings.get()
        new_layout = store.layouts.create(
            name=name,
            width=settings.json_dev_width,
            height=settings.json_dev_height,
            dpi=settings.json_dev_dpi,
        )
        store.settings.update(active_layout_id=new_layout.id)
        self.load_profiles()
        self._notify_reload()

    def _on_rename(self) -> None:
        layout_id = self._get_selected_layout_id()
        if layout_id is None:
            return

        layout = store.layouts.get(layout_id)
        if not layout:
            return

        new_name, ok = QInputDialog.getText(
            self, "Rename Profile", "Enter new name:", text=layout.name
        )
        if not ok or not new_name.strip() or new_name.strip() == layout.name:
            return

        target_name = new_name.strip()
        if store.layouts.get_by_name(target_name) is not None:
            QMessageBox.warning(self, "Name Conflict", f"A profile named '{target_name}' already exists.")
            return

        try:
            store.layouts.update(layout_id, name=target_name)
            self.load_profiles()
            self._notify_reload()
        except Exception as exc:
            logger.exception("Failed to rename profile")
            QMessageBox.critical(self, "Error", f"Could not rename profile:\n{exc}")

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
        except Exception as exc:
            logger.exception("Failed to duplicate profile")
            QMessageBox.critical(self, "Error", f"Could not duplicate profile:\n{exc}")

    def _on_clear_zones(self) -> None:
        layout_id = self._get_selected_layout_id()
        if layout_id is None:
            return

        confirm = QMessageBox.question(
            self,
            "Clear Zones",
            "Are you sure you want to remove all touch zones for this profile?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if confirm == QMessageBox.StandardButton.Yes:
            store.zones.delete_all_for_layout(layout_id)
            self.load_profiles()
            self._notify_reload()

    def _on_delete(self) -> None:
        layout_id = self._get_selected_layout_id()
        if layout_id is None:
            return

        confirm = QMessageBox.question(
            self,
            "Confirm Delete",
            "Delete this profile and all its mapped zones?\nThis cannot be undone.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if confirm != QMessageBox.StandardButton.Yes:
            return

        active_layout = store.get_active_layout()
        is_active = active_layout and active_layout.id == layout_id

        store.zones.delete_all_for_layout(layout_id)
        store.layouts.delete(layout_id)

        if is_active:
            store.settings.update(active_layout_id=None)

        self.load_profiles()
        self._notify_reload()
