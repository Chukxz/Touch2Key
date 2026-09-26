from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING

from PySide6.QtWidgets import (
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QListWidget,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from modules.database import store
from modules.database.config_io import export_bundle, export_layout_json, import_any
from modules.gui.widgets.layouts_plotter_widget import LayoutsPlotterWidget
from modules.scripts.adb_screen_capture import capture_android_screen
from modules.utils import CIRCLE, JSONS_FOLDER, PROFILES_FOLDER, RECTANGLE, MapperEvent
from .base_page import BasePage

if TYPE_CHECKING:
    from modules.utils import MapperEventDispatcher

logger = logging.getLogger("modules.gui.layout_editor")


class LayoutsEditorPage(BasePage):
    """HUD Layout Editor hosting the visual Plotter canvas and SQLite layout synchronization."""

    title = "Layout editor"

    def __init__(
        self,
        dispatcher: MapperEventDispatcher | None = None,
        parent: QWidget | None = None,
    ):
        super().__init__(dispatcher, parent)

        # Toolbar Row 1: Profile & File Operations
        top_toolbar = QHBoxLayout()
        top_toolbar.setContentsMargins(0, 0, 0, 0)

        self.active_layout_label = QLabel("Active Layout: None")
        self.active_layout_label.setStyleSheet(
            "font-weight: bold; color: palette(highlight);"
        )
        top_toolbar.addWidget(self.active_layout_label)
        top_toolbar.addSpacing(16)

        self.switch_layout_btn = QPushButton("Switch Layout")
        self.import_btn = QPushButton("Import Config / Layout")
        self.export_btn = QPushButton("Export Layout (.json)")
        self.export_bundle_btn = QPushButton("Export Bundle")
        self.capture_btn = QPushButton("Capture Reference Screenshot")

        top_toolbar.addWidget(self.switch_layout_btn)
        top_toolbar.addWidget(self.import_btn)
        top_toolbar.addWidget(self.export_btn)
        top_toolbar.addWidget(self.export_bundle_btn)
        top_toolbar.addWidget(self.capture_btn)
        top_toolbar.addStretch()

        self.content_layout().addLayout(top_toolbar)

        # Toolbar Row 2: Zone Drawing & Priority Controls
        tools_row = QHBoxLayout()
        tools_row.setContentsMargins(0, 0, 0, 0)

        self.priority_spin = QSpinBox()
        self.priority_spin.setRange(-100, 100)
        self.priority_spin.setValue(0)
        self.priority_spin.setPrefix("Priority: ")
        tools_row.addWidget(self.priority_spin)

        self.add_circle_btn = QPushButton("Add Circle (F6)")
        self.add_rect_btn = QPushButton("Add Rectangle (F7)")
        self.toggle_overlays_btn = QPushButton("Toggle Overlays (F4)")
        self.cancel_action_btn = QPushButton("Cancel (F8)")
        self.save_btn = QPushButton("Save to DB (F12)")

        tools_row.addWidget(self.add_circle_btn)
        tools_row.addWidget(self.add_rect_btn)
        tools_row.addWidget(self.toggle_overlays_btn)
        tools_row.addWidget(self.cancel_action_btn)
        tools_row.addWidget(self.save_btn)
        tools_row.addStretch()

        self.content_layout().addLayout(tools_row)

        # Interactive Canvas
        self.plotter_widget = LayoutsPlotterWidget(self, standalone=False)
        self.content_layout().addWidget(self.plotter_widget, stretch=1)

        self._wire_signals()
        self.refresh_active_layout_display()

    def on_page_shown(self) -> None:
        self.refresh_active_layout_display()
        self.plotter_widget.reload_active_layout()

    def _wire_signals(self) -> None:
        self.switch_layout_btn.clicked.connect(self.open_switch_layout_dialog)
        self.import_btn.clicked.connect(self.import_config_or_layout)
        self.export_btn.clicked.connect(self.open_export_dialog)
        self.export_bundle_btn.clicked.connect(self._on_export_bundle)
        self.capture_btn.clicked.connect(self._trigger_screenshot_capture)

        self.priority_spin.valueChanged.connect(self.on_priority_changed)

        self.add_circle_btn.clicked.connect(lambda: self._start_draw_mode(CIRCLE, 3))
        self.add_rect_btn.clicked.connect(lambda: self._start_draw_mode(RECTANGLE, 4))
        self.toggle_overlays_btn.clicked.connect(self.plotter_widget.toggle_visibility)
        self.cancel_action_btn.clicked.connect(self.plotter_widget.reset_state)
        self.save_btn.clicked.connect(self._on_save_button_clicked)

        self.plotter_widget.layout_saved.connect(self._on_layout_saved)
        self.plotter_widget.zone_selected.connect(self._on_zone_selected_on_canvas)

    def _start_draw_mode(self, shape_type: str, clicks: int) -> None:
        active = store.get_active_layout()
        if active is None:
            name, ok = QInputDialog.getText(
                self,
                "New Profile Required",
                "No active profile found. Enter a name to create one:",
            )
            if not ok or not name.strip():
                return
            try:
                settings = store.settings.get()
                new_layout = store.layouts.create(
                    name=name.strip(),
                    width=settings.json_dev_width,
                    height=settings.json_dev_height,
                    dpi=settings.json_dev_dpi,
                )
                store.settings.update(active_layout_id=new_layout.id)
                self.refresh_active_layout_display()
                self.plotter_widget.reload_active_layout()
                self._notify_engine_reload()
                logger.info(
                    "Initialized default profile '%s' (ID: %s) for drawing",
                    new_layout.name,
                    new_layout.id,
                )
            except Exception as exc:
                logger.exception("Failed to initialize profile for drawing")
                QMessageBox.critical(self, "Error", f"Could not create profile:\n{exc}")
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
                self.plotter_widget.update_title(
                    f"Zone ID {entry_id} Priority set to {val}", True
                )

    def _on_save_button_clicked(self) -> None:
        active = store.get_active_layout()
        if active is not None and hasattr(self.plotter_widget, "save_to_database"):
            self.plotter_widget.save_to_database(active.name)
        else:
            self.plotter_widget.enter_naming_mode()

    def _notify_engine_reload(self) -> None:
        if self.dispatcher is not None:
            self.dispatcher.dispatch(MapperEvent(action="ON_LAYOUT_RELOAD"))
            self.dispatcher.dispatch(MapperEvent(action="ON_CONFIG_RELOAD"))

    def refresh_active_layout_display(self) -> None:
        try:
            active_layout = store.get_active_layout()
            if active_layout is not None:
                self.active_layout_label.setText(
                    f"Active Layout: {active_layout.name} (ID: {active_layout.id})"
                )
            else:
                self.active_layout_label.setText("Active Layout: None")
        except Exception as exc:
            logger.exception("Failed to refresh active layout display")

    def _on_layout_saved(self, name: str, layout_id: int) -> None:
        logger.info("Layout '%s' (ID: %s) saved to database", name, layout_id)
        self.refresh_active_layout_display()
        self._notify_engine_reload()
        QMessageBox.information(
            self,
            "Layout Saved",
            f"Layout '{name}' saved successfully (ID: {layout_id}).",
        )

    def open_switch_layout_dialog(self) -> None:
        try:
            all_layouts = store.layouts.list_all()
        except Exception as exc:
            logger.exception("Failed to query layouts for switch dialog")
            QMessageBox.critical(
                self, "Database Error", f"Could not list profiles:\n{exc}"
            )
            return

        if not all_layouts:
            QMessageBox.information(
                self, "No Layouts", "No layouts found in the database."
            )
            return

        dialog = QDialog(self)
        dialog.setWindowTitle("Select Active Layout")
        dialog.resize(320, 260)
        dialog_layout = QVBoxLayout(dialog)

        dialog_layout.addWidget(QLabel("Select a layout to set as active:"))
        layout_list = QListWidget()
        active = store.get_active_layout()
        selected_row = 0

        for idx, l in enumerate(all_layouts):
            layout_list.addItem(l.name)
            if active and l.id == active.id:
                selected_row = idx

        layout_list.setCurrentRow(selected_row)
        dialog_layout.addWidget(layout_list)

        btn_row = QHBoxLayout()
        select_btn = QPushButton("Select")
        cancel_btn = QPushButton("Cancel")
        btn_row.addStretch()
        btn_row.addWidget(select_btn)
        btn_row.addWidget(cancel_btn)
        dialog_layout.addLayout(btn_row)

        def on_select() -> None:
            selected_items = layout_list.selectedItems()
            if not selected_items:
                return
            target_name = selected_items[0].text()
            target_layout = next(l for l in all_layouts if l.name == target_name)

            try:
                store.settings.update(active_layout_id=target_layout.id)
                self.refresh_active_layout_display()
                self.plotter_widget.reload_active_layout()
                self._notify_engine_reload()
                logger.info(
                    "Switched active layout to '%s' (ID: %s)",
                    target_layout.name,
                    target_layout.id,
                )
                dialog.accept()
            except Exception as exc:
                logger.exception("Failed to switch active layout to '%s'", target_name)
                QMessageBox.critical(
                    dialog, "Error", f"Failed to switch layout:\n{exc}"
                )

        select_btn.clicked.connect(on_select)
        cancel_btn.clicked.connect(dialog.reject)
        dialog.exec()

    def import_config_or_layout(self) -> None:
        JSONS_FOLDER.mkdir(parents=True, exist_ok=True)
        file_path_str, _ = QFileDialog.getOpenFileName(
            self,
            "Select Layout (.json) or Config (.toml) to Import",
            str(JSONS_FOLDER),
            "Configurations (*.json *.toml);;JSON Layouts (*.json);;TOML Configs (*.toml);;All files (*.*)",
        )
        if not file_path_str:
            return

        file_path = Path(file_path_str)
        try:
            if import_any(file_path):
                self.refresh_active_layout_display()
                self.plotter_widget.reload_active_layout()
                self._notify_engine_reload()
                logger.info("Imported configuration from '%s'", file_path.name)
                QMessageBox.information(
                    self,
                    "Success",
                    f"Imported '{file_path.stem}' successfully and updated active state.",
                )
            else:
                logger.warning("Failed to import '%s': format invalid", file_path.name)
                QMessageBox.critical(
                    self,
                    "Error",
                    f"Failed to import {file_path.name}. Check log console for details.",
                )
        except Exception as exc:
            logger.exception("Unexpected error while importing '%s'", file_path.name)
            QMessageBox.critical(self, "Import Error", f"Failed to import:\n{exc}")

    def open_export_dialog(self) -> None:
        try:
            all_layouts = store.layouts.list_all()
        except Exception as exc:
            logger.exception("Failed to retrieve layouts for export")
            QMessageBox.critical(
                self, "Database Error", f"Could not list profiles:\n{exc}"
            )
            return

        if not all_layouts:
            QMessageBox.information(
                self, "Empty", "No layouts found in database to export."
            )
            return

        dialog = QDialog(self)
        dialog.setWindowTitle("Export Layout")
        dialog.resize(320, 260)
        dialog_layout = QVBoxLayout(dialog)

        dialog_layout.addWidget(QLabel("Select layout to export:"))
        layout_list = QListWidget()
        active = store.get_active_layout()
        selected_row = 0

        for idx, l in enumerate(all_layouts):
            layout_list.addItem(l.name)
            if active and l.id == active.id:
                selected_row = idx

        layout_list.setCurrentRow(selected_row)
        dialog_layout.addWidget(layout_list)

        btn_row = QHBoxLayout()
        export_btn = QPushButton("Save As...")
        cancel_btn = QPushButton("Cancel")
        btn_row.addStretch()
        btn_row.addWidget(export_btn)
        btn_row.addWidget(cancel_btn)
        dialog_layout.addLayout(btn_row)

        def on_export_confirm() -> None:
            selected_items = layout_list.selectedItems()
            if not selected_items:
                QMessageBox.warning(
                    dialog, "Selection Required", "Please select a layout to export."
                )
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

        try:
            out_file = export_layout_json(layout.id, Path(save_path_str))
            logger.info(
                "Exported layout ID %s ('%s') to '%s'", layout.id, layout.name, out_file
            )
            QMessageBox.information(
                self,
                "Success",
                f"Layout exported successfully to:\n{out_file.name}",
            )
        except Exception as exc:
            logger.exception(
                "Layout export failed for ID %s ('%s')", layout.id, layout.name
            )
            QMessageBox.critical(self, "Export Failed", str(exc))

    def _on_export_bundle(self) -> None:
        PROFILES_FOLDER.mkdir(parents=True, exist_ok=True)
        folder = QFileDialog.getExistingDirectory(
            self, "Select Destination Folder for Profile Bundle", str(PROFILES_FOLDER)
        )
        if not folder:
            return

        try:
            t_file, j_file = export_bundle(Path(folder))
            logger.info("Exported bundle to %s", folder)
            QMessageBox.information(
                self,
                "Bundle Exported",
                f"Exported configuration bundle:\n- {t_file.name}\n- {j_file.name}",
            )
        except Exception as exc:
            logger.exception("Bundle export failed")
            QMessageBox.critical(self, "Export Failed", str(exc))

    def _trigger_screenshot_capture(self) -> None:
        try:
            capture_android_screen(parent=self)
            self.refresh_active_layout_display()
            self.plotter_widget.reload_active_layout()
            self._notify_engine_reload()
            logger.info("Screenshot captured and linked to active layout")
            QMessageBox.information(
                self, "Screenshot", "Reference screenshot captured and linked."
            )
        except Exception as exc:
            logger.exception("Screenshot capture failed")
            QMessageBox.critical(self, "Capture Failed", str(exc))
