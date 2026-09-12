from __future__ import annotations

from PySide6.QtWidgets import QWidget, QVBoxLayout, QLabel
from PySide6.QtGui import QFont


class BasePage(QWidget):
    """Common chrome for every sidebar page: a title heading plus a
    vertical content layout subclasses append their widgets to. Keeps
    page styling consistent without depending on a shared stylesheet."""

    title = "Page"

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self._root_layout = QVBoxLayout(self)
        self._root_layout.setContentsMargins(16, 16, 16, 16)
        self._root_layout.setSpacing(12)

        heading = QLabel(self.title)
        heading.setFont(QFont(heading.font().family(), 14, QFont.Weight.DemiBold))
        self._root_layout.addWidget(heading)

    def content_layout(self) -> QVBoxLayout:
        """Subclasses add their widgets via this layout, below the heading."""
        return self._root_layout
