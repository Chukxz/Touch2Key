from __future__ import annotations

import sys
from typing import TYPE_CHECKING

from PySide6.QtWidgets import (
    QApplication,
    QWidget,
    QPushButton,
    QGridLayout,
    QHBoxLayout,
    QSizePolicy,
)
from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QIcon

from modules.utils import (
    LOCK_KEYS,
    M_LEFT,
    M_MIDDLE,
    M_RIGHT,
    MODIFIER_KEYS,
    TOP_BEZEL_ID,
    VKB_STRUCT,
    ICONS_FOLDER,
    get_scancode_from_key,
)

from modules import AppLogManager

from modules.platforms import get_lock_states, check_single_instance

if TYPE_CHECKING:
    from multiprocessing.connection import Connection

VKB_NAME = "Touch2Key_VKB"

# --- Main Alphanumeric Block ---
MAIN_LAYOUT = [
    [
        ("Esc", 0x01, 1),
        ("F1", 0x3B, 1),
        ("F2", 0x3C, 1),
        ("F3", 0x3D, 1),
        ("F4", 0x3E, 1),
        ("F5", 0x3F, 1),
        ("F6", 0x40, 1),
        ("F7", 0x41, 1),
        ("F8", 0x42, 1),
        ("F9", 0x43, 1),
        ("F10", 0x44, 1),
        ("F11", 0x57, 1),
        ("F12", 0x58, 1),
        ("Delete", 0xE053, 2),
    ],
    [
        ("~", 0x29, 1),
        ("1", 0x02, 1),
        ("2", 0x03, 1),
        ("3", 0x04, 1),
        ("4", 0x05, 1),
        ("5", 0x06, 1),
        ("6", 0x07, 1),
        ("7", 0x08, 1),
        ("8", 0x09, 1),
        ("9", 0x0A, 1),
        ("0", 0x0B, 1),
        ("-", 0x0C, 1),
        ("=", 0x0D, 1),
        ("Backspace", 0x0E, 2),
    ],
    [
        ("Tab", 0x0F, 2),
        ("Q", 0x10, 1),
        ("W", 0x11, 1),
        ("E", 0x12, 1),
        ("R", 0x13, 1),
        ("T", 0x14, 1),
        ("Y", 0x15, 1),
        ("U", 0x16, 1),
        ("I", 0x17, 1),
        ("O", 0x18, 1),
        ("P", 0x19, 1),
        ("[", 0x1A, 1),
        ("]", 0x1B, 1),
        ("\\", 0x2B, 1),
    ],
    [
        ("Caps Lock", 0x3A, 2),
        ("A", 0x1E, 1),
        ("S", 0x1F, 1),
        ("D", 0x20, 1),
        ("F", 0x21, 1),
        ("G", 0x22, 1),
        ("H", 0x23, 1),
        ("J", 0x24, 1),
        ("K", 0x25, 1),
        ("L", 0x26, 1),
        (";", 0x27, 1),
        ("'", 0x28, 1),
        ("Enter", 0x1C, 2),
    ],
    [
        ("Shift", 0x2A, 2),
        ("Z", 0x2C, 1),
        ("X", 0x2D, 1),
        ("C", 0x2E, 1),
        ("V", 0x2F, 1),
        ("B", 0x30, 1),
        ("N", 0x31, 1),
        ("M", 0x32, 1),
        (",", 0x33, 1),
        (".", 0x34, 1),
        ("/", 0x35, 1),
        ("Shift", 0x36, 3),
    ],
    [
        ("Ctrl", 0x1D, 2),
        ("Alt", 0x38, 2),
        ("Space", 0x39, 7),
        ("Alt", 0xE038, 2),
        ("Ctrl", 0xE01D, 2),
    ],
]

# --- Navigation & Arrows Block ---
NAV_LAYOUT = [
    ("Insert", 0xE052, 0, 0, 1, 3),
    ("PrtSc", 0xE037, 0, 3, 1, 3),
    ("PgUp", 0xE049, 1, 2, 1, 2),
    ("Home", 0xE047, 2, 0, 1, 2),
    ("PgDn", 0xE051, 2, 2, 1, 2),
    ("End", 0xE04F, 2, 4, 1, 2),
    ("Up", 0xE048, 3, 2, 1, 2),
    ("Left", 0xE04B, 4, 0, 1, 2),
    ("Down", 0xE050, 4, 2, 1, 2),
    ("Right", 0xE04D, 4, 4, 1, 2),
    ("M_L", M_LEFT, 5, 0, 1, 2),
    ("M_Mid", M_MIDDLE, 5, 2, 1, 2),
    ("M_R", M_RIGHT, 5, 4, 1, 2),
]

# --- Numpad Block ---
NUMPAD_LAYOUT = [
    ("Toggle Cursor", TOP_BEZEL_ID, 0, 0, 1, 4),
    ("7", 0x47, 1, 0, 1, 1),
    ("8", 0x48, 1, 1, 1, 1),
    ("9", 0x49, 1, 2, 1, 1),
    ("/", 0xE035, 1, 3, 1, 1),
    ("4", 0x4B, 2, 0, 1, 1),
    ("5", 0x4C, 2, 1, 1, 1),
    ("6", 0x4D, 2, 2, 1, 1),
    ("*", 0x37, 2, 3, 1, 1),
    ("1", 0x4F, 3, 0, 1, 1),
    ("2", 0x50, 3, 1, 1, 1),
    ("3", 0x51, 3, 2, 1, 1),
    ("-", 0x4A, 3, 3, 1, 1),
    ("Num\nLock", 0x45, 4, 0, 2, 1),
    ("0", 0x52, 4, 1, 1, 1),
    (".", 0x53, 4, 2, 1, 1),
    ("+", 0x4E, 4, 3, 1, 1),
    ("Scroll Lock", 0x46, 5, 1, 1, 2),
    ("Enter", 0xE01C, 5, 3, 1, 1),
]


class VirtualKeyButton(QPushButton):
    """Custom button that emits key_codes and explicitly ignores OS focus."""

    LONG_PRESS_INTERVAL_MS = 300

    def __init__(
        self,
        key_label: str,
        key_code: int,
        mod_codes: list[int],
        parent_ref: VirtualKeyboard,
        lock_codes: list[int],
    ):
        super().__init__(key_label, parent_ref)
        self.key_code = key_code
        self.parent_ref = parent_ref
        self.is_lock_key = key_code in lock_codes
        self.is_mod_key = key_code in mod_codes
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)

        self.setStyleSheet("""
            QPushButton {
                background-color: #2b2b2b;
                color: #e0e0e0;
                font-family: 'Segoe UI', Arial, sans-serif;
                font-size: 13px;
                font-weight: bold;
                border: 1px solid #1a1a1a;
                border-radius: 4px;
                margin: 1px;
            }
            QPushButton:pressed {
                background-color: #4a90e2; 
                color: white;
                border: 1px solid #357abd;
            }
            QPushButton[active="true"] {
                background-color: #c62828;
                color: white;
                border: 1px solid #8e1c1c;
            }
        """)

        if self.is_mod_key:
            self.setCheckable(True)
            self.toggled.connect(self._on_modifier_toggled)
        else:
            self._locked = False
            self._long_press_fired = False
            self._suppress_release = False
            self._timer = QTimer(self)
            self._timer.setSingleShot(True)
            self._timer.setInterval(self.LONG_PRESS_INTERVAL_MS)
            self.pressed.connect(self._on_standard_pressed)
            self.released.connect(self._on_standard_released)
            self._timer.timeout.connect(self._on_long_press_threshold)

    def _on_modifier_toggled(self, checked: bool):
        self.set_active(checked)
        if checked:
            self._send_ipc_message(0, self.key_code)
        else:
            self._send_ipc_message(1, self.key_code)

    def _on_standard_pressed(self):
        if self.is_lock_key:
            self._send_ipc_message(0, self.key_code)
            return

        if self._locked:
            self._send_ipc_message(1, self.key_code)
            self._locked = False
            self._suppress_release = True
            self.set_active(False)
            return

        self._suppress_release = False
        self._long_press_fired = False
        self._send_ipc_message(0, self.key_code)
        self._timer.start()

    def _on_standard_released(self):
        if self.is_lock_key:
            self._send_ipc_message(1, self.key_code)
            return

        if self._suppress_release:
            self._suppress_release = False
            return

        self._timer.stop()
        if self._long_press_fired:
            self._locked = True
            self.set_active(True)
        else:
            self._send_ipc_message(1, self.key_code)

    def _on_long_press_threshold(self):
        self._long_press_fired = True

    def _send_ipc_message(self, state: int, key_code: int):
        self.parent_ref._send_key(state, key_code, self.text().upper())

    def set_active(self, active: bool) -> None:
        if self.property("active") == active:
            return
        self.setProperty("active", active)
        self.style().unpolish(self)
        self.style().polish(self)


class VirtualKeyboard(QWidget):
    LOCK_POLL_INTERVAL_MS = 250

    def __init__(self, conn: Connection | None):
        super().__init__()
        self.conn = conn
        self._pressed_keys = set()

        self.modifier_key_codes = [
            code
            for key in MODIFIER_KEYS.split(",")
            if (code := get_scancode_from_key(key)) is not None
        ]

        self.lock_key_codes = [
            code
            for key in LOCK_KEYS.split(",")
            if (code := get_scancode_from_key(key)) is not None
        ]
        self.lock_name_to_key_code = {
            name: code
            for name in LOCK_KEYS.split(",")
            if (code := get_scancode_from_key(name)) is not None
        }
        self.lock_buttons: dict[int, VirtualKeyButton] = {}

        self._linux_key_map = {}
        if sys.platform == "linux":
            from modules.platforms.linux.ecodes_map import LINUX_KEY_MAP

            self._linux_key_map = LINUX_KEY_MAP

        self.setWindowTitle("Touch2Key - Virtual Keyboard")
        self.resize(1100, 300)
        self.setStyleSheet("background-color: #121212;")

        self.setWindowFlags(
            Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
            | Qt.WindowType.WindowDoesNotAcceptFocus
        )
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setAttribute(Qt.WidgetAttribute.WA_QuitOnClose, True)

        self._setup_ui()

        self._poll_lock_states()
        self.lock_state_timer = QTimer(self)
        self.lock_state_timer.timeout.connect(self._poll_lock_states)
        self.lock_state_timer.start(self.LOCK_POLL_INTERVAL_MS)

    def _setup_ui(self):
        master_layout = QHBoxLayout(self)
        master_layout.setContentsMargins(10, 10, 10, 10)
        master_layout.setSpacing(15)

        main_grid = QGridLayout()
        main_grid.setSpacing(2)
        for row_idx, row_data in enumerate(MAIN_LAYOUT):
            col_idx = 0
            for label, key_code, col_span in row_data:
                btn = self._create_btn(label, key_code)
                main_grid.addWidget(btn, row_idx, col_idx, 1, col_span)
                col_idx += col_span

        nav_grid = QGridLayout()
        nav_grid.setSpacing(2)
        for label, key_code, r, c, r_span, c_span in NAV_LAYOUT:
            nav_grid.addWidget(self._create_btn(label, key_code), r, c, r_span, c_span)

        numpad_grid = QGridLayout()
        numpad_grid.setSpacing(2)
        for label, key_code, r, c, r_span, c_span in NUMPAD_LAYOUT:
            numpad_grid.addWidget(
                self._create_btn(label, key_code), r, c, r_span, c_span
            )

        master_layout.addLayout(main_grid, 15)
        master_layout.addLayout(nav_grid, 6)
        master_layout.addLayout(numpad_grid, 4)

    def _create_btn(self, label: str, key_code: int) -> VirtualKeyButton:
        btn = VirtualKeyButton(
            label,
            key_code,
            self.modifier_key_codes,
            self,
            lock_codes=self.lock_key_codes,
        )
        if btn.is_lock_key:
            self.lock_buttons[key_code] = btn
        return btn

    def _poll_lock_states(self) -> None:
        states = get_lock_states()
        if states is not None:
            for name, key_code in self.lock_name_to_key_code.items():
                btn = self.lock_buttons.get(key_code)
                if btn is not None:
                    btn.set_active(states.get(name, False))

    def _send_key(self, state: int, key_code: int, key_name: str):
        if state == 0:
            self._pressed_keys.add(key_code)
        elif state == 1:
            self._pressed_keys.discard(key_code)

        if self.conn is None:
            action = "DOWN" if state == 0 else "UP  "

            if sys.platform == "win32":
                if key_code in (TOP_BEZEL_ID, M_LEFT, M_RIGHT, M_MIDDLE):
                    key_code_hex = "Internal"
                else:
                    key_code_hex = hex(key_code)

            elif sys.platform == "linux":
                if key_code == TOP_BEZEL_ID:
                    key_code_hex = "Internal"
                else:
                    linux_code = self._linux_key_map.get(key_code, None)
                    if linux_code is None:
                        key_code_hex = "None"
                    else:
                        key_code_hex = hex(linux_code)

            print(f"[VirtualKeyboard] {key_name}: {action} | key_code: {key_code_hex}")
            return

        try:
            self.conn.send_bytes(VKB_STRUCT.pack(state, int(key_code)))
        except OSError:
            self.close()

    def release_all(self):
        if self.conn is not None and self._pressed_keys:
            for code in list(self._pressed_keys):
                try:
                    self.conn.send_bytes(VKB_STRUCT.pack(1, int(code)))
                except OSError:
                    pass
            self._pressed_keys.clear()

    def closeEvent(self, event):
        self.lock_state_timer.stop()
        self.release_all()

        if self.conn:
            try:
                self.conn.close()
            except Exception:
                pass

        event.accept()


def run(conn: Connection | None = None, enforce_single_instance=True):
    if enforce_single_instance:
        success, _ = check_single_instance(VKB_NAME)
        if not success:
            sys.exit(0)

    app = QApplication(sys.argv)
    app_icon_path = ICONS_FOLDER / "app.png"
    if app_icon_path.exists():
        app.setWindowIcon(QIcon(str(app_icon_path)))

    window = VirtualKeyboard(conn)
    window.show()
    sys.exit(app.exec())


def virtual_keyboard_worker(conn: Connection):
    run(conn, False)


def main() -> None:
    """Dedicated entry point for touch2key-vkb."""
    AppLogManager.setup_logging(is_gui=True, log_prefix="touch2key_vkb")
    run()


if __name__ == "__main__":
    main()
