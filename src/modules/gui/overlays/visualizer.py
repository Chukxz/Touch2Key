from __future__ import annotations

import atexit
import sys
import os
import time
import ctypes
import logging
from collections import deque
from typing import TYPE_CHECKING

from modules.utils import bresenham, clamp, get_scancode_from_key, scale_coord, ICONS_FOLDER
from modules.database import store
from modules.platforms import get_platform, get_specific_qt_key, check_single_instance

from PySide6.QtWidgets import QApplication, QMainWindow, QGraphicsScene, QGraphicsView
from PySide6.QtGui import (
    QKeyEvent,
    QMouseEvent,
    QGuiApplication,
    QColor,
    QPen,
    QBrush,
    QFont,
    QPainter,
    QIcon,
)
from PySide6.QtCore import QEvent, Qt, QTimer, Signal

from modules import AppLogManager
from modules.utils import READ_ATTEMPTS, VISUALIZER_RUNTIME_FILE

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


def get_locations_dict(width: int, height: int) -> dict[int, tuple[int, int]]:
    # NOTE: coordinates are scaled by the *device* resolution (json_dev_*).
    # Verify scale_coord maps into screen space; the scene is screen-sized.
    loc_dict: dict[int, tuple[int, int]] = {}

    zones = store.get_active_layout_zones()
    for zone in zones:
        scaled_x = int(scale_coord(width, zone.cx))
        scaled_y = int(scale_coord(height, zone.cy))
        loc_dict[zone.scancode] = (scaled_x, scaled_y)

    return loc_dict


class DiagnosticView(QGraphicsView):
    mouse_pressed = Signal(str, int, int)  # (button name, x, y)
    mouse_released = Signal(str)  # (button_name)
    arrow_pressed = Signal()
    resized = Signal(int, int)  # (x, y)

    def __init__(
        self,
        loc_dict: dict[int, tuple[int, int]],
        parent: QMainWindow | None = None,
    ):
        super().__init__(parent)
        self._loc_dict = loc_dict
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

    def _add_trail_rect(self, x: int, y: int, w=5, h=5) -> None:
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
        self, x: int, y: int, name: str, scancode: int | None, color: str
    ) -> None:
        self._set_active_buttons_pos(x, y)

        loc = self._loc_dict.get(scancode) if scancode is not None else None
        pos_x, pos_y = loc if loc is not None else (x, y)

        ripple = self._scene.addEllipse(
            pos_x - 15, pos_y - 15, 30, 30, QPen(QColor(color), 2)
        )
        label = self._scene.addText(f"{name}", QFont("Arial", 8))
        label.setDefaultTextColor(QColor(color))
        label.setPos(pos_x, pos_y + 15)

        self._expire_later([ripple, label], RIPPLE_LIFETIME_MS)

    def _expire_later(self, items: list[QGraphicsItem], msec: int) -> None:
        # Timer is parented to the view, so it dies with it and never fires
        # against a destroyed scene.
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

    def set_loc_dict(self, loc_dict: dict[int, tuple[int, int]]) -> None:
        self._loc_dict = loc_dict

    @staticmethod
    def _mouse_button_info(btn: Qt.MouseButton) -> tuple[str, str]:
        return MOUSE_BUTTON_INFO.get(btn, (f"Btn{int(btn.value)}", "white"))

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        pos = event.position().toPoint()
        pos_x = pos.x()
        pos_y = pos.y()

        points_generator = bresenham(
            self.f_p_x or pos_x,
            self.f_p_y or pos_y,
            pos_x,
            pos_y,
            width0=self.trail_width,
            height0=self.trail_height,
        )

        for generated_point in points_generator:
            x, y, w, h = generated_point
            self._add_trail_rect(x, y, w, h)

        self.f_p_x = pos_x
        self.f_p_y = pos_y

        self.active_buttons.setPos(pos.x() + 20, pos.y() - 20)
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

    def resizeEvent(self, event) -> None:
        w, h = self.viewport().width(), self.viewport().height()
        self.setSceneRect(0, 0, w, h)
        self.resized.emit(w, h)
        super().resizeEvent(event)

    def keyPressEvent(self, event: QKeyEvent) -> None:
        if event.key() == Qt.Key.Key_Left:
            self.trail_width = clamp(self.trail_width - 1, 1, MAX_TRAIL_WIDTH)
            self.arrow_pressed.emit()

        if event.key() == Qt.Key.Key_Right:
            self.trail_width = clamp(self.trail_width + 1, 1, MAX_TRAIL_WIDTH)
            self.arrow_pressed.emit()

        if event.key() == Qt.Key.Key_Down:
            self.trail_height = clamp(self.trail_height - 1, 1, MAX_TRAIL_HEIGHT)
            self.arrow_pressed.emit()

        if event.key() == Qt.Key.Key_Up:
            self.trail_height = clamp(self.trail_height + 1, 1, MAX_TRAIL_HEIGHT)
            self.arrow_pressed.emit()

        return super().keyPressEvent(event)


class MainWindow(QMainWindow):
    def __init__(
        self,
        toggle_key_scancode: int | None,
    ):
        super().__init__()

        self.toggle_key_scancode = toggle_key_scancode
        self.loc_dict: dict[int, tuple[int, int]] = {}
        # Positional args kept as-is; platform signature not visible here.
        self.cursor_visible = _PLATFORM.WindowManager().is_cursor_visible(True, 0)
        self.data: deque[dict] = deque(maxlen=MAX_EVENT_LOG)
        # Keyed by native scancode (fallback: Qt key) so unmapped keys don't collide.
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
            f"Press ESC to exit (when cursor is visible).\n(Left/Right: increase/decrease trail width ({self.view.trail_width}) [1-{MAX_TRAIL_WIDTH}]).\n(Up/Down: increase/decrease trail height ({self.view.trail_height}) [1-{MAX_TRAIL_HEIGHT}]).\nMaximum number of trails: {MAX_TRAIL_NUMBER}.",
            QFont("Arial", 15),
        )
        self.instruction.setDefaultTextColor(QColor("#cccccc"))
        _ins_bd_rect = self.instruction.boundingRect()

        _offset_x = int((self.width() - _ins_bd_rect.width()) * 0.5)
        _offset_y = int((self.height() - _ins_bd_rect.height()) * 0.2)

        self.instruction.setPos(_offset_x, _offset_y)

    # ----------------------------------------------------------------- cursor

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

    # ---------------------------------------------------------------- display

    def _update_active_display(self) -> None:
        parts = list(self.pressed_keys.values()) + sorted(self.pressed_mouse_buttons)
        self.view.set_active_text(f"[{' + '.join(parts)}]" if parts else "")

    def _clear_pressed_state(self) -> None:
        self.pressed_keys.clear()
        self.pressed_mouse_buttons.clear()
        self._update_active_display()

    def _update_instruction_text(self) -> None:
        self.instruction.setPlainText(
            f"Press ESC to exit (when cursor is visible).\n(Left/Right: increase/decrease trail width ({self.view.trail_width}) [1-{MAX_TRAIL_WIDTH}]).\n(Up/Down: increase/decrease trail height ({self.view.trail_height}) [1-{MAX_TRAIL_HEIGHT}]).\nMaximum number of trails: {MAX_TRAIL_NUMBER}.",
        )

    def _on_view_resized(self, w: int, h: int) -> None:
        self.loc_dict = get_locations_dict(w, h)
        self.view.set_loc_dict(self.loc_dict)

    # ------------------------------------------------------------ view slots

    def _on_mouse_pressed(self, btn_name: str, x: int, y: int) -> None:
        self.pressed_mouse_buttons.add(btn_name)
        self.data.append(
            {"x": x, "y": y, "type": f"{btn_name} Click", "time": time.time()}
        )
        self._update_active_display()

    def _on_mouse_released(self, btn_name: str) -> None:
        self.pressed_mouse_buttons.discard(btn_name)
        self._update_active_display()

    # ----------------------------------------------------------------- events

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

        if event.key() == Qt.Key.Key_Escape and self.cursor_visible:
            self.close()
            return

        key_name = key.strip().upper()
        self.pressed_keys[self._key_identity(event)] = key_name

        cursor_pos = self.view.mapFromGlobal(self.cursor().pos())
        mx, my = cursor_pos.x(), cursor_pos.y()
        self.data.append(
            {"x": mx, "y": my, "type": f"Key: {key_name}", "time": time.time()}
        )

        self.view.set_labelled_ripple(mx, my, key_name, scancode, "red")
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
        # Focus sits on the child view, so QMainWindow.focusOutEvent never fires;
        # window deactivation is the reliable signal.
        if event.type() == QEvent.Type.WindowDeactivate:
            self._clear_pressed_state()
        super().changeEvent(event)

    def closeEvent(self, event) -> None:
        # Always restore the cursor, whatever path closed the window.
        self._force_cursor_visible()
        super().closeEvent(event)


def _final_write():
    _write(-1)


def _write(payload: int) -> None:
    tmp = VISUALIZER_RUNTIME_FILE.with_suffix(".tmp")
    tmp.write_text(str(payload), encoding="utf-8")
    os.replace(tmp, VISUALIZER_RUNTIME_FILE)  # atomic: readers never see a torn file


def run(
    toggle_key_scancode: int | None = None,
) -> None:
    success, _ = check_single_instance(VISUALIZER_NAME)
    if not success:
        sys.exit(0)

    pid = os.getpid()
    _write(pid)

    atexit.register(_final_write)

    app = QApplication(sys.argv)
    app_icon_path = ICONS_FOLDER / "app.png"
    if app_icon_path.exists():
        app.setWindowIcon(QIcon(str(app_icon_path)))

    # Hold an owning reference for the lifetime of the event loop.
    window = MainWindow(toggle_key_scancode)
    window.showFullScreen()
    window.activateWindow()
    sys.exit(app.exec())


def main() -> None:
    """Dedicated entry point for touch2key-visualizer."""
    AppLogManager.setup_logging(is_gui=False, log_prefix="touch2key_visualizer")
    run()


if __name__ == "__main__":
    main()
