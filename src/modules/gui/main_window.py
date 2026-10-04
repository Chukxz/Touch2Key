from __future__ import annotations

import sys
import os
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
    QSizePolicy,
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
from modules.gui.log_handler import install_gui_logging

from modules.scripts.show_adb_path import run as show_adb_path_run
from modules.scripts.preflight import run as run_preflight
from modules.scripts.setup import run as run_setup
from modules.scripts.uninstall import run as run_uninstall

logger = logging.getLogger("modules.gui.main_window")


class EngineProcessController(QObject):
    """Owns the engine subprocess plus the GUI-side IPC dispatcher wired to it."""

    dispatcher_ready = Signal(object)

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
    ) -> None:
        if self.is_running():
            return

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
        )
        self.process.start()
        engine_conn.close()

        self.dispatcher.send_start(
            window_id,
        )
        self._watchdog.start()

    def stop_engine(self) -> None:
        if self.dispatcher is None or not self.is_running():
            return
        self.dispatcher.send_stop()

    def shutdown(self, timeout: float = 2.0) -> None:
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

        self.dispatcher = MapperEventDispatcher()
        self.engine_controller = EngineProcessController(self)

        self._setup_ui()
        self._setup_tools()
        self._setup_logging()
        self._wire_engine_signals()

        pid = os.getpid()
        logger.info(f"GUI Process PID: {pid}")

        success = run_preflight()
        if not success:
            QMessageBox.warning(
                self,
                "Pre-flight Checks Failed",
                f"System checks did not pass",
            )

    def _setup_ui(self) -> None:
        central = QWidget()
        self.setCentralWidget(central)
        main_layout = QHBoxLayout(central)
        main_layout.setContentsMargins(8, 8, 8, 8)

        nav_panel = QVBoxLayout()
        self.nav_group = QButtonGroup(self)
        self.nav_group.setExclusive(True)
        self.nav_buttons: dict[str, QPushButton] = {}

        self.dashboard_page = DashboardPage(self.dispatcher, self)
        self.dashboard_page.start_requested.connect(self._start_engine_from_dashboard)
        self.dashboard_page.stop_requested.connect(self._stop_engine_from_dashboard)

        self.pages: dict[str, QWidget] = {
            "Dashboard": self.dashboard_page,
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

        self.sidebar_engine_btn = QPushButton("Toggle Engine ON")
        self.sidebar_engine_btn.setStyleSheet(
            "font-weight: bold; background-color: #2e7d32; color: white; padding: 8px;"
        )
        self.sidebar_engine_btn.clicked.connect(self._toggle_engine)
        nav_panel.addWidget(self.sidebar_engine_btn)

        self.sidebar_visualizer_btn = QPushButton("Run Visualizer")
        self.sidebar_visualizer_btn.setStyleSheet(
            "font-weight: bold; background-color: #2e7d32; color: white; padding: 8px;"
        )
        self.sidebar_visualizer_btn.clicked.connect(self._start_visualizer)
        nav_panel.addWidget(self.sidebar_visualizer_btn)

        main_layout.addLayout(nav_panel, stretch=1)
        main_layout.addWidget(self.stack, stretch=5)

        self.log_dock = QDockWidget("Application Logs", self)
        self.log_dock.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding
        )

        self.log_console = QPlainTextEdit()
        self.log_console.setReadOnly(True)
        # Add expanding policy to the inner console widget too!
        self.log_console.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding
        )
        self.log_console.setStyleSheet(
            "background-color: #1e1e1e; color: #d4d4d4; font-family: monospace;"
        )

        self.log_dock.setWidget(self.log_console)
        self.addDockWidget(Qt.DockWidgetArea.BottomDockWidgetArea, self.log_dock)

        self._switch_page(0, "Dashboard")

    def _setup_logging(self) -> None:
        handler = install_gui_logging(logger_name="", level=logging.INFO)
        handler.emitter.message.connect(
            lambda msg, level: self.log_console.appendPlainText(msg)
        )

    def _wire_engine_signals(self) -> None:
        self.engine_controller.dispatcher_ready.connect(self._wire_engine_dispatcher)

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
        page_widget = self.stack.currentWidget()
        if page_widget is not None:
            logger.debug(
                f"Page '{title}' Min Size Hint: {page_widget.minimumSizeHint()}"
            )

        if title in self.nav_buttons:
            self.nav_buttons[title].setChecked(True)

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
            self.sidebar_engine_btn.setEnabled(False)
            self.engine_controller.start_engine(
                window_id=self.engine_controller.window_id,
            )

    def _start_engine_from_dashboard(self) -> None:
        if not self.engine_controller.is_running():
            self.dashboard_page.start_btn.setEnabled(False)
            self.engine_controller.start_engine(
                window_id=self.engine_controller.window_id
            )

    def _stop_engine_from_dashboard(self) -> None:
        if self.engine_controller.is_running():
            self.dashboard_page.stop_btn.setEnabled(False)
            self.engine_controller.stop_engine()

    def _on_engine_started(self) -> None:
        self.sidebar_engine_btn.setText("Toggle Engine OFF")
        self.sidebar_engine_btn.setStyleSheet(
            "font-weight: bold; background-color: #c62828; color: white; padding: 8px;"
        )
        self.sidebar_engine_btn.setEnabled(True)
        self.dashboard_page.set_running(True)
        logger.info("Touch mapping engine started successfully")

    def _on_engine_stopped(self) -> None:
        self.sidebar_engine_btn.setText("Toggle Engine ON")
        self.sidebar_engine_btn.setStyleSheet(
            "font-weight: bold; background-color: #2e7d32; color: white; padding: 8px;"
        )
        self.sidebar_engine_btn.setEnabled(True)
        self.dashboard_page.set_running(False)
        logger.info("Touch mapping engine stopped")

    def _on_engine_error(self, err_msg: str) -> None:
        self.sidebar_engine_btn.setText("Toggle Engine ON")
        self.sidebar_engine_btn.setStyleSheet(
            "font-weight: bold; background-color: #2e7d32; color: white; padding: 8px;"
        )
        self.sidebar_engine_btn.setEnabled(True)
        self.dashboard_page.set_running(False)
        QMessageBox.critical(
            self, "Engine Error", f"Mapping engine encountered an error:\n{err_msg}"
        )

    def _setup_tools(self):
        # Create a toolbar (you can also add it to a specific area like Qt.TopToolBarArea)
        toolbar = self.addToolBar("Tools")
        toolbar.setMovable(False)  # Lock the toolbar in place
        toolbar.setMinimumHeight(40)

        # Setup / Repair Action
        setup_action = QAction("Install / Repair Drivers...", self)
        setup_action.triggered.connect(self._on_run_setup)
        toolbar.addAction(setup_action)

        toolbar.addSeparator()

        # Preflight Action
        preflight_action = QAction("Run Preflight Checks...", self)
        preflight_action.triggered.connect(self._on_run_preflight)
        toolbar.addAction(preflight_action)

        toolbar.addSeparator()

        # Check ADB Path Action
        check_adb_action = QAction("Check ADB Binary Path...", self)
        check_adb_action.triggered.connect(self._on_check_adb)
        toolbar.addAction(check_adb_action)

        toolbar.addSeparator()

        # Uninstall Action
        uninstall_action = QAction("Uninstall Touch2Key...", self)
        uninstall_action.triggered.connect(self._on_run_uninstall)
        toolbar.addAction(uninstall_action)

    def _on_run_setup(self):
        reply = QMessageBox.question(
            self,
            "Driver Setup",
            "This will install or repair the necessary system drivers.\n\n"
            "Your OS will prompt you for Administrator permissions. Continue?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )

        if reply == QMessageBox.StandardButton.Yes:
            if self.engine_controller.is_running:
                self.engine_controller.stop_engine()
            run_setup()

    def _on_check_adb(self):
        """Runs the ADB diagnostic check and displays the result."""
        resolved_path = show_adb_path_run()
        if resolved_path:
            QMessageBox.information(
                self,
                "ADB Path Located",
                f"ADB executable resolved to:\n\n{resolved_path}",
            )
        else:
            QMessageBox.warning(
                self,
                "ADB Missing",
                "ADB executable could not be found.\n\n"
                "Please run Setup to download the Android Platform Tools, or ensure "
                "adb is installed in your system PATH.",
            )

    def _on_run_preflight(self):
        reply = QMessageBox.question(
            self,
            "Preflight Checks",
            "This will run a series of diagnostic checks to verify system configuration.\n\n"
            "Continue?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )

        if reply == QMessageBox.StandardButton.Yes:
            preflight_success = run_preflight(verbose=True, parent=self)

            if preflight_success:
                QMessageBox.information(
                    self,
                    "Preflight Checks Passed",
                    "All preflight checks passed successfully.",
                )

            else:
                QMessageBox.warning(
                    self,
                    "Pre-flight Checks Failed",
                    f"System checks did not pass",
                )

    def _on_run_uninstall(self):
        reply = QMessageBox.warning(
            self,
            "Uninstall Touch2Key",
            "This will remove the system drivers and completely close the application.\n\n"
            "Your OS will prompt you for Administrator permissions. Continue?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )

        if reply == QMessageBox.StandardButton.Yes:
            if self.engine_controller.is_running:
                self.engine_controller.stop_engine()
            uninstalled = run_uninstall()
            if uninstalled:
                QCoreApplication.quit()

    def closeEvent(self, event) -> None:
        if self.engine_controller.is_running():
            self.engine_controller.shutdown()
        store.close()
        event.accept()
