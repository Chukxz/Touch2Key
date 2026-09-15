from __future__ import annotations

from typing import TYPE_CHECKING
from PySide6.QtCore import QTimer, Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
)

from modules.platforms import get_platform
from modules.utils import WINDOWS_HEADERS
from .base_page import BasePage

if TYPE_CHECKING:
    from modules.utils import MapperEventDispatcher


class DevicesPage(BasePage):
    """Dynamic, non-blocking visible window monitor and ADB target selector."""

    title = "Devices"

    def __init__(
        self,
        dispatcher: MapperEventDispatcher | None = None,
        parent=None,
    ):
        super().__init__(dispatcher, parent)
        self.selected_window_id: int | None = None
        self.selected_window_title: str = ""

        self.window_manager = get_platform().WindowManager()
        self.windows_id_mapping: dict[int, int] = {}
        self.main_store: set[int] = set()
        self.tmp_store: set[int] = set()
        self.windows_data: dict[int, list] = {}

        self.status_label = QLabel("Selected Target: None")
        self.status_label.setStyleSheet("font-weight: bold; color: palette(highlight);")
        self.content_layout().addWidget(self.status_label)

        self.table = QTableWidget()
        self.table.setColumnCount(len(WINDOWS_HEADERS))
        self.table.setHorizontalHeaderLabels(WINDOWS_HEADERS)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)

        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(4, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(5, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(6, QHeaderView.ResizeMode.ResizeToContents)

        self.content_layout().addWidget(self.table)

        btn_row = QHBoxLayout()
        self.refresh_btn = QPushButton("Refresh Windows")
        self.select_btn = QPushButton("Bind Target Window")
        self.connect_wireless_btn = QPushButton("Connect Wirelessly (ADB)")

        btn_row.addWidget(self.refresh_btn)
        btn_row.addWidget(self.select_btn)
        btn_row.addWidget(self.connect_wireless_btn)
        self.content_layout().addLayout(btn_row)

        self.table.itemSelectionChanged.connect(self._on_row_selected)
        self.select_btn.clicked.connect(self._on_row_selected)
        self.refresh_btn.clicked.connect(self._update_list)

        self.poll_timer = QTimer(self)
        self.poll_timer.timeout.connect(self._update_list)
        self.poll_timer.start(1500)

    def on_page_shown(self) -> None:
        self._update_list()

    def _on_row_selected(self) -> None:
        row = self.table.currentRow()
        if row >= 0:
            id_item = self.table.item(row, 0)
            title_item = self.table.item(row, 1)
            if id_item and title_item:
                self.selected_window_id = id_item.data(Qt.ItemDataRole.UserRole)
                self.selected_window_title = title_item.text()
                self.status_label.setText(
                    f"Selected Target: {self.selected_window_title} (HWND: {self.selected_window_id})"
                )

    def _update_list(self) -> None:
        visible = self.window_manager.find_visible_windows()
        self.windows_data.clear()
        self.tmp_store.clear()

        for window_id, meta in visible.items():
            left, top = self.window_manager.get_window_position(window_id)
            width, height = self.window_manager.get_window_dimensions(window_id)
            if width == 0 or height == 0:
                continue

            self.tmp_store.add(window_id)
            self.windows_data[window_id] = [
                window_id,
                meta["title"],
                meta["class_name"],
                left,
                top,
                width,
                height,
            ]

        added = self.tmp_store - self.main_store
        removed = self.main_store - self.tmp_store
        self.main_store = set(self.tmp_store)

        for window_id in removed:
            del_idx = self.windows_id_mapping.pop(window_id, None)
            if del_idx is not None:
                self.table.removeRow(del_idx)
                for wid, idx in self.windows_id_mapping.items():
                    if idx > del_idx:
                        self.windows_id_mapping[wid] = idx - 1

        for window_id in added:
            row = self.table.rowCount()
            self.table.insertRow(row)
            data = self.windows_data[window_id]
            for col_idx, val in enumerate(data):
                item = QTableWidgetItem(str(val))
                if col_idx == 0:
                    item.setData(Qt.ItemDataRole.UserRole, window_id)
                self.table.setItem(row, col_idx, item)
            self.windows_id_mapping[window_id] = row