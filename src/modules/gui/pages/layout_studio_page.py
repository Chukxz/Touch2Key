"""
HUD Layout Editor hosting the visual Plotter canvas, Profile Management, and SQLite layout synchronization.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any

from PySide6.QtCore import Qt
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QSplitter,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from modules.core.pipeline import PipelineConfig
from modules.database import reset_layout_zones_to_app_settings, store
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

if TYPE_CHECKING:
    from modules.utils import MapperEventDispatcher

logger = logging.getLogger("modules.gui.layout_studio_page")

STATIC_SHORTCUTS_HELP = (
    "<b>Shortcuts:</b> "
    "<span style='color: palette(highlight);'>Ctrl+F</span> Find | "
    "<span style='color: palette(highlight);'>F12</span> Save | "
    "<span style='color: palette(highlight);'>Esc</span> Cancel/Exit | "
    "<span style='color: palette(highlight);'>F6</span> Circle | "
    "<span style='color: palette(highlight);'>F7</span> Rect | "
    "<span style='color: palette(highlight);'>Del</span> Delete | "
    "<span style='color: palette(highlight);'>F2</span> Clear All | "
    "<span style='color: palette(highlight);'>F4</span> Overlays | "
    "<span style='color: palette(highlight);'>Space</span> Toggle Pointer | "
    "<span style='color: palette(highlight);'>Arrows</span> Nudge"
)


def _format_timestamp(raw_ts: str | None) -> str:
    """Formats an SQLite timestamp string (YYYY-MM-DD HH:MM:SS) to YYYY-MM-DD HH:MM."""
    if not raw_ts or not raw_ts.strip():
        return "Unknown"
    clean = raw_ts.replace("T", " ").strip()
    return clean[:16] if len(clean) >= 16 else clean


def _get_relative_time_and_recency(
    timestamp_str: str | None, threshold_hours: int = 24
) -> tuple[str, bool]:
    """Returns a short human-readable relative string and a boolean flag if within threshold."""
    if not timestamp_str or not timestamp_str.strip():
        return "Unknown", False

    clean_ts = timestamp_str.replace("T", " ").strip()
    try:
        dt = datetime.strptime(clean_ts[:19], "%Y-%m-%d %H:%M:%S").replace(
            tzinfo=timezone.utc
        )
        now = datetime.now(timezone.utc)
        diff = now - dt

        total_seconds = int(diff.total_seconds())
        if total_seconds < 0:
            return "Just now", True

        is_recent = total_seconds < (threshold_hours * 3600)

        if total_seconds < 60:
            return "Just now", is_recent
        if total_seconds < 3600:
            return f"{total_seconds // 60}m ago", is_recent
        if total_seconds < 86400:
            return f"{total_seconds // 3600}h ago", is_recent
        if total_seconds < 604800:
            return f"{total_seconds // 86400}d ago", is_recent

        return clean_ts[:10], is_recent
    except Exception:
        return clean_ts[:16], False


class LayoutStudioPage(QWidget):
    """Unified Layout Editor, Profile Manager, and Pipeline Inspector."""

    title = "Layout Studio"

    def __init__(
        self,
        dispatcher: MapperEventDispatcher | None = None,
        parent: QWidget | None = None,
    ):
        super().__init__(parent)
        self.dispatcher = dispatcher

        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)

        # Main Splitter: Left (Profiles) | Center (Canvas) | Right (Inspector)
        self.splitter = QSplitter(Qt.Orientation.Horizontal)
        self.splitter.setChildrenCollapsible(False)
        main_layout.addWidget(self.splitter)

        self._setup_left_sidebar()
        self._setup_center_canvas()
        self._setup_right_inspector()

        # Responsive default split sizes fitting 1366x768 screens
        self.splitter.setSizes([240, 560, 280])
        self._current_inspected_uid: int | None = None

        self._wire_signals()
        self.load_profiles()

    def _setup_left_sidebar(self) -> None:
        sidebar_widget = QWidget()
        sidebar_widget.setMinimumWidth(200)
        sidebar_layout = QVBoxLayout(sidebar_widget)
        sidebar_layout.setContentsMargins(0, 0, 8, 0)

        profiles_group = QGroupBox("Profiles")
        profiles_layout = QVBoxLayout(profiles_group)

        # Sort Mode Selector
        sort_row = QHBoxLayout()
        sort_row.addWidget(QLabel("Sort:"))
        self.sort_combo = QComboBox()
        self.sort_combo.addItems(
            ["Recently Modified", "Name (A-Z)", "Created (Newest)"]
        )
        sort_row.addWidget(self.sort_combo, stretch=1)
        profiles_layout.addLayout(sort_row)

        # Real-time Search Input
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("Filter profiles... (Ctrl+F)")
        self.search_input.setClearButtonEnabled(True)
        profiles_layout.addWidget(self.search_input)

        self.profile_list = QListWidget()
        profiles_layout.addWidget(self.profile_list)

        self.details_label = QLabel("Select a profile to view details.")
        self.details_label.setStyleSheet(
            "color: palette(placeholder-text); padding: 4px;"
        )
        self.details_label.setWordWrap(True)
        profiles_layout.addWidget(self.details_label)

        # Profile Actions: 2x2 grid prevents pushing sidebar past 240px
        btn_grid_1 = QHBoxLayout()
        self.activate_btn = QPushButton("Set Active")
        self.activate_btn.setStyleSheet("font-weight: bold;")
        self.new_btn = QPushButton("New")
        btn_grid_1.addWidget(self.activate_btn)
        btn_grid_1.addWidget(self.new_btn)
        profiles_layout.addLayout(btn_grid_1)

        btn_grid_2 = QHBoxLayout()
        self.rename_btn = QPushButton("Rename")
        self.duplicate_btn = QPushButton("Duplicate")
        btn_grid_2.addWidget(self.rename_btn)
        btn_grid_2.addWidget(self.duplicate_btn)
        profiles_layout.addLayout(btn_grid_2)

        sidebar_layout.addWidget(profiles_group)

        io_group = QGroupBox("Import & Export")
        io_layout = QVBoxLayout(io_group)
        self.import_btn = QPushButton("Import (.json / .toml / Bundle)")

        export_row = QHBoxLayout()
        self.export_json_btn = QPushButton("JSON")
        self.export_toml_btn = QPushButton("TOML")
        self.export_bundle_btn = QPushButton("Bundle")

        export_row.addWidget(self.export_json_btn)
        export_row.addWidget(self.export_toml_btn)
        export_row.addWidget(self.export_bundle_btn)

        io_layout.addWidget(self.import_btn)
        io_layout.addLayout(export_row)
        sidebar_layout.addWidget(io_group)

        maint_group = QGroupBox("Maintenance")
        maint_layout = QHBoxLayout(maint_group)
        self.clear_zones_btn = QPushButton("Clear Zones")
        self.delete_btn = QPushButton("Delete")
        self.delete_btn.setStyleSheet("color: #d9534f;")

        maint_layout.addWidget(self.clear_zones_btn)
        maint_layout.addWidget(self.delete_btn)
        sidebar_layout.addWidget(maint_group)

        self.splitter.addWidget(sidebar_widget)

    def _setup_center_canvas(self) -> None:
        canvas_widget = QWidget()
        canvas_widget.setMinimumWidth(320)
        canvas_layout = QVBoxLayout(canvas_widget)
        canvas_layout.setContentsMargins(8, 0, 8, 0)

        status_box = QWidget()
        status_layout = QVBoxLayout(status_box)
        status_layout.setContentsMargins(0, 0, 0, 6)
        status_layout.setSpacing(2)

        self.canvas_status_label = QLabel("Initializing...")
        self.canvas_status_label.setStyleSheet(
            "font-size: 13px; font-weight: bold; color: palette(highlight);"
        )

        self.canvas_help_label = QLabel(STATIC_SHORTCUTS_HELP)
        self.canvas_help_label.setStyleSheet("font-size: 11px;")

        status_layout.addWidget(self.canvas_status_label)
        status_layout.addWidget(self.canvas_help_label)
        canvas_layout.addWidget(status_box)

        # Toolbar Row 1: Image management & overlay toggles
        tools_row_1 = QHBoxLayout()
        self.select_image_btn = QPushButton("Select Image")
        self.capture_btn = QPushButton("Capture Screenshot")
        self.toggle_overlays_btn = QPushButton("Toggle Overlays (F4)")

        tools_row_1.addWidget(self.select_image_btn)
        tools_row_1.addWidget(self.capture_btn)
        tools_row_1.addWidget(self.toggle_overlays_btn)
        tools_row_1.addStretch()
        canvas_layout.addLayout(tools_row_1)

        # Toolbar Row 2: Drawing shapes & persistence
        tools_row_2 = QHBoxLayout()
        self.add_circle_btn = QPushButton("Add Circle (F6)")
        self.add_rect_btn = QPushButton("Add Rectangle (F7)")
        self.cancel_action_btn = QPushButton("Cancel (F8)")
        self.save_btn = QPushButton("Save to DB (F12)")
        self.save_btn.setStyleSheet("font-weight: bold; color: palette(highlight);")

        tools_row_2.addWidget(self.add_circle_btn)
        tools_row_2.addWidget(self.add_rect_btn)
        tools_row_2.addWidget(self.cancel_action_btn)
        tools_row_2.addWidget(self.save_btn)
        tools_row_2.addStretch()
        canvas_layout.addLayout(tools_row_2)

        self.plotter_widget = LayoutsPlotterWidget(self, standalone=False)
        canvas_layout.addWidget(self.plotter_widget, stretch=1)

        self.splitter.addWidget(canvas_widget)

    def _setup_right_inspector(self) -> None:
        inspector_widget = QWidget()
        inspector_widget.setMinimumWidth(220)
        inspector_layout = QVBoxLayout(inspector_widget)
        inspector_layout.setContentsMargins(8, 0, 0, 0)

        self.inspector_stack = QStackedWidget()

        # Page 0: Global Layout Settings
        page_layout_settings = QWidget()
        layout_form = QVBoxLayout(page_layout_settings)
        layout_form.setContentsMargins(0, 0, 0, 0)

        lbl_global = QLabel(
            "<b>Layout Settings</b><br><small>Click any shape on the canvas to inspect it.</small>"
        )
        lbl_global.setWordWrap(True)
        layout_form.addWidget(lbl_global)
        layout_form.addSpacing(10)

        bezels_group = QGroupBox("System Bezels")
        bezels_form = QFormLayout(bezels_group)
        self.top_bezel_spin = QDoubleSpinBox()
        self.top_bezel_spin.setRange(2, 100)
        self.top_bezel_spin.setSuffix(" dp")

        self.bottom_bezel_spin = QDoubleSpinBox()
        self.bottom_bezel_spin.setRange(2, 100)
        self.bottom_bezel_spin.setSuffix(" dp")

        bezels_form.addRow("Top Bezel:", self.top_bezel_spin)
        bezels_form.addRow("Bottom Bezel:", self.bottom_bezel_spin)
        layout_form.addWidget(bezels_group)

        actions_group = QGroupBox("Layout Actions")
        actions_vbox = QVBoxLayout(actions_group)
        self.reset_all_zones_btn = QPushButton("Reset All Zones to Defaults")
        actions_vbox.addWidget(self.reset_all_zones_btn)
        layout_form.addWidget(actions_group)
        layout_form.addStretch()

        self.inspector_stack.addWidget(page_layout_settings)

        # Page 1: Zone Pipeline Settings
        page_zone_settings = QWidget()
        zone_layout = QVBoxLayout(page_zone_settings)
        zone_layout.setContentsMargins(0, 0, 0, 0)

        self.insp_name_label = QLabel("<b>Zone: Unset</b>")
        zone_layout.addWidget(self.insp_name_label)

        self.insp_ignore_app_settings = QCheckBox("Ignore Global App Settings")
        zone_layout.addWidget(self.insp_ignore_app_settings)

        region_group = QGroupBox("1. Region")
        region_form = QFormLayout(region_group)
        self.insp_priority = QSpinBox()
        self.insp_priority.setRange(-100, 200)
        region_form.addRow("Priority Value:", self.insp_priority)
        zone_layout.addWidget(region_group)

        transform_group = QGroupBox("4. Transformation")
        transform_form = QFormLayout(transform_group)

        self.insp_sens_x = QDoubleSpinBox()
        self.insp_sens_x.setRange(0.01, 10.0)
        self.insp_sens_x.setSingleStep(0.01)

        self.insp_sens_y = QDoubleSpinBox()
        self.insp_sens_y.setRange(0.01, 10.0)
        self.insp_sens_y.setSingleStep(0.01)

        wrapper = QWidget()
        row = QHBoxLayout(wrapper)
        row.setContentsMargins(0, 0, 0, 0)
        row.addWidget(self.insp_sens_x)
        row.addWidget(self.insp_sens_y)
        transform_form.addRow("Sens (X, Y):", wrapper)

        self.insp_deadzone = QDoubleSpinBox()
        self.insp_deadzone.setRange(0, 1.0)
        self.insp_deadzone.setSingleStep(0.01)

        self.insp_hysteresis = QDoubleSpinBox()
        self.insp_hysteresis.setRange(0, 45)
        self.insp_hysteresis.setSuffix("°")

        transform_form.addRow("Deadzone:", self.insp_deadzone)
        transform_form.addRow("Hysteresis:", self.insp_hysteresis)
        zone_layout.addWidget(transform_group)

        semantic_group = QGroupBox("5. Semantics & Output")
        semantic_form = QFormLayout(semantic_group)
        self.insp_pointer = QCheckBox("Output is Pointer Button")
        semantic_form.addRow("Pointer:", self.insp_pointer)
        zone_layout.addWidget(semantic_group)

        self.insp_reset_zone_btn = QPushButton("Reset Zone to Defaults")
        zone_layout.addWidget(self.insp_reset_zone_btn)

        zone_layout.addStretch()
        self.inspector_stack.addWidget(page_zone_settings)

        inspector_layout.addWidget(self.inspector_stack)
        self.splitter.addWidget(inspector_widget)

    def on_page_shown(self) -> None:
        self.load_profiles()
        self.plotter_widget.reload_active_layout()
        self._load_bezel_thicknesses_to_ui()

    def _wire_signals(self) -> None:
        # Search shortcut & key navigation
        self.search_shortcut = QShortcut(QKeySequence.StandardKey.Find, self)
        self.search_shortcut.activated.connect(self._focus_search)
        self.search_input.returnPressed.connect(self._on_search_return_pressed)
        self.search_input.textChanged.connect(self._filter_profiles)

        # Profile selection & sorting
        self.sort_combo.currentTextChanged.connect(self._on_sort_order_changed)
        self.profile_list.itemSelectionChanged.connect(self._on_selection_changed)
        self.activate_btn.clicked.connect(self._on_set_active)
        self.new_btn.clicked.connect(self._on_new_profile)
        self.rename_btn.clicked.connect(self._on_rename)
        self.duplicate_btn.clicked.connect(self._on_duplicate)

        # Import & Export
        self.import_btn.clicked.connect(self._on_import_clicked)
        self.export_json_btn.clicked.connect(self._on_export_json_clicked)
        self.export_toml_btn.clicked.connect(self._on_export_toml_clicked)
        self.export_bundle_btn.clicked.connect(self._on_export_bundle_clicked)

        # Maintenance
        self.clear_zones_btn.clicked.connect(self._on_clear_zones)
        self.delete_btn.clicked.connect(self._on_delete)

        # Canvas tools
        self.select_image_btn.clicked.connect(self._select_background_image)
        self.capture_btn.clicked.connect(self._trigger_screenshot_capture)
        self.add_circle_btn.clicked.connect(lambda: self._start_draw_mode(CIRCLE, 3))
        self.add_rect_btn.clicked.connect(lambda: self._start_draw_mode(RECTANGLE, 4))
        self.toggle_overlays_btn.clicked.connect(self.plotter_widget.toggle_visibility)
        self.cancel_action_btn.clicked.connect(self.plotter_widget.reset_state)
        self.save_btn.clicked.connect(self._on_save_button_clicked)

        # Plotter canvas bridge
        self.plotter_widget.layout_saved.connect(self._on_layout_saved)
        self.plotter_widget.zone_selected.connect(self._on_canvas_zone_selected)
        self.plotter_widget.status_updated.connect(self.canvas_status_label.setText)

        # Inspector controls
        self.top_bezel_spin.valueChanged.connect(
            lambda v: self._on_bezel_thickness_changed(True, v)
        )
        self.bottom_bezel_spin.valueChanged.connect(
            lambda v: self._on_bezel_thickness_changed(False, v)
        )
        self.reset_all_zones_btn.clicked.connect(self._on_reset_all_zones)

        self.insp_ignore_app_settings.toggled.connect(self._on_inspector_value_changed)
        self.insp_priority.valueChanged.connect(self._on_inspector_value_changed)
        self.insp_sens_x.valueChanged.connect(self._on_inspector_value_changed)
        self.insp_sens_y.valueChanged.connect(self._on_inspector_value_changed)
        self.insp_deadzone.valueChanged.connect(self._on_inspector_value_changed)
        self.insp_hysteresis.valueChanged.connect(self._on_inspector_value_changed)
        self.insp_pointer.toggled.connect(self._on_pointer_toggled)
        self.insp_reset_zone_btn.clicked.connect(self._on_reset_single_zone)

    def _focus_search(self) -> None:
        """Focuses search bar and selects existing text for immediate overwrite."""
        self.search_input.setFocus()
        self.search_input.selectAll()

    def _on_search_return_pressed(self) -> None:
        """Shifts keyboard focus to the profile list upon hitting Enter."""
        current_item = self.profile_list.currentItem()
        if current_item and not current_item.isHidden():
            self.profile_list.setFocus()

    def _on_sort_order_changed(self, sort_mode: str) -> None:
        """Persists selected profile sort mode to the database and re-sorts list."""
        try:
            store.settings.update(profile_sort_order=sort_mode)
            self.load_profiles()
        except Exception as exc:
            logger.exception("Failed to update profile sort order: %s", exc)

    def _sync_sort_combo_from_db(self) -> str:
        """Synchronizes QComboBox with database setting without firing duplicate change signals."""
        try:
            settings = store.settings.get()
            saved_mode = getattr(settings, "profile_sort_order", "Recently Modified")

            idx = self.sort_combo.findText(saved_mode)
            if idx != -1 and self.sort_combo.currentIndex() != idx:
                self.sort_combo.blockSignals(True)
                self.sort_combo.setCurrentIndex(idx)
                self.sort_combo.blockSignals(False)
            return saved_mode
        except Exception:
            return "Recently Modified"

    def _filter_profiles(self, text: str | None = None) -> None:
        """Filters profile list in-place, preserving active selection or defaulting to active layout."""
        query = (self.search_input.text() if text is None else text).strip().lower()

        first_visible_item: QListWidgetItem | None = None
        active_layout_item: QListWidgetItem | None = None
        current_item = self.profile_list.currentItem()
        current_still_visible = False

        active_layout = store.get_active_layout()
        active_id = active_layout.id if active_layout else None

        for index in range(self.profile_list.count()):
            item = self.profile_list.item(index)
            raw_name = item.data(Qt.ItemDataRole.UserRole + 1) or item.text()
            item_layout_id = item.data(Qt.ItemDataRole.UserRole)
            matches = query in raw_name.lower() or query in item.text().lower()

            item.setHidden(not matches)

            if matches:
                if first_visible_item is None:
                    first_visible_item = item
                if item_layout_id == active_id:
                    active_layout_item = item
                if current_item is not None and item == current_item:
                    current_still_visible = True

        if current_still_visible:
            self._on_selection_changed()
        elif bool(query) and first_visible_item is not None:
            self.profile_list.setCurrentItem(first_visible_item)
        elif active_layout_item is not None:
            self.profile_list.setCurrentItem(active_layout_item)
        elif first_visible_item is not None:
            self.profile_list.setCurrentItem(first_visible_item)
        else:
            self.profile_list.clearSelection()
            self._on_selection_changed()

    def load_profiles(self) -> None:
        self.profile_list.clear()
        try:
            layouts = store.layouts.list_all()
            active_layout = store.get_active_layout()
            active_id = active_layout.id if active_layout else None

            sort_mode = self._sync_sort_combo_from_db()
            if sort_mode == "Recently Modified":
                layouts.sort(
                    key=lambda l: l.updated_at or l.created_at or "", reverse=True
                )
            elif sort_mode == "Created (Newest)":
                layouts.sort(key=lambda l: l.created_at or "", reverse=True)
            elif sort_mode == "Name (A-Z)":
                layouts.sort(key=lambda l: l.name.lower())

            for layout in layouts:
                zones = store.zones.list_for_layout(layout.id)
                rel_time, is_recent = _get_relative_time_and_recency(
                    layout.updated_at, threshold_hours=24
                )

                recent_badge = " ●" if is_recent else ""
                display_text = (
                    f"{layout.name}  [{len(zones)} zones]  ({rel_time}){recent_badge}"
                )

                item = QListWidgetItem(display_text)
                item.setData(Qt.ItemDataRole.UserRole, layout.id)
                item.setData(Qt.ItemDataRole.UserRole + 1, layout.name)

                created_str = _format_timestamp(layout.created_at)
                updated_str = _format_timestamp(layout.updated_at)
                item.setToolTip(
                    f"<b>{layout.name}</b><br>"
                    f"Canvas: {layout.width}x{layout.height} ({layout.dpi} DPI)<br>"
                    f"Mapped Zones: {len(zones)}<br>"
                    f"<b>Modified:</b> {updated_str} ({rel_time})<br>"
                    f"<b>Created:</b> {created_str}"
                )

                font = item.font()
                if layout.id == active_id:
                    item.setText(f"★ {display_text} (Active)")
                    font.setBold(True)
                    item.setFont(font)
                elif is_recent:
                    item.setToolTip(
                        item.toolTip() + "<br><i>Recently modified within 24h</i>"
                    )

                self.profile_list.addItem(item)

            self._filter_profiles()
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
            img_info = Path(layout.image_path).name if layout.image_path else "None"

            created_str = _format_timestamp(layout.created_at)
            updated_str = _format_timestamp(layout.updated_at)

            self.details_label.setText(
                f"ID: {layout.id} | Canvas: {layout.width}x{layout.height} ({layout.dpi} DPI)\n"
                f"Zones: {len(zones)} | Image: {img_info}\n"
                f"Modified: {updated_str} (Created: {created_str})"
            )
        except Exception as exc:
            logger.exception("Failed to fetch details for layout ID %s", layout_id)

    def _notify_engine_reload(self) -> None:
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
            self.plotter_widget.reload_active_layout()
            self._load_bezel_thicknesses_to_ui()
            self._notify_engine_reload()
            logger.info("Activated profile ID %s", layout_id)
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
            self.plotter_widget.reload_active_layout()
            self._load_bezel_thicknesses_to_ui()
            self._notify_engine_reload()
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
            self._notify_engine_reload()
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
            try:
                store.zones.delete_all_for_layout(layout_id)
                self.load_profiles()
                active = store.get_active_layout()
                if active and active.id == layout_id:
                    self.plotter_widget.reload_active_layout()
                    self._notify_engine_reload()
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

            store.zones.delete_all_for_layout(layout_id)
            store.layouts.delete(layout_id)

            if is_active:
                store.settings.update(active_layout_id=None)
                self.plotter_widget.reload_active_layout()
                self._notify_engine_reload()

            self.load_profiles()
            logger.info("Deleted profile ID %s", layout_id)
        except Exception as exc:
            logger.exception("Failed to delete profile ID %s", layout_id)
            QMessageBox.critical(
                self, "Database Error", f"Could not delete profile:\n{exc}"
            )

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
                self.plotter_widget.reload_active_layout()
                self._notify_engine_reload()
                logger.info("Imported configuration from '%s'", file_path.name)
                QMessageBox.information(
                    self, "Success", f"Imported '{file_path.stem}' successfully."
                )
            else:
                QMessageBox.warning(
                    self,
                    "Import Failed",
                    f"Could not import {file_path.name}. Check logs.",
                )
        except Exception as exc:
            logger.exception("Unexpected error while importing '%s'", file_path.name)
            QMessageBox.critical(self, "Import Error", f"Failed to import:\n{exc}")

    def _on_export_json_clicked(self) -> None:
        layout_id = self._get_selected_layout_id()
        if layout_id is None:
            return

        layout = store.layouts.get(layout_id)
        if layout is None:
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
                self, "Export Successful", f"Exported layout to:\n{out_file.name}"
            )
        except Exception as exc:
            logger.exception("Failed to export profile JSON")
            QMessageBox.critical(self, "Export Failed", str(exc))

    def _on_export_toml_clicked(self) -> None:
        layout_id = self._get_selected_layout_id()
        if layout_id is None:
            return

        layout = store.layouts.get(layout_id)
        if layout is None:
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
            QMessageBox.critical(self, "Export Failed", str(exc))

    def _on_export_bundle_clicked(self) -> None:
        layout_id = self._get_selected_layout_id()
        if layout_id is None:
            return

        layout = store.layouts.get(layout_id)
        if layout is None:
            return

        PROFILES_FOLDER.mkdir(parents=True, exist_ok=True)
        folder = QFileDialog.getExistingDirectory(
            self,
            "Select Target Folder for Profile Bundle",
            str(PROFILES_FOLDER),
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

    def _start_draw_mode(self, shape_type: str, clicks: int) -> None:
        if store.get_active_layout() is None:
            QMessageBox.warning(
                self,
                "No Active Profile",
                "Please create or select an active profile in the sidebar first.",
            )
            return
        self.plotter_widget.start_mode(shape_type, clicks)

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
            QMessageBox.warning(
                self,
                "No Active Layout",
                "Please select or create an active layout before setting an image.",
            )
            return

        IMAGES_FOLDER.mkdir(parents=True, exist_ok=True)
        file_path_str, _ = QFileDialog.getOpenFileName(
            self,
            "Select Background Image from Folder",
            str(IMAGES_FOLDER),
            "Images (*.png *.jpg *.jpeg *.bmp);;All files (*.*)",
        )
        if not file_path_str:
            return

        img_path = Path(file_path_str)
        # Store clean filename if placed in data/images/ for cross-machine portability
        saved_img_ref = (
            img_path.name
            if img_path.parent.resolve() == IMAGES_FOLDER.resolve()
            else str(img_path.resolve())
        )

        try:
            store.layouts.update(active.id, image_path=saved_img_ref)
            self.load_profiles()
            self.plotter_widget.reload_active_layout()
            self._notify_engine_reload()
            logger.info(
                "Updated active layout ID %s background image to '%s'",
                active.id,
                img_path.name,
            )
        except Exception as exc:
            logger.exception("Failed to update background image")
            QMessageBox.critical(
                self, "Error", f"Failed to set background image:\n{exc}"
            )

    def _trigger_screenshot_capture(self) -> None:
        active = store.get_active_layout()
        if active is None:
            QMessageBox.warning(
                self,
                "No Active Layout",
                "Please select or create an active layout before capturing a screenshot.",
            )
            return

        try:
            capture_android_screen(parent=self)
            self.load_profiles()
            self.plotter_widget.reload_active_layout()
            self._notify_engine_reload()
            logger.info("Screenshot captured and linked to active layout")
            QMessageBox.information(
                self, "Screenshot", "Reference screenshot captured and linked."
            )
        except Exception as exc:
            logger.exception("Screenshot capture failed")
            QMessageBox.critical(self, "Capture Failed", str(exc))

    def _load_bezel_thicknesses_to_ui(self) -> None:
        active = store.get_active_layout()
        if not active:
            return

        self.top_bezel_spin.blockSignals(True)
        self.bottom_bezel_spin.blockSignals(True)

        top_zone = store.zones.get(self.plotter_widget.top_bezel_id)
        if top_zone:
            top_zone.set_parsed_config_from_json()
            _, _, val, _ = top_zone.CONFIG_HELPER.get_region_config()
            self.top_bezel_spin.setValue(val)

        bot_zone = store.zones.get(self.plotter_widget.bottom_bezel_id)
        if bot_zone:
            bot_zone.set_parsed_config_from_json()
            _, _, val, _ = bot_zone.CONFIG_HELPER.get_region_config()
            self.bottom_bezel_spin.setValue(val)

        self.top_bezel_spin.blockSignals(False)
        self.bottom_bezel_spin.blockSignals(False)

    def _on_bezel_thickness_changed(self, is_top: bool, val: float) -> None:
        active = store.get_active_layout()
        if not active:
            return
        bid = (
            self.plotter_widget.top_bezel_id
            if is_top
            else self.plotter_widget.bottom_bezel_id
        )
        if not bid:
            return

        zone = store.zones.get(bid)
        if not zone:
            return

        p_cfg = PipelineConfig()
        p_cfg.set_pipeline_config_from_json(zone.pipeline_json)
        r_idx, r_mode, _, prio = p_cfg.get_region_config()
        p_cfg.set_region_config(r_idx, val, prio)

        store.zones.update(bid, pipeline_json=p_cfg.get_pipeline_json_from_config())
        self.plotter_widget._render_bezels_notch()
        self.plotter_widget.canvas.draw_idle()

    def _on_reset_all_zones(self) -> None:
        active = store.get_active_layout()
        if not active:
            return
        reply = QMessageBox.question(
            self,
            "Reset All Zones",
            f"Reset all zones in layout '{active.name}' to default AppSettings?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply == QMessageBox.StandardButton.Yes:
            count = reset_layout_zones_to_app_settings(active.id)
            self.plotter_widget.reload_active_layout()
            self._notify_engine_reload()
            QMessageBox.information(
                self, "Success", f"Reset {count} zones to default AppSettings."
            )

    def _on_canvas_zone_selected(self, uid: int) -> None:
        if uid == -1 or uid not in self.plotter_widget.shapes:
            self.inspector_stack.setCurrentIndex(0)
            self._current_inspected_uid = None
            self._load_bezel_thicknesses_to_ui()
            return

        self._current_inspected_uid = uid
        self.inspector_stack.setCurrentIndex(1)
        shape_data = self.plotter_widget.shapes[uid]

        self.insp_name_label.setText(f"<b>Zone:</b> {shape_data['bridge_key']}")

        for w in [
            self.insp_ignore_app_settings,
            self.insp_priority,
            self.insp_sens_x,
            self.insp_sens_y,
            self.insp_deadzone,
            self.insp_hysteresis,
            self.insp_pointer,
        ]:
            w.blockSignals(True)

        self.insp_ignore_app_settings.setChecked(
            shape_data.get("ignore_app_settings", False)
        )
        self.insp_priority.setValue(shape_data.get("priority", 0))

        p_cfg = PipelineConfig()
        p_cfg.set_pipeline_config_from_json(shape_data.get("pipeline_json", "{}"))

        _, _, sx, sy, dz, hys = p_cfg.get_transform_config()
        self.insp_sens_x.setValue(sx)
        self.insp_sens_y.setValue(sy)
        self.insp_hysteresis.setValue(hys)

        active = store.get_active_layout()
        r = active.mouse_wheel_radius if active else 50.0
        self.insp_deadzone.setValue(dz / r if r > 0 else 0)

        _, sem_mode, ptr = p_cfg.get_semantic_config()
        self.insp_pointer.setEnabled(sem_mode == "BUTTON")
        self.insp_pointer.setChecked(shape_data.get("pointer", False))

        for w in [
            self.insp_ignore_app_settings,
            self.insp_priority,
            self.insp_sens_x,
            self.insp_sens_y,
            self.insp_deadzone,
            self.insp_hysteresis,
            self.insp_pointer,
        ]:
            w.blockSignals(False)

    def _on_pointer_toggled(self, checked: bool) -> None:
        if not checked or self._current_inspected_uid is None:
            self._on_inspector_value_changed()
            return

        for k, v in self.plotter_widget.shapes.items():
            if k != self._current_inspected_uid and v.get("pointer") is True:
                QMessageBox.warning(
                    self,
                    "Rule Violation",
                    "A look-area pointer already exists.\nYou cannot create a second one.",
                )
                self.insp_pointer.blockSignals(True)
                self.insp_pointer.setChecked(False)
                self.insp_pointer.blockSignals(False)
                return

        self._on_inspector_value_changed()

    def _on_inspector_value_changed(self, *_args: Any) -> None:
        if self._current_inspected_uid is None:
            return
        uid = self._current_inspected_uid
        shape = self.plotter_widget.shapes.get(uid)
        if not shape:
            return

        ign = self.insp_ignore_app_settings.isChecked()
        prio = self.insp_priority.value()
        ptr = self.insp_pointer.isChecked()

        shape["ignore_app_settings"] = ign
        shape["priority"] = prio
        shape["pointer"] = ptr

        p_cfg = PipelineConfig()
        p_cfg.set_pipeline_config_from_json(shape.get("pipeline_json", "{}"))

        r_idx, r_mode, b_dp, _ = p_cfg.get_region_config()
        p_cfg.set_region_config(r_idx, b_dp, prio)

        t_idx, t_mode, _, _, _, _ = p_cfg.get_transform_config()
        active = store.get_active_layout()
        r = active.mouse_wheel_radius if active else 50.0
        p_cfg.set_transform_config(
            t_idx,
            self.insp_sens_x.value(),
            self.insp_sens_y.value(),
            self.insp_deadzone.value() * r,
            self.insp_hysteresis.value(),
        )

        s_idx, s_mode, _ = p_cfg.get_semantic_config()
        p_cfg.set_semantic_config(s_idx, ptr)

        shape["pipeline_json"] = p_cfg.get_pipeline_json_from_config()
        self.plotter_widget.update_title(
            f"INSPECTING: {shape['bridge_key']} (Prio: {prio})", True
        )

    def _on_reset_single_zone(self) -> None:
        if self._current_inspected_uid is None:
            return
        settings = store.settings.get()
        self.insp_ignore_app_settings.setChecked(False)
        self.insp_sens_x.setValue(settings.sensitivity_x)
        self.insp_sens_y.setValue(settings.sensitivity_y)
        self.insp_deadzone.setValue(settings.deadzone)
        self.insp_hysteresis.setValue(settings.hysteresis)
        self._on_inspector_value_changed()

    def save_state(self) -> bool:
        """Persists any active layout, zone edits, and inspector values to the database."""
        try:
            active = store.get_active_layout()
            if active is not None and hasattr(self.plotter_widget, "save_to_database"):
                self.plotter_widget.save_to_database(active.name)
            return True
        except Exception as exc:
            logger.exception("Failed to save Layout Studio state")
            QMessageBox.critical(
                self,
                "Save Error",
                f"Could not save Layout Studio changes:\n\n{exc}",
            )
            return False
