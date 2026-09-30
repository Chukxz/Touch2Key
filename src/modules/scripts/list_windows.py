from __future__ import annotations

import logging
import queue
import threading
from typing import Optional

from modules.platforms import get_platform
from modules.utils import WINDOWS_HEADERS

logger = logging.getLogger("modules.platforms.windows.select_window")

REFRESH_INTERVAL_SECONDS = 1.0


def _gather_window_rows(window_manager) -> dict[int, list]:
    """Collect visible windows with non-zero dimensions, keyed by window id."""
    visible = window_manager.find_visible_windows()
    rows: dict[int, list] = {}
    for window_id, meta in visible.items():
        left, top = window_manager.get_window_position(window_id)
        width, height = window_manager.get_window_dimensions(window_id)
        if width == 0 or height == 0:
            continue
        rows[window_id] = [window_id, meta["title"], meta["class_name"], left, top, width, height]
    return rows


# ==========================================
# CLI Headless Query Engine
# ==========================================


def _print_window_table(rows: dict[int, list]) -> None:
    print("\033[2J\033[H", end="")  # clear screen, cursor home
    print("[?] Select target window (auto-refreshing every 1s, 'q' to abort):\n")
    if not rows:
        print("    [!] No visible windows detected.")
    else:
        print("    " + " | ".join(f"{h:<12}" for h in WINDOWS_HEADERS))
        for row in rows.values():
            print("    " + " | ".join(f"{str(v):<12}" for v in row))
    print("\n>> Enter window # + Enter to select, 'q' + Enter to abort: ", end="", flush=True)


def _stdin_reader(input_queue: "queue.Queue[str]") -> None:
    """Runs on a daemon thread; blocks on input() and forwards each line."""
    while True:
        try:
            line = input()
        except (EOFError, KeyboardInterrupt):
            input_queue.put("q")
            return
        input_queue.put(line.strip().lower())


def _select_window_cli() -> Optional[tuple[int, str]]:
    window_manager = get_platform().WindowManager()
    input_queue: "queue.Queue[str]" = queue.Queue()

    reader = threading.Thread(target=_stdin_reader, args=(input_queue,), daemon=True)
    reader.start()

    rows: dict[int, list] = {}

    try:
        while True:
            rows = _gather_window_rows(window_manager)
            _print_window_table(rows)

            try:
                choice = input_queue.get(timeout=REFRESH_INTERVAL_SECONDS)
            except queue.Empty:
                continue

            if choice == "q":
                return None
            if choice == "":
                continue

            try:
                window_id = int(choice)
            except ValueError:
                logger.warning("Invalid input: %r", choice)
                continue

            if window_id not in rows:
                logger.warning("Window # %s is not in the current list.", window_id)
                continue

            title = rows[window_id][1]
            logger.info("Window selected: %s (%s)", window_id, title)
            return window_id, title
    except KeyboardInterrupt:
        logger.info("Window selection cancelled.")
        return None


# ==========================================
# GUI Dialog Implementation
# ==========================================


def _create_gui_dialog():
    from PySide6.QtCore import Qt, QTimer
    from PySide6.QtGui import QFont
    from PySide6.QtWidgets import (
        QAbstractItemView,
        QDialog,
        QHeaderView,
        QPushButton,
        QTableWidget,
        QTableWidgetItem,
        QVBoxLayout,
    )

    class ListApp(QDialog):

        def __init__(self, parent=None):
            super().__init__(parent)
            self.setWindowTitle("Select Target Window")
            self.selected_window_id = None
            self.selected_window_title: str = ""

            self.v_layout = QVBoxLayout()

            self.table = QTableWidget()
            self.table.setColumnCount(len(WINDOWS_HEADERS))
            self.table.setHorizontalHeaderLabels(WINDOWS_HEADERS)
            self.table.setFont(QFont("Courier", 10))

            header = self.table.horizontalHeader()
            header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
            header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
            header.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
            header.setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
            header.setSectionResizeMode(4, QHeaderView.ResizeMode.ResizeToContents)
            header.setSectionResizeMode(5, QHeaderView.ResizeMode.ResizeToContents)
            header.setSectionResizeMode(6, QHeaderView.ResizeMode.ResizeToContents)

            self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
            self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
            self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
            self.table.verticalHeader().setVisible(False)

            self.table.cellActivated.connect(lambda row, col: self._handle_enter())

            self.v_layout.addWidget(self.table)

            self.enter_btn = QPushButton("Confirm Selection")
            self.enter_btn.clicked.connect(self._handle_enter)
            self.v_layout.addWidget(self.enter_btn)

            self.setLayout(self.v_layout)
            self.resize(900, 500)

            self.windows_id_mapping: dict[int, int] = {}
            self.main_store: set[int] = set()
            self.windows_data: dict[int, list] = {}
            self.window_manager = get_platform().WindowManager()

            self.timer = QTimer()
            self.timer.timeout.connect(self._update_list)
            self.timer.start(int(REFRESH_INTERVAL_SECONDS * 1000))

        def _get_windows_data(self):
            self.windows_data = _gather_window_rows(self.window_manager)
            tmp_store = set(self.windows_data.keys())

            added = tmp_store - self.main_store
            removed = self.main_store - tmp_store
            self.main_store = tmp_store
            return list(added), list(removed), list(self.main_store)

        def _update_list(self):
            added_ids, removed_ids, current_ids = self._get_windows_data()

            for window_id in removed_ids:
                deletion_index = self.windows_id_mapping.pop(window_id, None)
                if deletion_index is None:
                    continue
                self.table.removeRow(deletion_index)
                for wid, idx in self.windows_id_mapping.items():
                    if idx > deletion_index:
                        self.windows_id_mapping[wid] = idx - 1

            for window_id in added_ids:
                row = self.table.rowCount()
                self.table.insertRow(row)
                data = self.windows_data[window_id]
                for col_idx, value in enumerate(data):
                    item = QTableWidgetItem(str(value))
                    if col_idx == 0:
                        item.setData(Qt.ItemDataRole.UserRole, window_id)
                    self.table.setItem(row, col_idx, item)
                self.windows_id_mapping[window_id] = row

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
            if row < 0:
                return

            id_item = self.table.item(row, 0)
            title_item = self.table.item(row, 1)

            self.selected_window_id = id_item.data(Qt.ItemDataRole.UserRole) if id_item else None
            self.selected_window_title = title_item.text() if title_item else ""

            self.done(QDialog.DialogCode.Accepted)

    return ListApp


def _select_window_gui(parent=None) -> Optional[tuple[int, str]]:
    ListApp = _create_gui_dialog()
    dialog = ListApp(parent=parent)
    dialog.exec()
    dialog.timer.stop()
    if dialog.selected_window_id is None:
        return None
    return dialog.selected_window_id, dialog.selected_window_title


def select_window(parent=None) -> Optional[tuple[int, str]]:
    """Dual-mode window query. Automatically selects between CLI prompt and Qt Dialog."""
    try:
        from PySide6.QtWidgets import QApplication
        if QApplication.instance() is not None:
            return _select_window_gui(parent=parent)
    except ImportError:
        pass

    return _select_window_cli()
