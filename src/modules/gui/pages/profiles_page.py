from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QFileDialog,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QWidget,
)

from modules.database import store
from modules.database.config_io import (
    export_bundle,
    export_layout_json,
    export_settings_toml,
    import_any,
)
from modules.utils import JSONS_FOLDER, PROFILES_FOLDER, MapperEvent
from .base_page import BasePage

if TYPE_CHECKING:
    from modules.utils import MapperEventDispatcher

logger = logging.getLogger("modules.gui.profiles_page")


class ProfilesPage(BasePage):
    """Database-backed Profiles management page.
    Manages layout lifecycles, zone associations, duplication, renaming, activation,
    and profile/layout/bundle importing and exporting.
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
        self.details_label.setStyleSheet(
            "color: palette(placeholder-text); padding: 4px;"
        )
        self.content_layout().addWidget(self.details_label)

        # Action Buttons Layout - Row 1: Profile CRUD
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

        # Action Buttons Layout - Row 2: Imports & Exports
        btn_row_2 = QHBoxLayout()
        self.import_btn = QPushButton("Import (.json / .toml / Bundle)")
        self.export_json_btn = QPushButton("Export Selected (.json)")
        self.export_toml_btn = QPushButton("Export Selected (.toml)")
        self.export_bundle_btn = QPushButton("Export Selected Bundle")

        btn_row_2.addWidget(self.import_btn)
        btn_row_2.addWidget(self.export_json_btn)
        btn_row_2.addWidget(self.export_toml_btn)
        btn_row_2.addWidget(self.export_bundle_btn)
        self.content_layout().addLayout(btn_row_2)

        # Action Buttons Layout - Row 3: Maintenance
        btn_row_3 = QHBoxLayout()
        self.clear_zones_btn = QPushButton("Clear Zones")
        self.delete_btn = QPushButton("Delete Profile")
        self.delete_btn.setStyleSheet("color: #d9534f;")
        self.refresh_btn = QPushButton("Refresh")

        btn_row_3.addWidget(self.clear_zones_btn)
        btn_row_3.addWidget(self.delete_btn)
        btn_row_3.addWidget(self.refresh_btn)
        self.content_layout().addLayout(btn_row_3)

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

        self.import_btn.clicked.connect(self._on_import_clicked)
        self.export_json_btn.clicked.connect(self._on_export_json_clicked)
        self.export_toml_btn.clicked.connect(self._on_export_toml_clicked)
        self.export_bundle_btn.clicked.connect(self._on_export_bundle_clicked)

        self.clear_zones_btn.clicked.connect(self._on_clear_zones)
        self.delete_btn.clicked.connect(self._on_delete)
        self.refresh_btn.clicked.connect(self.load_profiles)

    def load_profiles(self) -> None:
        self.profile_list.clear()
        try:
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
        except Exception as exc:
            logger.exception("Failed to load layout profiles from database")
            QMessageBox.critical(
                self, "Database Error", f"Could not load profiles:\n{exc}"
            )

    def _get_selected_layout_id(self) -> int | None:
        selected = self.profile_list.selectedItems()
        if not selected:
            QMessageBox.warning(
                self, "Selection Required", "Please select a profile from the list."
            )
            return None
        return selected[0].data(Qt.ItemDataRole.UserRole)

    def _on_selection_changed(self) -> None:
        selected = self.profile_list.selectedItems()
        if not selected:
            self.details_label.setText("Select a profile to view details.")
            return

        layout_id = selected[0].data(Qt.ItemDataRole.UserRole)
        try:
            layout = store.layouts.get(layout_id)
            if not layout:
                return

            zones = store.zones.list_for_layout(layout.id)
            img_info = layout.image_path if layout.image_path else "None"
            self.details_label.setText(
                f"ID: {layout.id} | Canvas: {layout.width}x{layout.height} ({layout.dpi} DPI) | "
                f"Zones: {len(zones)} | Image: {img_info}"
            )
        except Exception as exc:
            logger.exception("Failed to fetch details for layout ID %s", layout_id)

    def _notify_reload(self) -> None:
        if self.dispatcher is not None:
            self.dispatcher.dispatch(MapperEvent(action="ON_LAYOUT_RELOAD"))
            self.dispatcher.dispatch(MapperEvent(action="ON_CONFIG_RELOAD"))

    def _on_set_active(self) -> None:
        layout_id = self._get_selected_layout_id()
        if layout_id is None:
            return

        try:
            store.settings.update(active_layout_id=layout_id)
            self.load_profiles()
            self._notify_reload()
            logger.info("Activated profile ID %s", layout_id)
            QMessageBox.information(
                self, "Profile Activated", "Active profile updated and hot-reloaded."
            )
        except Exception as exc:
            logger.exception("Failed to set active profile ID %s", layout_id)
            QMessageBox.critical(
                self, "Database Error", f"Could not activate profile:\n{exc}"
            )

    def _on_new_profile(self) -> None:
        name, ok = QInputDialog.getText(self, "New Profile", "Enter profile name:")
        if not ok or not name.strip():
            return

        name = name.strip()
        try:
            if store.layouts.get_by_name(name) is not None:
                QMessageBox.warning(
                    self, "Name Conflict", f"Profile '{name}' already exists."
                )
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
            logger.info("Created new profile '%s' (ID: %s)", name, new_layout.id)
        except Exception as exc:
            logger.exception("Failed to create new profile '%s'", name)
            QMessageBox.critical(
                self, "Database Error", f"Could not create profile:\n{exc}"
            )

    def _on_rename(self) -> None:
        layout_id = self._get_selected_layout_id()
        if layout_id is None:
            return

        try:
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
                QMessageBox.warning(
                    self,
                    "Name Conflict",
                    f"A profile named '{target_name}' already exists.",
                )
                return

            store.layouts.update(layout_id, name=target_name)
            self.load_profiles()
            self._notify_reload()
            logger.info("Renamed profile ID %s to '%s'", layout_id, target_name)
        except Exception as exc:
            logger.exception("Failed to rename profile ID %s", layout_id)
            QMessageBox.critical(self, "Error", f"Could not rename profile:\n{exc}")

    def _on_duplicate(self) -> None:
        layout_id = self._get_selected_layout_id()
        if layout_id is None:
            return

        try:
            source = store.layouts.get(layout_id)
            if source is None:
                return

            new_name, ok = QInputDialog.getText(
                self,
                "Duplicate Profile",
                "New profile name:",
                text=f"{source.name}_copy",
            )
            if not ok or not new_name.strip():
                return

            target_name = new_name.strip()
            if store.layouts.get_by_name(target_name) is not None:
                QMessageBox.warning(
                    self,
                    "Name Conflict",
                    f"A profile named '{target_name}' already exists.",
                )
                return

            new_layout = store.layouts.duplicate(layout_id, target_name)
            self.load_profiles()
            logger.info(
                "Duplicated profile ID %s to '%s' (ID: %s)",
                layout_id,
                target_name,
                new_layout.id,
            )
        except Exception as exc:
            logger.exception("Failed to duplicate profile ID %s", layout_id)
            QMessageBox.critical(self, "Error", f"Could not duplicate profile:\n{exc}")

    def _on_import_clicked(self) -> None:
        PROFILES_FOLDER.mkdir(parents=True, exist_ok=True)
        file_path_str, _ = QFileDialog.getOpenFileName(
            self,
            "Import Profile / Layout / Config",
            str(PROFILES_FOLDER),
            "Supported Files (*.json *.toml);;JSON Layouts (*.json);;TOML Configs (*.toml);;All files (*.*)",
        )
        if not file_path_str:
            return

        file_path = Path(file_path_str)
        try:
            if import_any(file_path):
                self.load_profiles()
                self._notify_reload()
                logger.info("Imported profile/configuration from '%s'", file_path.name)
                QMessageBox.information(
                    self,
                    "Import Successful",
                    f"Imported '{file_path.stem}' and refreshed profile repository.",
                )
            else:
                QMessageBox.warning(
                    self,
                    "Import Failed",
                    f"Could not import {file_path.name}. Check log console for details.",
                )
        except Exception as exc:
            logger.exception("Failed to import file %s", file_path.name)
            QMessageBox.critical(self, "Import Error", f"Error during import:\n{exc}")

    def _on_export_json_clicked(self) -> None:
        layout_id = self._get_selected_layout_id()
        if layout_id is None:
            return

        layout = store.layouts.get(layout_id)
        if not layout:
            return

        JSONS_FOLDER.mkdir(parents=True, exist_ok=True)
        default_save_path = str(JSONS_FOLDER / f"{layout.name}.json")

        save_path_str, _ = QFileDialog.getSaveFileName(
            self,
            "Save Layout JSON As",
            default_save_path,
            "JSON files (*.json);;All files (*.*)",
        )
        if not save_path_str:
            return

        try:
            out_file = export_layout_json(layout_id, Path(save_path_str))
            logger.info("Exported profile %s to %s", layout_id, out_file)
            QMessageBox.information(
                self,
                "Export Successful",
                f"Exported layout to:\n{out_file.name}",
            )
        except Exception as exc:
            logger.exception("Failed to export profile JSON")
            QMessageBox.critical(self, "Export Failed", str(exc))

    def _on_export_toml_clicked(self) -> None:
        layout_id = self._get_selected_layout_id()
        if layout_id is None:
            return

        layout = store.layouts.get(layout_id)
        if not layout:
            return

        PROFILES_FOLDER.mkdir(parents=True, exist_ok=True)
        default_save_path = str(PROFILES_FOLDER / f"{layout.name}.toml")

        save_path_str, _ = QFileDialog.getSaveFileName(
            self,
            "Save Settings TOML As",
            default_save_path,
            "TOML files (*.toml);;All files (*.*)",
        )
        if not save_path_str:
            return

        try:
            # Optionally link the corresponding JSON layout path if it exists
            json_path = JSONS_FOLDER / f"{layout.name}.json"
            linked_json = json_path if json_path.exists() else None

            out_file = export_settings_toml(
                Path(save_path_str), linked_json_path=linked_json
            )

            logger.info(
                "Exported settings TOML for profile %s to %s", layout.name, out_file
            )
            QMessageBox.information(
                self,
                "Export Successful",
                f"Exported settings TOML to:\n{out_file.name}",
            )
        except Exception as exc:
            logger.exception("Failed to export settings TOML")
            logging.critical(
                f"Export Failed: {exc}"
            )  # Ensures critical error hits logs
            QMessageBox.critical(self, "Export Failed", str(exc))

    def _on_export_bundle_clicked(self) -> None:
        layout_id = self._get_selected_layout_id()
        if layout_id is None:
            return

        layout = store.layouts.get(layout_id)
        if not layout:
            return

        PROFILES_FOLDER.mkdir(parents=True, exist_ok=True)
        folder = QFileDialog.getExistingDirectory(
            self, "Select Target Folder for Profile Bundle", str(PROFILES_FOLDER)
        )
        if not folder:
            return

        try:
            t_file, j_file = export_bundle(Path(folder), profile_name=layout.name)
            logger.info("Exported bundle for %s", layout.name)
            QMessageBox.information(
                self,
                "Bundle Exported",
                f"Exported configuration bundle:\n- {t_file.name}\n- {j_file.name}",
            )
        except Exception as exc:
            logger.exception("Failed to export bundle")
            QMessageBox.critical(self, "Export Failed", str(exc))

    def _on_clear_zones(self) -> None:
        """Removes all the zones while reseeding the bezels"""
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
            try:
                store.zones.delete_all_for_layout(layout_id)
                self.load_profiles()
                self._notify_reload()
                logger.info("Cleared all zones for profile ID %s", layout_id)
            except Exception as exc:
                logger.exception("Failed to clear zones for profile ID %s", layout_id)
                QMessageBox.critical(
                    self, "Database Error", f"Could not clear zones:\n{exc}"
                )

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

        try:
            active_layout = store.get_active_layout()
            is_active = active_layout and active_layout.id == layout_id

            store.zones.delete_all_for_layout(layout_id, False)
            store.layouts.delete(layout_id)

            if is_active:
                store.settings.update(active_layout_id=None)

            self.load_profiles()
            self._notify_reload()
            logger.info("Deleted profile ID %s", layout_id)
        except Exception as exc:
            logger.exception("Failed to delete profile ID %s", layout_id)
            QMessageBox.critical(
                self, "Database Error", f"Could not delete profile:\n{exc}"
            )
