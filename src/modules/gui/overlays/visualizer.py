import sys
import time
import ctypes
from typing import TYPE_CHECKING

from modules.utils import get_scancode_from_key
from modules.platforms import get_platform, check_single_instance, get_specific_qt_key

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

if TYPE_CHECKING:
    from PySide6.QtWidgets import QGraphicsItem
    
_PLATFORM = get_platform()

VISUALIZER_NAME = "Touch2Key_Visualizer"

class DiagnosticView(QGraphicsView):
    def __init__(self, parent):
        super().__init__(parent)
        self.parent_window = parent
        self.setMouseTracking(True)

        self.scene: QGraphicsScene | None = QGraphicsScene(self)
        self.setScene(self.scene)
        self.setStyleSheet("background: black; border: none;")
        self.setRenderHint(QPainter.RenderHint.Antialiasing)

        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        instruction = self.scene.addText("DIAGNOSTIC MODE: Press ESC to exit and view Heatmap", QFont("Arial", 10))
        instruction.setDefaultTextColor(QColor("#444444"))
        instruction.setPos(50, 30)

        self.active_key_text = self.scene.addText("", QFont("Courier", 16, QFont.Weight.Bold))
        self.active_key_text.setDefaultTextColor(QColor("lime"))
        self.active_key_text.setZValue(100)

    def mouseMoveEvent(self, event: QMouseEvent):
        pos = event.position().toPoint()
        
        if self.scene is not None:
            self.scene.addRect(pos.x(), pos.y(), 1, 1, QPen(QColor("#1a1a1a"))) 
            self.active_key_text.setPos(pos.x() + 20, pos.y() - 20)
            
        super().mouseMoveEvent(event)

    def mousePressEvent(self, event: QMouseEvent):
        pos = event.position().toPoint()
        btn = event.button()

        if btn == Qt.MouseButton.LeftButton:
            btn_name, color = "Left", "cyan"
        elif btn == Qt.MouseButton.RightButton:
            btn_name, color = "Right", "magenta"
        else:
            btn_name, color = "Middle", "yellow"

        self.parent_window.data.append(
            {
                "x": pos.x(),
                "y": pos.y(),
                "type": f"{btn_name} Click",
                "time": time.time(),
            }
        )
        
        if self.scene is not None:
            ripple = self.scene.addEllipse(pos.x() - 15, pos.y() - 15, 30, 30, QPen(QColor(color), 2))
            label = self.scene.addText(f"{btn_name}", QFont("Arial", 8))
            label.setDefaultTextColor(QColor(color))
            label.setPos(pos.x(), pos.y() + 15)
            
        QTimer.singleShot(1000, lambda: self._remove_scene_item(ripple))
        QTimer.singleShot(1000, lambda: self._remove_scene_item(label))

        super().mousePressEvent(event)

    def _remove_scene_item(self, item: QGraphicsItem, /) -> None:
        if self.scene is not None:
            self.scene.removeItem(item)



class MainWindow(QMainWindow):
    def __init__(self, toggle_key_scancode: int | None = None):
        super().__init__()
        self.toggle_key_scancode = toggle_key_scancode
        self.cursor_visible = _PLATFORM.WindowManager().is_cursor_visible(True, 0)
        self.data = []

        self.setWindowTitle(VISUALIZER_NAME)
        self.setWindowOpacity(0.4)
        self.showFullScreen()

        self.view = DiagnosticView(self)
        self.setCentralWidget(self.view)

        screen_geometry = QGuiApplication.primaryScreen().geometry()
        self.view.setSceneRect(0, 0, screen_geometry.width(), screen_geometry.height())

    def _force_cursor_hidden(self):
        while ctypes.windll.user32.ShowCursor(False) >= 0:
            pass

    def _force_cursor_visible(self):
        while ctypes.windll.user32.ShowCursor(True) < 0:
            pass

    def keyPressEvent(self, event: QKeyEvent):
        key = get_specific_qt_key(event)
        scancode = get_scancode_from_key(key)

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

        if event.key == Qt.Key.Key_Escape:
            if self.cursor_visible:
                self.close()
                return

        key_name = event.text().upper() if event.text() else f"KEY_{key.strip().upper()}"

        cursor_pos = self.view.mapFromGlobal(self.cursor().pos())
        mx, my = cursor_pos.x(), cursor_pos.y()

        self.data.append(
            {"x": mx, "y": my, "type": f"Key: {key_name}", "time": time.time()}
        )

        self.view.active_key_text.setPlainText(f"[{key_name}]")
        super().keyPressEvent(event)

def run():
    success, _ = check_single_instance(VISUALIZER_NAME)
    if not success:
        sys.exit(0)
        
    app = QApplication(sys.argv)
    MainWindow()
    sys.exit(app.exec())
    
if __name__ == "__main__":
    run()
