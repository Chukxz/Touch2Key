from __future__ import annotations

from typing import TYPE_CHECKING
from PySide6.QtGui import Qt, QFont
from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget, QScrollArea

if TYPE_CHECKING:
    from modules.utils import MapperEventDispatcher


class BasePage(QWidget):
    """Common foundation for sidebar pages: title header, standard margins,
    a global scroll area, and a lifecycle hook when switched to.
    """

    title = "Page"

    def __init__(
        self,
        dispatcher: MapperEventDispatcher | None = None,
        parent: QWidget | None = None,
    ):
        super().__init__(parent)
        self.dispatcher = dispatcher

        # Main layout for the page widget itself (houses the scroll area)
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        # Global Scroll Area
        scroll_area = QScrollArea(self)
        scroll_area.setWidgetResizable(True)
        scroll_area.setFrameShape(QScrollArea.Shape.NoFrame)
        scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        scroll_area.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)

        # Container widget inside the scroll area to hold the page content
        container = QWidget()
        self._content_layout = QVBoxLayout(container)
        self._content_layout.setContentsMargins(16, 16, 16, 16)
        self._content_layout.setSpacing(12)

        heading = QLabel(self.title)
        heading.setFont(QFont(heading.font().family(), 14, QFont.Weight.DemiBold))
        self._content_layout.addWidget(heading)

        scroll_area.setWidget(container)
        main_layout.addWidget(scroll_area)

    def content_layout(self) -> QVBoxLayout:
        return self._content_layout

    def on_page_shown(self) -> None:
        """Invoked when the user navigates to this page."""
        pass