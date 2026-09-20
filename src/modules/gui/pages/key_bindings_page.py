from __future__ import annotations

import logging
from typing import TYPE_CHECKING
from PySide6.QtCore import QEvent, QObject, Qt

from PySide6.QtWidgets import (
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QWidget,
)

from modules.database import store
from modules.platforms import get_specific_qt_key
from modules.utils import MapperEvent, get_scancode_and_bridge_key_from_key
from .base_page import BasePage

if TYPE_CHECKING:
    from modules.utils import MapperEventDispatcher

logger = logging.getLogger("modules.gui.key_bindings_page")


class KeyCaptureFilter(QObject):
    """Intercepts the next raw keypress without opening blocking modal dialogs."""

    def __init__(self, callback, parent=None):
        super().__init__(parent)
        self.callback = callback

    def eventFilter(self, obj: QObject, event) -> bool:
        if event.type() == QEvent.Type.KeyPress:
            if event.key() == Qt.Key.Key_Escape:
                self.callback(None)
                return True
            
            precise_key = get_specific_qt_key(event)
            _, bridge_key = get_scancode_and_bridge_key_from_key(precise_key)
            if bridge_key is not None:
                self.callback(bridge_key)
                return True
        return False


class KeyBindingsPage(BasePage):
    """Dynamic, non-blocking Key Bindings configuration page backed by SQLite."""

    title = "Key bindings"

    def __init__(
        self,
        dispatcher: MapperEventDispatcher | None = None,
        parent: QWidget | None = None,
    ):
        super().__init__(dispatcher, parent)
        self._active_filter: KeyCaptureFilter | None = None

        form_widget = QWidget()
        form = QFormLayout(form_widget)

        self.toggle_key_label = QLabel("Not set")
        self.toggle_key_btn = QPushButton("Capture")
        form.addRow(
            "Toggle Key (Menu Mode):",
            self._paired_row(self.toggle_key_label, self.toggle_key_btn),
        )

        self.sprint_key_label = QLabel("Not set")
        self.sprint_key_btn = QPushButton("Capture")
        form.addRow(
            "Sprint Key:",
            self._paired_row(self.sprint_key_label, self.sprint_key_btn),
        )

        self.content_layout().addWidget(form_widget)
        self.content_layout().addStretch()

        self.toggle_key_btn.clicked.connect(lambda: self._begin_capture("toggle_key"))
        self.sprint_key_btn.clicked.connect(lambda: self._begin_capture("sprint_key"))

        self.load_bindings()

    def on_page_shown(self) -> None:
        self.load_bindings()

    def load_bindings(self) -> None:
        try:
            settings = store.settings.get()
            self.toggle_key_label.setText(settings.toggle_key or "Not set")
            self.sprint_key_label.setText(settings.sprint_key or "Not set")
        except Exception as exc:
            logger.exception("Failed to load key bindings from database")

    def _begin_capture(self, target_field: str) -> None:
        btn = (
            self.toggle_key_btn if target_field == "toggle_key" else self.sprint_key_btn
        )
        lbl = (
            self.toggle_key_label
            if target_field == "toggle_key"
            else self.sprint_key_label
        )

        lbl.setText("Press any key (Esc to cancel)...")
        btn.setEnabled(False)

        def on_captured(key_name: str | None):
            if self._active_filter is not None:
                self.removeEventFilter(self._active_filter)
                self._active_filter = None
            btn.setEnabled(True)

            if key_name:
                try:
                    store.settings.update(**{target_field: key_name})
                    if self.dispatcher:
                        self.dispatcher.dispatch(MapperEvent(action="ON_CONFIG_RELOAD"))
                    logger.info("Bound %s to key '%s'", target_field, key_name)
                except Exception as exc:
                    logger.exception(
                        "Failed to update key binding for %s", target_field
                    )
                    QMessageBox.critical(
                        self, "Error", f"Could not save key binding:\n{exc}"
                    )
            self.load_bindings()

        self._active_filter = KeyCaptureFilter(on_captured, self)
        self.installEventFilter(self._active_filter)
        self.setFocus()

    @staticmethod
    def _paired_row(label: QLabel, button: QPushButton) -> QWidget:
        wrapper = QWidget()
        row = QHBoxLayout(wrapper)
        row.setContentsMargins(0, 0, 0, 0)
        row.addWidget(label)
        row.addWidget(button)
        row.addStretch()
        return wrapper
