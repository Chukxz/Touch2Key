from __future__ import annotations

from PySide6.QtWidgets import QFormLayout, QDoubleSpinBox, QWidget

from .base_page import BasePage


class PerformancePage(BasePage):
    """Replaces the modal NumericCaptureDialog flow: ADB rate cap and
    PPS alert threshold become persistent, always-editable fields
    backed by app_settings, instead of one-shot startup prompts with
    clamped-but-final values."""

    title = "Performance"

    def __init__(self, parent=None):
        super().__init__(parent)

        form_widget = QWidget()
        form = QFormLayout(form_widget)

        self.rate_cap_spin = QDoubleSpinBox()
        self.rate_cap_spin.setRange(60.0, 1000.0)
        self.rate_cap_spin.setSuffix(" Hz")
        form.addRow("ADB rate cap:", self.rate_cap_spin)

        self.pps_spin = QDoubleSpinBox()
        self.pps_spin.setRange(30.0, 120.0)
        self.pps_spin.setSuffix(" PPS")
        form.addRow("Alert threshold:", self.pps_spin)

        self.content_layout().addWidget(form_widget)
        self.content_layout().addStretch()

        # main_window.py should load current values from app_settings
        # when this page becomes visible, and write back on
        # valueChanged (debounced) or via an explicit Save action --
        # pick one convention and apply it to every settings-style page.
