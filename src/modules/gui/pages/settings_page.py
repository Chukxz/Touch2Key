from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING

from PySide6.QtWidgets import (
    QCheckBox,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from modules.database import store
from modules.database.config_io import (
    export_bundle,
    export_settings_toml,
    import_any,
)
from modules.utils import MapperEvent, TOML_PATH
from .base_page import BasePage

if TYPE_CHECKING:
    from modules.utils import MapperEventDispatcher

logger = logging.getLogger("modules.gui.settings_page")


class SettingsPage(BasePage):
    """General settings page covering input tuning, performance, hotkeys, and data reset."""

    title = "Settings"

    def __init__(
        self,
        dispatcher: MapperEventDispatcher | None = None,
        parent: QWidget | None = None,
    ):
        super().__init__(dispatcher, parent)

        # -------------------------------------------------------------------
        # 1. Input & Controls Group
        # -------------------------------------------------------------------
        input_group = QGroupBox("Touch & Input Controls")
        input_form = QFormLayout(input_group)

        self.left_handed_check = QCheckBox("Left-handed mode")
        input_form.addRow(self.left_handed_check)

        self.anchored_floating_check = QCheckBox("Anchored Floating Joystick")
        self.anchored_floating_check.setToolTip(
            "Locks touches near center to the anchor, floats dynamically elsewhere."
        )
        input_form.addRow(self.anchored_floating_check)

        self.snap_radius_spin = QDoubleSpinBox()
        self.snap_radius_spin.setRange(10.0, 500.0)
        self.snap_radius_spin.setSingleStep(5.0)
        self.snap_radius_spin.setSuffix(" px")
        input_form.addRow("Joystick Snap Radius:", self.snap_radius_spin)

        self.sensitivity_spin = QDoubleSpinBox()
        self.sensitivity_spin.setRange(0.1, 10.0)
        self.sensitivity_spin.setSingleStep(0.1)
        input_form.addRow("Sensitivity:", self.sensitivity_spin)

        self.deadzone_spin = QDoubleSpinBox()
        self.deadzone_spin.setRange(0.0, 1.0)
        self.deadzone_spin.setSingleStep(0.01)
        input_form.addRow("Deadzone:", self.deadzone_spin)

        self.content_layout().addWidget(input_group)

        # -------------------------------------------------------------------
        # 2. Performance & ADB Engine Group
        # -------------------------------------------------------------------
        perf_group = QGroupBox("Performance & Pipeline")
        perf_form = QFormLayout(perf_group)

        self.rate_cap_spin = QDoubleSpinBox()
        self.rate_cap_spin.setRange(30.0, 1000.0)
        self.rate_cap_spin.setSingleStep(10.0)
        self.rate_cap_spin.setSuffix(" Hz")
        perf_form.addRow("ADB Rate Cap:", self.rate_cap_spin)

        self.pps_alert_spin = QDoubleSpinBox()
        self.pps_alert_spin.setRange(10.0, 500.0)
        self.pps_alert_spin.setSingleStep(5.0)
        self.pps_alert_spin.setSuffix(" PPS")
        perf_form.addRow("PPS Alert Threshold:", self.pps_alert_spin)

        self.content_layout().addWidget(perf_group)

        # -------------------------------------------------------------------
        # 3. Keybinds Group
        # -------------------------------------------------------------------
        keys_group = QGroupBox("Hotkeys")
        keys_form = QFormLayout(keys_group)

        self.toggle_key_input = QLineEdit()
        self.toggle_key_input.setPlaceholderText("e.g. F1, grave, etc.")
        keys_form.addRow("Mapping Toggle Key:", self.toggle_key_input)

        self.sprint_key_input = QLineEdit()
        self.sprint_key_input.setPlaceholderText("e.g. shift")
        keys_form.addRow("Sprint Key:", self.sprint_key_input)

        self.content_layout().addWidget(keys_group)

        # -------------------------------------------------------------------
        # 4. Import / Export / Backup
        # -------------------------------------------------------------------
        io_row = QHBoxLayout()
        self.export_toml_btn = QPushButton("Export settings.toml")
        self.import_toml_btn = QPushButton("Import Config (.toml / .json)")
        self.export_bundle_btn = QPushButton("Export Full Bundle")

        io_row.addWidget(self.export_toml_btn)
        io_row.addWidget(self.import_toml_btn)
        io_row.addWidget(self.export_bundle_btn)
        self.content_layout().addLayout(io_row)

        # -------------------------------------------------------------------
        # 5. Database Reset Actions
        # -------------------------------------------------------------------
        reset_row = QHBoxLayout()
        self.reset_defaults_btn = QPushButton("Reset Settings to Defaults")
        self.delete_all_btn = QPushButton("Wipe Database (Factory Reset)")
        self.delete_all_btn.setStyleSheet("color: #d9534f;")

        reset_row.addWidget(self.reset_defaults_btn)
        reset_row.addWidget(self.delete_all_btn)
        self.content_layout().addLayout(reset_row)

        self.content_layout().addStretch()

        self._wire_signals()
        self.load_settings()

    def _wire_signals(self) -> None:
        self.left_handed_check.toggled.connect(self._on_left_handed_changed)
        self.anchored_floating_check.toggled.connect(self._on_anchored_floating_changed)
        self.snap_radius_spin.valueChanged.connect(self._on_snap_radius_changed)
        self.sensitivity_spin.valueChanged.connect(self._on_sensitivity_changed)
        self.deadzone_spin.valueChanged.connect(self._on_deadzone_changed)

        self.rate_cap_spin.valueChanged.connect(self._on_rate_cap_changed)
        self.pps_alert_spin.valueChanged.connect(self._on_pps_alert_changed)

        self.toggle_key_input.editingFinished.connect(self._on_keys_changed)
        self.sprint_key_input.editingFinished.connect(self._on_keys_changed)

        self.export_toml_btn.clicked.connect(self._on_export_toml)
        self.import_toml_btn.clicked.connect(self._on_import_toml)
        self.export_bundle_btn.clicked.connect(self._on_export_bundle)

        self.reset_defaults_btn.clicked.connect(self._on_reset_defaults)
        self.delete_all_btn.clicked.connect(self._on_delete_all)

    def on_page_shown(self) -> None:
        self.load_settings()

    def _notify_reload(self) -> None:
        if self.dispatcher:
            self.dispatcher.dispatch(MapperEvent(action="ON_CONFIG_RELOAD"))

    def load_settings(self) -> None:
        try:
            settings = store.settings.get()

            self.left_handed_check.blockSignals(True)
            self.anchored_floating_check.blockSignals(True)
            self.snap_radius_spin.blockSignals(True)
            self.sensitivity_spin.blockSignals(True)
            self.deadzone_spin.blockSignals(True)
            self.rate_cap_spin.blockSignals(True)
            self.pps_alert_spin.blockSignals(True)
            self.toggle_key_input.blockSignals(True)
            self.sprint_key_input.blockSignals(True)

            self.left_handed_check.setChecked(bool(settings.left_handed))
            self.anchored_floating_check.setChecked(bool(settings.anchored_floating_joystick))
            self.snap_radius_spin.setValue(settings.joystick_snap_radius)
            self.snap_radius_spin.setEnabled(bool(settings.anchored_floating_joystick))
            self.sensitivity_spin.setValue(settings.sensitivity)
            self.deadzone_spin.setValue(settings.deadzone)

            self.rate_cap_spin.setValue(settings.adb_rate_cap)
            self.pps_alert_spin.setValue(settings.pps_alert_threshold)

            self.toggle_key_input.setText(settings.toggle_key or "")
            self.sprint_key_input.setText(settings.sprint_key or "")

            self.left_handed_check.blockSignals(False)
            self.anchored_floating_check.blockSignals(False)
            self.snap_radius_spin.blockSignals(False)
            self.sensitivity_spin.blockSignals(False)
            self.deadzone_spin.blockSignals(False)
            self.rate_cap_spin.blockSignals(False)
            self.pps_alert_spin.blockSignals(False)
            self.toggle_key_input.blockSignals(False)
            self.sprint_key_input.blockSignals(False)
        except Exception as exc:
            logger.exception("Failed to load settings from database")

    def _on_left_handed_changed(self, checked: bool) -> None:
        try:
            store.settings.update(left_handed=int(checked))
            self._notify_reload()
        except Exception as exc:
            logger.exception("Failed to update left_handed setting")

    def _on_anchored_floating_changed(self, checked: bool) -> None:
        try:
            self.snap_radius_spin.setEnabled(checked)
            store.settings.update(anchored_floating_joystick=int(checked))
            self._notify_reload()
        except Exception as exc:
            logger.exception("Failed to update anchored_floating_joystick setting")

    def _on_snap_radius_changed(self, value: float) -> None:
        try:
            store.settings.update(joystick_snap_radius=value)
            self._notify_reload()
        except Exception as exc:
            logger.exception("Failed to update joystick_snap_radius setting")

    def _on_sensitivity_changed(self, value: float) -> None:
        try:
            store.settings.update(sensitivity=value)
            self._notify_reload()
        except Exception as exc:
            logger.exception("Failed to update sensitivity setting")

    def _on_deadzone_changed(self, value: float) -> None:
        try:
            store.settings.update(deadzone=value)
            self._notify_reload()
        except Exception as exc:
            logger.exception("Failed to update deadzone setting")

    def _on_rate_cap_changed(self, value: float) -> None:
        try:
            store.settings.update(adb_rate_cap=value)
            self._notify_reload()
        except Exception as exc:
            logger.exception("Failed to update adb_rate_cap setting")

    def _on_pps_alert_changed(self, value: float) -> None:
        try:
            store.settings.update(pps_alert_threshold=value)
            self._notify_reload()
        except Exception as exc:
            logger.exception("Failed to update pps_alert_threshold setting")

    def _on_keys_changed(self) -> None:
        try:
            store.settings.update(
                toggle_key=self.toggle_key_input.text().strip(),
                sprint_key=self.sprint_key_input.text().strip(),
            )
            self._notify_reload()
        except Exception as exc:
            logger.exception("Failed to update hotkey settings")

    def _on_reset_defaults(self) -> None:
        reply = QMessageBox.question(
            self,
            "Reset Settings",
            "Reset all tuning knobs and configurations to defaults?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply == QMessageBox.StandardButton.Yes:
            try:
                store.settings.reset_to_defaults()
                self.load_settings()
                self._notify_reload()
                logger.info("Application settings reset to defaults")
                QMessageBox.information(self, "Reset", "Settings reset to defaults.")
            except Exception as exc:
                logger.exception("Failed to reset settings to defaults")
                QMessageBox.critical(self, "Error", f"Failed to reset settings:\n{exc}")

    def _on_delete_all(self) -> None:
        reply = QMessageBox.warning(
            self,
            "Wipe Database",
            "Are you sure you want to delete ALL layouts and reset all settings?\nThis cannot be undone.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply == QMessageBox.StandardButton.Yes:
            try:
                for layout in store.layouts.list_all():
                    store.layouts.delete(layout.id)

                store.settings.reset_to_defaults()
                store.settings.update(active_layout_id=None)

                self.load_settings()
                self._notify_reload()
                if self.dispatcher:
                    self.dispatcher.dispatch(MapperEvent(action="ON_LAYOUT_RELOAD"))

                logger.info("Database wiped and reset to factory defaults")
                QMessageBox.information(self, "Wiped", "All layouts and settings cleared.")
            except Exception as exc:
                logger.exception("Failed to wipe database")
                QMessageBox.critical(self, "Error", f"Failed to wipe database:\n{exc}")

    def _on_export_toml(self) -> None:
        path_str, _ = QFileDialog.getSaveFileName(
            self,
            "Export Settings",
            str(TOML_PATH),
            "TOML files (*.toml);;All files (*.*)",
        )
        if not path_str:
            return

        try:
            out_path = export_settings_toml(Path(path_str))
            logger.info("Exported settings TOML to '%s'", out_path)
            QMessageBox.information(
                self,
                "Exported",
                f"Settings exported successfully to:\n{out_path.name}",
            )
        except Exception as exc:
            logger.exception("Failed to export settings TOML")
            QMessageBox.critical(self, "Export Error", str(exc))

    def _on_import_toml(self) -> None:
        path_str, _ = QFileDialog.getOpenFileName(
            self,
            "Import Settings or Bundle",
            str(TOML_PATH.parent),
            "Config files (*.toml *.json);;All files (*.*)",
        )
        if not path_str:
            return

        try:
            if import_any(Path(path_str)):
                self.load_settings()
                self._notify_reload()
                if self.dispatcher:
                    self.dispatcher.dispatch(MapperEvent(action="ON_LAYOUT_RELOAD"))
                logger.info("Imported configuration from '%s'", path_str)
                QMessageBox.information(
                    self,
                    "Imported",
                    "Configuration imported and synced to database.",
                )
            else:
                logger.warning("Could not parse or apply settings from '%s'", path_str)
                QMessageBox.warning(
                    self,
                    "Import Failed",
                    "Could not parse or apply settings from file.",
                )
        except Exception as exc:
            logger.exception("Unexpected error importing '%s'", path_str)
            QMessageBox.critical(self, "Import Error", f"Failed to import file:\n{exc}")

    def _on_export_bundle(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, "Select Target Folder for Bundle")
        if not folder:
            return

        try:
            t_file, j_file = export_bundle(Path(folder))
            logger.info("Exported configuration bundle: '%s', '%s'", t_file.name, j_file.name)
            QMessageBox.information(
                self,
                "Bundle Exported",
                f"Exported configuration bundle:\n- {t_file.name}\n- {j_file.name}",
            )
        except Exception as exc:
            logger.exception("Bundle export failed")
            QMessageBox.critical(self, "Bundle Export Failed", str(exc))
