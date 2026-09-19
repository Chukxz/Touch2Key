from __future__ import annotations

import logging
from typing import Optional

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
)

from modules.database import store
from modules.platforms import get_specific_qt_key
from modules.utils import (
    DEFAULT_ADB_RATE_CAP,
    DEFAULT_PPS,
    get_scancode_and_bridge_key_from_key,
)

logger = logging.getLogger("modules.gui.dialogs")


class KeyCaptureDialog(QDialog):
    def __init__(
        self, prompt: str, skippable: bool = False, default_key: str | None = None
    ):
        super().__init__()
        self.setWindowTitle("Key Capture")
        self.setFixedSize(400, 200)
        self.captured_key: str | None = None
        self.skippable = skippable
        self.default_key = default_key
        self._listening = True

        layout = QVBoxLayout()

        self.prompt_label = QLabel(prompt)
        self.prompt_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.prompt_label.setFont(QFont("Courier", 11))
        layout.addWidget(self.prompt_label)

        if default_key:
            self.key_label = QLabel(
                f"Waiting for keypress (Default : {default_key})..."
            )
        else:
            self.key_label = QLabel("Waiting for keypress (Default: '')...")
        self.key_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.key_label.setFont(QFont("Courier", 11))
        layout.addWidget(self.key_label)

        btn_layout = QHBoxLayout()

        self.retry_btn = QPushButton("Retry")
        self.retry_btn.setEnabled(False)
        self.retry_btn.clicked.connect(self._retry)
        btn_layout.addWidget(self.retry_btn)

        self.confirm_btn = QPushButton("Confirm")
        self.confirm_btn.setEnabled(False)
        self.confirm_btn.clicked.connect(self._confirm)
        btn_layout.addWidget(self.confirm_btn)

        if skippable:
            self.skip_btn = QPushButton("Skip")
            self.skip_btn.clicked.connect(self._skip)
            btn_layout.addWidget(self.skip_btn)

        self.reset_btn = QPushButton("Reset")
        self.reset_btn.clicked.connect(self._reset)
        btn_layout.addWidget(self.reset_btn)

        layout.addLayout(btn_layout)
        self.setLayout(layout)

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Escape:
            self.reject()
            return

        if not self._listening:
            return

        precise_key = get_specific_qt_key(event)
        _, key_name = get_scancode_and_bridge_key_from_key(precise_key)

        if key_name is None:
            return

        self.captured_key = key_name
        self.key_label.setText(f"Captured: {key_name}")
        self._listening = False
        self.retry_btn.setEnabled(True)
        self.confirm_btn.setEnabled(True)

    def _retry(self):
        self.captured_key = None
        self.key_label.setText("Waiting for keypress...")
        self._listening = True
        self.retry_btn.setEnabled(False)
        self.confirm_btn.setEnabled(False)

    def _confirm(self):
        self.done(QDialog.DialogCode.Accepted)

    def _skip(self):
        self.captured_key = self.default_key
        self.done(QDialog.DialogCode.Accepted)

    def _reset(self):
        self.captured_key = None
        self.done(QDialog.DialogCode.Accepted)


class NumericCaptureDialog(QDialog):
    """Text-entry counterpart to KeyCaptureDialog for numeric settings."""

    def __init__(
        self,
        prompt: str,
        default_value: float,
        min_value: float,
        max_value: float | None = None,
    ):
        super().__init__()
        self.setWindowTitle("Numeric Input")
        self.setFixedSize(400, 220)
        self.result_value: float | None = None
        self.default_value = default_value
        self.min_value = min_value
        self.max_value = max_value

        layout = QVBoxLayout()

        self.prompt_label = QLabel(prompt)
        self.prompt_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.prompt_label.setFont(QFont("Courier", 11))
        layout.addWidget(self.prompt_label)

        range_text = f"Min {min_value:g}"
        if max_value is not None:
            range_text += f", Max {max_value:g}"
        self.range_label = QLabel(f"{range_text} | Default {default_value:g}")
        self.range_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.range_label.setFont(QFont("Courier", 9))
        layout.addWidget(self.range_label)

        self.input_field = QLineEdit()
        self.input_field.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.input_field.setFont(QFont("Courier", 11))
        self.input_field.setPlaceholderText(f"Blank for default ({default_value:g})")
        self.input_field.returnPressed.connect(self._confirm)
        layout.addWidget(self.input_field)

        self.error_label = QLabel("")
        self.error_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.error_label.setFont(QFont("Courier", 9))
        self.error_label.setStyleSheet("color: red;")
        layout.addWidget(self.error_label)

        btn_layout = QHBoxLayout()

        self.confirm_btn = QPushButton("Confirm")
        self.confirm_btn.clicked.connect(self._confirm)
        btn_layout.addWidget(self.confirm_btn)

        self.skip_btn = QPushButton("Skip")
        self.skip_btn.clicked.connect(self._skip)
        btn_layout.addWidget(self.skip_btn)

        layout.addLayout(btn_layout)
        self.setLayout(layout)
        self.input_field.setFocus()

    def _confirm(self):
        text = self.input_field.text().strip()
        if not text:
            self._skip()
            return

        try:
            value = float(text)
        except ValueError:
            self.error_label.setText("Invalid number. Try again.")
            return

        if value < self.min_value:
            value = self.min_value
        if self.max_value is not None and value > self.max_value:
            value = self.max_value

        self.result_value = value
        self.done(QDialog.DialogCode.Accepted)

    def _skip(self):
        self.result_value = self.default_value
        self.done(QDialog.DialogCode.Accepted)


def capture_keys() -> tuple[str | None, str | None] | None:
    """Interactively captures toggle and sprint keys and commits them to store.settings."""
    settings = store.settings.get()
    default_toggle = settings.toggle_key
    default_sprint = settings.sprint_key

    toggle_dialog = KeyCaptureDialog(
        "Press the key to use as the TOGGLE key\nfor Camera/Menu mode toggle\n(or click Skip to use the default)",
        skippable=True,
        default_key=default_toggle,
    )
    if toggle_dialog.exec() == QDialog.DialogCode.Rejected:
        return None
    toggle_key = toggle_dialog.captured_key

    sprint_dialog = KeyCaptureDialog(
        "Press the key to use as the SPRINT key\n(or click Skip to use the default)",
        skippable=True,
        default_key=default_sprint,
    )
    if sprint_dialog.exec() == QDialog.DialogCode.Rejected:
        return None
    sprint_key = sprint_dialog.captured_key

    store.settings.update(
        toggle_key=toggle_key or "",
        sprint_key=sprint_key or "",
    )
    return toggle_key, sprint_key


def capture_performance_settings() -> tuple[float | None, float | None] | None:
    """Interactively captures rate cap and PPS and commits them to store.settings."""
    settings = store.settings.get()
    default_rate = settings.adb_rate_cap or DEFAULT_ADB_RATE_CAP
    default_pps = settings.pps_alert_threshold or DEFAULT_PPS

    rate_dialog = NumericCaptureDialog(
        "Enter the ADB rate cap (Hz)\nfor touch event polling\n(or click Skip to use the default)",
        default_value=default_rate,
        min_value=60.0,
    )
    if rate_dialog.exec() == QDialog.DialogCode.Rejected:
        return None
    rate_cap = rate_dialog.result_value

    pps_dialog = NumericCaptureDialog(
        "Enter the Alert Threshold (PPS)\nfor touch event rate monitoring\n(or click Skip to use the default)",
        default_value=default_pps,
        min_value=30.0,
        max_value=120.0,
    )
    if pps_dialog.exec() == QDialog.DialogCode.Rejected:
        return None
    pps = pps_dialog.result_value

    if rate_cap is not None and pps is not None:
        store.settings.update(
            adb_rate_cap=float(rate_cap),
            pps_alert_threshold=float(pps),
        )

    return rate_cap, pps