from __future__ import annotations

import atexit
import ctypes
import logging
import os
import signal
import sys
import time
from collections import deque
from typing import TYPE_CHECKING

from PySide6.QtCore import QCoreApplication, QEvent, Qt, QTimer, Signal
from PySide6.QtGui import (
    QColor,
    QFont,
    QGuiApplication,
    QIcon,
    QKeyEvent,
    QMouseEvent,
    QPainter,
    QPen,
    QBrush,
    QResizeEvent,
)
from PySide6.QtWidgets import QApplication, QGraphicsScene, QGraphicsView, QMainWindow

from modules import AppLogManager
from modules.database import store
from modules.platforms import (
    check_single_instance,
    get_platform,
    get_specific_qt_key,
)
from modules.utils import (
    ICONS_FOLDER,
    VISUALIZER_RUNTIME_FILE,
    CurveType,
    InputCurve,
    bresenham,
    clamp,
    get_scancode_from_key,
    parse_seq,
)
from modules.runtime_info import register_process, unregister_process

if TYPE_CHECKING:
    from PySide6.QtWidgets import QGraphicsItem


logger = logging.getLogger("modules.gui.overlays.visualizer")

_PLATFORM = get_platform()

VISUALIZER_NAME = "Touch2Key_Visualizer"

RIPPLE_LIFETIME_MS = 5000
MAX_EVENT_LOG = 10_000
MAX_TRAIL_NUMBER = 1000
MAX_TRAIL_WIDTH = 100
MAX_TRAIL_HEIGHT = 100

MOUSE_BUTTON_INFO: dict[Qt.MouseButton, tuple[str, str]] = {
    Qt.MouseButton.LeftButton: ("Left", "cyan"),
    Qt.MouseButton.RightButton: ("Right", "magenta"),
    Qt.MouseButton.MiddleButton: ("Middle", "blue"),
    Qt.MouseButton.BackButton: ("Back", "orange"),
    Qt.MouseButton.ForwardButton: ("Forward", "yellow"),
}


class DiagnosticView(QGraphicsView):
    mouse_pressed = Signal(str, int, int)  # (button name, x, y)
    mouse_released = Signal(str)  # (button name)
    arrow_pressed = Signal()
    resized = Signal(int, int)  # (viewport width, viewport height)

    def __init__(
        self,
        loc_dict: dict[int, tuple[float, float]],
        parent: QMainWindow | None = None,
    ) -> None:
        super().__init__(parent)

        self._loc_dict: dict[int, tuple[float, float]] = loc_dict
        self.setMouseTracking(True)

        self._scene = QGraphicsScene(self)
        self.setScene(self._scene)
        self.setStyleSheet("background: black; border: none;")
        self.setRenderHint(QPainter.RenderHint.Antialiasing)

        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        self.active_buttons = self._scene.addText(
            "", QFont("Courier", 16, QFont.Weight.Bold)
        )
        self.active_buttons.setDefaultTextColor(QColor("lime"))
        self.active_buttons.setZValue(100)

        self.trail_rects: list[QGraphicsItem] = []
        self.max_trail_number = MAX_TRAIL_NUMBER
        self.trail_width = 5
        self.trail_height = 5
        self.f_p_x: int | None = None
        self.f_p_y: int | None = None

        # Input curve cycling state (defaults to CUBIC on startup).
        self._curve_types: tuple[CurveType, ...] = tuple(CurveType)
        self._curve_idx: int = self._curve_types.index(CurveType.CUBIC)
        self._current_curve: CurveType = self._curve_types[self._curve_idx]

        self._adjust_curves: dict[str, InputCurve] = {
            key: InputCurve(self._current_curve) for key in ("left", "right", "down", "up")
        }
        self._pressed_keys: set[int] = set()
        self._last_f8_time = 0.0

        # Poll timer for smooth typematic curve evaluation on held arrow keys (5 ms interval)
        self._poll_timer = QTimer(self)
        self._poll_timer.setInterval(5)
        self._poll_timer.timeout.connect(self._poll_hotkeys)
        self._poll_timer.start()

        logger.info("[Visualizer Launch] Default Input Curve: %s", self._current_curve.name)

    def get_current_curve_name(self) -> str:
        return self._current_curve.name

    def _poll_hotkeys(self) -> None:
        now = time.perf_counter()

        left_pressed = Qt.Key.Key_Left in self._pressed_keys
        right_pressed = Qt.Key.Key_Right in self._pressed_keys
        down_pressed = Qt.Key.Key_Down in self._pressed_keys
        up_pressed = Qt.Key.Key_Up in self._pressed_keys

        # Opposing keys on the same axis cancel: treat both as released.
        if left_pressed and right_pressed:
            left_pressed = right_pressed = False
        if down_pressed and up_pressed:
            down_pressed = up_pressed = False

        changed = False
        if self._adjust_curves["left"].check_input(now, left_pressed):
            self.trail_width = int(clamp(self.trail_width - 1, 1, MAX_TRAIL_WIDTH))
            changed = True
        if self._adjust_curves["right"].check_input(now, right_pressed):
            self.trail_width = int(clamp(self.trail_width + 1, 1, MAX_TRAIL_WIDTH))
            changed = True
        if self._adjust_curves["down"].check_input(now, down_pressed):
            self.trail_height = int(clamp(self.trail_height - 1, 1, MAX_TRAIL_HEIGHT))
            changed = True
        if self._adjust_curves["up"].check_input(now, up_pressed):
            self.trail_height = int(clamp(self.trail_height + 1, 1, MAX_TRAIL_HEIGHT))
            changed = True

        if changed:
            self.arrow_pressed.emit()

    def set_active_text(self, text: str) -> None:
        self.active_buttons.setPlainText(text)

    def _add_trail_rect(
        self, x: int, y: int, w: int = 5, h: int = 5
    ) -> None:
        rect = self._scene.addRect(
            x, y, w, h, QPen(QColor("#cccccc")), QBrush(QColor("#cccccc"))
        )
        self.trail_rects.append(rect)

        if len(self.trail_rects) > self.max_trail_number:
            old_rect = self.trail_rects.pop(0)
            self._remove_scene_item(old_rect)

    def _set_active_buttons_pos(self, x: int, y: int) -> None:
        self.active_buttons.setPos(x + 20, y - 20)

    def set_labelled_ripple(
        self,
        x: int,
        y: int,
        name: str,
        scancode: int | None,
        color: str,
    ) -> None:
        self._set_active_buttons_pos(x, y)

        loc = self._loc_dict.get(scancode) if scancode is not None else None
        pos_x, pos_y = loc if loc is not None else (x, y)

        ripple = self._scene.addEllipse(
            pos_x - 15, pos_y - 15, 30, 30, QPen(QColor(color), 2)
        )
        label = self._scene.addText(name, QFont("Arial", 8))
        label.setDefaultTextColor(QColor(color))
        label.setPos(pos_x, pos_y + 15)

        self._expire_later([ripple, label], RIPPLE_LIFETIME_MS)

    def _expire_later(self, items: list[QGraphicsItem], msec: int) -> None:
        timer = QTimer(self)
        timer.setSingleShot(True)

        def _expire() -> None:
            for item in items:
                self._remove_scene_item(item)
            timer.deleteLater()

        timer.timeout.connect(_expire)
        timer.start(msec)

    def _remove_scene_item(self, item: QGraphicsItem, /) -> None:
        if item.scene() is self._scene:
            self._scene.removeItem(item)

    def set_loc_dict(
        self, loc_dict: dict[int, tuple[float, float]]
    ) -> None:
        self._loc_dict = loc_dict

    @staticmethod
    def _mouse_button_info(
        btn: Qt.MouseButton,
    ) -> tuple[str, str]:
        return MOUSE_BUTTON_INFO.get(
            btn, (f"Btn{int(btn.value)}", "white")
        )

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        pos = event.position().toPoint()
        pos_x, pos_y = pos.x(), pos.y()

        points_generator = bresenham(
            self.f_p_x if self.f_p_x is not None else pos_x,
            self.f_p_y if self.f_p_y is not None else pos_y,
            pos_x,
            pos_y,
            width0=self.trail_width,
            height0=self.trail_height,
        )

        for x, y, w, h in points_generator:
            self._add_trail_rect(x, y, w, h)

        self.f_p_x = pos_x
        self.f_p_y = pos_y
        self.active_buttons.setPos(pos_x + 20, pos_y - 20)

        super().mouseMoveEvent(event)

    def mousePressEvent(self, event: QMouseEvent) -> None:
        mouse_key = get_specific_qt_key(event)
        scancode = get_scancode_from_key(mouse_key)

        pos = event.position().toPoint()
        btn_name, color = self._mouse_button_info(event.button())

        self.set_labelled_ripple(pos.x(), pos.y(), btn_name, scancode, color)
        self.mouse_pressed.emit(btn_name, pos.x(), pos.y())

        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        btn_name, _color = self._mouse_button_info(event.button())
        self.mouse_released.emit(btn_name)
        super().mouseReleaseEvent(event)

    def resizeEvent(self, event: QResizeEvent) -> None:
        super().resizeEvent(event)

        viewport_size = self.viewport().size()
        width, height = viewport_size.width(), viewport_size.height()

        self.setSceneRect(0.0, 0.0, float(width), float(height))
        self.resized.emit(width, height)

    def keyPressEvent(self, event: QKeyEvent) -> None:
        if event.isAutoRepeat():
            super().keyPressEvent(event)
            return

        key = event.key()
        self._pressed_keys.add(key)

        if key == Qt.Key.Key_F8:
            now = time.perf_counter()
            if now - self._last_f8_time >= 0.35:  # 350 ms debounce
                self._last_f8_time = now
                self._curve_idx = (self._curve_idx + 1) % len(self._curve_types)
                self._current_curve = self._curve_types[self._curve_idx]
                for k in self._adjust_curves:
                    self._adjust_curves[k] = InputCurve(self._current_curve)
                logger.info("Visualizer Input Curve cycled to %s", self._current_curve.name)
                self.arrow_pressed.emit()

        super().keyPressEvent(event)

    def keyReleaseEvent(self, event: QKeyEvent) -> None:
        if event.isAutoRepeat():
            super().keyReleaseEvent(event)
            return

        self._pressed_keys.discard(event.key())
        super().keyReleaseEvent(event)


class MainWindow(QMainWindow):
    def __init__(self, toggle_key_scancode: int | None) -> None:
        super().__init__()

        self.toggle_key_scancode = toggle_key_scancode
        self.loc_dict: dict[int, tuple[float, float]] = {}

        self.cursor_visible = (
            _PLATFORM.WindowManager().is_cursor_visible(True, 0)[0]
        )

        self.data: deque[dict] = deque(maxlen=MAX_EVENT_LOG)
        self.pressed_keys: dict[int, str] = {}
        self.pressed_mouse_buttons: set[str] = set()
        self.pressed_scancodes: set[int] = set()
        self._hotkey_triggered = False

        self.setWindowTitle(VISUALIZER_NAME)
        self.setWindowOpacity(0.4)

        self.view = DiagnosticView(self.loc_dict, self)
        self.view.mouse_pressed.connect(self._on_mouse_pressed)
        self.view.mouse_
