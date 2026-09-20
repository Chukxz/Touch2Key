from __future__ import annotations

import sys
import logging

from PySide6.QtCore import Qt, QThread, Signal, QCoreApplication
from PySide6.QtGui import QAction
from PySide6.QtWidgets import (
    QButtonGroup,
    QDockWidget,
    QHBoxLayout,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from modules.database import store
from modules.engine import Engine
from modules.gui.pages import BasePage
from modules.gui.pages.dashboard_page import DashboardPage
from modules.gui.pages.devices_page import DevicesPage
from modules.gui.pages.key_bindings_page import KeyBindingsPage
from modules.gui.pages.layout_editor_page import LayoutEditorPage
from modules.gui.pages.performance_page import PerformancePage
from modules.gui.pages.pipelines_page import PipelinesPage
from modules.gui.pages.profiles_page import ProfilesPage
from modules.gui.pages.settings_page import SettingsPage
from modules.gui.pages.typematic_page import TypematicPage

from modules.utils import MapperEventDispatcher

logger = logging.getLogger("modules.gui.main_window")


class QtLogHandler(logging.Handler):
    """Custom logging handler routing records into the GUI console dock."""

    def __init__(self, text_widget: QPlainTextEdit):
        super().__init__()
        self.text_widget = text_widget

    def emit(self, record: logging.LogRecord) -> None:
        msg = self.format(record)
        self.text_widget.appendPlainText(msg)


class EngineWorker(QThread):
    """Executes the mapping engine on a background worker thread."""

    started_signal = Signal()
    stopped_signal = Signal()
    error_signal = Signal(str)

    def __init__(self, dispatcher: MapperEventDispatcher):
        super().__init__()
        self.dispatcher = dispatcher
        self.engine: Engine | None = None
        self._is_running = False

    def start_engine(
        self,
        window_id: int | None,
        rate_cap: float,
        pps: float,
        toggle_key: str | None,
        sprint_key: str | None,
        typematic_enabled: bool = True,
        typematic_delay_ms: float = 250.0,
        typematic_rate_hz: float = 30.0,
        typematic_exclude_keys: str | None = None,
    ) -> None:
        self.window_id = window_id
        self.rate_cap = rate_cap
        self.pps = pps
        self.toggle_key = toggle_key
        self.sprint_key = sprint_key
        self.typematic_enabled = typematic_enabled
        self.typematic_delay_ms = typematic_delay_ms
        self.typematic_rate_hz = typematic_rate_hz
        self.typematic_exclude_keys = typematic_exclude_keys
        self._is_running = True
        self.start()

    def run(self) -> None:
        try:
            self.engine = Engine(headless=True, dispatcher=self.dispatcher)

            # Forward all engine knobs including typematic repeat parameters
            self.engine.start_headless(
                window_id=self.window_id,
                rate_cap=self.rate_cap,
                pps=self.pps,
                toggle_key=self.toggle_key,
                sprint_key=self.sprint_key,
                typematic_enabled=self.typematic_enabled,
                typematic_delay_ms=self.typematic_delay_ms,
                typematic_rate_hz=self.typematic_rate_hz,
                typematic_exclude_keys=self.typematic_exclude_keys,
            )
            self.started_signal.emit()

            while self._is_running:
                self.msleep(100)

        except Exception as exc:
            logger.exception("Engine thread runtime failure")
            self.error_signal.emit(str(exc))
        finally:
            if self.engine:
                self.engine._shutdown()
            self.stopped_signal.emit()

    def stop_engine(self) -> None:
        self._is_running = False
        if self.engine:
            self.engine._shutdown()
        self.quit()
        self.wait(1500)


class MainWindow(QMainWindow):
    """Root Application Window with scannable layout, pages stack, and log console."""

    def __init__(self):
        super().__init__()
        self.setWindowTitle("Touch2Key")
        self.resize(1180, 780)

        self.dispatcher = MapperEventDispatcher()
        self.engine_worker = EngineWorker(self.dispatcher)

        self._setup_ui()
        self._setup_logging()
        self._wire_engine_signals()

    def _setup_ui(self) -> None:
        central = QWidget()
        self.setCentralWidget(central)
        main_layout = QHBoxLayout(central)
        main_layout.setContentsMargins(8, 8, 8, 8)

        # -------------------------------------------------------------------
        # Navigation Sidebar
        # -------------------------------------------------------------------
        nav_panel = QVBoxLayout()
        self.nav_group = QButtonGroup(self)
        self.nav_group.setExclusive(True)
        self.nav_buttons: dict[str, QPushButton] = {}

        self.pages: dict[str, QWidget] = {
            "Dashboard": DashboardPage(self.dispatcher, self),
            "Devices": DevicesPage(self.dispatcher, self),
            "Layout Editor": LayoutEditorPage(self.dispatcher, self),
            "Profiles": ProfilesPage(self.dispatcher, self),
            "Pipelines": PipelinesPage(self.dispatcher, self),
            "Key Bindings": KeyBindingsPage(self.dispatcher, self),
            "Performance": PerformancePage(self.dispatcher, self),
            "Settings": SettingsPage(self.dispatcher, self),
            "Typematic": TypematicPage(self.dispatcher, self),
        }

        self.stack = QStackedWidget()
        for idx, (title, widget) in enumerate(self.pages.items()):
            btn = QPushButton(title)
            btn.setCheckable(True)
            self.nav_group.addButton(btn, idx)
            btn.clicked.connect(lambda _, i=idx, t=title: self._switch_page(i, t))
            nav_panel.addWidget(btn)
            self.nav_buttons[title] = btn
            self.stack.addWidget(widget)

        nav_panel.addStretch()

        # Engine Action Button
        self.sidebar_engine_btn = QPushButton("Start Engine")
        self.sidebar_engine_btn.setStyleSheet(
            "font-weight: bold; background-color: #2e7d32; color: white; padding: 8px;"
        )
        self.sidebar_engine_btn.clicked.connect(self._toggle_engine)
        nav_panel.addWidget(self.sidebar_engine_btn)

        main_layout.addLayout(nav_panel, stretch=1)
        main_layout.addWidget(self.stack, stretch=5)

        # -------------------------------------------------------------------
        # Bottom Dock: Diagnostics & Log Stream
        # -------------------------------------------------------------------
        self.log_dock = QDockWidget("Application Logs", self)
        self.log_console = QPlainTextEdit()
        self.log_console.setReadOnly(True)
        self.log_console.setStyleSheet(
            "background-color: #1e1e1e; color: #d4d4d4; font-family: monospace;"
        )
        self.log_dock.setWidget(self.log_console)
        self.addDockWidget(Qt.DockWidgetArea.BottomDockWidgetArea, self.log_dock)

        # Activate initial view
        self._switch_page(0, "Dashboard")

    def _setup_logging(self) -> None:
        handler = QtLogHandler(self.log_console)
        formatter = logging.Formatter(
            "[%(asctime)s] [%(levelname)s] [%(name)s]: %(message)s", "%H:%M:%S"
        )
        handler.setFormatter(formatter)
        logging.getLogger().addHandler(handler)
        logging.getLogger().setLevel(logging.INFO)

    def _wire_engine_signals(self) -> None:
        self.engine_worker.started_signal.connect(self._on_engine_started)
        self.engine_worker.stopped_signal.connect(self._on_engine_stopped)
        self.engine_worker.error_signal.connect(self._on_engine_error)

    def _switch_page(self, index: int, title: str) -> None:
        self.stack.setCurrentIndex(index)
        if title in self.nav_buttons:
            self.nav_buttons[title].setChecked(True)

        page_widget = self.stack.currentWidget()
        if isinstance(page_widget, BasePage):
            page_widget.on_page_shown()

    def _toggle_engine(self) -> None:
        if self.engine_worker.isRunning():
            self.sidebar_engine_btn.setEnabled(False)
            self.engine_worker.stop_engine()
        else:
            devices_page = self.pages.get("Devices")
            target_hwnd = getattr(devices_page, "selected_window_id", None)
            settings = store.settings.get()

            self.sidebar_engine_btn.setEnabled(False)
            self.engine_worker.start_engine(
                window_id=target_hwnd,
                rate_cap=settings.adb_rate_cap,
                pps=settings.pps_alert_threshold,
                toggle_key=settings.toggle_key,
                sprint_key=settings.sprint_key,
                typematic_enabled=settings.typematic_enabled,
                typematic_delay_ms=settings.typematic_delay_ms,
                typematic_rate_hz=settings.typematic_rate_hz,
                typematic_exclude_keys=settings.typematic_exclude_keys,
            )

    def _on_engine_started(self) -> None:
        self.sidebar_engine_btn.setText("Stop Engine")
        self.sidebar_engine_btn.setStyleSheet(
            "font-weight: bold; background-color: #c62828; color: white; padding: 8px;"
        )
        self.sidebar_engine_btn.setEnabled(True)
        logger.info("Touch mapping engine started successfully")

    def _on_engine_stopped(self) -> None:
        self.sidebar_engine_btn.setText("Start Engine")
        self.sidebar_engine_btn.setStyleSheet(
            "font-weight: bold; background-color: #2e7d32; color: white; padding: 8px;"
        )
        self.sidebar_engine_btn.setEnabled(True)
        logger.info("Touch mapping engine stopped")

    def _on_engine_error(self, err_msg: str) -> None:
        self.sidebar_engine_btn.setText("Start Engine")
        self.sidebar_engine_btn.setStyleSheet(
            "font-weight: bold; background-color: #2e7d32; color: white; padding: 8px;"
        )
        self.sidebar_engine_btn.setEnabled(True)
        QMessageBox.critical(
            self, "Engine Error", f"Mapping engine encountered an error:\n{err_msg}"
        )

    def _setup_driver_menu(self):
        """Creates a 'Tools' menu for system-level driver actions."""
        menubar = self.menuBar()
        tools_menu = menubar.addMenu("Tools")

        # 1. Setup / Repair Action
        setup_action = QAction("Install / Repair Drivers...", self)
        setup_action.triggered.connect(self._on_run_setup)
        tools_menu.addAction(setup_action)

        tools_menu.addSeparator()

        # 2. Uninstall Action
        uninstall_action = QAction("Uninstall Touch2Key...", self)
        # Optional: Make the text red in the menu using a stylesheet or icon
        uninstall_action.triggered.connect(self._on_run_uninstall)
        tools_menu.addAction(uninstall_action)

    def _on_run_setup(self):
        """Triggers the setup script with Admin privileges (UAC prompt)."""
        reply = QMessageBox.question(
            self, 
            "Driver Setup",
            "This will install or repair the necessary system drivers.\n\n"
            "Your OS will prompt you for Administrator permissions. Continue?",
            QMessageBox.standardButton.Yes | QMessageBox.standardButton.No
        )
        
        if reply == QMessageBox.standardButton.Yes:
            if sys.platform == "win32":
                import ctypes
                # "runas" forces the Windows UAC Admin prompt
                ctypes.windll.shell32.ShellExecuteW(
                    None, "runas", sys.executable, "-m modules.scripts.setup", None, 1
                )
            else:
                import subprocess
                # Linux GUI Admin prompt
                subprocess.Popen(["pkexec", sys.executable, "-m", "modules.scripts.setup"])

    def _on_run_uninstall(self):
        """Triggers the uninstaller as Admin and closes the app to release file locks."""
        reply = QMessageBox.warning(
            self, 
            "Uninstall Touch2Key",
            "This will remove the system drivers and completely close the application.\n\n"
            "Your OS will prompt you for Administrator permissions. Continue?",
            QMessageBox.standardButton.Yes | QMessageBox.standardButton.No
        )
        
        if reply == QMessageBox.standardButton.Yes:
            if sys.platform == "win32":
                import ctypes
                # Launch uninstaller as Admin in a detached process
                ctypes.windll.shell32.ShellExecuteW(
                    None, "runas", sys.executable, "-m modules.scripts.uninstall", None, 1
                )
            else:
                import subprocess
                subprocess.Popen(["pkexec", sys.executable, "-m", "modules.scripts.uninstall"])
                
            # CRITICAL: Kill the GUI immediately so the SQLite DB and files unlock!
            QCoreApplication.quit()

    def closeEvent(self, event) -> None:
        if self.engine_worker.isRunning():
            self.engine_worker.stop_engine()
        store.close()
        event.accept()
