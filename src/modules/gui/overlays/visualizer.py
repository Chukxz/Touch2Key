from __future__ import annotations

import sys
import time
import ctypes
from typing import TYPE_CHECKING

from modules.utils import get_scancode_from_key, scale_coord, ICONS_FOLDER
from modules.database import store
from modules.platforms import get_platform, get_specific_qt_key

from PySide6.QtWidgets import QApplication, QMainWindow, QGraphicsScene, QGraphicsView
from PySide6.QtGui import (
    QKeyEvent,
    QMouseEvent,
    QGuiApplication,
    QColor,
    QPen,
    QFont,
    QPainter,
)
from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QIcon

if TYPE_CHECKING:
    from PySide6.QtWidgets import QGraphicsItem

_PLATFORM = get_platform()

VISUALIZER_NAME = "Touch2Key_Visualizer"

MOUSE_BUTTON_INFO: dict[Qt.MouseButton, tuple[str, str]] = {
    Qt.MouseButton.LeftButton: ("Left", "cyan"),
    Qt.MouseButton.RightButton: ("Right", "magenta"),
    Qt.MouseButton.MiddleButton: ("Middle", "blue"),
    Qt.MouseButton.BackButton: ("Back", "orange"),
    Qt.MouseButton.ForwardButton: ("Forward", "yellow"),
}


def get_locations_dict() -> dict[int, tuple[int, int]]:
    loc_dict: dict[int, tuple[int, int]] = {}
    settings = store.settings.get()
    w = float(settings.json_dev_width)
    h = float(settings.json_dev_height)

    zones = store.get_active_layout_zones()
    for zone in zones:
        scancode = int(zone.scancode)
        scaled_x = int(scale_coord(w, zone.cx))
        scaled_y = int(scale_coord(h, zone.cy))

        loc_dict[scancode] = (scaled_x, scaled_y)

    return loc_dict


class DiagnosticView(QGraphicsView):
    def __init__(self, parent: MainWindow):
        super().__init__(parent)
        self.parent_window = parent
        self.setMouseTracking(True)

        self.scene: QGraphicsScene | None = QGraphicsScene(self)
        self.setScene(self.scene)
        self.setStyleSheet("background: black; border: none;")
        self.setRenderHint(QPainter.RenderHint.Antialiasing)

        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        self.instruction = self.scene.addText(
            "DIAGNOSTIC MODE: Press ESC to exit (when cursor is visible).", QFont("Arial", 10)
        )
        self.instruction.setDefaultTextColor(QColor("#444444"))
        self.instruction.setPos(50, 30)

        self.active_buttons = self.scene.addText(
            "", QFont("Courier", 16, QFont.Weight.Bold)
        )
        self.active_buttons.setDefaultTextColor(QColor("lime"))
        self.active_buttons.setZValue(100)

        self.trail_rects: list[QGraphicsItem] = []
        self.max_trail_length = 50

    def _add_trail_rect(self, x: int, y: int):
        if self.scene is not None:
            rect = self.scene.addRect(x, y, 1, 1, QPen(QColor("#1a1a1a")))
            self.trail_rects.append(rect)
            if len(self.trail_rects) > self.max_trail_length:
                old_rect = self.trail_rects.pop(0)
                self.scene.removeItem(old_rect)

    def _set_active_buttons_pos(self, x, y):
        if self.scene is not None:
            self._add_trail_rect(x, y)
            self.active_buttons.setPos(x + 20, y - 20)

    def _set_labelled_ripple(self, x, y, name, scancode: int, color):
        self._set_active_buttons_pos(x, y)

        pos_x = x
        pos_y = y

        if self.scene is not None:
            loc_value = self.parent_window.loc_dict.get(scancode)
            if loc_value is not None:
                pos_x, pos_y = loc_value

            ripple = self.scene.addEllipse(
                pos_x - 15, pos_y - 15, 30, 30, QPen(QColor(color), 2)
            )
            label = self.scene.addText(f"{name}", QFont("Arial", 8))
            label.setDefaultTextColor(QColor(color))
            label.setPos(pos_x, pos_y + 15)

        QTimer.singleShot(5000, lambda: self._remove_scene_item(ripple))
        QTimer.singleShot(5000, lambda: self._remove_scene_item(label))

    @staticmethod
    def _mouse_button_info(btn: Qt.MouseButton) -> tuple[str, str]:
        return MOUSE_BUTTON_INFO.get(btn, (f"Btn{int(btn.value)}", "white"))

    def mouseMoveEvent(self, event: QMouseEvent):
        pos = event.position().toPoint()

        if self.scene is not None:
            self._add_trail_rect(pos.x(), pos.y())
            self.active_buttons.setPos(pos.x() + 20, pos.y() - 20)

        super().mouseMoveEvent(event)

    def mousePressEvent(self, event: QMouseEvent):
        mouse_key = get_specific_qt_key(event)
        scancode = get_scancode_from_key(mouse_key) or 0

        pos = event.position().toPoint()
        btn = event.button()
        btn_name, color = self._mouse_button_info(btn)

        self.parent_window.pressed_mouse_buttons.add(btn_name)

        self.parent_window.data.append(
            {
                "x": pos.x(),
                "y": pos.y(),
                "type": f"{btn_name} Click",
                "time": time.time(),
            }
        )

        self._set_labelled_ripple(pos.x(), pos.y(), btn_name, scancode, color)
        self.parent_window._update_active_display()
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent):
        btn_name, _color = self._mouse_button_info(event.button())
        self.parent_window.pressed_mouse_buttons.discard(btn_name)
        self.parent_window._update_active_display()
        super().mouseReleaseEvent(event)

    def _remove_scene_item(self, item: QGraphicsItem, /) -> None:
        if self.scene is not None:
            self.scene.removeItem(item)


class MainWindow(QMainWindow):
    def __init__(
        self,
        toggle_key_scancode: int | None,
    ):
        super().__init__()

        self.toggle_key_scancode = toggle_key_scancode
        self.loc_dict = get_locations_dict()
        self.cursor_visible = _PLATFORM.WindowManager().is_cursor_visible(True, 0)
        self.data = []
        self.pressed_keys: dict[int, str] = {}
        self.pressed_mouse_buttons: set[str] = set()

        self.setWindowTitle(VISUALIZER_NAME)
        self.setWindowOpacity(0.4)
        self.showFullScreen()

        self.view = DiagnosticView(self)
        self.setCentralWidget(self.view)

        screen_geometry = QGuiApplication.primaryScreen().geometry()
        self.view.setSceneRect(0, 0, screen_geometry.width(), screen_geometry.height())

    def _force_cursor_hidden(self):
        if sys.platform == "win32":
            while ctypes.windll.user32.ShowCursor(False) >= 0:
                pass
        elif sys.platform == "linux":
            while QGuiApplication.overrideCursor() is not None:
                QGuiApplication.restoreOverrideCursor()
            QGuiApplication.setOverrideCursor(Qt.CursorShape.BlankCursor)

    def _force_cursor_visible(self):
        if sys.platform == "win32":
            while ctypes.windll.user32.ShowCursor(True) < 0:
                pass
        elif sys.platform == "linux":
            while QGuiApplication.overrideCursor() is not None:
                QGuiApplication.restoreOverrideCursor()

    def _update_active_display(self) -> None:
        parts = list(self.pressed_keys.values()) + sorted(self.pressed_mouse_buttons)
        self.view.active_buttons.setPlainText(f"[{' + '.join(parts)}]" if parts else "")

    def keyPressEvent(self, event: QKeyEvent):
        key = get_specific_qt_key(event)
        scancode = get_scancode_from_key(key) or 0

        if scancode == self.toggle_key_scancode:
            if event.isAutoRepeat():
                super().keyPressEvent(event)
                return

            if self.cursor_visible:
                self._force_cursor_hidden()
                self.cursor_visible = False
            else:
                self._force_cursor_visible()
                self.cursor_visible = True

        if event.key() == Qt.Key.Key_Escape:
            if self.cursor_visible:
                self.close()
                return

        key_name = key.strip().upper()

        self.pressed_keys[scancode] = key_name

        cursor_pos = self.view.mapFromGlobal(self.cursor().pos())
        mx, my = cursor_pos.x(), cursor_pos.y()
        self.data.append(
            {"x": mx, "y": my, "type": f"Key: {key_name}", "time": time.time()}
        )

        self.view._set_labelled_ripple(mx, my, key_name, scancode, "red")
        self._update_active_display()
        super().keyPressEvent(event)

    def keyReleaseEvent(self, event: QKeyEvent):
        if event.isAutoRepeat():
            super().keyReleaseEvent(event)
            return

        key = get_specific_qt_key(event)
        scancode = get_scancode_from_key(key) or 0

        self.pressed_keys.pop(scancode, None)
        self._update_active_display()
        super().keyReleaseEvent(event)

    def focusOutEvent(self, event):
        self.pressed_keys.clear()
        self.pressed_mouse_buttons.clear()
        self._update_active_display()
        super().focusOutEvent(event)


def run(
    toggle_key_scancode: int | None = None,
):
    success, _ = check_single_instance(VISUALIZER_NAME)
    if not success:
        sys.exit(0)

    app = QApplication(sys.argv)
    app_icon_path = ICONS_FOLDER / "app.png"
    if app_icon_path.exists():
        app.setWindowIcon(QIcon(str(app_icon_path)))

    MainWindow(toggle_key_scancode)
    sys.exit(app.exec())


def main() -> None:
    """Dedicated entry point for touch2key-visualizer."""
    run()


if __name__ == "__main__":
    main()
