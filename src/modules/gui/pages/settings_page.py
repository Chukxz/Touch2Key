# src/modules/gui/pages/settings_page.py
from __future__ import annotations
from PySide6.QtWidgets import QCheckBox, QDoubleSpinBox, QFormLayout, QPushButton, QWidget
from modules.database import store
from modules.utils import MapperEvent
from .base_page import BasePage

class SettingsPage(BasePage):
    title = "Settings"

    def __init__(self, dispatcher=None, parent=None):
        super().__init__(dispatcher, parent)

        form_widget = QWidget()
        form = QFormLayout(form_widget)

        self.left_handed_check = QCheckBox("Left-handed")
        form.addRow(self.left_handed_check)

        self.anchored_floating_check = QCheckBox("Anchored Floating Joystick")
        form.addRow(self.anchored_floating_check)

        self.snap_radius_spin = QDoubleSpinBox()
        self.snap_radius_spin.setRange(10.0, 500.0)
        self.snap_radius_spin.setSuffix(" px")
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

        self.reset_defaults_btn = QPushButton("Reset to defaults")
        self.content_layout().addWidget(self.reset_defaults_btn)
        self.content_layout().addStretch()

        self.left_handed_check.toggled.connect(self._on_left_handed_changed)
        self.anchored_floating_check.toggled.connect(self._on_anchored_floating_changed)
        self.snap_radius_spin.valueChanged.connect(self._on_snap_radius_changed)
        self.sensitivity_spin.valueChanged.connect(self._on_sensitivity_changed)
        self.deadzone_spin.valueChanged.connect(self._on_deadzone_changed)
        self.reset_defaults_btn.clicked.connect(self._on_reset_defaults)

        self.load_settings()

    def _notify_reload(self) -> None:
        if self.dispatcher:
            self.dispatcher.dispatch(MapperEvent(action="ON_CONFIG_RELOAD"))

    def load_settings(self) -> None:
        s = store.settings.get()
        self.left_handed_check.blockSignals(True)
        self.anchored_floating_check.blockSignals(True)
        self.snap_radius_spin.blockSignals(True)
        self.sensitivity_spin.blockSignals(True)
        self.deadzone_spin.blockSignals(True)

        self.left_handed_check.setChecked(s.left_handed)
        self.anchored_floating_check.setChecked(s.anchored_floating_joystick)
        self.snap_radius_spin.setValue(s.joystick_snap_radius)
        self.snap_radius_spin.setEnabled(s.anchored_floating_joystick)
        self.sensitivity_spin.setValue(s.sensitivity)
        self.deadzone_spin.setValue(s.deadzone)

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

    def _on_snap_radius_changed(self, val: float) -> None:
        store.settings.update(joystick_snap_radius=val)
        self._notify_reload()

    def _on_sensitivity_changed(self, val: float) -> None:
        store.settings.update(sensitivity=val)
        self._notify_reload()

    def _on_deadzone_changed(self, val: float) -> None:
        store.settings.update(deadzone=val)
        self._notify_reload()

    def _on_reset_defaults(self) -> None:
        store.settings.reset_to_defaults()
        self.load_settings()
        self._notify_reload()