from __future__ import annotations

import time
from PySide6.QtCore import QObject, QThread, Signal
from PySide6.QtWidgets import QMessageBox, QProgressDialog, QWidget

from modules.utils import wireless_connect


class WirelessConnectWorker(QObject):
    """Background worker executing the wireless_connect polling loop."""

    connected = Signal(str)
    failed = Signal(str)
    finished = Signal()

    def __init__(self) -> None:
        super().__init__()
        self._is_running = True

    def run(self) -> None:
        try:
            while self._is_running:
                ret = wireless_connect(continuous=False)
                if ret:
                    success, endpoint = ret
                    if success:
                        self.connected.emit(endpoint)
                        return
                    elif not self._is_running:
                        break

                # Sleep in short intervals so user cancellation responds promptly
                for _ in range(10):
                    if not self._is_running:
                        break
                    time.sleep(0.1)

            if not self._is_running:
                self.failed.emit("Wireless connection cancelled by user.")

        except Exception as exc:
            self.failed.emit(str(exc))
        finally:
            self.finished.emit()

    def stop(self) -> None:
        self._is_running = False


class WirelessConnectDialog(QProgressDialog):
    """Thread-safe modal progress dialog managing worker and thread lifecycles."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(
            "Searching for USB device to switch to Wi-Fi...\n\n"
            "Ensure device is connected via USB and PC & phone are on the same Wi-Fi.",
            "Cancel",
            0,
            0,
            parent,
        )
        self.setWindowTitle("Wireless ADB Connection")
        self.setMinimumDuration(0)
        self.setAutoClose(False)
        self.setAutoReset(False)

        self.endpoint: str | None = None
        self.error_msg: str | None = None

        self.worker_thread = QThread(parent)
        self.worker = WirelessConnectWorker()
        self.worker.moveToThread(self.worker_thread)

        self.worker_thread.started.connect(self.worker.run)
        self.worker.finished.connect(self.worker_thread.quit)
        self.worker.finished.connect(self.worker.deleteLater)
        self.worker_thread.finished.connect(self.worker_thread.deleteLater)

        self.canceled.connect(self._on_canceled)

        # Because receiver methods belong to a main-thread QObject,
        # Qt automatically dispatches them via QueuedConnection across threads.
        self.worker.connected.connect(self._on_worker_connected)
        self.worker.failed.connect(self._on_worker_failed)

        self.worker_thread.start()

    def _on_canceled(self) -> None:
        self.worker.stop()
        self.reject()

    def _on_worker_connected(self, endpoint: str) -> None:
        self.endpoint = endpoint
        self.accept()  # Executes safely on the main GUI thread

    def _on_worker_failed(self, msg: str) -> None:
        self.error_msg = msg
        self.reject()  # Executes safely on the main GUI thread


def connect_wireless_gui(parent: QWidget | None = None) -> None:
    """Non-blocking GUI launcher with safe thread cleanup and post-modal alerts."""
    dialog = WirelessConnectDialog(parent)
    dialog.exec()

    # Ensure background thread is fully stopped before proceeding
    dialog.worker.stop()
    dialog.worker_thread.quit()
    dialog.worker_thread.wait(500)

    # Show alert dialogs ONLY after the modal progress dialog has closed
    if dialog.endpoint:
        QMessageBox.information(
            parent,
            "Wireless Connected",
            f"Successfully connected wirelessly to:\n{dialog.endpoint}\n\n"
            "You may now disconnect the USB cable.",
        )
    elif dialog.error_msg and "cancelled" not in dialog.error_msg.lower():
        QMessageBox.warning(
            parent,
            "Connection Failed",
            f"{dialog.error_msg}\n\n"
            "Verify that:\n"
            "1. USB Debugging is authorized on the phone screen.\n"
            "2. Both devices are on the exact same Wi-Fi network.",
        )
