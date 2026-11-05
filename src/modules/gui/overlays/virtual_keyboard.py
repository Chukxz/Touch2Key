from __future__ import annotations

import logging
import signal
import sys
from enum import Enum, auto
from typing import TYPE_CHECKING

from PySide6.QtCore import QCoreApplication, QPoint, QRect, Qt, QTimer
from PySide6.QtGui import (
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

# Window move/resize begins only after the pointer has remained nearly still
# for this long. Button presses do not use this delay.
WINDOW_HOLD_INTERVAL_MS = 300
WINDOW_HOLD_TOLERANCE_PX = 8


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


class InteractionState(Enum):
    IDLE = auto()
    BUTTON = auto()
    WINDOW_MOVE_PENDING = auto()
    WINDOW_RESIZE_PENDING = auto()
    WINDOW_MOVING = auto()
    WINDOW_RESIZING = auto()


class InteractionController:
    """
    Owns the single mouse interaction currently in progress.

    A button, window move, or window resize owns the pointer from DOWN until
    UP/cancellation. Ownership is never reassigned in the middle of a press.
    """

    def __init__(self, keyboard: VirtualKeyboard):
        self.keyboard = keyboard
        self.state = InteractionState.IDLE

        self.button: VirtualKeyButton | None = None
        self.start_global: QPoint | None = None
        self.start_geometry: QRect | None = None
        self.resize_edges = Qt.Edge(0)

        self.hold_timer = QTimer(keyboard)
        self.hold_timer.setSingleShot(True)
        self.hold_timer.setInterval(WINDOW_HOLD_INTERVAL_MS)
        self.hold_timer.timeout.connect(self._activate_window_gesture)

    @property
    def is_idle(self) -> bool:
        return self.state is InteractionState.IDLE

    def begin_button(self, button: VirtualKeyButton) -> bool:
        if not self.is_idle:
            return False

        self.state = InteractionState.BUTTON
        self.button = button
        button._begin_press()
        return True

    def finish_button(self, button: VirtualKeyButton, inside: bool) -> None:
        if self.state is not InteractionState.BUTTON or self.button is not button:
            return

        # Clear ownership before invoking button behaviour. A close action can
        # destroy the window, and must not leave this controller half-active.
        self.button = None
        self.state = InteractionState.IDLE
        button._finish_press(inside)

    def begin_window_gesture(
        self,
        global_pos: QPoint,
        resize_edges: Qt.Edge,
    ) -> bool:
        if not self.is_idle:
            return False

        self.start_global = QPoint(global_pos)
        self.start_geometry = QRect(self.keyboard.geometry())
        self.resize_edges = resize_edges

        if resize_edges:
            self.state = InteractionState.WINDOW_RESIZE_PENDING
        else:
            self.state = InteractionState.WINDOW_MOVE_PENDING

        self.hold_timer.start()
        return True

    def move_window_gesture(self, global_pos: QPoint) -> None:
        if self.state is InteractionState.IDLE:
            return

        if self.state in (
            InteractionState.WINDOW_MOVE_PENDING,
            InteractionState.WINDOW_RESIZE_PENDING,
        ):
            assert self.start_global is not None
            delta = global_pos - self.start_global

            if (
                abs(delta.x()) > WINDOW_HOLD_TOLERANCE_PX
                or abs(delta.y()) > WINDOW_HOLD_TOLERANCE_PX
            ):
                # Moving before the hold threshold cancels the gesture. It
                # does not turn into a normal drag or a pointer movement.
                self.cancel()
            return

        if self.state is InteractionState.WINDOW_MOVING:
            assert self.start_global is not None
            assert self.start_geometry is not None

            delta = global_pos - self.start_global
            self.keyboard.move(self.start_geometry.topLeft() + delta)
            return

        if self.state is InteractionState.WINDOW_RESIZING:
            self._apply_resize(global_pos)

    def finish_window_gesture(self) -> None:
        if self.state not in (
            InteractionState.WINDOW_MOVE_PENDING,
            InteractionState.WINDOW_RESIZE_PENDING,
            InteractionState.WINDOW_MOVING,
            InteractionState.WINDOW_RESIZING,
        ):
            return

        self._reset()

    def cancel(self) -> None:
        if self.state is InteractionState.BUTTON:
            button = self.button
            self._reset()

            if button is not None:
                button._finish_press(False)
            return

        self._reset()

    def _activate_window_gesture(self) -> None:
        if self.state is InteractionState.WINDOW_MOVE_PENDING:
            self.state = InteractionState.WINDOW_MOVING
        elif self.state is InteractionState.WINDOW_RESIZE_PENDING:
            self.state = InteractionState.WINDOW_RESIZING

    def _apply_resize(self, global_pos: QPoint) -> None:
        assert self.start_global is not None
        assert self.start_geometry is not None

        delta = global_pos - self.start_global
        start = self.start_geometry

        left = start.left()
        top = start.top()
        right = start.left() + start.width()
        bottom = start.top() + start.height()

        if self.resize_edges & Qt.Edge.LeftEdge:
            left = min(
                start.left() + delta.x(),
                right - self.keyboard.minimumWidth(),
            )
        elif self.resize_edges & Qt.Edge.RightEdge:
            right = max(
                start.left() + start.width() + delta.x(),
                left + self.keyboard.minimumWidth(),
            )

        if self.resize_edges & Qt.Edge.TopEdge:
            top = min(
                start.top() + delta.y(),
                bottom - self.keyboard.minimumHeight(),
            )
        elif self.resize_edges & Qt.Edge.BottomEdge:
            bottom = max(
                start.top() + start.height() + delta.y(),
                top + self.keyboard.minimumHeight(),
            )

        self.keyboard.setGeometry(
            left,
            top,
            right - left,
            bottom - top,
        )

    def _reset(self) -> None:
        self.hold_timer.stop()
        self.state = InteractionState.IDLE
        self.button = None
        self.start_global = None
        self.start_geometry = None
        self.resize_edges = Qt.Edge(0)


class VirtualKeyButton(QPushButton):
    """A virtual key with explicit press, release, and cancellation semantics."""

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

        # These internal actions must only execute after a valid release.
        self.is_action_key = key_code in (TOP_BEZEL_ID, CLOSE_VKB_ID)

        self._locked = False
        self._long_press_fired = False
        self._unlock_pending = False
        self._press_active = False
        self._pointer_inside = False

        self.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Expanding,
        )
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setMouseTracking(True)

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

        # We manage pointer handling ourselves so an outside release can be
        # distinguished from a normal QPushButton click.
        self.setCheckable(self.is_mod_key)

        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(self.LONG_PRESS_INTERVAL_MS)
        self._timer.timeout.connect(self._on_long_press_threshold)

    def was_pressed(self, key_code: int) -> bool:
        return key_code in self.parent_ref._pressed_keys

    def _key_name(self) -> str:
        return self.text().replace("\n", " ").upper()

    def _begin_press(self) -> None:
        self._press_active = True
        self._pointer_inside = True
        self._long_press_fired = False
        self._unlock_pending = False
        self.setDown(True)

        if self.is_mod_key:
            # Modifiers are toggled only on a valid release.
            return

        if self.is_action_key:
            # TOP_BEZEL is a release-triggered action in the mapper. CLOSE is
            # executed locally on a valid release. Neither needs a held key.
            if self.key_code == TOP_BEZEL_ID:
                self.parent_ref._set_key_state(
                    self.key_code,
                    True,
                    self._key_name(),
                )
            return

        if self._locked:
            # Do not unlock on DOWN: an outside release must leave the
            # previously locked key locked.
            self._unlock_pending = True
            return

        self.parent_ref._set_key_state(
            self.key_code,
            True,
            self._key_name(),
        )

        if not self.is_lock_key:
            self._timer.start()

    def _finish_press(self, inside: bool) -> None:
        if not self._press_active:
            return

        self._press_active = False
        self._timer.stop()
        self.setDown(False)

        valid_release = inside

        if self.is_mod_key:
            if valid_release:
                self.setChecked(not self.isChecked())
                self.set_active(self.isChecked())
                self.parent_ref._set_key_state(
                    self.key_code,
                    self.isChecked(),
                    self._key_name(),
                )
            return

        if self.key_code == CLOSE_VKB_ID:
            if valid_release:
                self.parent_ref._send_key(
                    0,
                    self.key_code,
                    self._key_name(),
                )
            return

        if self.key_code == TOP_BEZEL_ID:
            if valid_release:
                self.parent_ref._set_key_state(
                    self.key_code,
                    False,
                    self._key_name(),
                )
            else:
                # Mapper ignores TOP_BEZEL DOWN. Discard its local pending
                # state without sending UP, because UP performs the action.
                self.parent_ref._discard_key_state(self.key_code)
            return

        if self.is_lock_key:
            # Lock keys are momentary virtual keys. The OS lock indicator is
            # independently polled and updates the button's active property.
            self.parent_ref._set_key_state(
                self.key_code,
                False,
                self._key_name(),
            )
            return

        if self._unlock_pending:
            if valid_release:
                self._locked = False
                self.set_active(False)
                self.parent_ref._set_key_state(
                    self.key_code,
                    False,
                    self._key_name(),
                )
            # A cancelled unlock attempt leaves the key locked and held.
            self._unlock_pending = False
            return

        if not valid_release:
            # A long press released outside is cancelled, not locked.
            self.parent_ref._set_key_state(
                self.key_code,
                False,
                self._key_name(),
            )
            self._long_press_fired = False
            return

        if self._long_press_fired:
            self._locked = True
            self.set_active(True)
            # Intentionally leave the emitted key DOWN.
        else:
            self.parent_ref._set_key_state(
                self.key_code,
                False,
                self._key_name(),
            )

        self._long_press_fired = False

    def _on_long_press_threshold(self) -> None:
        if (
            self._press_active
            and self._pointer_inside
            and not self._locked
            and not self._unlock_pending
        ):
            self._long_press_fired = True

    def set_active(self, active: bool) -> None:
        if self.property("active") == active:
            return

        self.setProperty("active", active)
        self.style().unpolish(self)
        self.style().polish(self)
        self.update()

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            if self.parent_ref._interactions.begin_button(self):
                event.accept()
            else:
                event.ignore()
            return

        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        if self._press_active:
            self._pointer_inside = self.rect().contains(
                event.position().toPoint()
            )
            self.setDown(self._pointer_inside)
            event.accept()
            return

        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton and self._press_active:
            inside = self.rect().contains(event.position().toPoint())
            self.parent_ref._interactions.finish_button(self, inside)
            event.accept()
            return

        super().mouseReleaseEvent(event)

    def cancel_press(self) -> None:
        if self._press_active:
            self.parent_ref._interactions.finish_button(self, False)


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

        self._interactions = InteractionController(self)

        self.setWindowTitle("Touch2Key - Virtual Keyboard")
        self.setMinimumSize(MIN_VKB_WIDTH, MIN_VKB_HEIGHT)
        self.resize(1100, 300)
        self.setMouseTracking(True)
        self.setStyleSheet("background-color: #121212;")

        self.setWindowFlags(
            Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
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
        """Send key transitions only when the local logical state changes."""
        if pressed:
            if key_code in self._pressed_keys:
                return

            self._pressed_keys.add(key_code)
            self._send_key(0, key_code, key_name)
            return

        if key_code not in self._pressed_keys:
            return

        self._pressed_keys.remove(key_code)
        self._send_key(1, key_code, key_name)

    def _discard_key_state(self, key_code: int) -> None:
        """Discard a pending local state without emitting an UP event."""
        self._pressed_keys.discard(key_code)

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
        if edges == (Qt.Edge.TopEdge | Qt.Edge.LeftEdge) or edges == (
            Qt.Edge.BottomEdge | Qt.Edge.RightEdge
        ):
            self.setCursor(Qt.CursorShape.SizeFDiagCursor)

        elif edges == (Qt.Edge.TopEdge | Qt.Edge.RightEdge) or edges == (
            Qt.Edge.BottomEdge | Qt.Edge.LeftEdge
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

        if states is None:
            return

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
            platform = "Unsupported Platform"

            if key_code in (TOP_BEZEL_ID, M_LEFT, M_RIGHT, M_MIDDLE):
                key_code_hex = "Internal"
            else:
                key_code_hex = hex(key_code)

            if sys.platform == "win32":
                platform = "Windows"

            elif sys.platform == "linux":
                platform = "Linux"
                linux_code = self._linux_key_map.get(key_code)

                if linux_code is None:
                    key_code_hex = "None"
                else:
                    key_code_hex = hex(linux_code)

            logger.info(
                "[VirtualKeyboard] %s %s: %s | key_code: %s",
                platform,
                key_name,
                action,
                key_code_hex,
            )
            return

        try:
            self.conn.send_bytes(VKB_STRUCT.pack(state, int(key_code)))
        except (BrokenPipeError, EOFError, OSError):
            logger.exception("Virtual keyboard IPC connection failed")
            self.close()

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() != Qt.MouseButton.LeftButton:
            super().mousePressEvent(event)
            return

        local_pos = event.position().toPoint()
        global_pos = event.globalPosition().toPoint()
        edges = self._hit_test_edges(local_pos)

        if self._interactions.begin_window_gesture(global_pos, edges):
            event.accept()
            return

        event.ignore()

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        if self._interactions.state in (
            InteractionState.WINDOW_MOVE_PENDING,
            InteractionState.WINDOW_RESIZE_PENDING,
            InteractionState.WINDOW_MOVING,
            InteractionState.WINDOW_RESIZING,
        ):
            self._interactions.move_window_gesture(
                event.globalPosition().toPoint()
            )
            event.accept()
            return

        self._update_cursor_for_edges(
            self._hit_test_edges(event.position().toPoint())
        )
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            if self._interactions.state in (
                InteractionState.WINDOW_MOVE_PENDING,
                InteractionState.WINDOW_RESIZE_PENDING,
                InteractionState.WINDOW_MOVING,
                InteractionState.WINDOW_RESIZING,
            ):
                self._interactions.finish_window_gesture()
                self.unsetCursor()
                event.accept()
                return

        super().mouseReleaseEvent(event)

    def closeEvent(self, event) -> None:
        self.lock_state_timer.stop()
        self._interactions.cancel()

        if self.conn:
            try:
                self.conn.close()
            except Exception:
                logger.debug("Error closing virtual keyboard IPC connection", exc_info=True)

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

    sys.exit(app.exec())


def virtual_keyboard_worker(conn: Connection) -> None:
    run(conn, False)


def main() -> None:
    """Dedicated entry point for touch2key-keyboard."""
    AppLogManager.setup_logging(log_prefix="touch2key_keyboard")
    run()


if __name__ == "__main__":
    main()
