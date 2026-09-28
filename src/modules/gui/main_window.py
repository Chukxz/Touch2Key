from __future__ import annotations

import sys
import logging
import multiprocessing

from PySide6.QtCore import Qt, QObject, QTimer, Signal, QCoreApplication
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
from modules.engine import run_engine_process

from modules.gui.pages import (
    BasePage,
    DashboardPage,
    DevicesPage,
    KeyBindingsPage,
    LayoutsEditorPage,
    PerformancePage,
    PipelinesPage,
    ProfilesPage,
    SettingsPage,
    TypematicKeyBindingsPage,
    TypematicPage,
)

from modules.utils import MapperEventDispatcher, QtIpcMapperEventDispatcher

from modules.gui.overlays.visualizer import run as run_visualizer

logger = logging.getLogger("modules.gui.main_window")


class QtLogHandler(logging.Handler):
    """Custom logging handler routing records into the GUI console dock."""

    def __init__(self, text_widget: QPlainTextEdit):
        super().__init__()
        self.text_widget = text_widget

    def emit(self, record: logging.LogRecord) -> None:
        msg = self.format(record)
        self.text_widget.appendPlainText(msg)


class EngineProcessController(QObject):
    """Owns the engine subprocess plus the GUI-side IPC dispatcher wired to it.

    The engine runs in a separate multiprocessing.Process (not a QThread) so
    a crash there can't take the GUI process down with it. All
    communication -- start/stop/config-reload/layout-reload/devices-change/
    target-windows-change outbound, started/stopped/error inbound --
    goes over a multiprocessing.Pipe using the packed struct protocol in
    modules.utils.
    """

    dispatcher_ready = Signal(object)  # emits the new QtIpcMapperEventDispatcher

    def __init__(self, parent: QObject | None = None):
        super().__init__(parent)
        self.process: multiprocessing.Process | None = None
        self.dispatcher: QtIpcMapperEventDispatcher | None = None
        self.window_id: int | None = None
        self._gui_conn = None

        self._watchdog = QTimer(self)
        self._watchdog.setInterval(500)
        self._watchdog.timeout.connect(self._check_process_alive)

    def is_running(self) -> bool:
        return self.process is not None and self.process.is_alive()

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
        typematic_excluded_keys: str | None = None,
    ) -> None:
        if self.is_running():
            return

        # Clean up any leftover state from a previous run
        if self.dispatcher is not None:
            self.dispatcher.close()
            self.dispatcher.deleteLater()
            self.dispatcher = None
        if self._gui_conn is not None:
            try:
                self._gui_conn.close()
            except OSError:
                pass

        self.window_id = window_id

        gui_conn, engine_conn = multiprocessing.Pipe()
        self._gui_conn = gui_conn

        self.dispatcher = QtIpcMapperEventDispatcher(gui_conn, parent=self)
        self.dispatcher.engine_stopped.connect(self._watchdog.stop)
        self.dispatcher.engine_error.connect(lambda _msg: self._watchdog.stop())
        self.dispatcher_ready.emit(self.dispatcher)

        self.process = multiprocessing.Process(
            target=run_engine_process,
            name="Touch2Key-Engine",
            args=(engine_conn,),
            daemon=True,
        )
        self.process.start()
        engine_conn.close()  # parent doesn't need its own handle to the child's end

        self.dispatcher.send_start(
            window_id,
            rate_cap,
            pps,
            toggle_key,
            sprint_key,
            typematic_enabled,
            typematic_delay_ms,
            typematic_rate_hz,
            typematic_excluded_keys,
        )
        self._watchdog.start()

    def stop_engine(self) -> None:
        if self.dispatcher is None or not self.is_running():
            return
        self.dispatcher.send_stop()

    def shutdown(self, timeout: float = 2.0) -> None:
        """Hard-stop used on app close: signal stop, then force-terminate if needed."""
        self._watchdog.stop()
        if self.dispatcher is not None:
            self.dispatcher.send_stop()
        if self.process is not None:
            self.process.join(timeout)
            if self.process.is_alive():
                self.process.terminate()
                self.process.join(timeout)
                if self.process.is_alive():
                    self.process.kill()
        if self.dispatcher is not None:
            self.dispatcher.close()

    def _check_process_alive(self) -> None:
        if self.process is not None and not self.process.is_alive():
            self._watchdog.stop()
            if self.dispatcher is not None:
                self.dispatcher.engine_error.emit(
                    "Engine process terminated unexpectedly"
                )
                self.dispatcher.engine_stopped.emit()


class MainWindow(QMainWindow):
    """Root Application Window with scannable layout, pages stack, and log console."""

    def __init__(self):
        super().__init__()
        self.setWindowTitle("Touch2Key")
        self.resize(1180, 780)

        # Stable, in-process dispatcher used by GUI pages for GUI-internal
        # pub/sub -- unchanged from before. MainWindow bridges the subset of
        # these events that need to reach the (now out-of-process) engine.
        self.dispatcher = MapperEventDispatcher()
        self.engine_controller = EngineProcessController(self)

        self._setup_logging()
        self._setup_ui()
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
            "Layout Editor": LayoutsEditorPage(self.dispatcher, self),
            "Profiles": ProfilesPage(self.dispatcher, self),
            "Pipelines": PipelinesPage(self.dispatcher, self),
            "Key Bindings": KeyBindingsPage(self.dispatcher, self),
            "Performance": PerformancePage(self.dispatcher, self),
            "Settings": SettingsPage(self.dispatcher, self),
            "Typematic Key Bindings": TypematicKeyBindingsPage(self.dispatcher, self),
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

        # Visualizer Action Button
        self.sidebar_visualizer_btn = QPushButton("Run Visualizer")
        self.sidebar_visualizer_btn.setStyleSheet(
            "font-weight: bold; background-color: #2e7d32; color: white; padding: 8px;"
        )
        self.sidebar_visualizer_btn.clicked.connect(self._start_visualizer)
        nav_panel.addWidget(self.sidebar_visualizer_btn)

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
        # A fresh QtIpcMapperEventDispatcher is created per start_engine() call;
        # this fires once per instance and re-wires it each time.
        self.engine_controller.dispatcher_ready.connect(self._wire_engine_dispatcher)

        # Bridge GUI-page-originated events outward to the engine process,
        # whenever one is running. Pages don't need to know the engine is
        # out-of-process -- they still just dispatch on self.dispatcher.
        self.dispatcher.register_callback(
            "ON_CONFIG_RELOAD", self._forward_config_reload_to_engine
        )
        self.dispatcher.register_callback(
            "ON_LAYOUT_RELOAD", self._forward_layout_reload_to_engine
        )
        self.dispatcher.register_callback(
            "ON_DEVICES_CHANGE", self._forward_devices_change_to_engine
        )
        self.dispatcher.register_callback(
            "ON_TARGET_WINDOW_CHANGE", self._forward_target_window_change_to_engine
        )

    def _wire_engine_dispatcher(
        self, ipc_dispatcher: QtIpcMapperEventDispatcher
    ) -> None:
        ipc_dispatcher.engine_started.connect(self._on_engine_started)
        ipc_dispatcher.engine_stopped.connect(self._on_engine_stopped)
        ipc_dispatcher.engine_error.connect(self._on_engine_error)

    def _forward_config_reload_to_engine(self) -> None:
        if self.engine_controller.dispatcher is not None:
            self.engine_controller.dispatcher.send_config_reload()

    def _forward_layout_reload_to_engine(self) -> None:
        if self.engine_controller.dispatcher is not None:
            self.engine_controller.dispatcher.send_layout_reload()

    def _forward_devices_change_to_engine(
        self, keyboard_device_id: int | None, mouse_device_id: int | None
    ) -> None:
        if self.engine_controller.dispatcher is not None:
            self.engine_controller.dispatcher.send_devices_change(
                keyboard_device_id, mouse_device_id
            )

    def _forward_target_window_change_to_engine(
        self, target_window_id: int | None, target_window_title: str
    ) -> None:
        if self.engine_controller.dispatcher is not None:
            self.engine_controller.dispatcher.send_target_window_change(
                target_window_id, target_window_title
            )

    def _switch_page(self, index: int, title: str) -> None:
        self.stack.setCurrentIndex(index)
        if title in self.nav_buttons:
            self.nav_buttons[title].setChecked(True)

        page_widget = self.stack.currentWidget()
        if isinstance(page_widget, BasePage):
            page_widget.on_page_shown()

    def _start_visualizer(self):
        multiprocessing.Process(
            target=run_visualizer,
            name="Virtualizer",
            daemon=True,
        ).start()

    def _toggle_engine(self) -> None:
        if self.engine_controller.is_running():
            self.sidebar_engine_btn.setEnabled(False)
            self.engine_controller.stop_engine()
        else:
            settings = store.settings.get()

            self.sidebar_engine_btn.setEnabled(False)
            self.engine_controller.start_engine(
                window_id=self.engine_controller.window_id,
                rate_cap=settings.adb_rate_cap,
                pps=settings.pps_alert_threshold,
                toggle_key=settings.toggle_key,
                sprint_key=settings.sprint_key,
                typematic_enabled=settings.typematic_enabled,
                typematic_delay_ms=settings.typematic_delay_ms,
                typematic_rate_hz=settings.typematic_rate_hz,
                typematic_excluded_keys=settings.typematic_excluded_keys,
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
            QMessageBox.standardButton.Yes | QMessageBox.standardButton.No,
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
                subprocess.Popen(
                    ["pkexec", sys.executable, "-m", "modules.scripts.setup"]
                )

    def _on_run_uninstall(self):
        """Triggers the uninstaller as Admin and closes the app to release file locks."""
        reply = QMessageBox.warning(
            self,
            "Uninstall Touch2Key",
            "This will remove the system drivers and completely close the application.\n\n"
            "Your OS will prompt you for Administrator permissions. Continue?",
            QMessageBox.standardButton.Yes | QMessageBox.standardButton.No,
        )

        if reply == QMessageBox.standardButton.Yes:
            if sys.platform == "win32":
                import ctypes

                # Launch uninstaller as Admin in a detached process
                ctypes.windll.shell32.ShellExecuteW(
                    None,
                    "runas",
                    sys.executable,
                    "-m modules.scripts.uninstall",
                    None,
                    1,
                )
            else:
                import subprocess

                subprocess.Popen(
                    ["pkexec", sys.executable, "-m", "modules.scripts.uninstall"]
                )

            # CRITICAL: Kill the GUI immediately so the SQLite DB and files unlock!
            QCoreApplication.quit()

    def closeEvent(self, event) -> None:
        if self.engine_controller.is_running():
            self.engine_controller.shutdown()
        store.close()
        event.accept()
