# src/modules/gui/main_window.py

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from PySide6.QtCore import QObject, QThread, Qt, Signal
from PySide6.QtGui import QAction, QKeySequence
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
from modules.gui.dialogs.wireless_connect_dialog import connect_wireless_gui
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
    """Worker object to execute Engine.start_headless inside a worker QThread."""

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
            logger.exception("Engine failed during execution")
            self.failed.emit(str(exc))
        finally:
            self.finished.emit()


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

    # ---- Menu / Toolbar ---------------------------------------------------
    def _build_menu_and_toolbar(self) -> None:
        menu_bar = self.menuBar()

        file_menu = menu_bar.addMenu("&File")
        quit_action = QAction("&Quit", self)
        quit_action.setShortcut(QKeySequence.StandardKey.Quit)
        quit_action.triggered.connect(self.close)
        file_menu.addAction(quit_action)

        device_menu = menu_bar.addMenu("&Device")
        wireless_action = QAction("Connect &Wireless ADB...", self)
        wireless_action.triggered.connect(lambda: connect_wireless_gui(self))
        device_menu.addAction(wireless_action)

        self._view_menu = menu_bar.addMenu("&View")

        help_menu = menu_bar.addMenu("&Help")
        about_action = QAction("About Touch2Key", self)
        about_action.triggered.connect(self._show_about)
        help_menu.addAction(about_action)

        toolbar = QToolBar("Main")
        toolbar.setMovable(False)
        self.addToolBar(toolbar)

        self.start_action = QAction("&Start Engine", self)
        self.start_action.setShortcut(QKeySequence("Ctrl+R"))

        self.stop_action = QAction("S&top Engine", self)
        self.stop_action.setShortcut(QKeySequence("Ctrl+T"))
        self.stop_action.setEnabled(False)

        toolbar.addAction(self.start_action)
        toolbar.addAction(self.stop_action)

    def _show_about(self) -> None:
        QMessageBox.information(
            self, "About Touch2Key", "Touch2Key -- touch-to-keyboard/mouse mapper."
        )

    # ---- Sidebar + Stacked Pages -------------------------------------------
    def _build_sidebar_and_pages(self) -> None:
        central = QWidget()
        layout = QHBoxLayout(central)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self.sidebar = QListWidget()
        self.sidebar.setFixedWidth(160)
        self.stack = QStackedWidget()

        dispatcher = self.signal_bridge.dispatcher

        self.dashboard_page = DashboardPage(dispatcher=dispatcher)
        self.layout_editor_page = LayoutEditorPage(dispatcher=dispatcher)
        self.pipelines_page = PipelinesPage(dispatcher=dispatcher)
        self.devices_page = DevicesPage(dispatcher=dispatcher)
        self.key_bindings_page = KeyBindingsPage(dispatcher=dispatcher)
        self.performance_page = PerformancePage(dispatcher=dispatcher)
        self.profiles_page = ProfilesPage(dispatcher=dispatcher)
        self.settings_page = SettingsPage(dispatcher=dispatcher)

        self.pages = [
            self.dashboard_page,
            self.layout_editor_page,
            self.pipelines_page,
            self.devices_page,
            self.key_bindings_page,
            self.performance_page,
            self.profiles_page,
            self.settings_page,
        ]

        for page in self.pages:
            self.sidebar.addItem(QListWidgetItem(page.title))
            self.stack.addWidget(page)

        self.sidebar.currentRowChanged.connect(self._on_sidebar_row_changed)
        self.sidebar.setCurrentRow(0)

        layout.addWidget(self.sidebar)
        layout.addWidget(self.stack, stretch=1)
        self.setCentralWidget(central)

    def _on_sidebar_row_changed(self, row: int) -> None:
        self.stack.setCurrentIndex(row)
        current_page = self.stack.widget(row)
        if hasattr(current_page, "on_page_shown"):
            current_page.on_page_shown()

    # ---- Right-Hand Status Dock --------------------------------------------
    def _build_status_dock(self) -> None:
        dock = QDockWidget("Status", self)
        dock.setFeatures(
            QDockWidget.DockWidgetFeature.DockWidgetMovable
            | QDockWidget.DockWidgetFeature.DockWidgetClosable
        )

        panel = QWidget()
        panel_layout = QHBoxLayout(panel)
        self.connection_label = QLabel("Device: Disconnected")
        self.rate_label = QLabel("Rate: -- PPS")
        self.cursor_label = QLabel("Cursor: Shown")

        for lbl in (self.connection_label, self.rate_label, self.cursor_label):
            panel_layout.addWidget(lbl)
        panel_layout.addStretch()

        dock.setWidget(panel)
        self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, dock)
        self._view_menu.addAction(dock.toggleViewAction())
        self.status_dock = dock

        self.signal_bridge.menu_mode_toggled.connect(
            lambda visible: self.cursor_label.setText(
                f"Cursor: {'Shown' if visible else 'Hidden'}"
            )
        )
        if hasattr(self.signal_bridge, "rate_updated"):
            self.signal_bridge.rate_updated.connect(
                lambda rate: self.rate_label.setText(f"Rate: {rate:.1f} PPS")
            )
        if hasattr(self.signal_bridge, "device_status_changed"):
            self.signal_bridge.device_status_changed.connect(
                lambda status: self.connection_label.setText(f"Device: {status}")
            )

    # ---- Bottom Log Dock ----------------------------------------------------
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

    # ---- Status Bar ---------------------------------------------------------
    def _build_status_bar(self) -> None:
        self.statusBar().showMessage("Ready.")

    # ---- Dashboard / Engine Lifecycle Wiring --------------------------------
    def _wire_dashboard_buttons(self) -> None:
        self.dashboard_page.start_btn.clicked.connect(self._start_engine)
        self.dashboard_page.stop_btn.clicked.connect(self._stop_engine)
        self.start_action.triggered.connect(self._start_engine)
        self.stop_action.triggered.connect(self._stop_engine)

    def _start_engine(self) -> None:
        if self.engine is not None:
            return

        target_window_id = self.devices_page.selected_window_id
        if target_window_id is None:
            QMessageBox.warning(
                self,
                "No Window Selected",
                "Please select and bind a target window from the 'Devices' page before starting.",
            )
            self.sidebar.setCurrentRow(3)  # Switch to Devices tab
            return

        try:
            from modules.engine import Engine

            self.engine = Engine(headless=True)
            self.signal_bridge.bind(self.engine.mapper_event_dispatcher)

            # Route engine dispatcher directly to child pages
            for page in self.pages:
                page.dispatcher = self.engine.mapper_event_dispatcher

            self.engine_thread = QThread(self)
            self.engine_worker = EngineWorker(self.engine, target_window_id)
            self.engine_worker.moveToThread(self.engine_thread)

            self.engine_thread.started.connect(self.engine_worker.run)
            self.engine_worker.started.connect(self._on_engine_started)
            self.engine_worker.failed.connect(self._on_engine_failed)
            self.engine_worker.finished.connect(self.engine_thread.quit)
            self.engine_worker.finished.connect(self.engine_worker.deleteLater)
            self.engine_thread.finished.connect(self.engine_thread.deleteLater)

            self.engine_thread.start()

        except Exception as exc:
            logger.exception("Failed to initialize engine")
            QMessageBox.critical(self, "Start failed", str(exc))
            self._cleanup_engine()

    def _on_engine_started(self) -> None:
        title = self.devices_page.selected_window_title
        self.dashboard_page.set_running(True, window_title=title)
        self.start_action.setEnabled(False)
        self.stop_action.setEnabled(True)
        self.statusBar().showMessage(f"Engine running (Target: {title}).")

    def _on_engine_failed(self, error_msg: str) -> None:
        QMessageBox.critical(self, "Engine Error", f"Engine failed to start:\n{error_msg}")
        self._stop_engine()

    def _cleanup_engine(self) -> None:
        self.signal_bridge.unbind()

        # Restore the standalone dispatcher for GUI pages
        for page in self.pages:
            page.dispatcher = self.signal_bridge.dispatcher

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
        store.close()
        super().closeEvent(event)
