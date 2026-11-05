from __future__ import annotations

import logging
import signal
import sys
from typing import TYPE_CHECKING

from PySide6.QtCore import QCoreApplication, QPoint, QRect, Qt, QTimer
from PySide6.QtGui import (
    QCursor,
    QIcon,
    QMouseEvent,
    QPainter,
    QColor,
    QPen,
)
from PySide6.QtWidgets import (
    QApplication,
    QGridLayout,
    QHBoxLayout,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from modules import AppLogManager
from modules.platforms import check_single_instance, get_lock_states
from modules.utils import (
    CLOSE_VKB_ID,
    ICONS_FOLDER,
    LOCK_KEYS,
    M_LEFT,
    M_MIDDLE,
    M_RIGHT,
    MODIFIER_KEYS,
    TOP_BEZEL_ID,
    VKB_STRUCT,
    get_scancode_from_key,
)

if TYPE_CHECKING:
    from multiprocessing.connection import Connection

logger = logging.getLogger("modules.gui.overlays.virtual_keyboard")

VKB_NAME = "Touch2Key_VKB"
RESIZE_MARGIN = 8
MIN_VKB_WIDTH = 550
MIN_VKB_HEIGHT = 160

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
    ("Toggle", TOP_BEZEL_ID, 0, 0, 1, 2),
    ("Close", CLOSE_VKB_ID, 0, 2, 1, 2),
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

        self.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Expanding,
        )
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

    def was_pressed(self, key_code: int) -> bool:
        """Check whether a key is currently held."""
        return key_code in self.parent_ref._pressed_keys

    def _on_modifier_toggled(self, checked: bool):
        self.set_active(checked)
        self.parent_ref._set_key_state(
            self.key_code,
            checked,
            self.text().upper(),
        )

    def _on_standard_pressed(self):
        if self.is_lock_key:
            self.parent_ref._set_key_state(
                self.key_code,
                True,
                self.text().upper(),
            )
            return

        if self._locked:
            self.parent_ref._set_key_state(
                self.key_code,
                False,
                self.text().upper(),
            )
            self._locked = False
            self._suppress_release = True
            self.set_active(False)
            return

        self._suppress_release = False
        self._long_press_fired = False

        self.parent_ref._set_key_state(
            self.key_code,
            True,
            self.text().upper(),
        )

        self._timer.start()

    def _on_standard_released(self):
        if self.is_lock_key:
            self.parent_ref._set_key_state(
                self.key_code,
                False,
                self.text().upper(),
            )
            return

        if self._suppress_release:
            self._suppress_release = False
            return

        self._timer.stop()

        if self._long_press_fired:
            self._locked = True
            self.set_active(True)
        else:
            self.parent_ref._set_key_state(
                self.key_code,
                False,
                self.text().upper(),
            )

    def _on_long_press_threshold(self):
        self._long_press_fired = True

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
        self._pressed_keys: set[int] = set()

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

        self._drag_offset: QPoint | None = None
        self._resize_edges: Qt.Edge = Qt.Edge(0)
        self._resize_start_geom: QRect | None = None
        self._resize_start_mouse: QPoint | None = None

        self.setWindowTitle("Touch2Key - Virtual Keyboard")
        self.setMinimumSize(MIN_VKB_WIDTH, MIN_VKB_HEIGHT)
        self.resize(1100, 300)
        self.setMouseTracking(True)
        self.setStyleSheet("background-color: #121212;")

        self.setWindowFlags(
            Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
            | Qt.WindowType.WindowDoesNotAcceptFocus
            | Qt.WindowType.FramelessWindowHint
        )

        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setAttribute(Qt.WidgetAttribute.WA_QuitOnClose, True)

        self._setup_ui()

        self._poll_lock_states()
        self.lock_state_timer = QTimer(self)
        self.lock_state_timer.timeout.connect(self._poll_lock_states)
        self.lock_state_timer.start(self.LOCK_POLL_INTERVAL_MS)

    def _setup_ui(self) -> None:
        outer_layout = QVBoxLayout(self)
        outer_layout.setContentsMargins(
            RESIZE_MARGIN,
            RESIZE_MARGIN,
            RESIZE_MARGIN,
            RESIZE_MARGIN,
        )
        outer_layout.setSpacing(0)

        master_layout = QHBoxLayout()
        master_layout.setContentsMargins(2, 2, 2, 2)
        master_layout.setSpacing(12)

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
            nav_grid.addWidget(
                self._create_btn(label, key_code),
                r,
                c,
                r_span,
                c_span,
            )

        numpad_grid = QGridLayout()
        numpad_grid.setSpacing(2)

        for label, key_code, r, c, r_span, c_span in NUMPAD_LAYOUT:
            numpad_grid.addWidget(
                self._create_btn(label, key_code),
                r,
                c,
                r_span,
                c_span,
            )

        master_layout.addLayout(main_grid, 15)
        master_layout.addLayout(nav_grid, 6)
        master_layout.addLayout(numpad_grid, 4)

        outer_layout.addLayout(master_layout)

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

        if key_code == CLOSE_VKB_ID:
            btn.setStyleSheet(btn.styleSheet() + """
                QPushButton {
                    background-color: #7f1d1d;
                    border: 1px solid #450a0a;
                }
                QPushButton:pressed,
                QPushButton[pressed_state="true"] {
                    background-color: #991b1b;
                }
            """)

        return btn

    def _set_key_state(
        self,
        key_code: int,
        pressed: bool,
        key_name: str,
    ) -> None:
        """Send key transitions only when the logical state changes."""
        if pressed:
            if key_code in self._pressed_keys:
                return

            self._pressed_keys.add(key_code)
            self._send_key(0, key_code, key_name)

        else:
            if key_code not in self._pressed_keys:
                return

            self._pressed_keys.remove(key_code)
            self._send_key(1, key_code, key_name)

    def paintEvent(self, event) -> None:
        super().paintEvent(event)

        painter = QPainter(self)

        pen = QPen(QColor("#333333"), 1)
        painter.setPen(pen)
        painter.drawRect(0, 0, self.width() - 1, self.height() - 1)

        grip_pen = QPen(QColor("#666666"), 2)
        painter.setPen(grip_pen)

        w, h = self.width(), self.height()

        for offset in (4, 8, 12):
            painter.drawLine(
                w - offset,
                h - 2,
                w - 2,
                h - offset,
            )

    def _hit_test_edges(self, local_pos: QPoint) -> Qt.Edge:
        edges = Qt.Edge(0)
        w, h = self.width(), self.height()
        x, y = local_pos.x(), local_pos.y()

        if x <= RESIZE_MARGIN:
            edges |= Qt.Edge.LeftEdge
        elif x >= w - RESIZE_MARGIN:
            edges |= Qt.Edge.RightEdge

        if y <= RESIZE_MARGIN:
            edges |= Qt.Edge.TopEdge
        elif y >= h - RESIZE_MARGIN:
            edges |= Qt.Edge.BottomEdge

        return edges

    def _update_cursor_for_edges(self, edges: Qt.Edge) -> None:
        if edges in (
            Qt.Edge.TopEdge | Qt.Edge.LeftEdge,
            Qt.Edge.BottomEdge | Qt.Edge.RightEdge,
        ):
            self.setCursor(Qt.CursorShape.SizeFDiagCursor)

        elif edges in (
            Qt.Edge.TopEdge | Qt.Edge.RightEdge,
            Qt.Edge.BottomEdge | Qt.Edge.LeftEdge,
        ):
            self.setCursor(Qt.CursorShape.SizeBDiagCursor)

        elif edges in (Qt.Edge.LeftEdge, Qt.Edge.RightEdge):
            self.setCursor(Qt.CursorShape.SizeHorCursor)

        elif edges in (Qt.Edge.TopEdge, Qt.Edge.BottomEdge):
            self.setCursor(Qt.CursorShape.SizeVerCursor)

        else:
            self.unsetCursor()

    def _poll_lock_states(self) -> None:
        states = get_lock_states()

        if states is not None:
            for name, key_code in self.lock_name_to_key_code.items():
                btn = self.lock_buttons.get(key_code)

                if btn is not None:
                    btn.set_active(states.get(name, False))

    def _send_key(self, state: int, key_code: int, key_name: str) -> None:
        if key_code == CLOSE_VKB_ID:
            if state == 0:
                self.close()
            return

        if self.conn is None:
            action = "DOWN" if state == 0 else "UP"
            _platform = "Unsupported Platform"

            if key_code in (TOP_BEZEL_ID, M_LEFT, M_RIGHT, M_MIDDLE):
                key_code_hex = "Internal"
            else:
                key_code_hex = hex(key_code)

            if sys.platform == "win32":
                _platform = "Windows"

            elif sys.platform == "linux":
                _platform = "Linux"
                linux_code = self._linux_key_map.get(key_code)

                if linux_code is None:
                    key_code_hex = "None"
                else:
                    key_code_hex = hex(linux_code)

            logger.info(
                "[VirtualKeyboard] %s %s: %s | key_code: %s",
                _platform,
                key_name,
                action,
                key_code_hex,
            )
            return

        try:
            self.conn.send_bytes(VKB_STRUCT.pack(state, int(key_code)))
        except OSError:
            self.close()

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            local_pos = event.position().toPoint()
            global_pos = QCursor.pos()
            edges = self._hit_test_edges(local_pos)

            if edges:
                win_handle = self.windowHandle()

                if win_handle is not None and win_handle.startSystemResize(edges):
                    event.accept()
                    return

                self._resize_edges = edges
                self._resize_start_geom = self.geometry()
                self._resize_start_mouse = global_pos
                event.accept()
                return

            self._drag_offset = global_pos - self.frameGeometry().topLeft()
            event.accept()
            return

        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        global_pos = QCursor.pos()

        if (
            self._resize_edges
            and self._resize_start_geom
            and self._resize_start_mouse
        ):
            delta = global_pos - self._resize_start_mouse
            geom = QRect(self._resize_start_geom)

            if self._resize_edges & Qt.Edge.LeftEdge:
                new_left = geom.left() + delta.x()

                if geom.right() - new_left >= self.minimumWidth():
                    geom.setLeft(new_left)

            elif self._resize_edges & Qt.Edge.RightEdge:
                geom.setWidth(
                    max(self.minimumWidth(), geom.width() + delta.x())
                )

            if self._resize_edges & Qt.Edge.TopEdge:
                new_top = geom.top() + delta.y()

                if geom.bottom() - new_top >= self.minimumHeight():
                    geom.setTop(new_top)

            elif self._resize_edges & Qt.Edge.BottomEdge:
                geom.setHeight(
                    max(self.minimumHeight(), geom.height() + delta.y())
                )

            self.setGeometry(geom)
            event.accept()
            return

        if (
            self._drag_offset is not None
            and event.buttons() & Qt.MouseButton.LeftButton
        ):
            self.move(global_pos - self._drag_offset)
            event.accept()
            return

        self._update_cursor_for_edges(
            self._hit_test_edges(event.position().toPoint())
        )
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_offset = None
            self._resize_edges = Qt.Edge(0)
            self._resize_start_geom = None
            self._resize_start_mouse = None
            self.unsetCursor()
            event.accept()
            return

        super().mouseReleaseEvent(event)

    def closeEvent(self, event) -> None:
        self.lock_state_timer.stop()

        if self.conn:
            try:
                self.conn.close()
            except Exception:
                pass

        event.accept()


def run(
    conn: Connection | None = None,
    enforce_single_instance: bool = True,
) -> None:
    if enforce_single_instance:
        success, _ = check_single_instance(VKB_NAME)

        if not success:
            sys.exit(0)

    app = QApplication(sys.argv)

    app_icon_path = ICONS_FOLDER / "app.png"

    if app_icon_path.exists():
        app.setWindowIcon(QIcon(str(app_icon_path)))

    # Allow Python signals to be processed periodically.
    timer = QTimer()
    timer.start(500)
    timer.timeout.connect(lambda: None)

    # Handle Ctrl+C cleanly.
    signal.signal(signal.SIGINT, lambda *_: QCoreApplication.quit())

    window = VirtualKeyboard(conn)
    window.show()
    window.raise_()

    sys.exit(app.exec())


def virtual_keyboard_worker(conn: Connection) -> None:
    run(conn, False)


def main() -> None:
    """Dedicated entry point for touch2key-keyboard."""
    AppLogManager.setup_logging(log_prefix="touch2key_keyboard")
    run()


if __name__ == "__main__":
    main()