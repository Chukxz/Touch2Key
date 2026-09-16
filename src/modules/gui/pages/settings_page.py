from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from PySide6.QtWidgets import (
    QCheckBox,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QMessageBox,
    QPushButton,
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


class SettingsPage(BasePage):
    """General settings page for handedness, sensitivity, deadzones, and TOML sync."""

    title = "Settings"

    def __init__(
        self,
        dispatcher: MapperEventDispatcher | None = None,
        parent: QWidget | None = None,
    ):
        super().__init__(dispatcher, parent)

        form_widget = QWidget()
        form = QFormLayout(form_widget)

        self.left_handed_check = QCheckBox("Left-handed")
        form.addRow(self.left_handed_check)

        self.anchored_floating_check = QCheckBox("Anchored Floating Joystick")
        self.anchored_floating_check.setToolTip(
            "When enabled with a plotted HUD joystick circle, touches near the center lock "
            "to the fixed anchor, while touches elsewhere float dynamically."
        )
        form.addRow(self.anchored_floating_check)

        self.snap_radius_spin = QDoubleSpinBox()
        self.snap_radius_spin.setRange(10.0, 500.0)
        self.snap_radius_spin.setSingleStep(5.0)
        self.snap_radius_spin.setSuffix(" px")
        self.snap_radius_spin.setToolTip(
            "Touch proximity radius around the fixed HUD icon to snap the center."
        )
        form.addRow("Joystick Snap Radius:", self.snap_radius_spin)

        self.sensitivity_spin = QDoubleSpinBox()
        self.sensitivity_spin.setRange(0.1, 10.0)
        self.sensitivity_spin.setSingleStep(0.1)
        form.addRow("Sensitivity:", self.sensitivity_spin)

        self.deadzone_spin = QDoubleSpinBox()
        self.deadzone_spin.setRange(0.0, 1.0)
        self.deadzone_spin.setSingleStep(0.01)
        form.addRow("Deadzone:", self.deadzone_spin)

        self.content_layout().addWidget(form_widget)

        self.reset_defaults_btn = QPushButton("Reset to Defaults")
        self.content_layout().addWidget(self.reset_defaults_btn)

        # TOML Settings & Bundle IO
        toml_btn_row = QHBoxLayout()
        self.export_toml_btn = QPushButton("Export settings.toml")
        self.import_toml_btn = QPushButton("Import settings.toml")
        self.export_bundle_btn = QPushButton("Export Full Bundle")

        toml_btn_row.addWidget(self.export_toml_btn)
        toml_btn_row.addWidget(self.import_toml_btn)
        toml_btn_row.addWidget(self.export_bundle_btn)
        self.content_layout().addLayout(toml_btn_row)

        self.content_layout().addStretch()

        self._wire_signals()
        self.load_settings()

    def _wire_signals(self) -> None:
        self.left_handed_check.toggled.connect(self._on_left_handed_changed)
        self.anchored_floating_check.toggled.connect(self._on_anchored_floating_changed)
        self.snap_radius_spin.valueChanged.connect(self._on_snap_radius_changed)
        self.sensitivity_spin.valueChanged.connect(self._on_sensitivity_changed)
        self.deadzone_spin.valueChanged.connect(self._on_deadzone_changed)
        self.reset_defaults_btn.clicked.connect(self._on_reset_defaults)

        self.export_toml_btn.clicked.connect(self._on_export_toml)
        self.import_toml_btn.clicked.connect(self._on_import_toml)
        self.export_bundle_btn.clicked.connect(self._on_export_bundle)

    def on_page_shown(self) -> None:
        self.load_settings()

    def _notify_reload(self) -> None:
        if self.dispatcher:
            self.dispatcher.dispatch(MapperEvent(action="ON_CONFIG_RELOAD"))

    def load_settings(self) -> None:
        settings = store.settings.get()

        self.left_handed_check.blockSignals(True)
        self.anchored_floating_check.blockSignals(True)
        self.snap_radius_spin.blockSignals(True)
        self.sensitivity_spin.blockSignals(True)
        self.deadzone_spin.blockSignals(True)

        self.left_handed_check.setChecked(settings.left_handed)
        self.anchored_floating_check.setChecked(settings.anchored_floating_joystick)
        self.snap_radius_spin.setValue(settings.joystick_snap_radius)
        self.snap_radius_spin.setEnabled(settings.anchored_floating_joystick)
        self.sensitivity_spin.setValue(settings.sensitivity)
        self.deadzone_spin.setValue(settings.deadzone)

        self.left_handed_check.blockSignals(False)
        self.anchored_floating_check.blockSignals(False)
        self.snap_radius_spin.blockSignals(False)
        self.sensitivity_spin.blockSignals(False)
        self.deadzone_spin.blockSignals(False)

    def _on_left_handed_changed(self, checked: bool) -> None:
        store.settings.update(left_handed=int(checked))
        self._notify_reload()

    def _on_anchored_floating_changed(self, checked: bool) -> None:
        self.snap_radius_spin.setEnabled(checked)
        store.settings.update(anchored_floating_joystick=int(checked))
        self._notify_reload()

    def _on_snap_radius_changed(self, value: float) -> None:
        store.settings.update(joystick_snap_radius=value)
        self._notify_reload()

    def _on_sensitivity_changed(self, value: float) -> None:
        store.settings.update(sensitivity=value)
        self._notify_reload()

    def _on_deadzone_changed(self, value: float) -> None:
        store.settings.update(deadzone=value)
        self._notify_reload()

    def _on_reset_defaults(self) -> None:
        store.settings.reset_to_defaults()
        self.load_settings()
        self._notify_reload()

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
            QMessageBox.information(
                self,
                "Exported",
                f"Settings exported successfully to:\n{out_path.name}",
            )
        except Exception as e:
            QMessageBox.critical(self, "Export Error", str(e))

    def _on_import_toml(self) -> None:
        path_str, _ = QFileDialog.getOpenFileName(
            self,
            "Import Settings or Bundle",
            str(TOML_PATH.parent),
            "Config files (*.toml *.json);;All files (*.*)",
        )
        if not path_str:
            return

        if import_any(Path(path_str)):
            self.load_settings()
            self._notify_reload()
            if self.dispatcher:
                self.dispatcher.dispatch(MapperEvent(action="ON_LAYOUT_RELOAD"))
            QMessageBox.information(
                self,
                "Imported",
                "Configuration imported and synced to database.",
            )
        else:
            QMessageBox.warning(
                self,
                "Import Failed",
                "Could not parse or apply settings from file.",
            )

    def _on_export_bundle(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, "Select Target Folder for Bundle")
        if not folder:
            return

        try:
            t_file, j_file = export_bundle(Path(folder))
            QMessageBox.information(
                self,
                "Bundle Exported",
                f"Exported configuration bundle:\n- {t_file.name}\n- {j_file.name}",
            )
        except Exception as e:
            QMessageBox.critical(self, "Bundle Export Failed", str(e))
