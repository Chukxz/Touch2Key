# src/modules/gui/pages/base_page.py
from __future__ import annotations
from typing import TYPE_CHECKING
from PySide6.QtWidgets import QWidget, QVBoxLayout, QLabel
from PySide6.QtGui import QFont

if TYPE_CHECKING:
    from modules.utils import MapperEventDispatcher

class BasePage(QWidget):
    title = "Page"

    def __init__(self, dispatcher: MapperEventDispatcher | None = None, parent: QWidget | None = None):
        super().__init__(parent)
        self.dispatcher = dispatcher
        self._root_layout = QVBoxLayout(self)
        self._root_layout.setContentsMargins(16, 16, 16, 16)
        self._root_layout.setSpacing(12)

        heading = QLabel(self.title)
        heading.setFont(QFont(heading.font().family(), 14, QFont.Weight.DemiBold))
        self._root_layout.addWidget(heading)

    def content_layout(self) -> QVBoxLayout:
        return self._root_layout

    def on_page_shown(self) -> None:
        """Override in subclasses to reload data when the user switches tabs."""
        pass