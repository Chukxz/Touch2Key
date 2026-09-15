from __future__ import annotations

import json
import logging
from pathlib import Path

import tomlkit
from PySide6.QtWidgets import (
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
    QSpinBox,
)

from modules.database import store
from modules.database.legacy_migration import migrate_json_to_layout
from modules.gui.widgets.layout_plotter_widget import LayoutPlotterWidget
from modules.utils import CIRCLE, RECTANGLE, JSONS_FOLDER, TOML_PATH
from .base_page import BasePage

logger = logging.getLogger("modules.gui.layout_editor")


class LayoutEditorPage(BasePage):
    """Integrated HUD Layout Editor hosting the interactive Plotter canvas,
    profile switcher, zone drawing controls, and import/export flows.
    """

    title = "Layout editor"

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)

        # Toolbar Row 1: Profile & File Operations
        top_toolbar = QHBoxLayout()
        top_toolbar.setContentsMargins(0, 0, 0, 0)

        self.active_layout_label = QLabel("Active Layout: None")
        self.active_layout_label.setStyleSheet("font-weight: bold; color: palette(highlight);")
        top_toolbar.addWidget(self.active_layout_label)
        top_toolbar.addSpacing(16)

        self.switch_layout_btn = QPushButton("Switch Layout")
        self.import_btn = QPushButton("Import (.json)")
        self.export_btn = QPushButton("Export (.json)")
        self.capture_btn = QPushButton("Capture Reference Screenshot")

        top_toolbar.addWidget(self.switch_layout_btn)
        top_toolbar.addWidget(self.import_btn)
        top_toolbar.addWidget(self.export_btn)
        top_toolbar.addWidget(self.capture_btn)
        top_toolbar.addStretch()

        self.content_layout().addLayout(top_toolbar)

        # Toolbar Row 2: Zone Drawing & Editing Controls
        tools_row = QHBoxLayout()
        tools_row.setContentsMargins(0, 0, 0, 0)

        self.add_circle_btn = QPushButton("Add Circle (F6)")
        self.add_rect_btn = QPushButton("Add Rectangle (F7)")
        self.toggle_overlays_btn = QPushButton("Toggle Overlays (F4)")
        self.cancel_action_btn = QPushButton("Cancel (F8)")
        self.save_btn = QPushButton("Save to DB (F12)")
        
        self.priority_spin = QSpinBox()
        self.priority_spin.setRange(-100, 100)
        self.priority_spin.setValue(0)
        self.priority_spin.setPrefix("Priority: ")

        self.priority_spin.valueChanged.connect(self.on_priority_changed)
        tools_row.addWidget(self.priority_spin)

        tools_row.addWidget(self.add_circle_btn)
        tools_row.addWidget(self.add_rect_btn)
        tools_row.addWidget(self.toggle_overlays_btn)
        tools_row.addWidget(self.cancel_action_btn)
        tools_row.addWidget(self.save_btn)
        tools_row.addStretch()

        self.content_layout().addLayout(tools_row)

        # Embedded Interactive Canvas Widget
        self.plotter_widget = LayoutPlotterWidget(self)
        self.content_layout().addWidget(self.plotter_widget, stretch=1)

        self._wire_signals()
        self.refresh_active_layout_display()

    def on_priority_changed(self, val: int):
        if self.plotter_widget.current_draggable:
            entry_id = self.plotter_widget.current_draggable.entry_id
            self.plotter_widget.shapes[entry_id]["priority"] = val
            self.plotter_widget.update_title(f"Zone ID {entry_id} Priority set to {val}", True)

    def _wire_signals(self) -> None:
        self.switch_layout_btn.clicked.connect(self.open_switch_layout_dialog)
        self.import_btn.clicked.connect(self.import_layout)
        self.export_btn.clicked.connect(self.open_export_dialog)
        self.capture_btn.clicked.connect(self._trigger_screenshot_capture)

        self.add_circle_btn.clicked.connect(lambda: self.plotter_widget.start_mode(CIRCLE, 3))
        self.add_rect_btn.clicked.connect(lambda: self.plotter_widget.start_mode(RECTANGLE, 4))
        self.toggle_overlays_btn.clicked.connect(self.plotter_widget.toggle_visibility)
        self.cancel_action_btn.clicked.connect(self.plotter_widget.reset_state)
        self.save_btn.clicked.connect(self.plotter_widget.enter_naming_mode)

        self.plotter_widget.layout_saved.connect(self._on_layout_saved)

    def refresh_active_layout_display(self) -> None:
        active_layout = store.get_active_layout()
        if active_layout is not None:
            self.active_layout_label.setText(f"Active Layout: {active_layout.name} (ID: {active_layout.id})")
        else:
            self.active_layout_label.setText("Active Layout: None")

    def _on_layout_saved(self, name: str, layout_id: int) -> None:
        self.refresh_active_layout_display()
        QMessageBox.information(self, "Layout Saved", f"Layout '{name}' saved successfully (ID: {layout_id}).")

    def open_switch_layout_dialog(self) -> None:
        all_layouts = store.layouts.list_all()
        if not all_layouts:
            QMessageBox.information(self, "No Layouts", "No layouts found in the database.")
            return

        dialog = QDialog(self)
        dialog.setWindowTitle("Select Active Layout")
        dialog.resize(320, 260)
        dialog_layout = QVBoxLayout(dialog)

        dialog_layout.addWidget(QLabel("Select a layout to set as active:"))
        layout_list = QListWidget()
        for l in all_layouts:
            layout_list.addItem(l.name)
        dialog_layout.addWidget(layout_list)

        btn_row = QHBoxLayout()
        select_btn = QPushButton("Select")
        cancel_btn = QPushButton("Cancel")
        btn_row.addStretch()
        btn_row.addWidget(select_btn)
        btn_row.addWidget(cancel_btn)
        dialog_layout.addLayout(btn_row)

        def on_select():
            selected_items = layout_list.selectedItems()
            if not selected_items:
                return
            target_name = selected_items[0].text()
            target_layout = next(l for l in all_layouts if l.name == target_name)
            store.set_active_layout(target_layout.id)
            self.refresh_active_layout_display()
            self.plotter_widget.reload_active_layout()
            dialog.accept()

        select_btn.clicked.connect(on_select)
        cancel_btn.clicked.connect(dialog.reject)
        dialog.exec()

    def import_layout(self) -> None:
        JSONS_FOLDER.mkdir(parents=True, exist_ok=True)
        file_path_str, _ = QFileDialog.getOpenFileName(
            self,
            "Select JSON Mapping Profile to Import",
            str(JSONS_FOLDER),
            "JSON files (*.json);;All files (*.*)",
        )
        if not file_path_str:
            return

        file_path = Path(file_path_str)
        if not file_path.exists():
            QMessageBox.critical(self, "Error", f"File '{file_path.name}' not found.")
            return

        image_to_assign = ""
        if TOML_PATH.exists():
            try:
                with open(TOML_PATH, "r", encoding="utf-8") as f:
                    doc = tomlkit.load(f)
                legacy_json_str = doc.get("system", {}).get("json_path")
                if legacy_json_str and Path(legacy_json_str).resolve() == file_path.resolve():
                    image_to_assign = doc.get("system", {}).get("image_path", "")
            except Exception as e:
                logger.warning("Could not parse legacy TOML for image path: %s", e)

        layout_id = migrate_json_layout(
            json_path=file_path,
            image_path=image_to_assign,
            set_active=True,
        )

        if layout_id is not None:
            try:
                file_path.unlink()
            except OSError:
                pass
            self.refresh_active_layout_display()
            self.plotter_widget.reload_active_layout()
            QMessageBox.information(
                self,
                "Success",
                f"Imported '{file_path.stem}' successfully!\nIt is now set as the active layout.",
            )
        else:
            QMessageBox.critical(
                self,
                "Error",
                f"Failed to import {file_path.name}. Check log console for details.",
            )

    def open_export_dialog(self) -> None:
        all_layouts = store.layouts.list_all()
        if not all_layouts:
            QMessageBox.information(self, "Empty", "No layouts found in database to export.")
            return

        dialog = QDialog(self)
        dialog.setWindowTitle("Export Layout")
        dialog.resize(320, 260)
        dialog_layout = QVBoxLayout(dialog)

        dialog_layout.addWidget(QLabel("Select layout to export:"))
        layout_list = QListWidget()
        for l in all_layouts:
            layout_list.addItem(l.name)
        dialog_layout.addWidget(layout_list)

        btn_row = QHBoxLayout()
        export_btn = QPushButton("Save As...")
        cancel_btn = QPushButton("Cancel")
        btn_row.addStretch()
        btn_row.addWidget(export_btn)
        btn_row.addWidget(cancel_btn)
        dialog_layout.addLayout(btn_row)

        def on_export_confirm():
            selected_items = layout_list.selectedItems()
            if not selected_items:
                return
            target_name = selected_items[0].text()
            target_layout = next(l for l in all_layouts if l.name == target_name)
            self.execute_export(target_layout)
            dialog.accept()

        export_btn.clicked.connect(on_export_confirm)
        cancel_btn.clicked.connect(dialog.reject)
        dialog.exec()

    def execute_export(self, layout) -> None:
        JSONS_FOLDER.mkdir(parents=True, exist_ok=True)
        default_save_path = str(JSONS_FOLDER / f"{layout.name}.json")

        save_path_str, _ = QFileDialog.getSaveFileName(
            self,
            "Save Layout As",
            default_save_path,
            "JSON files (*.json);;All files (*.*)",
        )
        if not save_path_str:
            return

        zones = store.zones.list_for_layout(layout.id)
        output_content = []

        for zone in zones:
            entry = {
                "name": zone.name,
                "scancode": zone.scancode,
                "type": zone.zone_type,
                "cx": zone.cx or 0.0,
                "cy": zone.cy or 0.0,
                "val1": zone.r if zone.zone_type == CIRCLE else (zone.x1 or 0.0),
                "val2": zone.y1 or 0.0,
                "val3": zone.x2 or 0.0,
                "val4": zone.y2 or 0.0,
                "move_camera": bool(zone.move_camera),
            }
            output_content.append(entry)

        json_data = {
            "metadata": {
                "width": layout.width,
                "height": layout.height,
                "dpi": layout.dpi,
                "mouse_wheel_radius": layout.mouse_wheel_radius,
                "sprint_distance": layout.sprint_distance,
            },
            "content": output_content,
        }

        try:
            with open(save_path_str, "w", encoding="utf-8") as f:
                json.dump(json_data, f, indent=4)
            QMessageBox.information(
                self,
                "Success",
                f"Layout exported successfully to:\n{Path(save_path_str).name}",
            )
        except Exception as e:
            QMessageBox.critical(self, "Export Failed", str(e))

    def _trigger_screenshot_capture(self) -> None:
        try:
            from modules.scripts.adb_screen_capture import _capture_android_screen
            _capture_android_screen()
            self.refresh_active_layout_display()
            self.plotter_widget.reload_active_layout()
            QMessageBox.information(self, "Screenshot", "Reference screenshot captured and linked.")
        except Exception as exc:
            logger.exception("Screenshot capture failed")
            QMessageBox.critical(self, "Capture Failed", str(exc))