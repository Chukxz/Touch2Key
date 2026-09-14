from __future__ import annotations

from PySide6.QtWidgets import QFormLayout, QPushButton, QLabel, QWidget, QHBoxLayout

from .base_page import BasePage


class KeyBindingsPage(BasePage):
    """Replaces the modal KeyCaptureDialog flow (core/key_capture.py):
    toggle/sprint key capture become inline 'Capture' rows instead of
    blocking startup dialogs, so bindings can be changed anytime while
    the app is running, not just before the engine starts."""

    title = "Key bindings"

    def __init__(self, parent=None):
        super().__init__(parent)

        form_widget = QWidget()
        form = QFormLayout(form_widget)

        self.toggle_key_label = QLabel("Not set")
        self.toggle_key_btn = QPushButton("Capture")
        form.addRow(
            "Toggle key:", self._paired_row(self.toggle_key_label, self.toggle_key_btn)
        )

        self.sprint_key_label = QLabel("Not set")
        self.sprint_key_btn = QPushButton("Capture")
        form.addRow(
            "Sprint key:", self._paired_row(self.sprint_key_label, self.sprint_key_btn)
        )

        self.content_layout().addWidget(form_widget)
        self.content_layout().addStretch()

        # main_window.py should connect *_btn.clicked to a short-lived
        # keyPressEvent grab (similar in spirit to KeyCaptureDialog's
        # keyPressEvent override) that updates the paired label and
        # persists to app_settings, rather than reopening a QDialog.

    @staticmethod
    def _paired_row(label: QLabel, button: QPushButton) -> QWidget:
        wrapper = QWidget()
        row = QHBoxLayout(wrapper)
        row.setContentsMargins(0, 0, 0, 0)
        row.addWidget(label)
        row.addWidget(button)
        row.addStretch()
        return wrapper
