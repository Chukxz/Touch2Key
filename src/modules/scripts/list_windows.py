from __future__ import annotations

import logging
import sys
import time
import os
from typing import Optional

from modules.platforms import get_platform
from modules.utils import WINDOWS_HEADERS

logger = logging.getLogger("modules.platforms.windows.select_window")

REFRESH_INTERVAL_SECONDS = 1.0

# Platform-specific imports for non-blocking console input
if sys.platform == "win32":
    import msvcrt
else:
    import select
    import termios
    import tty


def _gather_window_rows(window_manager) -> dict[int, list]:
    """Collect visible windows with non-zero dimensions, keyed by window id."""
    visible = window_manager.find_visible_windows()
    rows: dict[int, list] = {}
    for window_id, meta in visible.items():
        left, top = window_manager.get_window_position(window_id)
        width, height = window_manager.get_window_dimensions(window_id)
        if width == 0 or height == 0:
            continue
        rows[window_id] = [
            window_id,
            meta["title"],
            meta["class_name"],
            left,
            top,
            width,
            height,
        ]
    return rows


def _print_window_table(
    rows: dict[int, list], current_input: str = "", last_warning: str = ""
) -> str:
    # Use native OS command for clean terminal clearing on both Windows and Linux
    os.system("cls" if sys.platform == "win32" else "clear")
    table_str = ""

    table_str += "[?] Select target window (auto-refreshing every 1s, 'q' to abort):\n"
    if not rows:
        table_str += "    [!] No visible windows detected.\n"
    else:
        header_str = " | ".join(
            [
                f"{WINDOWS_HEADERS[0]:<10}",
                f"{WINDOWS_HEADERS[1]:<35}",
                f"{WINDOWS_HEADERS[2]:<25}",
                f"{WINDOWS_HEADERS[3]:<6}",
                f"{WINDOWS_HEADERS[4]:<6}",
                f"{WINDOWS_HEADERS[5]:<6}",
                f"{WINDOWS_HEADERS[6]:<6}",
            ]
        )

        table_str += f"    {header_str}\n"
        table_str += "    " + "-" * len(header_str) + "\n"

        for row in rows.values():
            wid, title, cls_name, left, top, width, height = row

            safe_title = (title[:32] + "...") if len(title) > 35 else title
            safe_cls = (cls_name[:22] + "...") if len(cls_name) > 25 else cls_name

            row_str = " | ".join(
                [
                    f"{wid:<10}",
                    f"{safe_title:<35}",
                    f"{safe_cls:<25}",
                    f"{left:<6}",
                    f"{top:<6}",
                    f"{width:<6}",
                    f"{height:<6}",
                ]
            )
            table_str += f"    {row_str}\n"

    print(table_str + last_warning)

    print(
        f"\n>> Enter window # + Enter to select, 'q' + Enter to abort: {current_input}",
        end="",
        flush=True,
    )

    return table_str


def _poll_key_windows() -> tuple[Optional[str], Optional[str]]:
    """Non-blocking key check for Windows."""
    if msvcrt.kbhit():
        ch = msvcrt.getch()
        if ch in (b"\r", b"\n"):
            return "enter", None
        elif ch in (b"\x08", b"\x7f"):  # Backspace
            return "backspace", None
        elif ch == b"\x03":  # Ctrl+C
            raise KeyboardInterrupt
        else:
            try:
                decoded = ch.decode("utf-8", errors="ignore")
                if decoded.isprintable():
                    return "char", decoded
            except Exception:
                pass
    return None, None


def _poll_key_unix() -> tuple[Optional[str], Optional[str]]:
    """Non-blocking key check for Linux / macOS."""
    fd = sys.stdin.fileno()
    old_settings = termios.tcgetattr(fd)
    try:
        tty.setcbreak(fd)
        if select.select([sys.stdin], [], [], 0)[0]:
            ch = sys.stdin.read(1)
            if ch in ("\r", "\n"):
                return "enter", None
            elif ch in ("\x7f", "\b"):  # Backspace
                return "backspace", None
            elif ch == "\x03":  # Ctrl+C
                raise KeyboardInterrupt
            elif ch.isprintable():
                return "char", ch
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old_settings)
    return None, None


def _select_window_cli() -> Optional[tuple[int, str]]:
    window_manager = get_platform().WindowManager()
    buffer: list[str] = []
    is_typing = False
    table_str = ""
    last_warning = ""

    try:
        while True:
            rows = _gather_window_rows(window_manager)

            if not is_typing:
                table_str = _print_window_table(
                    rows, "".join(buffer), last_warning=last_warning
                )

            elapsed = 0.0
            while elapsed < REFRESH_INTERVAL_SECONDS:
                action, val = (
                    _poll_key_windows() if sys.platform == "win32" else _poll_key_unix()
                )

                if action == "enter":
                    print()
                    line = "".join(buffer).strip().lower()
                    if line == "q":
                        return None
                    if line == "":
                        buffer.clear()
                        is_typing = False
                        break

                    try:
                        window_id = int(line)
                    except ValueError:
                        logger.warning("Invalid input: %r", line)
                        buffer.clear()
                        is_typing = False
                        break

                    if window_id not in rows:
                        last_warning = (
                            f"Window {window_id} is not in the current list.\n"
                        )
                        logger.warning(
                            "Window # %s is not in the current list.", window_id
                        )
                        buffer.clear()
                        is_typing = False
                        break

                    title = rows[window_id][1]
                    logger.info("Window selected: %s (%s)", window_id, title)
                    return window_id, title

                elif action == "backspace":
                    if buffer:
                        buffer.pop()
                        if not buffer:
                            is_typing = False

                    os.system("cls" if sys.platform == "win32" else "clear")
                    print(table_str)
                    # Added trailing spaces ("   ") to blank out any leftover trailing characters
                    print(
                        f"\r>> Enter window # + Enter to select, 'q' + Enter to abort: {''.join(buffer)}   ",
                        end="",
                        flush=True,
                    )

                elif action == "char" and val:
                    buffer.append(val)
                    is_typing = True

                    os.system("cls" if sys.platform == "win32" else "clear")
                    print(table_str)
                    print(
                        f"\r>> Enter window # + Enter to select, 'q' + Enter to abort: {''.join(buffer)}",
                        end="",
                        flush=True,
                    )

                time.sleep(0.05)
                elapsed += 0.05

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
        QAbstractScrollArea,
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

            # Enable smooth pixel-based scrolling for both directions
            self.table.setVerticalScrollMode(QAbstractScrollArea.ScrollMode.ScrollPerPixel)
            self.table.setHorizontalScrollMode(QAbstractScrollArea.ScrollMode.ScrollPerPixel)
            
            # Ensure scrollbars appear dynamically as needed
            self.table.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
            self.table.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)

            header = self.table.horizontalHeader()
            header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
            header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
            header.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
            header.setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
            header.setSectionResizeMode(4, QHeaderView.ResizeMode.ResizeToContents)
            header.setSectionResizeMode(5, QHeaderView.ResizeMode.ResizeToContents)
            header.setSectionResizeMode(6, QHeaderView.ResizeMode.ResizeToContents)

            self.table.setSelectionBehavior(
                QAbstractItemView.SelectionBehavior.SelectRows
            )
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

            self.selected_window_id = (
                id_item.data(Qt.ItemDataRole.UserRole) if id_item else None
            )
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
