from __future__ import annotations

from PySide6.QtWidgets import QLabel, QPushButton, QHBoxLayout

from .base_page import BasePage


class LayoutEditorPage(BasePage):
    """Placeholder for the zone canvas from the sqlite migration plan:
    renders layout_zones for the active layout over a captured
    reference screenshot, with click-to-select and drag-to-resize per
    zone. This stub wires the toolbar only -- the canvas widget (most
    likely a QGraphicsView/QGraphicsScene subclass, one QGraphicsItem
    per zone) is the next real build step, not something to fake here."""

    title = "Layout editor"

    def __init__(self, parent=None):
        super().__init__(parent)

        toolbar_row = QHBoxLayout()
        self.capture_btn = QPushButton("Capture reference screenshot")
        self.new_zone_btn = QPushButton("Add zone")
        toolbar_row.addWidget(self.capture_btn)
        toolbar_row.addWidget(self.new_zone_btn)
        toolbar_row.addStretch()
        self.content_layout().addLayout(toolbar_row)

        self.canvas_placeholder = QLabel("Zone canvas goes here (QGraphicsView).")
        self.canvas_placeholder.setMinimumHeight(320)
        self.canvas_placeholder.setStyleSheet("border: 1px dashed palette(mid);")
        self.content_layout().addWidget(self.canvas_placeholder)
