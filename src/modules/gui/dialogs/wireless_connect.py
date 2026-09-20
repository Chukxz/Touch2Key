from __future__ import annotations

import time
from PySide6.QtCore import QObject, QThread, Signal
from PySide6.QtWidgets import QMessageBox, QProgressDialog, QWidget

from modules.utils import wireless_connect


class WirelessConnectWorker(QObject):
    """Background worker executing wireless_connect polling loop."""

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

                # Prevent 100% CPU core spinning while waiting for USB/network
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


def connect_wireless_gui(parent: QWidget | None = None) -> None:
    """Non-blocking GUI launcher with progress indicator and cancellation."""
    progress = QProgressDialog(
        "Searching for USB device to switch to Wi-Fi...\nEnsure device is plugged in via USB with USB Debugging enabled.",
        "Cancel",
        0,
        0,
        parent,
    )
    progress.setWindowTitle("Wireless ADB Connection")
    progress.setMinimumDuration(0)
    progress.setAutoClose(False)
    progress.setAutoReset(False)

    thread = QThread(parent)
    worker = WirelessConnectWorker()
    worker.moveToThread(thread)

    thread.started.connect(worker.run)
    worker.finished.connect(thread.quit)
    worker.finished.connect(worker.deleteLater)
    thread.finished.connect(thread.deleteLater)

    # Clean cancellation link
    progress.canceled.connect(worker.stop)

    def on_connected(endpoint: str) -> None:
        progress.close()
        QMessageBox.information(
            parent,
            "Wireless Connected",
            f"Successfully connected wirelessly to:\n{endpoint}",
        )

    def on_failed(msg: str) -> None:
        progress.close()
        if "cancelled" not in msg.lower():
            QMessageBox.warning(parent, "Connection Failed", msg)

    worker.connected.connect(on_connected)
    worker.failed.connect(on_failed)

    thread.start()
    progress.exec()