from __future__ import annotations

import logging
import multiprocessing
import os
import queue
import subprocess
import sys
import threading

from PySide6.QtCore import QObject, Qt, QTimer, QSize, Signal
from PySide6.QtGui import QAction, QCloseEvent
from PySide6.QtNetwork import QLocalServer
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

from modules.database import store
from modules.engine import run_engine_process
from modules.gui.dialogs.wireless_connect import connect_wireless_gui
from modules.gui.log_handler import install_gui_logging
from modules.gui.overlays.visualizer import run as run_visualizer
from modules.gui.pages.dashboard_page import DashboardPage
from modules.gui.pages.layout_studio_page import LayoutStudioPage
from modules.gui.pages.settings_page import SettingsPage
from modules.log_manager import AppLogManager
from modules.scripts.preflight import run as run_preflight
from modules.scripts.show_adb_path import run as run_show_adb_path
from modules.utils import (
    APP_NAME,
    MapperEventDispatcher,
    QtIpcMapperEventDispatcher,
    get_scancode_from_key,
)

logger = logging.getLogger("modules.gui.main_window")


def _spawn_module(module: str) -> subprocess.Popen:
    return subprocess.Popen([sys.executable, "-m", module, "--gui", "-y"])


class SingleInstanceServer(QObject):
    def __init__(self, window: QMainWindow, server_name: str):
        super().__init__(window)
        self.window = window
        self.server_name = server_name

        # NOTE: Removing the server name unconditionally can interfere
        # with an already-running instance. Keep this behavior in mind
        # if you later revise the single-instance startup protocol.
        QLocalServer.removeServer(self.server_name)

        self.server = QLocalServer(self)

        if self.server.listen(self.server_name):
            self.server.newConnection.connect(self._handle_new_connection)
        else:
            logger.warning(
                "Could not start single-instance server %r: %s",
                self.server_name,
                self.server.errorString(),
            )

    def _handle_new_connection(self) -> None:
        while self.server.hasPendingConnections():
            client = self.server.nextPendingConnection()

            if client is None:
                continue

            # This retains the original message protocol. The blocking
            # wait is bounded, but it still briefly blocks the GUI thread.
            if client.waitForReadyRead(1000):
                message = bytes(client.readAll().data()).decode(
                    "utf-8",
                    errors="ignore",
                )

                if message == "SHOW_WINDOW":
                    self.window.showMaximized()
                    self.window.raise_()
                    self.window.activateWindow()

            client.disconnectFromServer()
            client.deleteLater()


class CurrentPageStack(QStackedWidget):
    """Sizes itself from the visible page only. QStackedLayout uses the max
    minimum size over ALL pages, so one tall hidden page pins the window's
    minimum height and stops the log dock from growing."""

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.currentChanged.connect(lambda _i: self.updateGeometry())

    def sizeHint(self) -> QSize:
        page = self.currentWidget()
        return page.sizeHint() if page is not None else super().sizeHint()

    def minimumSizeHint(self) -> QSize:
        page = self.currentWidget()
        if page is None:
            return super().minimumSizeHint()
        return page.minimumSizeHint().expandedTo(page.minimumSize())


class CustomDockWidget(QDockWidget):
    signal_closed = Signal()

    def __init__(
        self,
        title: str,
        /,
        parent: QWidget | None = None,
    ):
        super().__init__(title, parent)

    def closeEvent(self, event: QCloseEvent) -> None:
        self.signal_closed.emit()
        super().closeEvent(event)


class EngineProcessController(QObject):
    """Own the engine subprocess and its GUI-side IPC dispatcher."""

    dispatcher_ready = Signal(object)
    process_crashed = Signal(str)
    stopped = Signal()

    def __init__(self, parent: QObject | None = None):
        super().__init__(parent)

        self.process: multiprocessing.Process | None = None
        self.dispatcher: QtIpcMapperEventDispatcher | None = None

        self.window_id: int | None = None
        self.window_title: str | None = None
        self.k_id: int | None = None
        self.m_id: int | None = None

        self._gui_conn = None
        self.lock = threading.Lock()

        self._stop_requested = False
        self._shutdown_in_progress = False
        self._stopped_signal_emitted = False

        self._watchdog = QTimer(self)
        self._watchdog.setInterval(500)
        self._watchdog.timeout.connect(self._check_process_alive)

    def is_running(self) -> bool:
        return self.process is not None and self.process.is_alive()

    def start_engine(
        self,
        window_id: int | None,
        log_queue: multiprocessing.Queue,
    ) -> None:
        if self.is_running():
            return

        self._watchdog.stop()
        self._stop_requested = False
        self._shutdown_in_progress = False
        self._stopped_signal_emitted = False

        # Dispose of resources left by a previous engine instance.
        self._close_dispatcher()
        self._close_gui_connection()
        self._reap_finished_process()

        self.window_id = window_id

        gui_conn, engine_conn = multiprocessing.Pipe()
        self._gui_conn = gui_conn

        self.dispatcher = QtIpcMapperEventDispatcher(
            gui_conn,
            parent=self,
        )

        # The controller owns the process lifecycle. The dispatcher
        # reports a normal stop acknowledgement through this controller.
        self.dispatcher.engine_stopped.connect(self._on_dispatcher_stopped)

        # Let MainWindow connect its handlers before starting the child.
        self.dispatcher_ready.emit(self.dispatcher)

        process = multiprocessing.Process(
            target=run_engine_process,
            name="Touch2Key-Engine",
            args=(engine_conn, log_queue),
            daemon=False,
        )

        try:
            process.start()
        except Exception:
            logger.exception("Failed to start engine process")

            try:
                process.close()
            except (OSError, ValueError):
                pass

            self._close_dispatcher()
            self._close_gui_connection()
            raise
        finally:
            # The parent must close its copy of the child's endpoint.
            try:
                engine_conn.close()
            except OSError:
                pass

        self.process = process

        try:
            if self.dispatcher is None:
                raise RuntimeError("Engine IPC dispatcher was not initialized")

            self.dispatcher.send_start(window_id)
            self._watchdog.start()

        except Exception:
            logger.exception("Failed to initialize communication with engine")
            self.shutdown()
            raise

    def stop_engine(self) -> None:
        if self.dispatcher is None or not self.is_running():
            return

        self._stop_requested = True

        try:
            self.dispatcher.send_stop()
        except Exception:
            # A failed stop request must not cause a subsequent process
            # failure to be incorrectly classified as intentional.
            self._stop_requested = False
            logger.exception("Failed to send engine stop command")
            raise

        with self.lock:
            self.window_title = None
            self.window_id = None
            self.k_id = None
            self.m_id = None

    def shutdown(self, timeout: float = 2.0) -> None:
        """Stop the engine, reap the child, and release IPC resources."""
        self._shutdown_in_progress = True
        self._stop_requested = True
        self._watchdog.stop()

        process = self.process

        try:
            if (
                self.dispatcher is not None
                and process is not None
                and process.is_alive()
            ):
                try:
                    self.dispatcher.send_stop()
                except Exception:
                    logger.exception("Failed to send engine stop during shutdown")

            with self.lock:
                self.window_title = None
                self.window_id = None
                self.k_id = None
                self.m_id = None

            if process is not None:
                self._terminate_process(process, timeout)

            self._close_dispatcher()
            self._close_gui_connection()

            if self.process is not None and not self.process.is_alive():
                self.process = None

        finally:
            self._shutdown_in_progress = False

    def _terminate_process(
        self,
        process: multiprocessing.Process,
        timeout: float,
    ) -> None:
        """Join the process, escalating only if it fails to exit."""
        try:
            if process.is_alive():
                process.join(timeout)

            if process.is_alive():
                logger.warning(
                    "Engine did not stop within %.1f seconds; " "terminating it",
                    timeout,
                )
                process.terminate()
                process.join(timeout)

            if process.is_alive():
                logger.error("Engine did not terminate; killing it")
                process.kill()
                process.join(timeout)

            if not process.is_alive():
                process.close()
                self.process = None
            else:
                logger.error("Engine process is still alive after termination")

        except (OSError, ValueError):
            logger.exception("Error while terminating engine process")

    def _on_dispatcher_stopped(self) -> None:
        """Forward the dispatcher's normal stop acknowledgement."""
        self._emit_stopped_once()

        # Do not stop the watchdog here. The process may still be alive,
        # and the watchdog must continue detecting an unexpected exit.

    def _check_process_alive(self) -> None:
        process = self.process

        if process is None:
            self._watchdog.stop()
            return

        if process.is_alive():
            return

        self._watchdog.stop()

        try:
            process.join(timeout=0)
            exit_code = process.exitcode
        except (OSError, ValueError):
            exit_code = None

        unexpected_exit = not self._stop_requested and not self._shutdown_in_progress

        self._close_dispatcher()
        self._close_gui_connection()

        try:
            process.close()
        except (OSError, ValueError):
            logger.debug("Could not close finished engine process handle")

        self.process = None
        self._stop_requested = False

        if unexpected_exit:
            message = (
                "Engine process terminated unexpectedly " f"(exit code: {exit_code})"
            )
            logger.error(message)
            self.process_crashed.emit(message)
        else:
            self._emit_stopped_once()

    def _emit_stopped_once(self) -> None:
        if self._stopped_signal_emitted:
            return

        self._stopped_signal_emitted = True
        self.stopped.emit()

    def _reap_finished_process(self) -> None:
        process = self.process

        if process is None:
            return

        if process.is_alive():
            return

        try:
            process.join(timeout=0)
            process.close()
        except (OSError, ValueError):
            logger.debug("Could not reap previous engine process")

        self.process = None

    def _close_dispatcher(self) -> None:
        dispatcher = self.dispatcher
        self.dispatcher = None

        if dispatcher is None:
            return

        try:
            dispatcher.close()
        except Exception:
            logger.exception("Failed to close engine IPC dispatcher")

        dispatcher.deleteLater()

    def _close_gui_connection(self) -> None:
        connection = self._gui_conn
        self._gui_conn = None

        if connection is None:
            return

        try:
            connection.close()
        except OSError:
            logger.debug("GUI IPC connection was already closed")


class MainWindow(QMainWindow):
    """Root application window with pages, navigation, and log console."""

    log_message = Signal(str)

    def __init__(self):
        super().__init__()

        self.setWindowTitle(APP_NAME)
        self._single_instance_server = SingleInstanceServer(
            self,
            APP_NAME,
        )

        # Created before anything that can start the engine.
        self.log_queue = multiprocessing.Queue()
        self._stop_log_thread = threading.Event()

        self.dispatcher = MapperEventDispatcher()
        self.engine_controller = EngineProcessController(self)

        self._setup_ui()
        self._setup_tools()
        self._setup_logging()
        self._wire_engine_signals()

        self._log_thread = threading.Thread(
            target=self._consume_engine_logs,
            name="Touch2Key-LogConsumer",
            daemon=True,
        )
        self._log_thread.start()

        logger.info("GUI Process PID: %s", os.getpid())

        QTimer.singleShot(
            500,
            self.run_initial_preflight,
        )

    def run_initial_preflight(self) -> None:
        success = run_preflight()

        if not success:
            QMessageBox.warning(
                self,
                "Pre-flight Checks Failed",
                "System checks did not pass",
            )

    def _setup_ui(self) -> None:
        central = QWidget()
        self.setCentralWidget(central)

        main_layout = QHBoxLayout(central)
        main_layout.setContentsMargins(8, 8, 8, 8)
        main_layout.setSpacing(0)

        # Sidebar toggle remains visible when the sidebar is collapsed.
        self.nav_toggle_btn = QPushButton("◀")
        self.nav_toggle_btn.setFixedWidth(28)
        self.nav_toggle_btn.setCheckable(True)
        self.nav_toggle_btn.setToolTip("Collapse sidebar")
        self.nav_toggle_btn.clicked.connect(self._toggle_nav_panel)

        self.main_splitter = QSplitter(Qt.Orientation.Horizontal)
        self.main_splitter.setChildrenCollapsible(False)

        main_layout.addWidget(
            self.nav_toggle_btn,
            alignment=Qt.AlignmentFlag.AlignTop,
        )
        main_layout.addWidget(self.main_splitter, 1)

        # Dedicated container for the navigation panel.
        self.nav_container = QWidget()
        self.nav_container.setMinimumWidth(160)

        nav_panel = QVBoxLayout(self.nav_container)
        nav_panel.setContentsMargins(0, 0, 4, 0)

        self.nav_group = QButtonGroup(self)
        self.nav_group.setExclusive(True)
        self.nav_buttons: dict[str, QPushButton] = {}

        self.dashboard_page = DashboardPage(
            self.engine_controller,
            self.dispatcher,
            self,
        )
        self.dashboard_page.start_requested.connect(self._start_engine_from_dashboard)
        self.dashboard_page.stop_requested.connect(self._stop_engine_from_dashboard)
        self.dashboard_page.navigate_requested.connect(self._navigate_to_page)

        self.pages: dict[str, QWidget] = {
            "Dashboard": self.dashboard_page,
            "Layout Studio": LayoutStudioPage(
                self.dispatcher,
                self,
            ),
            "Settings": SettingsPage(
                self.engine_controller,
                self.dispatcher,
                self,
            ),
        }

        self.stack = CurrentPageStack()

        for index, (title, widget) in enumerate(self.pages.items()):
            button = QPushButton(title)
            button.setCheckable(True)

            if title == "Layout Studio":
                button.setStyleSheet("font-weight: bold; padding: 6px;")

            self.nav_group.addButton(button, index)
            button.clicked.connect(
                lambda _checked=False, i=index, t=title: self._switch_page(i, t)
            )

            nav_panel.addWidget(button)
            self.nav_buttons[title] = button
            self.stack.addWidget(widget)

        nav_panel.addStretch()

        # Engine toggle button.
        self.sidebar_engine_btn = QPushButton("Toggle Engine ON")
        self.sidebar_engine_btn.setStyleSheet(
            "font-weight: bold; "
            "background-color: #2e7d32; "
            "color: white; "
            "padding: 8px;"
        )
        self.sidebar_engine_btn.clicked.connect(self._toggle_engine)
        nav_panel.addWidget(self.sidebar_engine_btn)

        # Visualizer launcher.
        self.sidebar_visualizer_btn = QPushButton("Run Visualizer")
        self.sidebar_visualizer_btn.setStyleSheet(
            "font-weight: bold; "
            "background-color: #1976d2; "
            "color: white; "
            "padding: 8px;"
        )
        self.sidebar_visualizer_btn.clicked.connect(self._start_visualizer)
        nav_panel.addWidget(self.sidebar_visualizer_btn)

        # Log visibility toggle.
        self.sidebar_logs_btn = QPushButton("Hide Logs")
        self.sidebar_logs_btn.setStyleSheet(
            "font-weight: bold; "
            "background-color: #555555; "
            "color: white; "
            "padding: 8px;"
        )
        self.sidebar_logs_btn.clicked.connect(self._toggle_logs)
        nav_panel.addWidget(self.sidebar_logs_btn)

        # Sidebar and page stack.
        self.main_splitter.addWidget(self.nav_container)
        self.main_splitter.addWidget(self.stack)
        self.main_splitter.setSizes([200, 980])

        # Log dock.
        self.custom_log_dock = CustomDockWidget(
            "Application Logs",
            self,
        )
        self.custom_log_dock.signal_closed.connect(self._custom_log_dock_closed)
        self.custom_log_dock.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Expanding,
        )

        self.log_console = QPlainTextEdit()
        self.log_console.setReadOnly(True)
        self.log_console.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Expanding,
        )
        self.log_console.setStyleSheet(
            "background-color: #1e1e1e; " "color: #d4d4d4; " "font-family: monospace;"
        )

        self.custom_log_dock.setWidget(self.log_console)
        self.addDockWidget(
            Qt.DockWidgetArea.BottomDockWidgetArea,
            self.custom_log_dock,
        )

        self._switch_page(0, "Dashboard")

    def _navigate_to_page(self, page_title: str):
        index = -1
        title = page_title.strip()

        for cur_index, (cur_title, _) in enumerate(self.pages.items()):
            if cur_title.strip() == title:
                index = cur_index
                break

        if index > 0:
            self._switch_page(index, title)
        else:
            logger.info("Could not find a page with title '%s'.", title)

    def _setup_logging(self) -> None:
        self._gui_log_handler = install_gui_logging(
            logger_name="",
            level=logging.INFO,
        )
        self._gui_log_handler.emitter.message.connect(self._on_gui_log_line)
        self.log_message.connect(self.log_console.appendPlainText)

    def _on_gui_log_line(self, line: str, levelno: int) -> None:
        self.log_console.appendPlainText(line)

    def _wire_engine_signals(self) -> None:
        controller = self.engine_controller

        controller.dispatcher_ready.connect(self._wire_engine_dispatcher)
        controller.process_crashed.connect(self._on_engine_error)
        controller.stopped.connect(self._on_engine_stopped)

        self.dispatcher.register_callback(
            "ON_RELOAD",
            self._forward_reload_to_engine,
        )
        self.dispatcher.register_callback(
            "ON_DEVICES_CHANGE",
            self._forward_devices_change_to_engine,
        )
        self.dispatcher.register_callback(
            "ON_TARGET_WINDOW_CHANGE",
            self._forward_target_window_change_to_engine,
        )

    def _wire_engine_dispatcher(
        self,
        ipc_dispatcher: QtIpcMapperEventDispatcher,
    ) -> None:
        ipc_dispatcher.engine_started.connect(self._on_engine_started)
        ipc_dispatcher.engine_error.connect(self._on_engine_error)

    def _forward_reload_to_engine(self) -> None:
        dispatcher = self.engine_controller.dispatcher

        if dispatcher is not None:
            dispatcher.send_reload()

    def _forward_devices_change_to_engine(
        self,
        keyboard_device_id: int | None,
        mouse_device_id: int | None,
    ) -> None:
        dispatcher = self.engine_controller.dispatcher

        if dispatcher is not None:
            dispatcher.send_devices_change(
                keyboard_device_id,
                mouse_device_id,
            )

    def _forward_target_window_change_to_engine(
        self,
        target_window_id: int | None,
        target_window_title: str,
    ) -> None:
        dispatcher = self.engine_controller.dispatcher

        if dispatcher is not None:
            dispatcher.send_target_window_change(
                target_window_id,
                target_window_title,
            )

    def _switch_page(
        self,
        index: int,
        title: str,
    ) -> None:
        self.stack.setCurrentIndex(index)

        if title in self.nav_buttons:
            self.nav_buttons[title].setChecked(True)

        page_widget = self.stack.currentWidget()

        if page_widget is not None:
            show_page = getattr(
                page_widget,
                "on_page_shown",
                None,
            )

            if show_page is not None:
                show_page()

    def _custom_log_dock_closed(self) -> None:
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

    def _flush_settings(self) -> None:
        """Write queued Settings spin box steps to the DB.

        Used before the engine starts so the worker reads the latest values.
        Deliberately does not touch Layout Studio: saving a dirty canvas must
        stay an explicit user action (Save / Discard prompt).
        """
        page = self.pages.get("Settings")
        save_state = getattr(page, "save_state", None)
        if save_state is not None:
            save_state()

    def _toggle_engine(self) -> None:
        self.sidebar_engine_btn.setEnabled(False)

        try:
            if self.engine_controller.is_running():
                self.engine_controller.stop_engine()
            else:
                self._flush_settings()
                self.engine_controller.start_engine(
                    window_id=self.engine_controller.window_id,
                    log_queue=self.log_queue,
                )

        except Exception as exc:
            logger.exception("Engine toggle failed")
            self.sidebar_engine_btn.setEnabled(True)
            QMessageBox.critical(
                self,
                "Engine Error",
                str(exc),
            )

    def _start_engine_from_dashboard(self) -> None:
        try:
            if not self.engine_controller.is_running():
                self.dashboard_page.start_btn.setEnabled(False)
                self._flush_settings()
                self.engine_controller.start_engine(
                    window_id=self.engine_controller.window_id,
                    log_queue=self.log_queue,
                )

        except Exception as exc:
            logger.exception("Engine start failed")
            self.dashboard_page.set_running(self.engine_controller.is_running())
            QMessageBox.critical(
                self,
                "Engine Error",
                str(exc),
            )

    def _stop_engine_from_dashboard(self) -> None:
        try:
            if self.engine_controller.is_running():
                self.dashboard_page.stop_btn.setEnabled(False)
                self.engine_controller.stop_engine()

        except Exception as exc:
            logger.exception("Engine stop failed")
            self.dashboard_page.set_running(self.engine_controller.is_running())
            QMessageBox.critical(
                self,
                "Engine Error",
                str(exc),
            )

    def _on_engine_started(self) -> None:
        self.sidebar_engine_btn.setText("Toggle Engine OFF")
        self.sidebar_engine_btn.setStyleSheet(
            "font-weight: bold; "
            "background-color: #c62828; "
            "color: white; "
            "padding: 8px;"
        )
        self.sidebar_engine_btn.setEnabled(True)
        self.dashboard_page.set_running(True)

        logger.info("Touch mapping engine started successfully")

    def _on_engine_stopped(self) -> None:
        self.sidebar_engine_btn.setText("Toggle Engine ON")
        self.sidebar_engine_btn.setStyleSheet(
            "font-weight: bold; "
            "background-color: #2e7d32; "
            "color: white; "
            "padding: 8px;"
        )
        self.sidebar_engine_btn.setEnabled(True)
        self.dashboard_page.set_running(False)

        logger.info("Touch mapping engine stopped")

    def _on_engine_error(self, err_msg: str) -> None:
        self.sidebar_engine_btn.setText("Toggle Engine ON")
        self.sidebar_engine_btn.setStyleSheet(
            "font-weight: bold; "
            "background-color: #2e7d32; "
            "color: white; "
            "padding: 8px;"
        )
        self.sidebar_engine_btn.setEnabled(True)
        self.dashboard_page.set_running(False)

        QMessageBox.critical(
            self,
            "Engine Error",
            f"Mapping engine encountered an error:\n{err_msg}",
        )

        with self.engine_controller.lock:
            self.engine_controller.window_title = None
            self.engine_controller.window_id = None
            self.engine_controller.k_id = None
            self.engine_controller.m_id = None

    def _setup_tools(self) -> None:
        toolbar = self.addToolBar("Tools")
        toolbar.setMovable(False)
        toolbar.setMinimumHeight(40)

        wireless_action = QAction(
            "Connect Wireless ADB",
            self,
        )
        wireless_action.triggered.connect(self._on_wireless_connect)
        toolbar.addAction(wireless_action)

        toolbar.addSeparator()

        setup_action = QAction(
            "Install / Repair Drivers (Setup)",
            self,
        )
        setup_action.triggered.connect(self._on_run_setup)
        toolbar.addAction(setup_action)

        toolbar.addSeparator()

        preflight_action = QAction(
            "Run Preflight Checks",
            self,
        )
        preflight_action.triggered.connect(self._on_run_preflight)
        toolbar.addAction(preflight_action)

        toolbar.addSeparator()

        check_adb_action = QAction(
            "Check ADB Binary Path",
            self,
        )
        check_adb_action.triggered.connect(self._on_check_adb)
        toolbar.addAction(check_adb_action)

        toolbar.addSeparator()

        uninstall_action = QAction(
            "Uninstall Touch2Key",
            self,
        )
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

            sizes = getattr(
                self,
                "_saved_splitter_sizes",
                [200, 980],
            )
            self.main_splitter.setSizes(sizes)

            self.nav_toggle_btn.setText("◀")
            self.nav_toggle_btn.setToolTip("Collapse sidebar")

    def save_all_pages(self) -> bool:
        """Persist state from all GUI pages to the database.

        Every page is given the chance to save, even if an earlier one fails,
        so a failed Layout Studio save can't leave queued Settings steps
        unwritten. Returns False if any page reported failure.
        """
        logger.info("Initiating global state save across all pages")

        ok = True
        try:
            for title, page_widget in self.pages.items():
                save_state = getattr(
                    page_widget,
                    "save_state",
                    None,
                )

                if save_state is not None and not save_state():
                    logger.info(
                        "GUI page %s state was not saved",
                        title,
                    )
                    ok = False

            if ok:
                logger.info("All GUI page states saved successfully")
            return ok

        except Exception as exc:
            logger.exception(
                "Global save operation encountered an error: %s",
                exc,
            )
            QMessageBox.critical(
                self,
                "Save Error",
                "An unexpected error occurred while saving changes:\n\n" f"{exc}",
            )
            return False

    def _on_run_setup(self) -> None:
        if not self.save_all_pages():
            return

        reply = QMessageBox.question(
            self,
            "Driver Setup",
            "This will install or repair necessary system drivers.\n\n"
            "Your OS will prompt you for Administrator permissions. "
            "Continue?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )

        if reply != QMessageBox.StandardButton.Yes:
            return

        if self.engine_controller.is_running():
            logger.info("Stopping engine prior to setup execution")
            self.engine_controller.shutdown()

        logger.info(
            "Spawning setup utility as an external process, additional details can be found in 'touch2key-setup' logs."
        )

        try:
            _spawn_module("modules.scripts.setup")
        except Exception as exc:
            logger.exception("Failed to spawn setup subprocess")
            QMessageBox.critical(
                self,
                "Setup Error",
                f"Failed to launch setup utility:\n\n{exc}",
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
                "ADB executable could not be found.\n\n"
                "Please run Setup to download the Android Platform Tools, "
                "or ensure adb is installed in your system PATH.",
            )

    def _on_run_preflight(self) -> None:
        reply = QMessageBox.question(
            self,
            "Preflight Checks",
            "This will run diagnostic checks to verify system "
            "configuration.\n\nContinue?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )

        if reply != QMessageBox.StandardButton.Yes:
            return

        preflight_success = run_preflight(
            verbose=True,
            parent=self,
        )

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
            "Your OS will prompt you for Administrator permissions. "
            "Continue?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )

        if reply != QMessageBox.StandardButton.Yes:
            return

        if self.engine_controller.is_running():
            logger.info("Stopping engine prior to uninstallation")
            self.engine_controller.shutdown()

        logger.info(
            "Spawning uninstaller as an external process, additional details can be found in 'touch2key-uninstall' logs."
        )

        try:
            _spawn_module("modules.scripts.uninstall")
            self.close()

        except Exception as exc:
            logger.exception("Failed to spawn uninstaller subprocess")
            QMessageBox.critical(
                self,
                "Uninstall Error",
                f"Failed to launch uninstaller:\n\n{exc}",
            )

    def _consume_engine_logs(self) -> None:
        min_level = logging.INFO
        while True:
            try:
                record = self.log_queue.get(timeout=0.2)
            except queue.Empty:
                if self._stop_log_thread.is_set():
                    break
                continue
            except (EOFError, OSError, ValueError):
                break

            if record is None:
                break

            if not isinstance(record, logging.LogRecord):
                self.log_message.emit(str(record))
                continue

            # File gets everything, including DEBUG.
            AppLogManager.write_record(record)

            # Console gets INFO+, formatted like GUI-process lines.
            if record.levelno >= min_level:
                self.log_message.emit(self._gui_log_handler.format(record))

    def closeEvent(self, event: QCloseEvent) -> None:
        if not self.save_all_pages():
            event.ignore()
            return

        # Shut down even if is_running() is already false; the controller
        # may still own a finished process handle or open IPC resources.
        self.engine_controller.shutdown()

        self._stop_log_thread.set()

        try:
            self.log_queue.put_nowait(None)
        except (OSError, ValueError):
            pass

        if self._log_thread.is_alive():
            self._log_thread.join(timeout=1.0)

        try:
            self.log_queue.close()
            self.log_queue.join_thread()
        except (OSError, ValueError):
            logger.debug("Log queue was already closed")

        store.close()
        event.accept()