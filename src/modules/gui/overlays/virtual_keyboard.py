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
    QStyle,
)
from PySide6.QtCore import Qt, QTimer

from modules.utils import (
    LOCK_KEYS,
    M_MIDDLE,
    MODIFIER_KEYS,
    TOGGLE_KEY_ID,
    VKB_STRUCT,
    get_scancode_from_key,
)

from modules.platforms import get_lock_states, check_single_instance

if TYPE_CHECKING:
    from multiprocessing.connection import Connection
    
VKB_NAME = "Touch2Key_VKB"

# --- Main Alphanumeric Block ---
# Format: (Label, Scancode, Column Span)
MAIN_LAYOUT = [
    # Row 0: Esc, F-Keys and Delete (Span 1 each, 14 total columns)
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
    # Row 1: Numbers
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
    # Row 2: QWERTY
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
    # Row 3: ASDFG
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
    # Row 4: ZXCVB
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
    # Row 5: Modifiers
    [
        ("Ctrl", 0x1D, 2),
        ("Alt", 0x38, 2),
        ("Space", 0x39, 7),
        ("Alt", 0xE038, 2),
        ("Ctrl", 0xE01D, 2),
    ],
]

# --- Navigation & Arrows Block ---
# Format: (Label, Scancode, Row, Col, RowSpan, ColSpan)

NAV_LAYOUT = [
    ("Insert", 0xE050, 0, 0, 1, 3),
    ("PrtSc", 0xE037, 0, 3, 1, 3),
    ("Toggle Cursor", TOGGLE_KEY_ID, 1, 0, 1, 6),
    ("Home", 0xE047, 3, 0, 1, 2),
    ("End", 0xE04F, 3, 4, 1, 2),
    ("PgUp", 0xE049, 2, 2, 1, 2),
    ("PgDn", 0xE051, 3, 2, 1, 2),
    ("Left", 0xE04B, 5, 0, 1, 2),
    ("Right", 0xE04D, 5, 4, 1, 2),
    ("Up", 0xE048, 4, 2, 1, 2),
    ("Down", 0xE050, 5, 2, 1, 2),
]

# --- Numpad Block ---
# Format: (Label, Scancode, Row, RowSpan, ColSpan)
NUMPAD_LAYOUT = [
    ("Mouse Middle", M_MIDDLE, 0, 0, 1, 4),
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
    """Custom button that emits scancodes and explicitly ignores OS focus."""

    def __init__(
        self,
        key_label: str,
        scancode: int,
        mod_codes: list[int],
        parent_ref: VirtualKeyboard,
        lock_codes: list[int] | None = None,
    ):
        super().__init__(key_label, parent_ref)
        self.scancode = scancode
        self.modifier_scancodes = mod_codes
        self.parent_ref = parent_ref
        self.is_lock_key = scancode in (lock_codes or [])
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

        # CRITICAL: Do not accept focus, otherwise clicking a key minimizes the full-screen game
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

        # Make modifiers "Sticky"
        if scancode in mod_codes:
            self.setCheckable(True)
            self.toggled.connect(self._on_modifier_toggled)
        else:
            # Standard keys (including lock keys) trigger normally: momentary
            # down+up per tap. Lock keys additionally get a "active" visual
            # indicator (see set_active), but that's purely cosmetic and
            # driven externally by polled OS state -- it never changes how
            # this button sends, only how it looks.
            self.pressed.connect(self._on_standard_pressed)
            self.released.connect(self._on_standard_released)

    def _on_modifier_toggled(self, checked: bool):
        # 'checked' is True if the button is currently pressed down
        self.set_active(checked)
        if checked:
            self._send_ipc_message(0, self.scancode)
        else:
            self._send_ipc_message(1, self.scancode)

    def _on_standard_pressed(self):
        self._send_ipc_message(0, self.scancode)

    def _on_standard_released(self):
        self._send_ipc_message(1, self.scancode)

    def _send_ipc_message(self, state: int, scancode: int):
        self.parent_ref._send_key(state, scancode)

    def set_active(self, active: bool) -> None:
        """
        Visual: Shows if the current modifier or lock key is active.
        """
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

        self.modifier_scancodes = [
            code
            for key in MODIFIER_KEYS.split(",")
            if (code := get_scancode_from_key(key)) is not None
        ]

        # Lock keys: scancodes for the sticky-vs-momentary check above, and
        # a name->scancode map to translate get_lock_states()'s
        # "caps_lock"/"num_lock"/"scroll_lock" keys into the button to
        # update during polling.
        self.lock_scancodes = [
            code
            for key in LOCK_KEYS.split(",")
            if (code := get_scancode_from_key(key)) is not None
        ]
        self.lock_name_to_scancode = {
            name: code
            for name in LOCK_KEYS.split(",")
            if (code := get_scancode_from_key(name)) is not None
        }
        self.lock_buttons: dict[int, VirtualKeyButton] = {}

        self.setWindowTitle("Touch2Key - Virtual Keyboard")
        # Made wider to accommodate all 3 blocks cleanly
        self.resize(1100, 300)
        self.setStyleSheet("background-color: #121212;")

        # OSK Window Flags: StaysOnTop, hidden from taskbar, completely non-activating
        self.setWindowFlags(
            Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
            | Qt.WindowType.WindowDoesNotAcceptFocus
        )
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)

        # ADD THIS LINE: Forces the Qt app to exit when this "Tool" window is closed
        self.setAttribute(Qt.WidgetAttribute.WA_QuitOnClose, True)

        self._setup_ui()

        # Reflect real lock-key state immediately on open (don't wait for
        # the first timer tick), then keep polling.
        self._poll_lock_states()
        self.lock_state_timer = QTimer(self)
        self.lock_state_timer.timeout.connect(self._poll_lock_states)
        self.lock_state_timer.start(self.LOCK_POLL_INTERVAL_MS)

        # Proactive Fail-Safe: Check if Main Engine is still alive

    def _setup_ui(self):
        """Constructs the 3 distinct blocks (Main, Nav, Numpad) side-by-side."""
        master_layout = QHBoxLayout(self)
        master_layout.setContentsMargins(10, 10, 10, 10)
        master_layout.setSpacing(15)

        # 1. Main Block
        main_grid = QGridLayout()
        main_grid.setSpacing(2)
        for row_idx, row_data in enumerate(MAIN_LAYOUT):
            col_idx = 0
            for label, scancode, col_span in row_data:
                btn = self._create_btn(label, scancode)
                main_grid.addWidget(btn, row_idx, col_idx, 1, col_span)
                col_idx += col_span

        # 2. Nav Block
        nav_grid = QGridLayout()
        nav_grid.setSpacing(2)
        for label, scancode, r, c, r_span, c_span in NAV_LAYOUT:
            nav_grid.addWidget(self._create_btn(label, scancode), r, c, r_span, c_span)

        # 3. Numpad Block
        numpad_grid = QGridLayout()
        numpad_grid.setSpacing(2)
        for label, scancode, r, c, r_span, c_span in NUMPAD_LAYOUT:
            numpad_grid.addWidget(
                self._create_btn(label, scancode), r, c, r_span, c_span
            )

        # Add all to master layout (Stretch factors: 15 for Main, 6 for Nav, 4 for Numpad)
        master_layout.addLayout(main_grid, 15)
        master_layout.addLayout(nav_grid, 6)
        master_layout.addLayout(numpad_grid, 4)

    def _create_btn(self, label: str, scancode: int) -> VirtualKeyButton:
        btn = VirtualKeyButton(
            label,
            scancode,
            self.modifier_scancodes,
            self,
            lock_codes=self.lock_scancodes,
        )
        if btn.is_lock_key:
            self.lock_buttons[scancode] = btn
        return btn

    def _poll_lock_states(self) -> None:
        """Refreshes each lock button's visual 'active' state from live OS
        state (see get_lock_states in modules.utils). Read-only: never
        sends anything, never touches _pressed_keys.
        """
        states = get_lock_states()
        if states is not None:
            for name, scancode in self.lock_name_to_scancode.items():
                btn = self.lock_buttons.get(scancode)
                if btn is not None:
                    btn.set_active(states.get(name, False))

    def _send_key(self, state: int, scancode: int):
        """Packs the keystroke and sends it through the IPC pipe."""
        if state == 0:  # DOWN
            self._pressed_keys.add(scancode)
        elif state == 1:  # UP
            self._pressed_keys.discard(scancode)

        if self.conn is None:
            # Standalone Testing Mode ONLY: Print to console
            action = "DOWN" if state == 0 else "UP  "
            print(f"[VirtualKeyboard] {action} | Scancode: {hex(scancode)}")
            return

        # Production Mode: SILENT IPC Write
        try:
            self.conn.send_bytes(VKB_STRUCT.pack(state, int(scancode)))
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
        """Ensures the terminal loop dies completely when the window 'X' is clicked."""
        self.lock_state_timer.stop()

        # Release all pressed keys and close the IPC pipe cleanly

        self.release_all()

        if self.conn:
            try:
                self.conn.close()
            except Exception:
                pass

        event.accept()

    def _heartbeat_loop(self): ...


def run(conn: Connection | None = None, enforce_single_instance=True):
    if enforce_single_instance:
        success, _ = check_single_instance(VKB_NAME)
        if not success:
            sys.exit(0)
    
    app = QApplication(sys.argv)
    app.setWindowIcon(
        QApplication.style().standardIcon(QStyle.StandardPixmap.SP_ComputerIcon)
    )

    window = VirtualKeyboard(conn)
    window.show()

    # sys.exit ensures the terminal prompt returns instantly when app closes
    sys.exit(app.exec())


if __name__ == "__main__":
    run()


def virtual_keyboard_worker(conn: Connection):
    run(conn, False) # Don't enforce single instance checks
