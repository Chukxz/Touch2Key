from __future__ import annotations

from PySide6.QtWidgets import (
    QFormLayout,
    QCheckBox,
    QDoubleSpinBox,
    QWidget,
    QPushButton,
)

from .base_page import BasePage


class SettingsPage(BasePage):
    """General app_settings fields not covered by a dedicated page:
    handedness, joystick sensitivity/deadzone. 'Reset to defaults'
    replaces scripts/hard_reset_toml.py's CLI-only reset flow."""

    title = "Settings"

    def __init__(self, parent=None):
        super().__init__(parent)

        form_widget = QWidget()
        form = QFormLayout(form_widget)

        self.left_handed_check = QCheckBox("Left-handed")
        form.addRow(self.left_handed_check)

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
