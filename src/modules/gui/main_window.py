"""
Touch2Key main GUI window.

Layout: menu bar + toolbar at top, sidebar navigation driving a
central QStackedWidget, a right-hand status dock fed by
EngineSignalBridge, a bottom log console dock fed by QtLogHandler, and
a persistent status bar.

This window owns no engine/ADB/touch logic itself -- it only starts
and stops an Engine instance and reacts to its signals. Keep page
widgets and this window dumb about mapper internals, so `touch2key`
(CLI) and `touch2key-gui` stay thin callers over the same core/ logic
rather than two divergent implementations.
"""
from __future__ import annotations
from typing import TYPE_CHECKING

import logging

from PySide6.QtCore import Qt
from PySide6.QtGui import QAction
from PySide6.QtWidgets import (
    QMainWindow,
    QWidget,
    QListWidget,
    QListWidgetItem,
    QStackedWidget,
    QDockWidget,
    QPlainTextEdit,
    QHBoxLayout,
    QLabel,
    QToolBar,
    QMessageBox,
)

from modules.gui.signal_bridge import EngineSignalBridge
from modules.gui.log_bridge import install_gui_logging
from modules.gui.pages import (
    DashboardPage,
    LayoutEditorPage,
    DevicesPage,
    KeyBindingsPage,
    PerformancePage,
    ProfilesPage,
    SettingsPage,
)

if TYPE_CHECKING:
    from modules.engine import Engine

logger = logging.getLogger("modules.gui")


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Touch2Key")
        self.resize(1000, 640)

        self.engine: "Engine | None" = None
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

        # populated with dock toggle actions once the docks exist below
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
        self.devices_page = DevicesPage()
        self.key_bindings_page = KeyBindingsPage()
        self.performance_page = PerformancePage()
        self.profiles_page = ProfilesPage()
        self.settings_page = SettingsPage()

        pages = [
            self.dashboard_page,
            self.layout_editor_page,
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
        # rate_label / connection_label currently have no source signal --
        # Mapper._pulse_status() and TouchReader's connect/disconnect
        # paths only print() today. Wiring those live would mean adding
        # a couple of dispatcher.dispatch(MapperEvent(...)) calls at
        # those points and a matching signal + register_callback here,
        # the same pattern used for ON_MENU_MODE_TOGGLE above.

    # ---- Bottom log dock ----------------------------------------------------
    def _build_log_dock(self) -> None:
        dock = QDockWidget("Log", self)
        dock.setFeatures(
            QDockWidget.DockWidgetFeature.DockWidgetMovable
            | QDockWidget.DockWidgetFeature.DockWidgetClosable
        )

        self.log_console = QPlainTextEdit()
        self.log_console.setReadOnly(True)
        self.log_console.setMaximumBlockCount(2000)  # caps memory growth
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
            from modules.engine import Engine  # local import: heavy deps

            self.engine = Engine()

            # IMPORTANT: Engine._start() currently runs its setup
            # sequence (select_window -> capture_keys ->
            # capture_performance_settings -> keyboard.wait()) as
            # blocking calls on whatever thread calls it. Calling it
            # directly here would freeze the GUI event loop at
            # keyboard.wait(). Before this button is safe to use,
            # _start() needs to either:
            #   (a) run on a QThread/worker thread, with its dialogs
            #       replaced by the Devices/KeyBindings/Performance
            #       pages already collecting that state, or
            #   (b) be split into discrete non-blocking steps this
            #       window calls explicitly, with keyboard.wait()
            #       replaced entirely (the GUI event loop already
            #       serves that "keep running" role).
            # This call is left in as the intended call site; wire it
            # up once one of the above is done.
            self.signal_bridge.bind(getattr(self.engine, "mapper_event_dispatcher", None))

        except Exception as exc:
            logger.exception("Failed to start engine")
            QMessageBox.critical(self, "Start failed", str(exc))
            self.engine = None
            return

        self.dashboard_page.set_running(True)
        self.start_action.setEnabled(False)
        self.stop_action.setEnabled(True)
        self.statusBar().showMessage("Engine running.")

    def _stop_engine(self) -> None:
        if self.engine is None:
            return

        try:
            self.engine._shutdown()
        except Exception:
            logger.exception("Error during engine shutdown")
        self.engine = None

        self.dashboard_page.set_running(False)
        self.start_action.setEnabled(True)
        self.stop_action.setEnabled(False)
        self.statusBar().showMessage("Engine stopped.")

    def closeEvent(self, event) -> None:
        if self.engine is not None:
            self._stop_engine()
        super().closeEvent(event)
