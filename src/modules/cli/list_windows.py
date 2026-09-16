from __future__ import annotations

from PySide6.QtWidgets import (
    QDialog,
    QVBoxLayout,
    QTableWidget,
    QTableWidgetItem,
    QPushButton,
    QHeaderView,
    QAbstractItemView,
)
from PySide6.QtCore import QTimer, Qt
from PySide6.QtGui import QFont

from modules.platforms import get_platform
from modules.utils import WINDOWS_HEADERS


class ListApp(QDialog):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Select Target Window")
        self.selected_window_id = None
        self.selected_window_title: str = ""

        self.v_layout = QVBoxLayout()

        # Initialize QTableWidget instead of QListWidget/QLabel
        self.table = QTableWidget()
        self.table.setColumnCount(len(WINDOWS_HEADERS))
        self.table.setHorizontalHeaderLabels(WINDOWS_HEADERS)
        self.table.setFont(QFont("Courier", 10))

        # Configure Responsive Headers
        header = self.table.horizontalHeader()

        # Make the 'Title' and 'Class Name' columns (indexes 1 and 2) stretch to fill empty space
        # Make the other columns resize interactively or snap to content
        header.setSectionResizeMode(
            0, QHeaderView.ResizeMode.ResizeToContents
        )  # Window_ID
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)  # Title
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)  # Class Name
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)  # Left
        header.setSectionResizeMode(4, QHeaderView.ResizeMode.ResizeToContents)  # Top
        header.setSectionResizeMode(5, QHeaderView.ResizeMode.ResizeToContents)  # Width
        header.setSectionResizeMode(
            6, QHeaderView.ResizeMode.ResizeToContents
        )  # Height

        # Configure Table Behavior to act like a List Selection
        self.table.setSelectionBehavior(
            QAbstractItemView.SelectionBehavior.SelectRows
        )  # Select whole row
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setEditTriggers(
            QAbstractItemView.EditTrigger.NoEditTriggers
        )  # Prevent user editing cells
        self.table.verticalHeader().setVisible(False)  # Hide row numbers

        # Enter/Return on a selected row confirms it, same as clicking the button
        self.table.cellActivated.connect(lambda row, col: self._handle_enter())

        self.v_layout.addWidget(self.table)

        self.enter_btn = QPushButton("Confirm Selection")
        self.enter_btn.clicked.connect(self._handle_enter)
        self.v_layout.addWidget(self.enter_btn)

        self.setLayout(self.v_layout)
        self.resize(900, 500)

        self.windows_id_mapping: dict[int, int] = {}
        self.main_store: set[int] = set()
        self.tmp_store: set[int] = set()
        self.windows_data: dict[int, list] = {}
        self.window_manager = get_platform().WindowManager()

        self.timer = QTimer()
        self.timer.timeout.connect(self._update_list)
        self.timer.start(1000)

    def _get_windows_data(self):
        visible = self.window_manager.find_visible_windows()  # single pass
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
        self.main_store.clear()
        self.main_store.update(self.tmp_store)
        return list(added), list(removed), list(self.main_store)

    def _update_list(self):
        added_ids, removed_ids, current_ids = self._get_windows_data()

        # Handle Removals
        for window_id in removed_ids:
            deletion_index = self.windows_id_mapping.pop(window_id, None)
            if deletion_index is None:
                continue

            self.table.removeRow(deletion_index)

            # Shift mappings down for rows below the deleted one
            for wid, idx in self.windows_id_mapping.items():
                if idx > deletion_index:
                    self.windows_id_mapping[wid] = idx - 1

        # Handle Additions
        for window_id in added_ids:
            row = self.table.rowCount()
            self.table.insertRow(row)
            data = self.windows_data[window_id]

            # Populate table cells
            for col_idx, value in enumerate(data):
                item = QTableWidgetItem(str(value))
                if col_idx == 0:
                    # Store the ID secretly in the first column's data role
                    item.setData(Qt.ItemDataRole.UserRole, window_id)
                self.table.setItem(row, col_idx, item)

            self.windows_id_mapping[window_id] = row

        # Handle Editing
        for window_id in current_ids:
            row_index = self.windows_id_mapping.get(window_id)
            if row_index is None:
                continue
            data = self.windows_data.get(window_id)
            if data is None:
                continue

            for col_idx, value in enumerate(data):
                item = self.table.item(row_index, col_idx)
                if item is None:
                    continue
                new_text = str(value)
                if item.text() != new_text:
                    item.setText(new_text)

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Escape:
            self.reject()
            return
        super().keyPressEvent(event)

    def _handle_enter(self):
        row = self.table.currentRow()
        if row < 0:  # No row selected
            return

        # Retrieve data directly from the table items
        id_item = self.table.item(row, 0)
        title_item = self.table.item(row, 1)

        if id_item:
            self.selected_window_id = id_item.data(Qt.ItemDataRole.UserRole)
        else:
            self.selected_window_id = None

        if title_item:
            self.selected_window_title = title_item.text()
        else:
            self.selected_window_title = ""

        self.done(QDialog.DialogCode.Accepted)


def select_window() -> tuple[int, str] | None:
    dialog = ListApp()
    dialog.exec_()
    dialog.timer.stop()
    if dialog.selected_window_id is None:
        return None
    return dialog.selected_window_id, dialog.selected_window_title