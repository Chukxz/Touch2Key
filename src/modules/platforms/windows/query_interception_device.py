from __future__ import annotations

import logging
import re
from typing import Optional
from interception.constants import FilterKeyFlag, FilterMouseButtonFlag, KeyFlag
from interception.interception import Interception
from modules.utils import MODIFIER_KEYS, get_scancode_from_key

logger = logging.getLogger("modules.platforms.windows.query_interception_device")

DEVICE_HEADERS = ["Device ID", "VID", "PID", "Hardware ID"]
KEYBOARD_RANGE = range(0, 10)
MOUSE_RANGE = range(10, 20)
_MODIFIER_SCANCODES = [
    code for key in MODIFIER_KEYS if (code := get_scancode_from_key(key)) is not None
]

_VID_REGEX = re.compile(r"VID[_\-]([0-9A-Fa-f]{4})", re.IGNORECASE)
_PID_REGEX = re.compile(r"PID[_\-]([0-9A-Fa-f]{4})", re.IGNORECASE)


def _extract_vid_pid(hwid: str) -> tuple[str, str]:
    """Parse VID and PID from an Interception device hardware ID."""
    vid_match = _VID_REGEX.search(hwid)
    pid_match = _PID_REGEX.search(hwid)
    vid = vid_match.group(1).upper() if vid_match else "0000"
    pid = pid_match.group(1).upper() if pid_match else "0000"
    return vid, pid


def _qualifies_stroke(stroke, is_keyboard: bool) -> bool:
    if not is_keyboard:
        return True
    if getattr(stroke, "flags", None) != KeyFlag.KEY_DOWN:
        return False
    scan_code = stroke.code & 0xFF
    return scan_code not in _MODIFIER_SCANCODES


# ==========================================
# CLI Headless Query Engine
# ==========================================


def _select_device_cli(
    context: Interception,
    device_range: range,
    is_keyboard: bool,
    prompt: str,
) -> int | None:
    print(f"\n[?] {prompt}")
    print("Available devices detected in registry:\n")

    rows: list[list] = []
    for dev in device_range:
        raw_hwid = context.devices[dev].get_HWID()
        if raw_hwid:
            clean = raw_hwid.split("\x00")[0].strip()
            vid, pid = _extract_vid_pid(clean)
            rows.append([dev, vid, pid, clean])

    if not rows:
        print("    [!] No devices actively registered in this category.")
    else:
        print(f"    {'Device ID':<10} │ {'VID':<9} │ {'PID':<9} │ {'Hardware ID'}")
        print(f"    {'─' * 10}┼{'─' * 11}┼{'─' * 11}┼{'─' * 20}")
        for dev_id, vid, pid, clean in rows:
            print(f"    {str(dev_id):<10} │ {vid:<9} │ {pid:<9} │ {clean}")

    print(
        "\n>> Press a physical key/button on the target device (or enter device # manually, 'q' to abort): "
    )

    target_filter_fn = context.is_keyboard if is_keyboard else context.is_mouse
    other_filter_fn = context.is_mouse if is_keyboard else context.is_keyboard
    active_flag = (
        FilterKeyFlag.FILTER_KEY_DOWN
        if is_keyboard
        else FilterMouseButtonFlag.FILTER_MOUSE_LEFT_BUTTON_DOWN
    )

    try:
        context.set_filter(target_filter_fn, active_flag)
        context.set_filter(other_filter_fn, 0)
    except Exception as exc:
        print(f"[!] Failed to bind interception filters: {exc}")
        return None

    try:
        while True:
            dev = context.await_input(150)
            if dev is not None:
                stroke = context.devices[dev].receive()
                if stroke is not None:
                    context.send(dev, stroke)
                    if dev in device_range and _qualifies_stroke(stroke, is_keyboard):
                        raw_hwid = context.devices[dev].get_HWID() or ""
                        clean = raw_hwid.split("\x00")[0].strip()
                        vid, pid = _extract_vid_pid(clean)
                        print(f"[+] Hardware detected: Device {dev} (VID: {vid}, PID: {pid}) -> {clean}")
                        return dev
    except KeyboardInterrupt:
        logger.info("\n[!] Input capture cancelled.")
        return None
    finally:
        try:
            context.set_filter(target_filter_fn, 0)
            context.set_filter(other_filter_fn, 0)
        except Exception:
            pass


def _select_devices_cli() -> Optional[tuple[int, int]]:
    ctx = Interception()
    try:
        k_id = _select_device_cli(
            ctx,
            KEYBOARD_RANGE,
            is_keyboard=True,
            prompt="Tap any non-modifier key on the KEYBOARD to bind:",
        )
        if k_id is None:
            return None

        m_id = _select_device_cli(
            ctx,
            MOUSE_RANGE,
            is_keyboard=False,
            prompt="Left-click on the MOUSE to bind:",
        )
        if m_id is None:
            return None

        return k_id, m_id
    finally:
        ctx.destroy()


# ==========================================
# GUI Dialog Implementation
# ==========================================


def _create_gui_dialogs(context: Interception):
    from PySide6.QtCore import Qt, QThread, Signal
    from PySide6.QtGui import QFont
    from PySide6.QtWidgets import (
        QAbstractItemView,
        QDialog,
        QHBoxLayout,
        QHeaderView,
        QLabel,
        QPushButton,
        QTableWidget,
        QTableWidgetItem,
        QVBoxLayout,
    )

    class DeviceListenerThread(QThread):
        device_detected = Signal(int, str, str, str)
        error = Signal(str)

        def __init__(
            self, ctx: Interception, dev_range: range, is_kb: bool, parent=None
        ):
            super().__init__(parent)
            self.ctx = ctx
            self.dev_range = dev_range
            self.is_kb = is_kb
            self._stop = False

        def stop(self) -> None:
            self._stop = True

        def run(self) -> None:
            target_filter = self.ctx.is_keyboard if self.is_kb else self.ctx.is_mouse
            other_filter = self.ctx.is_mouse if self.is_kb else self.ctx.is_keyboard
            active_flag = (
                FilterKeyFlag.FILTER_KEY_DOWN
                if self.is_kb
                else FilterMouseButtonFlag.FILTER_MOUSE_LEFT_BUTTON_DOWN
            )

            try:
                self.ctx.set_filter(target_filter, active_flag)
                self.ctx.set_filter(other_filter, 0)
            except Exception as exc:
                self.error.emit(str(exc))
                return

            try:
                while not self._stop:
                    dev = self.ctx.await_input(200)
                    if dev is None:
                        continue
                    stroke = self.ctx.devices[dev].receive()
                    if stroke is None:
                        continue
                    self.ctx.send(dev, stroke)
                    if dev in self.dev_range and _qualifies_stroke(stroke, self.is_kb):
                        raw = self.ctx.devices[dev].get_HWID() or ""
                        clean = raw.split("\x00")[0].strip()
                        vid, pid = _extract_vid_pid(clean)
                        self.device_detected.emit(dev, vid, pid, clean)
            except Exception as exc:
                self.error.emit(str(exc))
            finally:
                try:
                    self.ctx.set_filter(target_filter, 0)
                    self.ctx.set_filter(other_filter, 0)
                except Exception:
                    pass

    class DeviceListDialog(QDialog):
        def __init__(
            self,
            ctx: Interception,
            dev_range: range,
            is_kb: bool,
            title: str = "Select Device",
            prompt: str = "",
            parent=None,
        ):
            super().__init__(parent)
            self.setWindowTitle(title)
            self.ctx = ctx
            self.dev_range = dev_range
            self.is_kb = is_kb
            self.selected_device: Optional[int] = None
            self.selected_vid: str = ""
            self.selected_pid: str = ""
            self.selected_hwid: str = ""

            layout = QVBoxLayout(self)
            if prompt:
                layout.addWidget(QLabel(prompt))

            self.status_label = QLabel("Listening for input...")
            layout.addWidget(self.status_label)

            self.table = QTableWidget(self)
            self.table.setColumnCount(len(DEVICE_HEADERS))
            self.table.setHorizontalHeaderLabels(DEVICE_HEADERS)
            self.table.setFont(QFont("Courier", 9))

            header = self.table.horizontalHeader()
            header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
            header.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
            header.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
            header.setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)

            self.table.setSelectionBehavior(
                QAbstractItemView.SelectionBehavior.SelectRows
            )
            self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
            self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
            self.table.verticalHeader().setVisible(False)
            layout.addWidget(self.table)

            btn_row = QHBoxLayout()
            refresh_btn = QPushButton("Refresh List")
            refresh_btn.clicked.connect(self._populate)
            confirm_btn = QPushButton("Confirm Selection")
            confirm_btn.clicked.connect(self._handle_confirm)
            btn_row.addWidget(refresh_btn)
            btn_row.addWidget(confirm_btn)
            layout.addLayout(btn_row)

            self.resize(720, 420)
            self._populate()

            self.listener = DeviceListenerThread(ctx, dev_range, is_kb, self)
            self.listener.device_detected.connect(self._on_detected)
            self.listener.start()

        def _populate(self) -> None:
            self.table.setRowCount(0)
            for dev in self.dev_range:
                raw = self.ctx.devices[dev].get_HWID()
                if not raw:
                    continue
                clean = raw.split("\x00")[0].strip()
                vid, pid = _extract_vid_pid(clean)

                row = self.table.rowCount()
                self.table.insertRow(row)

                item_id = QTableWidgetItem(str(dev))
                item_id.setData(Qt.ItemDataRole.UserRole, dev)
                self.table.setItem(row, 0, item_id)
                self.table.setItem(row, 1, QTableWidgetItem(vid))
                self.table.setItem(row, 2, QTableWidgetItem(pid))
                self.table.setItem(row, 3, QTableWidgetItem(clean))

        def _on_detected(self, dev: int, vid: str, pid: str, hwid: str) -> None:
            for r in range(self.table.rowCount()):
                item = self.table.item(r, 0)
                if item is not None and item.data(Qt.ItemDataRole.UserRole) == dev:
                    self.table.selectRow(r)
                    break
            self.status_label.setText(
                f"Detected: Device #{dev} | VID: {vid} | PID: {pid} ({hwid[:35]}...)"
            )

        def _handle_confirm(self) -> None:
            row = self.table.currentRow()
            if row >= 0:
                device_item = self.table.item(row, 0)
                vid_item = self.table.item(row, 1)
                pid_item = self.table.item(row, 2)
                hwid_item = self.table.item(row, 3)

                if device_item is not None:
                    self.selected_device = device_item.data(Qt.ItemDataRole.UserRole)
                else:
                    self.selected_device = None
                    logger.info("\n[!] Device could not be gotten.")

                self.selected_vid = vid_item.text() if vid_item is not None else "0000"
                self.selected_pid = pid_item.text() if pid_item is not None else "0000"

                if hwid_item is not None:
                    self.selected_hwid = hwid_item.text()
                else:
                    self.selected_hwid = ""
                    logger.info("\n[!] HWID could not be gotten.")

                self.done(QDialog.DialogCode.Accepted)

        def closeEvent(self, event) -> None:
            if self.listener.isRunning():
                self.listener.stop()
                self.listener.wait(400)
            super().closeEvent(event)

    return DeviceListDialog


def _select_devices_gui(parent=None) -> Optional[tuple[int, int]]:
    from PySide6.QtWidgets import QDialog

    ctx = Interception()
    DeviceListDialog = _create_gui_dialogs(ctx)
    try:
        kb_dlg = DeviceListDialog(
            ctx,
            KEYBOARD_RANGE,
            is_kb=True,
            title="Configure Keyboard Device",
            prompt="Tap any physical key on the keyboard you wish to bind:",
            parent=parent,
        )
        if kb_dlg.exec() != QDialog.DialogCode.Accepted:
            return None
        kb_device = kb_dlg.selected_device

        mouse_dlg = DeviceListDialog(
            ctx,
            MOUSE_RANGE,
            is_kb=False,
            title="Configure Mouse Device",
            prompt="Click left mouse button on the device you wish to bind:",
            parent=parent,
        )
        if mouse_dlg.exec() != QDialog.DialogCode.Accepted:
            return None
        mouse_device = mouse_dlg.selected_device

        if kb_device is not None and mouse_device is not None:
            return kb_device, mouse_device
        return None
    finally:
        ctx.destroy()


def select_keyboard_then_mouse(parent=None) -> Optional[tuple[int, int]]:
    """Dual-mode device query. Automatically selects between CLI prompt and Qt Dialog."""
    try:
        from PySide6.QtWidgets import QApplication

        if QApplication.instance() is not None:
            return _select_devices_gui(parent=parent)
    except ImportError:
        pass

    return _select_devices_cli()