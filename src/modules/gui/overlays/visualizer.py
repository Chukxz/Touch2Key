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
    bresenham,
    clamp,
    get_scancode_from_key,
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
        # Parenting the timer to the view prevents it outliving the scene.
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
        # Let QGraphicsView update its viewport before measuring it.
        super().resizeEvent(event)

        viewport_size = self.viewport().size()
        width, height = viewport_size.width(), viewport_size.height()

        self.setSceneRect(0.0, 0.0, float(width), float(height))
        self.resized.emit(width, height)

    def keyPressEvent(self, event: QKeyEvent) -> None:
        key = event.key()

        if key == Qt.Key.Key_Left:
            self.trail_width = clamp(
                self.trail_width - 1, 1, MAX_TRAIL_WIDTH
            )
            self.arrow_pressed.emit()
        elif key == Qt.Key.Key_Right:
            self.trail_width = clamp(
                self.trail_width + 1, 1, MAX_TRAIL_WIDTH
            )
            self.arrow_pressed.emit()
        elif key == Qt.Key.Key_Down:
            self.trail_height = clamp(
                self.trail_height - 1, 1, MAX_TRAIL_HEIGHT
            )
            self.arrow_pressed.emit()
        elif key == Qt.Key.Key_Up:
            self.trail_height = clamp(
                self.trail_height + 1, 1, MAX_TRAIL_HEIGHT
            )
            self.arrow_pressed.emit()

        super().keyPressEvent(event)


class MainWindow(QMainWindow):
    def __init__(self, toggle_key_scancode: int | None) -> None:
        super().__init__()

        self.toggle_key_scancode = toggle_key_scancode
        self.loc_dict: dict[int, tuple[float, float]] = {}

        # Positional arguments retained because the platform signature is
        # determined by the existing WindowManager implementation.
        self.cursor_visible = (
            _PLATFORM.WindowManager().is_cursor_visible(True, 0)[0]
        )

        self.data: deque[dict] = deque(maxlen=MAX_EVENT_LOG)
        # Keyed by native scancode (fallback: Qt key).
        self.pressed_keys: dict[int, str] = {}
        self.pressed_mouse_buttons: set[str] = set()

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
            QFont("Arial", 15),
        )
        self.instruction.setDefaultTextColor(QColor("#cccccc"))

        # Show first so the initial resize event has a valid viewport size.
        self.showFullScreen()
        self._on_view_resized(
            self.view.viewport().width(),
            self.view.viewport().height(),
        )
        self._position_instruction()

    # ------------------------------------------------------------------
    # Cursor
    # ------------------------------------------------------------------

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

    # ------------------------------------------------------------------
    # Display
    # ------------------------------------------------------------------

    def _update_active_display(self) -> None:
        parts = list(self.pressed_keys.values()) + sorted(
            self.pressed_mouse_buttons
        )
        self.view.set_active_text(
            f"[{' + '.join(parts)}]" if parts else ""
        )

    def _clear_pressed_state(self) -> None:
        self.pressed_keys.clear()
        self.pressed_mouse_buttons.clear()
        self._update_active_display()

    def _instruction_text(self) -> str:
        return (
            "Press ESC to exit (when cursor is visible).\n"
            f"(Left/Right: increase/decrease trail width "
            f"({self.view.trail_width}) [1-{MAX_TRAIL_WIDTH}]).\n"
            f"(Up/Down: increase/decrease trail height "
            f"({self.view.trail_height}) [1-{MAX_TRAIL_HEIGHT}]).\n"
            f"Maximum number of trails: {MAX_TRAIL_NUMBER}."
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

        layout_width = float(layout.width or 0)
        layout_height = float(layout.height or 0)

        # Incomplete or invalid layouts should not cause division by zero.
        if layout_width <= 0.0 or layout_height <= 0.0:
            return loc_dict

        zones = store.get_active_layout_zones()
        scale_x = width / layout_width
        scale_y = height / layout_height

        for zone in zones:
            loc_dict[zone.scancode] = (
                float(zone.cx or 0) * scale_x,
                float(zone.cy or 0) * scale_y,
            )

        return loc_dict

    # ------------------------------------------------------------------
    # View slots
    # ------------------------------------------------------------------

    def _on_mouse_pressed(
        self, btn_name: str, x: int, y: int
    ) -> None:
        self.pressed_mouse_buttons.add(btn_name)
        self.data.append(
            {
                "x": x,
                "y": y,
                "type": f"{btn_name} Click",
                "time": time.time(),
            }
        )
        self._update_active_display()

    def _on_mouse_released(self, btn_name: str) -> None:
        self.pressed_mouse_buttons.discard(btn_name)
        self._update_active_display()

    # ------------------------------------------------------------------
    # Events
    # ------------------------------------------------------------------

    @staticmethod
    def _key_identity(event: QKeyEvent) -> int:
        return event.nativeScanCode() or int(event.key())

    def keyPressEvent(self, event: QKeyEvent) -> None:
        key = get_specific_qt_key(event)
        scancode = get_scancode_from_key(key)

        if (
            self.toggle_key_scancode is not None
            and scancode == self.toggle_key_scancode
        ):
            if event.isAutoRepeat():
                super().keyPressEvent(event)
                return

            if self.cursor_visible:
                self._force_cursor_hidden()
                self.cursor_visible = False
            else:
                self._force_cursor_visible()
                self.cursor_visible = True

        if (
            event.key() == Qt.Key.Key_Escape
            and self.cursor_visible
        ):
            self.close()
            return

        key_name = key.strip().upper()
        self.pressed_keys[self._key_identity(event)] = key_name

        cursor_pos = self.view.mapFromGlobal(self.cursor().pos())
        mouse_x, mouse_y = cursor_pos.x(), cursor_pos.y()

        self.data.append(
            {
                "x": mouse_x,
                "y": mouse_y,
                "type": f"Key: {key_name}",
                "time": time.time(),
            }
        )

        self.view.set_labelled_ripple(
            mouse_x, mouse_y, key_name, scancode, "red"
        )
        self._update_active_display()
        super().keyPressEvent(event)

    def keyReleaseEvent(self, event: QKeyEvent) -> None:
        if event.isAutoRepeat():
            super().keyReleaseEvent(event)
            return

        self.pressed_keys.pop(self._key_identity(event), None)
        self._update_active_display()
        super().keyReleaseEvent(event)

    def changeEvent(self, event: QEvent) -> None:
        # Focus is on the child view, so window deactivation is the
        # reliable place to clear potentially stuck pressed-key state.
        if event.type() == QEvent.Type.WindowDeactivate:
            self._clear_pressed_state()

        super().changeEvent(event)

    def closeEvent(self, event) -> None:
        # Restore the cursor on every close path.
        self._force_cursor_visible()
        super().closeEvent(event)


def unregister_visualizer_file() -> None:
    unregister_process(VISUALIZER_RUNTIME_FILE)

def run(toggle_key_scancode: int | None = None) -> None:
    success, _ = check_single_instance(VISUALIZER_NAME)
    if not success:
        sys.exit(0)

    register_process(VISUALIZER_RUNTIME_FILE)
    atexit.register(unregister_visualizer_file)

    app = QApplication(sys.argv)
    app_icon_path = ICONS_FOLDER / "app.png"
    if app_icon_path.exists():
        app.setWindowIcon(QIcon(str(app_icon_path)))

    # Periodically give Python a chance to process SIGINT.
    timer = QTimer()
    timer.start(500)
    timer.timeout.connect(lambda: None)

    signal.signal(
        signal.SIGINT,
        lambda *_: QCoreApplication.quit(),
    )

    window = MainWindow(toggle_key_scancode)
    window.activateWindow()
    sys.exit(app.exec())


def main() -> None:
    """Dedicated entry point for touch2key-visualizer."""
    AppLogManager.setup_logging(log_prefix="touch2key_visualizer")
    run()


if __name__ == "__main__":
    main()
