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
    QMessageBox,
    QPushButton,
    QWidget,
    QVBoxLayout,
)

from modules.database import store
from modules.database.config_io import (
    export_bundle,
    export_settings_toml,
    import_any,
)
from modules.utils import MapperEvent, PROFILES_FOLDER, TOML_PATH
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

        # 1. Input & Controls Group
        input_group = QGroupBox("Touch & Input Controls")
        input_layout = QVBoxLayout(input_group)

        self.left_handed_check = QCheckBox("Left-handed mode")
        input_layout.addWidget(self.left_handed_check)

        self.floating_check = QCheckBox("Floating Joystick")
        self.floating_check.setToolTip("Floats dynamically, is overridden by anchored.")
        input_layout.addWidget(self.floating_check)

        self.anchored_check = QCheckBox("Anchored Joystick")
        self.anchored_check.setToolTip(
            "Locks touches near center to the anchor, floats dynamically elsewhere. Overrides floating."
        )
        input_layout.addWidget(self.anchored_check)

        # Form layout specifically for the tuning spinboxes
        input_form = QFormLayout()

        self.sensitivity_spin_x = QDoubleSpinBox()
        self.sensitivity_spin_x.setRange(0.1, 10.0)
        self.sensitivity_spin_x.setSingleStep(0.1)
        input_form.addRow("Sensitivity X:", self.sensitivity_spin_x)

        self.sensitivity_spin_y = QDoubleSpinBox()
        self.sensitivity_spin_y.setRange(0.1, 10.0)
        self.sensitivity_spin_y.setSingleStep(0.1)
        input_form.addRow("Sensitivity Y:", self.sensitivity_spin_y)

        self.deadzone_spin = QDoubleSpinBox()
        self.deadzone_spin.setRange(0.0, 1.0)
        self.deadzone_spin.setSingleStep(0.01)
        input_form.addRow("Deadzone:", self.deadzone_spin)

        self.hysteresis_spin = QDoubleSpinBox()
        self.hysteresis_spin.setRange(0.0, 45.0)
        self.hysteresis_spin.setSingleStep(1.0)
        self.hysteresis_spin.setSuffix("°")
        input_form.addRow("Hysteresis:", self.hysteresis_spin)

        input_layout.addLayout(input_form)

        self.content_layout().addWidget(input_group)

        # 2. Performance & ADB Engine Group
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

        # 3. Typematic Group
        typematic_group = QGroupBox("Typematic")
        typematic_form = QFormLayout(typematic_group)

        self.typematic_enabled_check = QCheckBox("Enable Typematic")
        typematic_form.addRow("Enable Typematic:", self.typematic_enabled_check)

        self.typematic_delay_spin = QDoubleSpinBox()
        self.typematic_delay_spin.setRange(100.0, 1000.0)
        self.typematic_delay_spin.setSingleStep(10.0)
        self.typematic_delay_spin.setSuffix(" ms")
        typematic_form.addRow("Typematic Delay:", self.typematic_delay_spin)

        self.typematic_rate_spin = QDoubleSpinBox()
        self.typematic_rate_spin.setRange(1, 30)
        self.typematic_rate_spin.setSingleStep(1.0)
        self.typematic_rate_spin.setSuffix(" Hz")
        typematic_form.addRow("Typematic Rate:", self.typematic_rate_spin)

        self.content_layout().addWidget(typematic_group)

        # 4. System Group
        system_group = QGroupBox("System")
        system_form = QFormLayout(system_group)

        self.double_tap_enabled_check = QCheckBox()
        system_form.addRow("Enable Double-Tap Gesture:", self.double_tap_enabled_check)

        self.bezel_toggle_enabled_check = QCheckBox()
        system_form.addRow("Enable Bezel Toggles:", self.bezel_toggle_enabled_check)

        self.content_layout().addWidget(system_group)

        # 5. Import / Export / Backup
        io_row = QHBoxLayout()
        self.export_toml_btn = QPushButton("Export settings.toml")
        self.import_toml_btn = QPushButton("Import Config (.toml / .json / Bundle)")
        self.export_bundle_btn = QPushButton("Export Full Bundle")

        io_row.addWidget(self.export_toml_btn)
        io_row.addWidget(self.import_toml_btn)
        io_row.addWidget(self.export_bundle_btn)

        self.content_layout().addLayout(io_row)

        # 6. Database Reset Actions
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
        self.floating_check.toggled.connect(self._on_floating_joystick_changed)
        self.anchored_check.toggled.connect(self._on_anchored_joystick_changed)
        self.sensitivity_spin_x.valueChanged.connect(self._on_sensitivity_x_changed)
        self.sensitivity_spin_y.valueChanged.connect(self._on_sensitivity_y_changed)
        self.deadzone_spin.valueChanged.connect(self._on_deadzone_changed)
        self.hysteresis_spin.valueChanged.connect(self._on_hysteresis_changed)

        self.rate_cap_spin.valueChanged.connect(self._on_rate_cap_changed)
        self.pps_alert_spin.valueChanged.connect(self._on_pps_alert_changed)

        self.typematic_enabled_check.toggled.connect(
            self._on_typematic_enabled__changed
        )
        self.typematic_delay_spin.valueChanged.connect(self._on_typematic_delay_changed)
        self.typematic_rate_spin.valueChanged.connect(self._on_typematic_rate_changed)

        self.double_tap_enabled_check.toggled.connect(
            self._on_double_tap_enabled__changed
        )
        self.bezel_toggle_enabled_check.toggled.connect(
            self._on_bezel_toggle_enabled_changed
        )

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

            # Block all Signals
            self.left_handed_check.blockSignals(True)
            self.floating_check.blockSignals(True)
            self.anchored_check.blockSignals(True)
            self.sensitivity_spin_x.blockSignals(True)
            self.sensitivity_spin_y.blockSignals(True)
            self.deadzone_spin.blockSignals(True)
            self.hysteresis_spin.blockSignals(True)

            self.rate_cap_spin.blockSignals(True)
            self.pps_alert_spin.blockSignals(True)

            self.typematic_enabled_check.blockSignals(True)
            self.typematic_delay_spin.blockSignals(True)
            self.typematic_rate_spin.blockSignals(True)

            self.double_tap_enabled_check.blockSignals(True)
            self.bezel_toggle_enabled_check.blockSignals(True)

            # Set Values
            self.left_handed_check.setChecked(settings.left_handed)
            self.floating_check.setChecked(settings.floating_joystick)
            self.anchored_check.setChecked(settings.anchored_joystick)
            self.sensitivity_spin_x.setValue(settings.sensitivity_x)
            self.sensitivity_spin_y.setValue(settings.sensitivity_y)
            self.deadzone_spin.setValue(settings.deadzone)
            self.hysteresis_spin.setValue(settings.hysteresis)

            self.rate_cap_spin.setValue(settings.adb_rate_cap)
            self.pps_alert_spin.setValue(settings.pps_alert_threshold)

            self.typematic_enabled_check.setChecked(settings.typematic_enabled)
            self.typematic_delay_spin.setValue(settings.typematic_delay_ms)
            self.typematic_rate_spin.setValue(settings.typematic_rate_hz)

            self.double_tap_enabled_check.setChecked(settings.double_tap_enabled)
            self.bezel_toggle_enabled_check.setChecked(settings.bezel_toggle_enabled)

            # Unblock all Signals
            self.left_handed_check.blockSignals(False)
            self.floating_check.blockSignals(False)
            self.anchored_check.blockSignals(False)
            self.sensitivity_spin_x.blockSignals(False)
            self.sensitivity_spin_y.blockSignals(False)
            self.deadzone_spin.blockSignals(False)
            self.hysteresis_spin.blockSignals(False)

            self.rate_cap_spin.blockSignals(False)
            self.pps_alert_spin.blockSignals(False)

            self.typematic_enabled_check.blockSignals(False)
            self.typematic_delay_spin.blockSignals(False)
            self.typematic_rate_spin.blockSignals(False)

            self.double_tap_enabled_check.blockSignals(False)
            self.bezel_toggle_enabled_check.blockSignals(False)

        except Exception as exc:
            logger.exception("Failed to load settings from database")

    def _on_left_handed_changed(self, checked: bool) -> None:
        try:
            store.settings.update(left_handed=checked)
            self._notify_reload()
        except Exception as exc:
            logger.exception("Failed to update left_handed setting")

    def _on_floating_joystick_changed(self, checked: bool) -> None:
        try:
            store.settings.update(floating_joystick=checked)
            self._notify_reload()
        except Exception as exc:
            logger.exception("Failed to update floating_joystick setting")

    def _on_anchored_joystick_changed(self, checked: bool) -> None:
        try:
            store.settings.update(anchored_joystick=checked)
            self._notify_reload()
        except Exception as exc:
            logger.exception("Failed to update anchored_joystick setting")

    def _on_sensitivity_x_changed(self, value: float) -> None:
        try:
            store.settings.update(sensitivity_x=value)
            self._notify_reload()
        except Exception as exc:
            logger.exception("Failed to update X sensitivity setting")

    def _on_sensitivity_y_changed(self, value: float) -> None:
        try:
            store.settings.update(sensitivity_y=value)
            self._notify_reload()
        except Exception as exc:
            logger.exception("Failed to update Y sensitivity setting")

    def _on_deadzone_changed(self, value: float) -> None:
        try:
            store.settings.update(deadzone=value)
            self._notify_reload()
        except Exception as exc:
            logger.exception("Failed to update deadzone setting")

    def _on_hysteresis_changed(self, value: float) -> None:
        try:
            store.settings.update(hysteresis=value)
            self._notify_reload()
        except Exception as exc:
            logger.exception("Failed to update hysteresis setting")

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

    def _on_typematic_enabled__changed(self, checked: bool) -> None:
        try:
            store.settings.update(typematic_enabled=checked)
            self._notify_reload()
        except Exception as exc:
            logger.exception("Failed to update typematic enabled setting")

    def _on_typematic_delay_changed(self, value: float) -> None:
        try:
            store.settings.update(typematic_delay_ms=value)
            self._notify_reload()
        except Exception as exc:
            logger.exception("Failed to update typematic_delay setting")

    def _on_typematic_rate_changed(self, value: float) -> None:
        try:
            store.settings.update(typematic_rate_hz=value)
            self._notify_reload()
        except Exception as exc:
            logger.exception("Failed to update typematic_rate setting")

    def _on_double_tap_enabled__changed(self, checked: bool) -> None:
        try:
            store.settings.update(double_tap_enabled=checked)
            self._notify_reload()
        except Exception as exc:
            logger.exception("Failed to update double_tap enabled setting")

    def _on_bezel_toggle_enabled_changed(self, checked: bool) -> None:
        try:
            store.settings.update(bezel_toggle_enabled=checked)
            self._notify_reload()
        except Exception as exc:
            logger.exception("Failed to update bezel_toggle enabled setting")

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
                QMessageBox.information(
                    self, "Wiped", "All layouts and settings cleared."
                )
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
        PROFILES_FOLDER.mkdir(parents=True, exist_ok=True)
        path_str, _ = QFileDialog.getOpenFileName(
            self,
            "Import Settings, Layout or Bundle",
            str(PROFILES_FOLDER),
            "Supported Files (*.toml *.json);;TOML files (*.toml);;JSON files (*.json);;All files (*.*)",
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
        PROFILES_FOLDER.mkdir(parents=True, exist_ok=True)
        folder = QFileDialog.getExistingDirectory(
            self, "Select Target Folder for Bundle", str(PROFILES_FOLDER)
        )
        if not folder:
            return

        try:
            t_file, j_file = export_bundle(Path(folder))
            logger.info(
                "Exported configuration bundle: '%s', '%s'", t_file.name, j_file.name
            )
            QMessageBox.information(
                self,
                "Bundle Exported",
                f"Exported configuration bundle:\n- {t_file.name}\n- {j_file.name}",
            )
        except Exception as exc:
            logger.exception("Bundle export failed")
            QMessageBox.critical(self, "Bundle Export Failed", str(exc))
