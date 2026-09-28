from __future__ import annotations

import logging
from typing import TYPE_CHECKING
from PySide6.QtCore import QEvent, QObject
from PySide6.QtGui import QKeyEvent
from PySide6.QtWidgets import (
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from modules.database import store
from modules.platforms import get_specific_qt_key
from modules.utils import MapperEvent, get_scancode_and_bridge_key_from_key
from .base_page import BasePage

if TYPE_CHECKING:
    from modules.utils import MapperEventDispatcher

logger = logging.getLogger("modules.gui.key_bindings_page")


class ContinuousSequenceFilter(QObject):
    """Intercepts all sequential KeyPress events."""

    def __init__(self, key_callback, parent=None):
        super().__init__(parent)
        self.key_callback = key_callback

    def eventFilter(self, obj: QObject, event: QEvent) -> bool:
        if event.type() == QEvent.Type.KeyPress and isinstance(event, QKeyEvent):
            if event.isAutoRepeat():
                return True

            precise_key = get_specific_qt_key(event)
            _, bridge_key = get_scancode_and_bridge_key_from_key(precise_key)
            if bridge_key is not None:
                db_token = bridge_key.strip().lower()
                self.key_callback(db_token)
                return True

        return False


class KeySequenceRow(QWidget):
    """Encapsulates sequence preview, record toggle, pop/clear, and DB persistence."""

    def __init__(
        self,
        target_field: str,
        page: TypematicKeyBindingsPage,  # TypematicKeyBindingsPage inherits from BasePage which inherits from QWidget
    ):
        super().__init__(page)
        self.target_field = target_field
        self.page = page
        self.sequence: list[str] = []

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)

        controls = QHBoxLayout()
        controls.setContentsMargins(0, 0, 0, 0)

        self.sequence_label = QLabel("None")
        self.sequence_label.setStyleSheet("font-family: monospace; font-weight: bold;")

        self.record_btn = QPushButton("Record Sequence")
        self.record_btn.setCheckable(True)

        self.remove_btn = QPushButton("Remove Last")
        self.clear_btn = QPushButton("Clear")

        controls.addWidget(self.sequence_label)
        controls.addWidget(self.record_btn)
        controls.addWidget(self.remove_btn)
        controls.addWidget(self.clear_btn)
        controls.addStretch()

        layout.addLayout(controls)

        self.status_label = QLabel("")
        self.status_label.setStyleSheet("color: #7f8c8d; font-size: 11px;")
        layout.addWidget(self.status_label)

        self.record_btn.toggled.connect(self._on_toggle_recording)
        self.remove_btn.clicked.connect(self._remove_last_key)
        self.clear_btn.clicked.connect(self._clear_sequence)

    def set_sequence(self, sequence: list[str]) -> None:
        self.sequence = [k.strip().lower() for k in sequence if k.strip()]
        self._update_display()

    def add_key(self, db_key: str) -> None:
        self.sequence.append(db_key)
        self._update_display()
        self.save()

    def stop_recording(self) -> None:
        if self.record_btn.isChecked():
            self.record_btn.setChecked(False)

    def _on_toggle_recording(self, checked: bool) -> None:
        if checked:
            self.record_btn.setText("Stop Recording")
            self.status_label.setText(
                "Recording keypresses (Esc included)... Click Stop when done."
            )
            self.page.begin_sequence_capture(self)
        else:
            self.record_btn.setText("Record Sequence")
            self.status_label.setText("")
            self.page.end_sequence_capture(self)

    def _remove_last_key(self) -> None:
        if self.sequence:
            self.sequence.pop()
            self._update_display()
            self.save()

    def _clear_sequence(self) -> None:
        if self.sequence:
            self.sequence.clear()
            self._update_display()
            self.save()

    def _update_display(self) -> None:
        if not self.sequence:
            self.sequence_label.setText("None")
            self.remove_btn.setEnabled(False)
            self.clear_btn.setEnabled(False)
        else:
            self.sequence_label.setText(" + ".join(self.sequence))
            self.remove_btn.setEnabled(True)
            self.clear_btn.setEnabled(True)

    def save(self) -> None:
        # Formats directly as "lshift,lctrl,esc" (or empty string if cleared)
        serialized = ",".join(self.sequence)
        self.page.persist_binding(self.target_field, serialized)


class TypematicKeyBindingsPage(BasePage):
    """Dynamic key bindings page capturing arbitrary sequences into SQLite."""

    title = "Typematic Key Bindings"

    def __init__(
        self,
        dispatcher: MapperEventDispatcher | None = None,
        parent: QWidget | None = None,
    ):
        super().__init__(dispatcher, parent)
        self._active_filter: ContinuousSequenceFilter | None = None
        self._active_row: KeySequenceRow | None = None

        form_widget = QWidget()
        form = QFormLayout(form_widget)
        form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)

        self.typematic_excluded_keys = KeySequenceRow("typematic_excluded_keys", self)
        form.addRow("Excluded Typematic Keys:", self.typematic_excluded_keys)

        self.content_layout().addWidget(form_widget)
        self.content_layout().addStretch()

        self.load_bindings()

    def on_page_shown(self) -> None:
        self.load_bindings()

    def load_bindings(self) -> None:
        try:
            settings = store.settings.get()

            def parse_seq(val: str | None) -> list[str]:
                if not val or not val.strip():
                    return []
                return [k.strip().lower() for k in val.split(",") if k.strip()]

            self.typematic_excluded_keys.set_sequence(
                parse_seq(settings.typematic_excluded_keys)
            )
        except Exception:
            logger.exception("Failed to load key bindings from database")

    def begin_sequence_capture(self, row: KeySequenceRow) -> None:
        if self._active_row is not None and self._active_row is not row:
            self._active_row.stop_recording()

        self._active_row = row

        if self._active_filter is not None:
            self.removeEventFilter(self._active_filter)

        self._active_filter = ContinuousSequenceFilter(
            key_callback=self._on_key_captured,
            parent=self,
        )
        self.installEventFilter(self._active_filter)
        self.setFocus()

    def end_sequence_capture(self, row: KeySequenceRow) -> None:
        if self._active_filter is not None:
            self.removeEventFilter(self._active_filter)
            self._active_filter = None

        if self._active_row is row:
            self._active_row = None

    def _on_key_captured(self, db_key: str) -> None:
        if self._active_row is not None:
            self._active_row.add_key(db_key)

    def persist_binding(self, target_field: str, serialized_val: str) -> None:
        try:
            store.settings.update(**{target_field: serialized_val})
            if self.dispatcher:
                self.dispatcher.dispatch(MapperEvent(action="ON_CONFIG_RELOAD"))
            logger.info(
                "Updated sequence for %s to: '%s'", target_field, serialized_val
            )
        except Exception as exc:
            logger.exception("Failed to update sequence binding for %s", target_field)
            QMessageBox.critical(
                self, "Error", f"Could not save key sequence binding:\n{exc}"
            )
