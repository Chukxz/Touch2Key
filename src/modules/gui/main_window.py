"""
Touch2Key main GUI window.

Layout: menu bar + toolbar at top, sidebar navigation driving a
central QStackedWidget, a right-hand status dock fed by
EngineSignalBridge, a bottom log console dock fed by QtLogHandler, and
a persistent status bar.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from PySide6.QtCore import QObject, QThread, Qt, Signal
from PySide6.QtGui import QAction
from PySide6.QtWidgets import (
    QDockWidget,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QStackedWidget,
    QToolBar,
    QWidget,
)

from modules.database import store
from modules.gui.log_bridge import install_gui_logging
from modules.gui.pages import (
    DashboardPage,
    DevicesPage,
    KeyBindingsPage,
    LayoutEditorPage,
    PerformancePage,
    PipelinesPage,
    ProfilesPage,
    SettingsPage,
)
from modules.gui.signal_bridge import EngineSignalBridge

if TYPE_CHECKING:
    from modules.engine import Engine

logger = logging.getLogger("modules.gui")


class EngineWorker(QObject):
    """Worker object to run Engine.start_headless inside a separate QThread."""

    started = Signal()
    finished = Signal()
    failed = Signal(str)

    def __init__(self, engine: "Engine", window_id: int):
        super().__init__()
        self.engine = engine
        self.window_id = window_id

    def run(self) -> None:
        try:
            s = store.settings.get()
            self.engine.start_headless(
                window_id=self.window_id,
                rate_cap=s.adb_rate_cap,
                pps=s.pps_alert_threshold,
                toggle_key=s.toggle_key,
                sprint_key=s.sprint_key,
            )
            self.started.emit()
        except Exception as exc:
            logger.exception("Engine failed to launch in worker thread")
            self.failed.emit(str(exc))


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Touch2Key")
        self.resize(1000, 640)

        self.engine: "Engine | None" = None
        self.engine_thread: QThread | None = None
        self.engine_worker: EngineWorker | None = None
        self.signal_bridge = EngineSignalBridge(self)

        self._build_menu_and_toolbar()
        self._build_sidebar_and_pages()
        self._build_status_dock()
        self._build_log_dock()
        self._build_status_bar()
        self._wire_dashboard_buttons()

    # ---- Menu / toolbar ---------------------------------------------------
    def _build_menu_and_toolbar(self) -> None:
        menu_bar = self.menuBar()

        file_menu = menu_bar.addMenu("&File")
        quit_action = QAction("Quit", self)
        quit_action.triggered.connect(self.close)
        file_menu.addAction(quit_action)

        device_menu = menu_bar.addMenu("&Device")
        connect_wireless_action = QAction("Connect wirelessly", self)
        device_menu.addAction(connect_wireless_action)

        self._view_menu = menu_bar.addMenu("&View")

        help_menu = menu_bar.addMenu("&Help")
        about_action = QAction("About Touch2Key", self)
        about_action.triggered.connect(self._show_about)
        help_menu.addAction(about_action)

        toolbar = QToolBar("Main")
        toolbar.setMovable(False)
        self.addToolBar(toolbar)

        self.start_action = QAction("Start", self)
        self.stop_action = QAction("Stop", self)
        self.stop_action.setEnabled(False)
        toolbar.addAction(self.start_action)
        toolbar.addAction(self.stop_action)

    def _show_about(self) -> None:
        QMessageBox.information(
            self, "About Touch2Key", "Touch2Key -- touch-to-keyboard/mouse mapper."
        )

    # ---- Sidebar + stacked pages -------------------------------------------
    def _build_sidebar_and_pages(self) -> None:
        central = QWidget()
        layout = QHBoxLayout(central)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self.sidebar = QListWidget()
        self.sidebar.setFixedWidth(160)
        self.stack = QStackedWidget()

        self.dashboard_page = DashboardPage()
        self.layout_editor_page = LayoutEditorPage()
        self.pipelines_page = PipelinesPage()
        self.devices_page = DevicesPage()
        self.key_bindings_page = KeyBindingsPage()
        self.performance_page = PerformancePage()
        self.profiles_page = ProfilesPage()
        self.settings_page = SettingsPage()

        pages = [
            self.dashboard_page,
            self.layout_editor_page,
            self.pipelines_page,
            self.devices_page,
            self.key_bindings_page,
            self.performance_page,
            self.profiles_page,
            self.settings_page,
        ]
        for page in pages:
            self.sidebar.addItem(QListWidgetItem(page.title))
            self.stack.addWidget(page)

        self.sidebar.currentRowChanged.connect(self.stack.setCurrentIndex)
        self.sidebar.setCurrentRow(0)

        layout.addWidget(self.sidebar)
        layout.addWidget(self.stack, stretch=1)
        self.setCentralWidget(central)

        self.layout_editor_page = LayoutEditorPage(dispatcher=self.signal_bridge.dispatcher)
        self.profiles_page = ProfilesPage(dispatcher=self.signal_bridge.dispatcher)

    # ---- Right-hand status dock --------------------------------------------
    def _build_status_dock(self) -> None:
        dock = QDockWidget("Status", self)
        dock.setFeatures(
            QDockWidget.DockWidgetFeature.DockWidgetMovable
            | QDockWidget.DockWidgetFeature.DockWidgetClosable
        )

        panel = QWidget()
        panel_layout = QHBoxLayout(panel)
        self.connection_label = QLabel("Device: disconnected")
        self.rate_label = QLabel("Rate: --")
        self.cursor_label = QLabel("Cursor: shown")
        for lbl in (self.connection_label, self.rate_label, self.cursor_label):
            panel_layout.addWidget(lbl)
        panel_layout.addStretch()

        dock.setWidget(panel)
        self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, dock)
        self._view_menu.addAction(dock.toggleViewAction())
        self.status_dock = dock

        self.signal_bridge.menu_mode_toggled.connect(
            lambda visible: self.cursor_label.setText(
                f"Cursor: {'shown' if visible else 'hidden'}"
            )
        )

    # ---- Bottom log dock ----------------------------------------------------
    def _build_log_dock(self) -> None:
        dock = QDockWidget("Log", self)
        dock.setFeatures(
            QDockWidget.DockWidgetFeature.DockWidgetMovable
            | QDockWidget.DockWidgetFeature.DockWidgetClosable
        )

        self.log_console = QPlainTextEdit()
        self.log_console.setReadOnly(True)
        self.log_console.setMaximumBlockCount(2000)
        dock.setWidget(self.log_console)

        self.addDockWidget(Qt.DockWidgetArea.BottomDockWidgetArea, dock)
        self._view_menu.addAction(dock.toggleViewAction())
        self.log_dock = dock

        handler = install_gui_logging()
        handler.emitter.message.connect(self._append_log_line)

    def _append_log_line(self, line: str, levelno: int) -> None:
        self.log_console.appendPlainText(line)

    # ---- Status bar ---------------------------------------------------------
    def _build_status_bar(self) -> None:
        self.statusBar().showMessage("Ready.")

    # ---- Dashboard / engine lifecycle wiring --------------------------------
    def _wire_dashboard_buttons(self) -> None:
        self.dashboard_page.start_btn.clicked.connect(self._start_engine)
        self.dashboard_page.stop_btn.clicked.connect(self._stop_engine)
        self.start_action.triggered.connect(self._start_engine)
        self.stop_action.triggered.connect(self._stop_engine)

    def _start_engine(self) -> None:
        if self.engine is not None:
            return

        try:
            from modules.core.list_windows import select_window
            from modules.engine import Engine

            # 1. Target Window Selection
            selected = select_window()
            if not selected:
                return
            window_id, _ = selected

            # 2. Instantiate Engine
            self.engine = Engine(headless=True)
            self.signal_bridge.bind(self.engine.mapper_event_dispatcher)

            # 3. Launch Engine in QThread
            self.engine_thread = QThread()
            self.engine_worker = EngineWorker(self.engine, window_id)
            self.engine_worker.moveToThread(self.engine_thread)

            self.engine_thread.started.connect(self.engine_worker.run)
            self.engine_worker.started.connect(self._on_engine_started)
            self.engine_worker.failed.connect(self._on_engine_failed)

            self.engine_thread.start()

        except Exception as exc:
            logger.exception("Failed to initialize engine")
            QMessageBox.critical(self, "Start failed", str(exc))
            self._cleanup_engine()

    def _on_engine_started(self) -> None:
        self.dashboard_page.set_running(True)
        self.start_action.setEnabled(False)
        self.stop_action.setEnabled(True)
        self.statusBar().showMessage("Engine running.")

    def _on_engine_failed(self, error_msg: str) -> None:
        QMessageBox.critical(self, "Engine Error", f"Engine failed to start:\n{error_msg}")
        self._stop_engine()

    def _cleanup_engine(self) -> None:
        if self.engine_thread and self.engine_thread.isRunning():
            self.engine_thread.quit()
            self.engine_thread.wait(1000)
        self.engine_thread = None
        self.engine_worker = None
        self.engine = None

    def _stop_engine(self) -> None:
        if self.engine is not None:
            try:
                self.engine._shutdown()
            except Exception:
                logger.exception("Error during engine shutdown")

        self._cleanup_engine()

        self.dashboard_page.set_running(False)
        self.start_action.setEnabled(True)
        self.stop_action.setEnabled(False)
        self.statusBar().showMessage("Engine stopped.")

    def closeEvent(self, event) -> None:
        if self.engine is not None:
            self._stop_engine()
        super().closeEvent(event)