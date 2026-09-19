import sys
import struct
import psutil
import argparse
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

# IPC Struct: 1 byte for state (1=Down, 0=Up), 2 bytes for Scancode
VKB_STRUCT = struct.Struct("<B H")

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
    # Row 5: Modifiers (Removed Win Key)
    [
        ("Ctrl", 0x1D, 2),
        ("Alt", 0x38, 2),
        ("Space", 0x39, 7),
        ("Alt", 0xE038, 2),
        ("Ctrl", 0xE01D, 2),
    ],
]

# --- Arrows Block ---
# Format: (Row, Col, Label, Scancode)

ARROW_LAYOUT = [
    (4, 1, "Up", 0xE048),
    (5, 0, "Left", 0xE04B),
    (5, 1, "Down", 0xE050),
    (5, 2, "Right", 0xE04D),
]

# --- Navigation Block ---
# Format: (Row, Col, Label, Scancode)

NAV_LAYOUT = [
    (0, 0, "PrtSc", 0xE037),
    (0, 1, "ScrLk", 0x46),
    (0, 2, "Pause", 0xE046),
    (1, 0, "Insert", 0xE052),
    (1, 1, "Home", 0xE047),
    (1, 2, "PgUp", 0xE049),
    (2, 1, "End", 0xE04F),
    (2, 2, "PgDn", 0xE051),
]

# --- Numpad Block ---
# Format: (Row, Col, RowSpan, ColSpan, Label, Scancode)
NUMPAD_LAYOUT = [
    # Row 0 is an empty gap to align with F-Keys
    (1, 0, 1, 1, "NumLk", 0x45),
    (1, 1, 1, 1, "/", 0xE035),
    (1, 2, 1, 1, "*", 0x37),
    (1, 3, 1, 1, "-", 0x4A),
    (2, 0, 1, 1, "7", 0x47),
    (2, 1, 1, 1, "8", 0x48),
    (2, 2, 1, 1, "9", 0x49),
    (2, 3, 2, 1, "+", 0x4E),  # + spans 2 rows
    (3, 0, 1, 1, "4", 0x4B),
    (3, 1, 1, 1, "5", 0x4C),
    (3, 2, 1, 1, "6", 0x4D),
    (4, 0, 1, 1, "1", 0x4F),
    (4, 1, 1, 1, "2", 0x50),
    (4, 2, 1, 1, "3", 0x51),
    (4, 3, 2, 1, "Ent", 0xE01C),  # Ent spans 2 rows
    (5, 0, 1, 2, "0", 0x52),
    (5, 2, 1, 1, ".", 0x53),  # 0 spans 2 cols
]


class KeyButton(QPushButton):
    """Custom button that emits scancodes and explicitly ignores OS focus."""

    def __init__(self, text: str, scancode: int, parent=None):
        super().__init__(text, parent)
        self.scancode = scancode
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
        """)


class VirtualKeyboard(QWidget):
    def __init__(self, pipe_name: str | None = None, parent_pid: int | None = None):
        super().__init__()
        self.pipe_name = pipe_name
        self.parent_pid = parent_pid
        self.pipe = None

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
        self._connect_pipe()

        # Proactive Fail-Safe: Check if Main Engine is still alive
        if self.parent_pid:
            self.health_timer = QTimer(self)
            self.health_timer.timeout.connect(self._check_parent_alive)
            self.health_timer.start(1000)

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

        # 2. Numpad Block
        numpad_grid = QGridLayout()
        numpad_grid.setSpacing(2)
        numpad_grid.setRowStretch(0, 1)  # Gap for row 0
        for r, c, r_span, c_span, label, scancode in NUMPAD_LAYOUT:
            numpad_grid.addWidget(
                self._create_btn(label, scancode), r, c, r_span, c_span
            )

        # 3. Arrow Block
        arrow_grid = QGridLayout()
        arrow_grid.setSpacing(2)
        # Force the empty row 3 to have the same height scaling as active rows
        arrow_grid.setRowStretch(3, 1)
        for r, c, label, scancode in ARROW_LAYOUT:
            arrow_grid.addWidget(self._create_btn(label, scancode), r, c)

        # 4. Nav Block
        nav_grid = QGridLayout()
        nav_grid.setSpacing(2)
        # Force the empty row 3 to have the same height scaling as active rows
        nav_grid.setRowStretch(3, 1)
        for r, c, label, scancode in NAV_LAYOUT:
            nav_grid.addWidget(self._create_btn(label, scancode), r, c)

        # Add all to master layout (Stretch factors: 15 for Main, 3 for Nav, 4 for Numpad)
        master_layout.addLayout(main_grid, 15)
        master_layout.addLayout(numpad_grid, 4)
        master_layout.addLayout(arrow_grid, 4)
        master_layout.addLayout(nav_grid, 3)

    def _create_btn(self, label: str, scancode: int) -> KeyButton:
        btn = KeyButton(label, scancode)
        btn.pressed.connect(lambda s=scancode: self._send_key(1, s))
        btn.released.connect(lambda s=scancode: self._send_key(0, s))
        return btn

    def _connect_pipe(self):
        """Attempts to open the named IPC pipe to the main engine."""
        if not self.pipe_name:
            return

        try:
            self.pipe = open(self.pipe_name, "wb")
        except Exception as e:
            # Silent fail in production to avoid console spam
            pass

    def _send_key(self, state: int, scancode: int):
        """Packs the keystroke and sends it through the IPC pipe."""
        if not self.pipe:
            # Standalone Testing Mode ONLY: Print to console
            action = "DOWN" if state == 1 else "UP  "
            print(f"[VirtualKeyboard] {action} | Scancode: {hex(scancode)}")
            return

        # Production Mode: SILENT IPC Write
        try:
            packet = VKB_STRUCT.pack(state, scancode)
            self.pipe.write(packet)
            self.pipe.flush()
        except (BrokenPipeError, EOFError, OSError):
            self.close()

    def _check_parent_alive(self):
        """Forces the keyboard to close if the parent process dies unexpectedly."""
        if self.parent_pid is not None and not psutil.pid_exists(self.parent_pid):
            self.close()

    def closeEvent(self, event):
        """Ensures the terminal loop dies completely when the window 'X' is clicked."""
        # Stop the background timer so it doesn't keep the process alive
        if hasattr(self, "health_timer") and self.health_timer.isActive():
            self.health_timer.stop()

        # Close the IPC pipe cleanly
        if self.pipe:
            try:
                self.pipe.close()
            except Exception:
                pass

        event.accept()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--pipe", type=str, help="Named pipe file descriptor", default=None
    )
    parser.add_argument("--pid", type=int, help="Parent Process ID", default=None)
    args = parser.parse_args()

    app = QApplication(sys.argv)
    app.setWindowIcon(
        QApplication.style().standardIcon(QStyle.StandardPixmap.SP_ComputerIcon)
    )

    window = VirtualKeyboard(pipe_name=args.pipe, parent_pid=args.pid)
    window.show()

    # sys.exit ensures the terminal prompt returns instantly when app closes
    sys.exit(app.exec())
