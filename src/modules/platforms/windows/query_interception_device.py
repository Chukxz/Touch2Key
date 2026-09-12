from __future__ import annotations

from typing import Optional

from PySide6.QtWidgets import (
    QDialog,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QTableWidget,
    QTableWidgetItem,
    QPushButton,
    QHeaderView,
    QAbstractItemView,
)
from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtGui import QFont

from interception.interception import Interception
from interception.constants import FilterKeyFlag, FilterMouseButtonFlag, KeyFlag

DEVICE_HEADERS = ["Device #", "Hardware ID"]

# Interception numbers keyboards 0-9 and mice 10-19 (both ranges exclusive of
# the upper bound), matching the numbering used by auto_capture_devices.
KEYBOARD_RANGE = range(0, 10)
MOUSE_RANGE = range(10, 20)

# Standard PS/2 set-1 scan codes for ctrl/shift/alt (left + right variants
# share the base code; the E0 prefix bit is stripped by the caller before
# this comparison).
_MODIFIER_SCANCODES = {0x1D, 0x2A, 0x36, 0x38}


class DeviceListenerThread(QThread):
    """Listens on the interception context for input from devices in
    `device_range` and emits `device_detected(device_num, hwid)` the moment
    it sees a qualifying stroke from one of them - a KEY_DOWN (non-modifier)
    for keyboards, a left-button-down for mice.

    Every stroke it reads is forwarded back with `context.send()` so input
    is never eaten from the user's session, regardless of whether it came
    from an in-range device or not.

    `Interception.await_input(timeout_milliseconds=-1)` genuinely accepts a
    timeout - `-1` just happens to reinterpret as `INFINITE` when passed to
    `WaitForMultipleObjects` as an unsigned DWORD. We poll on
    `poll_timeout_ms` (default 200ms) instead of relying on the infinite
    default, so `stop()` is checked regularly even with no input arriving,
    and `DeviceListDialog._shutdown_listener` can rely on `wait()` returning
    promptly rather than needing a long grace period.
    """

    device_detected = Signal(int, str)  # device_num, hwid
    error = Signal(str)

    def __init__(
        self,
        context: Interception,
        device_range: range,
        *,
        is_keyboard: bool,
        poll_timeout_ms: int = 200,
        parent=None,
    ):
        super().__init__(parent)
        self.context = context
        self.device_range = device_range
        self.is_keyboard = is_keyboard
        self.poll_timeout_ms = poll_timeout_ms
        self._stop = False

    def stop(self) -> None:
        self._stop = True

    def run(self) -> None:
        target_filter_fn = (
            self.context.is_keyboard if self.is_keyboard else self.context.is_mouse
        )
        other_filter_fn = (
            self.context.is_mouse if self.is_keyboard else self.context.is_keyboard
        )
        active_flag = (
            FilterKeyFlag.FILTER_KEY_DOWN
            if self.is_keyboard
            else FilterMouseButtonFlag.FILTER_MOUSE_LEFT_BUTTON_DOWN
        )

        try:
            self.context.set_filter(target_filter_fn, active_flag)
            self.context.set_filter(other_filter_fn, 0)
        except Exception as exc:
            self.error.emit(f"Failed to set filters: {exc}")
            return

        try:
            while not self._stop:
                device = self._await_input()
                if device is None:
                    continue  # poll timeout expired, nothing arrived - re-check _stop

                stroke = self.context.devices[device].receive()
                if stroke is None:
                    continue

                # Forward immediately regardless of range so nothing is lost.
                self.context.send(device, stroke)

                if device not in self.device_range:
                    continue

                if self._qualifies(stroke):
                    raw_hwid = self.context.devices[device].get_HWID() or ""
                    # Sanitize the C-buffer string to remove trailing junk/null bytes
                    clean_hwid = raw_hwid.split("\x00")[0].strip()
                    self.device_detected.emit(device, clean_hwid)
        except Exception as exc:
            self.error.emit(str(exc))
        finally:
            self._clear_filters(target_filter_fn, other_filter_fn)

    def _await_input(self):
        # Returns None on timeout as well as on genuine failure - both cases
        # just mean "loop again and re-check _stop", so no need to tell them
        # apart here.
        return self.context.await_input(self.poll_timeout_ms)

    def _qualifies(self, stroke) -> bool:
        if not self.is_keyboard:
            return True  # left-click filter already narrowed this to a click

        if getattr(stroke, "flags", None) != KeyFlag.KEY_DOWN:
            return False

        scan_code = stroke.code & 0xFF  # strip E0 prefix bit if present
        return scan_code not in _MODIFIER_SCANCODES

    def _clear_filters(self, *filter_fns) -> None:
        for fn in filter_fns:
            try:
                self.context.set_filter(fn, 0)
            except Exception:
                pass  # best-effort cleanup - dialog may already be closing


class DeviceListDialog(QDialog):
    """Lists interception devices in `device_range` and lets the user pick
    one, either by clicking a row directly or by pressing/clicking the
    physical device - a `DeviceListenerThread` runs for the lifetime of the
    dialog and auto-selects (but does not auto-confirm) the matching row as
    soon as it sees qualifying input from an in-range device.
    """

    def __init__(
        self,
        context: Interception,
        device_range: range,
        *,
        is_keyboard: bool,
        title: str = "Select Device",
        prompt: str = "",
    ):
        super().__init__()
        self.setWindowTitle(title)
        self.context = context
        self.device_range = device_range
        self.is_keyboard = is_keyboard
        self.selected_device: Optional[int] = None
        self.selected_hwid: str = ""

        self.v_layout = QVBoxLayout()

        if prompt:
            self.v_layout.addWidget(QLabel(prompt))

        self.status_label = QLabel("Waiting for input from the target device...")
        self.v_layout.addWidget(self.status_label)

        self.table = QTableWidget()
        self.table.setColumnCount(len(DEVICE_HEADERS))
        self.table.setHorizontalHeaderLabels(DEVICE_HEADERS)
        self.table.setFont(QFont("Courier", 10))

        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)

        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        self.table.cellActivated.connect(lambda row, col: self._handle_enter())

        self.v_layout.addWidget(self.table)

        btn_row = QHBoxLayout()
        self.refresh_btn = QPushButton("Refresh List")
        self.refresh_btn.clicked.connect(self._populate)
        self.enter_btn = QPushButton("Confirm Selection")
        self.enter_btn.clicked.connect(self._handle_enter)
        btn_row.addWidget(self.refresh_btn)
        btn_row.addWidget(self.enter_btn)
        self.v_layout.addLayout(btn_row)

        self.setLayout(self.v_layout)
        self.resize(520, 420)

        self._device_row: dict[int, int] = {}
        self._populate()

        self.listener = DeviceListenerThread(
            context, device_range, is_keyboard=is_keyboard
        )
        self.listener.device_detected.connect(self._on_device_detected)
        self.listener.error.connect(self._on_listener_error)
        self.listener.start()

    def _populate(self) -> None:
        self.table.setRowCount(0)
        self._device_row.clear()
        for device_num in self.device_range:
            raw_hwid = self.context.devices[device_num].get_HWID()
            if raw_hwid is None:
                continue
            # Sanitize the C-buffer string
            clean_hwid = raw_hwid.split("\x00")[0].strip()
            self._add_row(device_num, clean_hwid)

    def _add_row(self, device_num: int, hwid: str) -> int:
        row = self.table.rowCount()
        self.table.insertRow(row)

        num_item = QTableWidgetItem(str(device_num))
        num_item.setData(Qt.ItemDataRole.UserRole, device_num)
        self.table.setItem(row, 0, num_item)
        self.table.setItem(row, 1, QTableWidgetItem(hwid))

        self._device_row[device_num] = row
        return row

    def _on_device_detected(self, device_num: int, hwid: str) -> None:
        row = self._device_row.get(device_num)
        if row is None:
            row = self._add_row(device_num, hwid)

        self.table.selectRow(row)
        kind = "keyboard" if self.is_keyboard else "mouse"
        self.status_label.setText(
            f"Detected input from device {device_num} ({hwid[:40]}). "
            f"Press Confirm, or use the other {kind} to pick a different one."
        )

    def _on_listener_error(self, message: str) -> None:
        self.status_label.setText(f"Listener error: {message}")

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Escape:
            self.reject()
            return
        super().keyPressEvent(event)

    def _handle_enter(self) -> None:
        row = self.table.currentRow()
        if row < 0:  # No row selected
            return

        num_item = self.table.item(row, 0)
        hwid_item = self.table.item(row, 1)
        if num_item is None:
            return

        self.selected_device = num_item.data(Qt.ItemDataRole.UserRole)
        self.selected_hwid = hwid_item.text() if hwid_item else ""
        self.done(QDialog.DialogCode.Accepted)

    def _shutdown_listener(self, wait_ms: int = 600) -> None:
        """Stops the listener thread. `await_input` is polled at
        `poll_timeout_ms` (default 200ms), so `stop()` should be picked up
        and the thread should exit within roughly one poll interval; 600ms
        leaves headroom for stroke processing and filter cleanup. If it
        still hasn't stopped by then something is genuinely wrong (e.g.
        `set_filter` hanging), and the thread is left running detached
        rather than blocking the dialog close indefinitely.
        """
        if not self.listener.isRunning():
            return
        self.listener.stop()
        if not self.listener.wait(wait_ms):
            self.status_label.setText(
                "Listener did not stop cleanly and was left running in the "
                "background."
            )

    def done(self, result: int) -> None:
        self._shutdown_listener()
        super().done(result)

    def reject(self) -> None:
        self._shutdown_listener()
        super().reject()


def select_keyboard_then_mouse() -> Optional[tuple[int, int]]:
    """Shows a keyboard selection dialog, then - only if confirmed - a mouse
    selection dialog. Each dialog runs its own listener scoped to its device
    category, so a keystroke during the mouse phase (or vice versa) is
    forwarded but ignored for correlation purposes.

    Returns `(keyboard_device, mouse_device)`, or `None` if either dialog was
    cancelled (Escape / window close).
    """
    context = Interception()
    try:
        kb_dialog = DeviceListDialog(
            context,
            KEYBOARD_RANGE,
            is_keyboard=True,
            title="Select Keyboard Device",
            prompt="Press any key on the keyboard you want to bind.",
        )
        if kb_dialog.exec_() != QDialog.DialogCode.Accepted:
            return None
        keyboard_device = kb_dialog.selected_device

        mouse_dialog = DeviceListDialog(
            context,
            MOUSE_RANGE,
            is_keyboard=False,
            title="Select Mouse Device",
            prompt="Left-click with the mouse you want to bind.",
        )
        if mouse_dialog.exec_() != QDialog.DialogCode.Accepted:
            return None
        mouse_device = mouse_dialog.selected_device
    finally:
        context.destroy()

    if keyboard_device is None or mouse_device is None:
        return None
    return keyboard_device, mouse_device
