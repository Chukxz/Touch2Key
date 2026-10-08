from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    """
HUD Layout Editor hosting the visual Plotter canvas, Profile Management, and SQLite layout synchronization.
"""

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
    QSpinBox,
    QVBoxLayout,
    QWidget,
    QSplitter,
    QGroupBox,
)

from modules.database import store
from modules.database.config_io import (
    export_bundle,
    export_layout_json,
    export_settings_toml,
    import_any,
)
from modules.gui.widgets.layouts_plotter_widget import LayoutsPlotterWidget
from modules.scripts.adb_screen_capture import capture_android_screen
from modules.utils import (
    CIRCLE,
    IMAGES_FOLDER,
    JSONS_FOLDER,
    PROFILES_FOLDER,
    RECTANGLE,
    MapperEvent,
)
from .base_page import BasePage

if TYPE_CHECKING:
    from modules.utils import MapperEventDispatcher

logger = logging.getLogger("modules.gui.layout_editor")


class LayoutStudioPage(BasePage):
    """Unified Layout Editor and Profile Manager."""

    title = "Layout Studio"

    def __init__(
        self,
        dispatcher: MapperEventDispatcher | None = None,
        parent: QWidget | None = None,
    ):
        super().__init__(dispatcher, parent)

        # Main Splitter: Left (Profiles) | Right (Canvas)
        self.splitter = QSplitter(Qt.Orientation.Horizontal)
        self.content_layout().addWidget(self.splitter)

        self._setup_left_sidebar()
        self._setup_right_canvas()
        
        # Set initial splitter sizes (e.g., 30% left, 70% right)
        self.splitter.setSizes([300, 700])

        self._wire_signals()
        self.load_profiles()

    def _setup_left_sidebar(self):
        sidebar_widget = QWidget()
        sidebar_layout = QVBoxLayout(sidebar_widget)
        sidebar_layout.setContentsMargins(0, 0, 10, 0)

        # Profiles List Group
        profiles_group = QGroupBox("Profiles")
        profiles_layout = QVBoxLayout(profiles_group)
        
        self.profile_list = QListWidget()
        profiles_layout.addWidget(self.profile_list)

        self.details_label = QLabel("Select a profile to view details.")
        self.details_label.setStyleSheet("color: palette(placeholder-text); padding: 4px;")
        self.details_label.setWordWrap(True)
        profiles_layout.addWidget(self.details_label)

        # Profile Actions
        btn_row_1 = QHBoxLayout()
        self.activate_btn = QPushButton("Set Active")
        self.activate_btn.setStyleSheet("font-weight: bold;")
        self.new_btn = QPushButton("New")
        self.rename_btn = QPushButton("Rename")
        self.duplicate_btn = QPushButton("Duplicate")
        
        btn_row_1.addWidget(self.activate_btn)
        btn_row_1.addWidget(self.new_btn)
        btn_row_1.addWidget(self.rename_btn)
        btn_row_1.addWidget(self.duplicate_btn)
        profiles_layout.addLayout(btn_row_1)

        sidebar_layout.addWidget(profiles_group)

        # File I/O Group
        io_group = QGroupBox("Import & Export")
        io_layout = QVBoxLayout(io_group)
        
        self.import_btn = QPushButton("Import (.json / .toml / Bundle)")
        
        export_row = QHBoxLayout()
        self.export_json_btn = QPushButton("Export JSON")
        self.export_toml_btn = QPushButton("Export TOML")
        self.export_bundle_btn = QPushButton("Export Bundle")
        
        export_row.addWidget(self.export_json_btn)
        export_row.addWidget(self.export_toml_btn)
        export_row.addWidget(self.export_bundle_btn)

        io_layout.addWidget(self.import_btn)
        io_layout.addLayout(export_row)
        sidebar_layout.addWidget(io_group)

        # Maintenance Group
        maint_group = QGroupBox("Maintenance")
        maint_layout = QHBoxLayout(maint_group)
        
        self.clear_zones_btn = QPushButton("Clear Zones")
        self.delete_btn = QPushButton("Delete Profile")
        self.delete_btn.setStyleSheet("color: #d9534f;")
        
        maint_layout.addWidget(self.clear_zones_btn)
        maint_layout.addWidget(self.delete_btn)
        sidebar_layout.addWidget(maint_group)

        self.splitter.addWidget(sidebar_widget)

    def _setup_right_canvas(self):
        canvas_widget = QWidget()
        canvas_layout = QVBoxLayout(canvas_widget)
        canvas_layout.setContentsMargins(10, 0, 0, 0)

        # Toolbar: Canvas Tools
        tools_row = QHBoxLayout()
        
        self.select_image_btn = QPushButton("Select Image")
        self.capture_btn = QPushButton("Capture Screenshot")
        
        self.priority_spin = QSpinBox()
        self.priority_spin.setRange(-100, 100)
        self.priority_spin.setValue(0)
        self.priority_spin.setPrefix("Priority: ")

        self.add_circle_btn = QPushButton("Add Circle (F6)")
        self.add_rect_btn = QPushButton("Add Rectangle (F7)")
        self.toggle_overlays_btn = QPushButton("Toggle Overlays (F4)")
        self.cancel_action_btn = QPushButton("Cancel (F8)")
        self.save_btn = QPushButton("Save to DB (F12)")
        self.save_btn.setStyleSheet("font-weight: bold;")

        tools_row.addWidget(self.select_image_btn)
        tools_row.addWidget(self.capture_btn)
        tools_row.addSpacing(10)
        tools_row.addWidget(self.priority_spin)
        tools_row.addWidget(self.add_circle_btn)
        tools_row.addWidget(self.add_rect_btn)
        tools_row.addWidget(self.toggle_overlays_btn)
        tools_row.addWidget(self.cancel_action_btn)
        tools_row.addWidget(self.save_btn)
        tools_row.addStretch()

        canvas_layout.addLayout(tools_row)

        # Interactive Canvas
        self.plotter_widget = LayoutsPlotterWidget(self, standalone=False)
        canvas_layout.addWidget(self.plotter_widget, stretch=1)

        self.splitter.addWidget(canvas_widget)

    def on_page_shown(self) -> None:
        self.load_profiles()
        self.plotter_widget.reload_active_layout()

    def _wire_signals(self) -> None:
        # Sidebar Signals
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

        # Canvas Signals
        self.select_image_btn.clicked.connect(self._select_background_image)
        self.capture_btn.clicked.connect(self._trigger_screenshot_capture)
        self.priority_spin.valueChanged.connect(self.on_priority_changed)
        self.add_circle_btn.clicked.connect(lambda: self._start_draw_mode(CIRCLE, 3))
        self.add_rect_btn.clicked.connect(lambda: self._start_draw_mode(RECTANGLE, 4))
        self.toggle_overlays_btn.clicked.connect(self.plotter_widget.toggle_visibility)
        self.cancel_action_btn.clicked.connect(self.plotter_widget.reset_state)
        self.save_btn.clicked.connect(self._on_save_button_clicked)

        self.plotter_widget.layout_saved.connect(self._on_layout_saved)
        self.plotter_widget.zone_selected.connect(self._on_zone_selected_on_canvas)

    # --- SIDEBAR LOGIC ---

    def load_profiles(self) -> None:
        self.profile_list.clear()
        try:
            layouts = store.layouts.list_all()
            active_layout = store.get_active_layout()
            active_id = active_layout.id if active_layout else None

            for layout in layouts:
                zones = store.zones.list_for_layout(layout.id)
                display_text = f"{layout.name}  [{len(zones)} zones]"

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
            QMessageBox.critical(self, "Database Error", f"Could not load profiles:\n{exc}")

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
        try:
            layout = store.layouts.get(layout_id)
            if not layout: return

            zones = store.zones.list_for_layout(layout.id)
            img_info = layout.image_path if layout.image_path else "None"
            self.details_label.setText(
                f"ID: {layout.id} | Canvas: {layout.width}x{layout.height} ({layout.dpi} DPI)\n"
                f"Zones: {len(zones)} | Image: {img_info}"
            )
        except Exception as exc:
            logger.exception("Failed to fetch details for layout ID %s", layout_id)

    def _notify_engine_reload(self) -> None:
        if self.dispatcher is not None:
            self.dispatcher.dispatch(MapperEvent(action="ON_LAYOUT_RELOAD"))
            self.dispatcher.dispatch(MapperEvent(action="ON_CONFIG_RELOAD"))

    def _on_set_active(self) -> None:
        layout_id = self._get_selected_layout_id()
        if layout_id is None: return

        try:
            store.settings.update(active_layout_id=layout_id)
            self.load_profiles()
            self.plotter_widget.reload_active_layout()
            self._notify_engine_reload()
            logger.info("Activated profile ID %s", layout_id)
        except Exception as exc:
            logger.exception("Failed to set active profile ID %s", layout_id)
            QMessageBox.critical(self, "Database Error", f"Could not activate profile:\n{exc}")

    def _on_new_profile(self) -> None:
        name, ok = QInputDialog.getText(self, "New Profile", "Enter profile name:")
        if not ok or not name.strip(): return
        name = name.strip()
        
        try:
            if store.layouts.get_by_name(name) is not None:
                QMessageBox.warning(self, "Name Conflict", f"Profile '{name}' already exists.")
                return

            settings = store.settings.get()
            new_layout = store.layouts.create(
                name=name, width=settings.json_dev_width,
                height=settings.json_dev_height, dpi=settings.json_dev_dpi,
            )
            store.settings.update(active_layout_id=new_layout.id)
            self.load_profiles()
            self.plotter_widget.reload_active_layout()
            self._notify_engine_reload()
            logger.info("Created new profile '%s' (ID: %s)", name, new_layout.id)
        except Exception as exc:
            logger.exception("Failed to create new profile '%s'", name)
            QMessageBox.critical(self, "Database Error", f"Could not create profile:\n{exc}")

    def _on_rename(self) -> None:
        layout_id = self._get_selected_layout_id()
        if layout_id is None: return

        try:
            layout = store.layouts.get(layout_id)
            if not layout: return

            new_name, ok = QInputDialog.getText(self, "Rename Profile", "Enter new name:", text=layout.name)
            if not ok or not new_name.strip() or new_name.strip() == layout.name: return

            target_name = new_name.strip()
            if store.layouts.get_by_name(target_name) is not None:
                QMessageBox.warning(self, "Name Conflict", f"A profile named '{target_name}' already exists.")
                return

            store.layouts.update(layout_id, name=target_name)
            self.load_profiles()
            self._notify_engine_reload()
            logger.info("Renamed profile ID %s to '%s'", layout_id, target_name)
        except Exception as exc:
            logger.exception("Failed to rename profile ID %s", layout_id)
            QMessageBox.critical(self, "Error", f"Could not rename profile:\n{exc}")

    def _on_duplicate(self) -> None:
        layout_id = self._get_selected_layout_id()
        if layout_id is None: return

        try:
            source = store.layouts.get(layout_id)
            if source is None: return

            new_name, ok = QInputDialog.getText(self, "Duplicate Profile", "New profile name:", text=f"{source.name}_copy")
            if not ok or not new_name.strip(): return

            target_name = new_name.strip()
            if store.layouts.get_by_name(target_name) is not None:
                QMessageBox.warning(self, "Name Conflict", f"A profile named '{target_name}' already exists.")
                return

            new_layout = store.layouts.duplicate(layout_id, target_name)
            self.load_profiles()
            logger.info("Duplicated profile ID %s to '%s' (ID: %s)", layout_id, target_name, new_layout.id)
        except Exception as exc:
            logger.exception("Failed to duplicate profile ID %s", layout_id)
            QMessageBox.critical(self, "Error", f"Could not duplicate profile:\n{exc}")

    def _on_clear_zones(self) -> None:
        layout_id = self._get_selected_layout_id()
        if layout_id is None: return

        confirm = QMessageBox.question(
            self, "Clear Zones", "Are you sure you want to remove all touch zones for this profile?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if confirm == QMessageBox.StandardButton.Yes:
            try:
                store.zones.delete_all_for_layout(layout_id) # Using cleaned up API
                self.load_profiles()
                active = store.get_active_layout()
                if active and active.id == layout_id:
                    self.plotter_widget.reload_active_layout()
                    self._notify_engine_reload()
                logger.info("Cleared all zones for profile ID %s", layout_id)
            except Exception as exc:
                logger.exception("Failed to clear zones for profile ID %s", layout_id)
                QMessageBox.critical(self, "Database Error", f"Could not clear zones:\n{exc}")

    def _on_delete(self) -> None:
        layout_id = self._get_selected_layout_id()
        if layout_id is None: return

        confirm = QMessageBox.question(
            self, "Confirm Delete", "Delete this profile and all its mapped zones?\nThis cannot be undone.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if confirm != QMessageBox.StandardButton.Yes: return

        try:
            active_layout = store.get_active_layout()
            is_active = active_layout and active_layout.id == layout_id

            store.zones.delete_all_for_layout(layout_id) # Using cleaned up API
            store.layouts.delete(layout_id)

            if is_active:
                store.settings.update(active_layout_id=None)
                self.plotter_widget.reload_active_layout()
                self._notify_engine_reload()

            self.load_profiles()
            logger.info("Deleted profile ID %s", layout_id)
        except Exception as exc:
            logger.exception("Failed to delete profile ID %s", layout_id)
            QMessageBox.critical(self, "Database Error", f"Could not delete profile:\n{exc}")

    # --- FILE I/O LOGIC ---

    def _on_import_clicked(self) -> None:
        PROFILES_FOLDER.mkdir(parents=True, exist_ok=True)
        file_path_str, _ = QFileDialog.getOpenFileName(
            self, "Import Profile / Layout / Config", str(PROFILES_FOLDER),
            "Supported Files (*.json *.toml);;JSON Layouts (*.json);;TOML Configs (*.toml);;All files (*.*)"
        )
        if not file_path_str: return

        file_path = Path(file_path_str)
        try:
            if import_any(file_path):
                self.load_profiles()
                self.plotter_widget.reload_active_layout()
                self._notify_engine_reload()
                logger.info("Imported configuration from '%s'", file_path.name)
                QMessageBox.information(self, "Success", f"Imported '{file_path.stem}' successfully.")
            else:
                QMessageBox.warning(self, "Import Failed", f"Could not import {file_path.name}. Check logs.")
        except Exception as exc:
            logger.exception("Unexpected error while importing '%s'", file_path.name)
            QMessageBox.critical(self, "Import Error", f"Failed to import:\n{exc}")

    def _on_export_json_clicked(self) -> None:
        layout_id = self._get_selected_layout_id()
        if layout_id is None: return

        layout = store.layouts.get(layout_id)
        JSONS_FOLDER.mkdir(parents=True, exist_ok=True)
        default_save_path = str(JSONS_FOLDER / f"{layout.name}.json")

        save_path_str, _ = QFileDialog.getSaveFileName(
            self, "Save Layout JSON As", default_save_path, "JSON files (*.json);;All files (*.*)"
        )
        if not save_path_str: return

        try:
            out_file = export_layout_json(layout_id, Path(save_path_str))
            logger.info("Exported profile %s to %s", layout_id, out_file)
            QMessageBox.information(self, "Export Successful", f"Exported layout to:\n{out_file.name}")
        except Exception as exc:
            logger.exception("Failed to export profile JSON")
            QMessageBox.critical(self, "Export Failed", str(exc))

    def _on_export_toml_clicked(self) -> None:
        layout_id = self._get_selected_layout_id()
        if layout_id is None: return

        layout = store.layouts.get(layout_id)
        PROFILES_FOLDER.mkdir(parents=True, exist_ok=True)
        default_save_path = str(PROFILES_FOLDER / f"{layout.name}.toml")

        save_path_str, _ = QFileDialog.getSaveFileName(
            self, "Save Settings TOML As", default_save_path, "TOML files (*.toml);;All files (*.*)"
        )
        if not save_path_str: return

        try:
            json_path = JSONS_FOLDER / f"{layout.name}.json"
            linked_json = json_path if json_path.exists() else None
            out_file = export_settings_toml(Path(save_path_str), linked_json_path=linked_json)

            logger.info("Exported settings TOML for profile %s to %s", layout.name, out_file)
            QMessageBox.information(self, "Export Successful", f"Exported settings TOML to:\n{out_file.name}")
        except Exception as exc:
            logger.exception("Failed to export settings TOML")
            QMessageBox.critical(self, "Export Failed", str(exc))

    def _on_export_bundle_clicked(self) -> None:
        layout_id = self._get_selected_layout_id()
        if layout_id is None: return

        layout = store.layouts.get(layout_id)
        PROFILES_FOLDER.mkdir(parents=True, exist_ok=True)
        folder = QFileDialog.getExistingDirectory(self, "Select Target Folder for Profile Bundle", str(PROFILES_FOLDER))
        if not folder: return

        try:
            t_file, j_file = export_bundle(Path(folder), profile_name=layout.name)
            logger.info("Exported bundle for %s", layout.name)
            QMessageBox.information(self, "Bundle Exported", f"Exported configuration bundle:\n- {t_file.name}\n- {j_file.name}")
        except Exception as exc:
            logger.exception("Failed to export bundle")
            QMessageBox.critical(self, "Export Failed", str(exc))

    # --- CANVAS LOGIC ---

    def _start_draw_mode(self, shape_type: str, clicks: int) -> None:
        if store.get_active_layout() is None:
            QMessageBox.warning(self, "No Active Profile", "Please create or select an active profile in the sidebar first.")
            return
        self.plotter_widget.start_mode(shape_type, clicks)

    def _on_zone_selected_on_canvas(self, priority: int) -> None:
        self.priority_spin.blockSignals(True)
        self.priority_spin.setValue(priority)
        self.priority_spin.blockSignals(False)

    def on_priority_changed(self, val: int) -> None:
        if self.plotter_widget.current_draggable:
            entry_id = self.plotter_widget.current_draggable.entry_id
            if entry_id in self.plotter_widget.shapes:
                self.plotter_widget.shapes[entry_id]["priority"] = val
                self.plotter_widget.update_title(f"Zone ID {entry_id} Priority set to {val}", True)

    def _on_save_button_clicked(self) -> None:
        active = store.get_active_layout()
        if active is not None and hasattr(self.plotter_widget, "save_to_database"):
            self.plotter_widget.save_to_database(active.name)
        else:
            self.plotter_widget.enter_naming_mode()

    def _on_layout_saved(self, name: str, layout_id: int) -> None:
        logger.info("Layout '%s' (ID: %s) saved to database", name, layout_id)
        self.load_profiles()
        self._notify_engine_reload()

    def _select_background_image(self) -> None:
        active = store.get_active_layout()
        if active is None:
            QMessageBox.warning(self, "No Active Layout", "Please select or create an active layout before setting an image.")
            return

        IMAGES_FOLDER.mkdir(parents=True, exist_ok=True)
        file_path_str, _ = QFileDialog.getOpenFileName(
            self, "Select Background Image from Folder", str(IMAGES_FOLDER),
            "Images (*.png *.jpg *.jpeg *.bmp);;All files (*.*)"
        )
        if not file_path_str: return

        img_path = Path(file_path_str)
        try:
            store.layouts.update(active.id, image_path=str(img_path.resolve()))
            self.load_profiles()
            self.plotter_widget.reload_active_layout()
            self._notify_engine_reload()
            logger.info("Updated active layout ID %s background image to '%s'", active.id, img_path.name)
        except Exception as exc:
            logger.exception("Failed to update background image")
            QMessageBox.critical(self, "Error", f"Failed to set background image:\n{exc}")

    def _trigger_screenshot_capture(self) -> None:
        active = store.get_active_layout()
        if active is None:
            QMessageBox.warning(self, "No Active Layout", "Please select or create an active layout before capturing a screenshot.")
            return

        try:
            capture_android_screen(parent=self)
            self.load_profiles()
            self.plotter_widget.reload_active_layout()
            self._notify_engine_reload()
            logger.info("Screenshot captured and linked to active layout")
            QMessageBox.information(self, "Screenshot", "Reference screenshot captured and linked.")
        except Exception as exc:
            logger.exception("Screenshot capture failed")
            QMessageBox.critical(self, "Capture Failed", str(exc))
,
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
