from __future__ import annotations

import logging
import multiprocessing
import os
import subprocess
import sys
import threading

from PySide6.QtCore import QObject, Qt, QTimer, Signal
from PySide6.QtGui import QAction, QCloseEvent
from PySide6.QtWidgets import (
    QButtonGroup,
    QDockWidget,
    QHBoxLayout,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QSizePolicy,
    QSplitter,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)
from PySide6.QtNetwork import QLocalServer

from modules.utils import APP_NAME
from modules.database import store
from modules.engine import run_engine_process
from modules.gui.dialogs.wireless_connect import connect_wireless_gui
from modules.gui.log_handler import install_gui_logging
from modules.gui.overlays.visualizer import run as run_visualizer
from modules.gui.pages.dashboard_page import DashboardPage
from modules.gui.pages.layout_studio_page import LayoutStudioPage
from modules.gui.pages.settings_page import SettingsPage
from modules.scripts.preflight import run as run_preflight
from modules.scripts.show_adb_path import run as run_show_adb_path
from modules.utils import (
    MapperEventDispatcher,
    QtIpcMapperEventDispatcher,
    get_scancode_from_key,
)

logger = logging.getLogger("modules.gui.main_window")


class SingleInstanceServer(QObject):
    def __init__(self, window, server_name: str):
        super().__init__()
        self.window = window
        self.server_name = server_name

        # Clean up any stale sockets/servers
        QLocalServer.removeServer(self.server_name)
        self.server = QLocalServer(self)
        if self.server.listen(self.server_name):
            self.server.newConnection.connect(self._handle_new_connection)

    def _handle_new_connection(self):
        client = self.server.nextPendingConnection()
        if client and client.waitForReadyRead(1000):
            msg = bytes(client.readAll().data()).decode("utf-8", errors="ignore")
            if msg == "SHOW_WINDOW":
                # Bring window to front
                self.window.showMaximized()
                self.window.raise_()
                self.window.activateWindow()
        if client:
            client.disconnectFromServer()


class CustomDockWidget(QDockWidget):
    signal_closed = Signal()

    def __init__(self, title: str, /, parent: QWidget | None = None):
        super().__init__(title, parent)

    def closeEvent(self, event: QCloseEvent) -> None:
        self.signal_closed.emit()
        return super().closeEvent(event)


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
        self._stop_requested = False

    def is_running(self) -> bool:
        return self.process is not None and self.process.is_alive()

    def start_engine(
        self, window_id: int | None, log_queue: multiprocessing.Queue
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
            args=(engine_conn, log_queue),
            daemon=False,
        )
        self.process.start()
        engine_conn.close()

        self.dispatcher.send_start(window_id)
        self._watchdog.start()

    def stop_engine(self) -> None:
        if self.dispatcher is None or not self.is_running():
            return
        self._stop_requested = True
        self.dispatcher.send_stop()

    def shutdown(self, timeout: float = 2.0) -> None:
        self._stop_requested = True
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
            if not self._stop_requested and self.dispatcher is not None:
                self.dispatcher.engine_error.emit(
                    "Engine process terminated unexpectedly"
                )
                self.dispatcher.engine_stopped.emit()
        self._stop_requested = False


class MainWindow(QMainWindow):
    """Root Application Window with scannable layout, pages stack, and log console."""

    def __init__(self):
        super().__init__()
        self.setWindowTitle(APP_NAME)
        self._single_instance_server = SingleInstanceServer(self, APP_NAME)

        self.dispatcher = MapperEventDispatcher()
        self.engine_controller = EngineProcessController(self)

        self._setup_ui()
        self._setup_tools()
        self._setup_logging()
        self._wire_engine_signals()

        self.log_queue = multiprocessing.Queue()
        self._stop_log_thread = threading.Event()
        self._log_thread = threading.Thread(
            target=self._consume_engine_logs, daemon=True
        )
        self._log_thread.start()

        pid = os.getpid()
        logger.info(f"GUI Process PID: {pid}")

        QTimer(self).singleShot(500, self.run_initial_preflight)

    def run_initial_preflight(self):
        success = run_preflight()
        if not success:
            QMessageBox.warning(
                self, "Pre-flight Checks Failed", "System checks did not pass"
            )

    def _setup_ui(self) -> None:
        central = QWidget()
        self.setCentralWidget(central)

        main_layout = QHBoxLayout(central)
        main_layout.setContentsMargins(8, 8, 8, 8)
        main_layout.setSpacing(0)

        # Sidebar toggle — stays visible when the sidebar is collapsed
        self.nav_toggle_btn = QPushButton("◀")
        self.nav_toggle_btn.setFixedWidth(28)
        self.nav_toggle_btn.setCheckable(True)
        self.nav_toggle_btn.setToolTip("Collapse sidebar")
        self.nav_toggle_btn.clicked.connect(self._toggle_nav_panel)

        # Horizontal splitter allowing the user to drag and resize the sidebar
        self.main_splitter = QSplitter(Qt.Orientation.Horizontal)
        self.main_splitter.setChildrenCollapsible(False)

        main_layout.addWidget(self.nav_toggle_btn, alignment=Qt.AlignmentFlag.AlignTop)
        main_layout.addWidget(self.main_splitter, 1)

        # Wrap nav_panel inside a dedicated container widget
        self.nav_container = QWidget()
        self.nav_container.setMinimumWidth(
            160
        )  # Prevents shrinking into unreadable state

        nav_panel = QVBoxLayout(self.nav_container)
        nav_panel.setContentsMargins(0, 0, 4, 0)

        self.nav_group = QButtonGroup(self)
        self.nav_group.setExclusive(True)
        self.nav_buttons: dict[str, QPushButton] = {}

        self.dashboard_page = DashboardPage(self.dispatcher, self)
        self.dashboard_page.start_requested.connect(self._start_engine_from_dashboard)
        self.dashboard_page.stop_requested.connect(self._stop_engine_from_dashboard)

        self.pages: dict[str, QWidget] = {
            "Dashboard": self.dashboard_page,
            "Layout Studio": LayoutStudioPage(self.dispatcher, self),
            "Settings": SettingsPage(self.dispatcher, self),
        }

        self.stack = QStackedWidget()
        for idx, (title, widget) in enumerate(self.pages.items()):
            btn = QPushButton(title)
            btn.setCheckable(True)
            if title == "Layout Studio":
                btn.setStyleSheet("font-weight: bold; padding: 6px;")
            self.nav_group.addButton(btn, idx)
            btn.clicked.connect(lambda _, i=idx, t=title: self._switch_page(i, t))
            nav_panel.addWidget(btn)
            self.nav_buttons[title] = btn
            self.stack.addWidget(widget)

        nav_panel.addStretch()

        # Engine Toggle Button
        self.sidebar_engine_btn = QPushButton("Toggle Engine ON")
        self.sidebar_engine_btn.setStyleSheet(
            "font-weight: bold; background-color: #2e7d32; color: white; padding: 8px;"
        )
        self.sidebar_engine_btn.clicked.connect(self._toggle_engine)
        nav_panel.addWidget(self.sidebar_engine_btn)

        # Visualizer Launcher Button
        self.sidebar_visualizer_btn = QPushButton("Run Visualizer")
        self.sidebar_visualizer_btn.setStyleSheet(
            "font-weight: bold; background-color: #1976d2; color: white; padding: 8px;"
        )
        self.sidebar_visualizer_btn.clicked.connect(self._start_visualizer)
        nav_panel.addWidget(self.sidebar_visualizer_btn)

        # Log Toggle Button
        self.sidebar_logs_btn = QPushButton("Hide Logs")
        self.sidebar_logs_btn.setStyleSheet(
            "font-weight: bold; background-color: #555555; color: white; padding: 8px;"
        )
        self.sidebar_logs_btn.clicked.connect(self._toggle_logs)
        nav_panel.addWidget(self.sidebar_logs_btn)

        # Add panes to splitter and assign default widths: sidebar (200px), pages (980px)
        self.main_splitter.addWidget(self.nav_container)
        self.main_splitter.addWidget(self.stack)
        self.main_splitter.setSizes([200, 980])

        # Dock widget setup
        self.custom_log_dock = CustomDockWidget("Application Logs", self)
        self.custom_log_dock.signal_closed.connect(self._custom_log_dock_closed)
        self.custom_log_dock.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding
        )

        self.log_console = QPlainTextEdit()
        self.log_console.setReadOnly(True)
        self.log_console.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding
        )
        self.log_console.setStyleSheet(
            "background-color: #1e1e1e; color: #d4d4d4; font-family: monospace;"
        )

        self.custom_log_dock.setWidget(self.log_console)
        self.addDockWidget(Qt.DockWidgetArea.BottomDockWidgetArea, self.custom_log_dock)
        self.custom_log_dock.closeEvent

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
            self.engine_controller.window_id = target_window_id

    def _switch_page(self, index: int, title: str) -> None:
        self.stack.setCurrentIndex(index)
        page_widget = self.stack.currentWidget()

        if title in self.nav_buttons:
            self.nav_buttons[title].setChecked(True)

        if page_widget is not None:
            show_page = getattr(page_widget, "on_page_shown", None)
            if show_page is not None:
                show_page()

    def _custom_log_dock_closed(self):
        self.sidebar_logs_btn.setText("Show Logs")

    def _toggle_logs(self) -> None:
        is_visible = not self.custom_log_dock.isVisible()
        self.custom_log_dock.setVisible(is_visible)
        self.sidebar_logs_btn.setText("Hide Logs" if is_visible else "Show Logs")

    def _start_visualizer(self) -> None:
        toggle_key_scancode = None
        toggle_key = store.settings.get().toggle_key
        if toggle_key is not None:
            toggle_key_scancode = get_scancode_from_key(toggle_key)

        multiprocessing.Process(
            target=run_visualizer,
            args=(toggle_key_scancode,),
            name="Visualizer",
            daemon=True,
        ).start()

    def _on_wireless_connect(self) -> None:
        connect_wireless_gui(parent=self)

    def _toggle_engine(self) -> None:
        if self.engine_controller.is_running():
            self.sidebar_engine_btn.setEnabled(False)
            self.engine_controller.stop_engine()
        else:
            self.sidebar_engine_btn.setEnabled(False)
            self.engine_controller.start_engine(
                window_id=self.engine_controller.window_id,
                log_queue=self.log_queue,
            )

    def _start_engine_from_dashboard(self) -> None:
        if not self.engine_controller.is_running():
            self.dashboard_page.start_btn.setEnabled(False)
            self.engine_controller.start_engine(
                window_id=self.engine_controller.window_id,
                log_queue=self.log_queue,
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

    def _setup_tools(self) -> None:
        toolbar = self.addToolBar("Tools")
        toolbar.setMovable(False)
        toolbar.setMinimumHeight(40)

        wireless_action = QAction("Connect Wireless ADB", self)
        wireless_action.triggered.connect(self._on_wireless_connect)
        toolbar.addAction(wireless_action)

        toolbar.addSeparator()
        setup_action = QAction("Install / Repair Drivers (Setup)", self)
        setup_action.triggered.connect(self._on_run_setup)
        toolbar.addAction(setup_action)

        toolbar.addSeparator()
        preflight_action = QAction("Run Preflight Checks", self)
        preflight_action.triggered.connect(self._on_run_preflight)
        toolbar.addAction(preflight_action)

        toolbar.addSeparator()
        check_adb_action = QAction("Check ADB Binary Path", self)
        check_adb_action.triggered.connect(self._on_check_adb)
        toolbar.addAction(check_adb_action)

        toolbar.addSeparator()
        uninstall_action = QAction("Uninstall Touch2Key", self)
        uninstall_action.triggered.connect(self._on_run_uninstall)
        toolbar.addAction(uninstall_action)

    def _toggle_nav_panel(self, checked: bool) -> None:
        if checked:
            self._saved_splitter_sizes = self.main_splitter.sizes()
            self.nav_container.hide()
            self.nav_toggle_btn.setText("▶")
            self.nav_toggle_btn.setToolTip("Expand sidebar")
        else:
            self.nav_container.show()

            sizes = getattr(self, "_saved_splitter_sizes", [200, 980])
            self.main_splitter.setSizes(sizes)

            self.nav_toggle_btn.setText("◀")
            self.nav_toggle_btn.setToolTip("Collapse sidebar")

    def save_all_pages(self) -> bool:
        """Aggregates and persists state from all GUI pages to the database."""
        logger.info("Initiating global state save across all pages")
        try:
            for title, page_widget in self.pages.items():
                save_state = getattr(page_widget, "save_state", None)
                if save_state is not None:
                    if not save_state():
                        logger.info(
                            "GUI page: %s state saved successfully to database.", title
                        )
                        return False

            logger.info("All GUI page states saved successfully to database.")
            return True

        except Exception as exc:
            logger.exception(
                "Global save operation encountered an error: %s",
                exc,
                exc_info=True,
            )
            QMessageBox.critical(
                self,
                "Save Error",
                f"An unexpected error occurred while saving changes:\n\n{exc}",
            )
            return False

    def _on_run_setup(self) -> None:
        if not self.save_all_pages():
            return

        reply = QMessageBox.question(
            self,
            "Driver Setup",
            "This will install or repair necessary system drivers.\n\n"
            "Your OS will prompt you for Administrator permissions. Continue?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        if self.engine_controller.is_running():
            logger.info("Stopping engine prior to setup execution")
            self.engine_controller.shutdown()

        logger.info("Spawning setup utility as an external process")
        try:
            subprocess.Popen([sys.executable, "-m", "modules.scripts.setup"])
        except Exception as exc:
            logger.exception("Failed to spawn setup subprocess")
            QMessageBox.critical(
                self, "Setup Error", f"Failed to launch setup utility:\n\n{exc}"
            )

    def _on_check_adb(self) -> None:
        resolved_path = run_show_adb_path()
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
                "ADB executable could not be found.\n\nPlease run Setup to download the Android Platform Tools, or ensure adb is installed in your system PATH.",
            )

    def _on_run_preflight(self) -> None:
        reply = QMessageBox.question(
            self,
            "Preflight Checks",
            "This will run diagnostic checks to verify system configuration.\n\nContinue?",
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
                    "System checks did not pass.",
                )

    def _on_run_uninstall(self) -> None:
        if not self.save_all_pages():
            return

        reply = QMessageBox.warning(
            self,
            "Uninstall Touch2Key",
            "This will remove system drivers and clean application data.\n\n"
            "Your OS will prompt you for Administrator permissions. Continue?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        if self.engine_controller.is_running():
            logger.info("Stopping engine prior to uninstallation")
            self.engine_controller.shutdown()

        logger.info("Spawning uninstaller as an external process")
        try:
            subprocess.Popen([sys.executable, "-m", "modules.scripts.uninstall"])
            self.close()
        except Exception as exc:
            logger.exception("Failed to spawn uninstaller subprocess")
            QMessageBox.critical(
                self,
                "Uninstall Error",
                f"Failed to launch uninstaller:\n\n{exc}",
            )

    def _consume_engine_logs(self) -> None:
        while not self._stop_log_thread.is_set():
            try:
                record = self.log_queue.get(timeout=0.2)
                if record:
                    msg = (
                        record.getMessage()
                        if hasattr(record, "getMessage")
                        else str(record)
                    )
                    self.log_console.appendPlainText(msg)
            except Exception:
                continue

    def closeEvent(self, event) -> None:
        self._stop_log_thread.set()
        if self.engine_controller.is_running():
            self.engine_controller.shutdown()
        store.close()
        event.accept()
