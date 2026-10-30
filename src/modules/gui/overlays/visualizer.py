"""
touch2key-visualizer: standalone diagnostic overlay rendering live touch ripples,
event traces, and dynamic input curve telemetry from the running engine.
"""

from __future__ import annotations

import atexit
import ctypes
import logging
import signal
import sys
import time
from collections import deque
from typing import TYPE_CHECKING

from PySide6.QtCore import QCoreApplication, QEvent, Qt, QTimer, Signal
from PySide6.QtGui import (
    QBrush,
    QColor,
    QFont,
    QGuiApplication,
    QIcon,
    QKeyEvent,
    QMouseEvent,
    QPainter,
    QPen,
    QResizeEvent,
)
from PySide6.QtWidgets import (
    QApplication,
    QGraphicsScene,
    QGraphicsView,
    QMainWindow,
    QGraphicsDropShadowEffect,
)

from modules.database import store
from modules.log_manager import AppLogManager, modify_qt_logging_rules_on_win32
from modules.platforms import (
    check_single_instance,
    get_platform,
    get_specific_qt_key,
)
from modules.runtime_info import attach, register_process, unregister_process
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

if TYPE_CHECKING:
    from PySide6.QtWidgets import QGraphicsItem


logger = logging.getLogger("modules.gui.overlays.visualizer")

_PLATFORM = get_platform()

VISUALIZER_NAME = "Touch2Key_Visualizer"

RIPPLE_LIFETIME_MS = 5000
MAX_EVENT_LOG = 10_000
MAX_TRAIL_NUMBER = 5000
MIN_TRAIL_NUMBER = 500
MAX_TRAIL_WIDTH = 100
MAX_TRAIL_HEIGHT = 100


MOUSE_BUTTON_INFO: dict[Qt.MouseButton, tuple[str, str]] = {
    Qt.MouseButton.LeftButton: ("Left", "cyan"),
    Qt.MouseButton.RightButton: ("Right", "magenta"),
    Qt.MouseButton.MiddleButton: ("Middle", "blue"),
    Qt.MouseButton.BackButton: ("Back", "orange"),
    Qt.MouseButton.ForwardButton: ("Forward", "yellow"),
}


def _create_high_visibility_shadow() -> QGraphicsDropShadowEffect:
    """Creates a hard, opaque black outline for text legibility over any background."""
    effect = QGraphicsDropShadowEffect()
    effect.setBlurRadius(4.0)
    effect.setColor(QColor(0, 0, 0, 255))
    effect.setOffset(1.0, 1.0)
    return effect


class DiagnosticView(QGraphicsView):
    mouse_pressed = Signal(str, int, int)  # (button name, x, y)
    mouse_released = Signal(str)  # (button name)
    arrow_pressed = Signal()
    resized = Signal(int, int)  # (viewport width, viewport height)

    def __init__(
        self,
        loc_dict: dict[int, tuple[float, float]],
        parent: MainWindow | None = None,
    ) -> None:
        super().__init__(parent)

        self._loc_dict: dict[int, tuple[float, float]] = loc_dict
        self.cursor_visible = _PLATFORM.WindowManager().is_cursor_visible(True, 0)[0]
        self.data: deque[dict] = deque(maxlen=MAX_EVENT_LOG)
        self.pressed_keys: dict[int, str] = {}
        self.pressed_mouse_buttons: set[str] = set()
        self.pressed_scancodes_list: list[int] = []
        self._hotkey_triggered = False
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
        self.active_buttons.setDefaultTextColor(QColor("#00FF00"))  # Lime Green
        self.active_buttons.setGraphicsEffect(_create_high_visibility_shadow())
        self.active_buttons.setZValue(100)

        self.trail_rects: list[QGraphicsItem] = []
        self.max_trail_number = 1000
        self.trail_width = 5
        self.trail_height = 5
        self.f_p_x: int | None = None
        self.f_p_y: int | None = None

        # Input curve cycling state (defaults to CUBIC on startup).
        self._curve_types: tuple[CurveType, ...] = tuple(CurveType)
        self._curve_idx: int = self._curve_types.index(CurveType.CUBIC)
        self._current_curve: CurveType = self._curve_types[self._curve_idx]

        self._adjust_curves: dict[str, InputCurve] = {
            key: InputCurve(self._current_curve)
            for key in ("left", "right", "down", "up", "inc_num", "dec_num")
        }
        # key -> (attribute, sign, lo, hi); applied as sign * count per poll.
        self._adjust_specs: dict[str, tuple[str, int, int, int]] = {
            "left": ("trail_width", -1, 1, MAX_TRAIL_WIDTH),
            "right": ("trail_width", +1, 1, MAX_TRAIL_WIDTH),
            "down": ("trail_height", -1, 1, MAX_TRAIL_HEIGHT),
            "up": ("trail_height", +1, 1, MAX_TRAIL_HEIGHT),
            "dec_num": ("max_trail_number", -1, MIN_TRAIL_NUMBER, MAX_TRAIL_NUMBER),
            "inc_num": ("max_trail_number", +1, MIN_TRAIL_NUMBER, MAX_TRAIL_NUMBER),
        }
        self._pressed_keys: set[int] = set()
        self._last_f8_time = 0.0
        self._last_dim_check = 0.0

        # Poll timer for smooth typematic curve evaluation & live engine sync (5 ms interval)
        self._poll_timer = QTimer(self)
        self._poll_timer.setInterval(5)
        self._poll_timer.timeout.connect(self._poll_hotkeys)
        self._poll_timer.start()

        logger.info(
            "[Visualizer Launch] Default Input Curve: %s", self._current_curve.name
        )

    def _force_cursor_hidden(self) -> None:
        if sys.platform == "win32":
            while ctypes.windll.user32.ShowCursor(False) >= 0:
                pass
        elif sys.platform == "linux":
            while QGuiApplication.overrideCursor() is not None:
                QGuiApplication.restoreOverrideCursor()
            QGuiApplication.setOverrideCursor(Qt.CursorShape.BlankCursor)

    def _force_cursor_visible(self) -> None:
        if sys.platform == "win32":
            while ctypes.windll.user32.ShowCursor(True) < 0:
                pass
        elif sys.platform == "linux":
            while QGuiApplication.overrideCursor() is not None:
                QGuiApplication.restoreOverrideCursor()

    def get_current_curve_name(self) -> str:
        return self._current_curve.name

    def _adjust(self, attr: str, delta: int, lo: int, hi: int) -> bool:
        """Apply delta with clamping. Returns True only if the value changed."""
        old = getattr(self, attr)
        new = int(clamp(old + delta, lo, hi))
        if new == old:
            return False
        setattr(self, attr, new)
        return True

    def _poll_hotkeys(self) -> None:
        now = time.perf_counter()

        is_control = Qt.Key.Key_Control in self._pressed_keys
        pressed = {
            "left": Qt.Key.Key_Left in self._pressed_keys and is_control,
            "right": Qt.Key.Key_Right in self._pressed_keys and is_control,
            "down": Qt.Key.Key_Down in self._pressed_keys and is_control,
            "up": Qt.Key.Key_Up in self._pressed_keys and is_control,
            "dec_num": Qt.Key.Key_F6 in self._pressed_keys and is_control,
            "inc_num": Qt.Key.Key_F7 in self._pressed_keys and is_control,
        }

        # Opposing keys on the same axis cancel: treat both as released.
        for a, b in (("left", "right"), ("down", "up"), ("dec_num", "inc_num")):
            if pressed[a] and pressed[b]:
                pressed[a] = pressed[b] = False

        changed = False
        for key, curve in self._adjust_curves.items():
            count = curve.check_input(now, pressed[key])
            if not count:
                continue
            attr, sign, lo, hi = self._adjust_specs[key]
            if self._adjust(attr, sign * count, lo, hi):
                changed = True

        if changed:
            self.arrow_pressed.emit()

        # Silently sync live device dimensions from the engine every 2.0 seconds
        if now - self._last_dim_check > 2.0:
            self._last_dim_check = now
            viewport_size = self.viewport().size()
            new_locs = MainWindow.get_locations_dict(
                viewport_size.width(), viewport_size.height()
            )
            if new_locs and new_locs != self._loc_dict:
                self._loc_dict = new_locs
                if isinstance(self.parent(), MainWindow):
                    self.parent().loc_dict = new_locs

    def set_active_text(self, text: str) -> None:
        self.active_buttons.setPlainText(text)

    def _add_trail_rect(self, x: int, y: int, w: int = 5, h: int = 5) -> None:
        rect = self._scene.addRect(
            x, y, w, h, QPen(QColor("#cccccc")), QBrush(QColor("#cccccc"))
        )
        self.trail_rects.append(rect)

        while len(self.trail_rects) > self.max_trail_number:
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
        label.setGraphicsEffect(_create_high_visibility_shadow())
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

    def set_loc_dict(self, loc_dict: dict[int, tuple[float, float]]) -> None:
        self._loc_dict = loc_dict

    def _update_active_display(self) -> None:
        parts = list(self.pressed_keys.values()) + sorted(self.pressed_mouse_buttons)
        self.set_active_text(f"[{' + '.join(parts)}]" if parts else "")

    def _clear_pressed_state(self) -> None:
        self.pressed_keys.clear()
        self.pressed_mouse_buttons.clear()
        self.pressed_scancodes_list.clear()
        self._hotkey_triggered = False
        self._update_active_display()

    @staticmethod
    def _mouse_button_info(
        btn: Qt.MouseButton,
    ) -> tuple[str, str]:
        return MOUSE_BUTTON_INFO.get(btn, (f"Btn{int(btn.value)}", "white"))

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

    @staticmethod
    def _key_identity(event: QKeyEvent) -> int:
        return event.nativeScanCode() or int(event.key())

    def keyPressEvent(self, event: QKeyEvent) -> None:
        if event.isAutoRepeat():
            super().keyPressEvent(event)
            return

        self._pressed_keys.add(event.key())

        scancode_key = get_specific_qt_key(event)
        scancode = get_scancode_from_key(scancode_key)

        if scancode is not None:
            if scancode not in self.pressed_scancodes_list:
                self.pressed_scancodes_list.append(scancode)

        settings = store.settings.get()
        hotkeys_str = settings.toggle_hotkeys or ""
        expected_scancodes = [
            code
            for name in parse_seq(hotkeys_str, ",")
            if (code := get_scancode_from_key(name)) is not None
        ]

        if expected_scancodes and self.pressed_scancodes_list == expected_scancodes:
            if not self._hotkey_triggered:
                self._hotkey_triggered = True

                if self.cursor_visible:
                    self._force_cursor_hidden()
                    self.cursor_visible = False
                else:
                    self._force_cursor_visible()
                    self.cursor_visible = True

        if (
            Qt.Key.Key_F8 in self._pressed_keys
            and Qt.Key.Key_Control in self._pressed_keys
        ):
            now = time.perf_counter()
            if now - self._last_f8_time >= 0.35:  # 350 ms debounce
                self._last_f8_time = now
                self._curve_idx = (self._curve_idx + 1) % len(self._curve_types)
                self._current_curve = self._curve_types[self._curve_idx]
                for k in self._adjust_curves:
                    self._adjust_curves[k] = InputCurve(self._current_curve)
                logger.info(
                    "Visualizer Input Curve cycled to %s", self._current_curve.name
                )
                self.arrow_pressed.emit()

        key_name = scancode_key.strip().upper()
        self.pressed_keys[self._key_identity(event)] = key_name

        cursor_pos = self.mapFromGlobal(self.cursor().pos())
        mouse_x, mouse_y = cursor_pos.x(), cursor_pos.y()

        self.data.append(
            {
                "x": mouse_x,
                "y": mouse_y,
                "type": f"Key: {key_name}",
                "time": time.time(),
            }
        )

        self.set_labelled_ripple(mouse_x, mouse_y, key_name, scancode, "red")

        self._update_active_display()
        super().keyPressEvent(event)

    def keyReleaseEvent(self, event: QKeyEvent) -> None:
        if event.isAutoRepeat():
            super().keyReleaseEvent(event)
            return

        self._pressed_keys.discard(event.key())

        key = get_specific_qt_key(event)
        scancode = get_scancode_from_key(key)
        if scancode is not None:
            while scancode in self.pressed_scancodes_list:
                self.pressed_scancodes_list.remove(scancode)

        settings = store.settings.get()
        hotkeys_str = settings.toggle_hotkeys or ""
        expected_scancodes = [
            code
            for name in parse_seq(hotkeys_str, ",")
            if (code := get_scancode_from_key(name)) is not None
        ]

        if self.pressed_scancodes_list != expected_scancodes:
            self._hotkey_triggered = False

        self.pressed_keys.pop(self._key_identity(event), None)

        self._update_active_display()
        super().keyReleaseEvent(event)


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()

        self.loc_dict: dict[int, tuple[float, float]] = {}
        self.setWindowTitle(VISUALIZER_NAME)
        self.setWindowOpacity(0.4)

        self.view = DiagnosticView(self.loc_dict, self)
        self.view.mouse_pressed.connect(self._on_mouse_pressed)
        self.view.mouse_released.connect(self._on_mouse_released)
        self.view.arrow_pressed.connect(self._update_instruction_text)
        self.view.resized.connect(self._on_view_resized)
        self.setCentralWidget(self.view)

        self.instruction = self.view._scene.addText(
            self._instruction_text(),
            QFont("Arial", 15, QFont.Weight.Bold),
        )
        self.instruction.setDefaultTextColor(QColor("#00FFFF"))  # Cyan
        self.instruction.setGraphicsEffect(_create_high_visibility_shadow())

        self.showFullScreen()
        self._on_view_resized(
            self.view.viewport().width(),
            self.view.viewport().height(),
        )
        self._position_instruction()

    def _instruction_text(self) -> str:
        curve_name = self.view.get_current_curve_name()
        return (
            "Press ESC to exit (when cursor is visible).\n"
            f"[CTRL + F8] Cycle Input Curve: [{curve_name}]\n"
            f"(CTRL + Left/Right: decrease/increase trail width "
            f"({self.view.trail_width}) [1-{MAX_TRAIL_WIDTH}]).\n"
            f"(CTRL + Up/Down: increase/decrease trail height "
            f"({self.view.trail_height}) [1-{MAX_TRAIL_HEIGHT}]).\n"
            f"(CTRL + F6/F7: decrease/increase max trail number) "
            f"({self.view.max_trail_number}) [{MIN_TRAIL_NUMBER}-{MAX_TRAIL_NUMBER}]."
        )

    def _update_instruction_text(self) -> None:
        self.instruction.setPlainText(self._instruction_text())
        self._position_instruction()

    def _position_instruction(self) -> None:
        instruction = getattr(self, "instruction", None)
        if instruction is None:
            return

        viewport = self.view.viewport()
        bounds = instruction.boundingRect()

        x = (viewport.width() - bounds.width()) * 0.5
        y = (viewport.height() - bounds.height()) * 0.2
        instruction.setPos(x, y)

    def _on_view_resized(self, width: int, height: int) -> None:
        self.loc_dict = self.get_locations_dict(width, height)
        self.view.set_loc_dict(self.loc_dict)
        self._position_instruction()

    @staticmethod
    def get_locations_dict(
        width: int,
        height: int,
    ) -> dict[int, tuple[float, float]]:
        loc_dict: dict[int, tuple[float, float]] = {}

        layout = store.get_active_layout()
        if layout is None:
            return loc_dict

        # Default fallback to static layout dimensions
        dev_w = float(layout.width or 0)
        dev_h = float(layout.height or 0)

        # Silently check for live engine telemetry snapshot dimensions (the engine & visualizer's little secret)
        attached = attach()
        if attached is not None:
            _, snap = attached
            live_w = snap.get("device_width")
            live_h = snap.get("device_height")
            if live_w and live_h:
                dev_w, dev_h = float(live_w), float(live_h)

        if dev_w <= 0.0 or dev_h <= 0.0:
            return loc_dict

        zones = store.get_active_layout_zones()
        scale_x = width / dev_w
        scale_y = height / dev_h

        for zone in zones:
            loc_dict[zone.scancode] = (
                float(zone.cx or 0) * scale_x,
                float(zone.cy or 0) * scale_y,
            )

        return loc_dict

    def _on_mouse_pressed(self, btn_name: str, x: int, y: int) -> None:
        self.view.pressed_mouse_buttons.add(btn_name)
        self.view.data.append(
            {
                "x": x,
                "y": y,
                "type": f"{btn_name} Click",
                "time": time.time(),
            }
        )
        self.view._update_active_display()

    def _on_mouse_released(self, btn_name: str) -> None:
        self.view.pressed_mouse_buttons.discard(btn_name)
        self.view._update_active_display()

    def keyPressEvent(self, event: QKeyEvent) -> None:
        if event.isAutoRepeat():
            super().keyPressEvent(event)
            return

        if event.key() == Qt.Key.Key_Escape and self.view.cursor_visible:
            self.close()
            return
        return super().keyPressEvent(event)

    def changeEvent(self, event: QEvent) -> None:
        if event.type() == QEvent.Type.WindowDeactivate:
            self.view._clear_pressed_state()

        super().changeEvent(event)

    def closeEvent(self, event) -> None:
        self.view._force_cursor_visible()
        super().closeEvent(event)


def unregister_visualizer_file() -> None:
    unregister_process(VISUALIZER_RUNTIME_FILE)


def run() -> None:
    success, _ = check_single_instance(VISUALIZER_NAME)
    if not success:
        sys.exit(0)

    register_process(VISUALIZER_RUNTIME_FILE)
    atexit.register(unregister_visualizer_file)

    modify_qt_logging_rules_on_win32()

    app = QApplication(sys.argv)
    app_icon_path = ICONS_FOLDER / "app.png"
    if app_icon_path.exists():
        app.setWindowIcon(QIcon(str(app_icon_path)))

    timer = QTimer()
    timer.start(500)
    timer.timeout.connect(lambda: None)

    signal.signal(
        signal.SIGINT,
        lambda *_: QCoreApplication.quit(),
    )

    window = MainWindow()
    window.activateWindow()
    sys.exit(app.exec())


def main() -> None:
    """Dedicated entry point for touch2key-visualizer."""
    AppLogManager.setup_logging(log_prefix="touch2key_visualizer")
    run()


if __name__ == "__main__":
    main()
