from __future__ import annotations

import sys
import logging

from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from modules.database import store
from modules.utils import MapperEvent

logger = logging.getLogger("modules.gui.pages.devices")


class DevicesPage(QWidget):
    def __init__(self, dispatcher, parent=None):
        super().__init__(parent)
        self.dispatcher = dispatcher

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(16)

        title = QLabel("Hardware & Device Configuration")
        title.setStyleSheet("font-size: 18px; font-weight: bold;")
        layout.addWidget(title)

        desc = QLabel(
            "Select and assign physical input devices. On Windows, this routes "
            "Interception kernel drivers directly to your designated keyboard and mouse."
        )
        desc.setWordWrap(True)
        layout.addWidget(desc)

        # Status Display Box
        self.info_frame = QFrame()
        self.info_frame.setFrameShape(QFrame.Shape.StyledPanel)
        frame_layout = QVBoxLayout(self.info_frame)

        self.k_label = QLabel("Configured Keyboard: None")
        self.m_label = QLabel("Configured Mouse: None")
        frame_layout.addWidget(self.k_label)
        frame_layout.addWidget(self.m_label)
        layout.addWidget(self.info_frame)

        # Action Buttons
        btn_layout = QHBoxLayout()
        self.rebind_btn = QPushButton("Detect & Rebind Hardware")
        self.rebind_btn.clicked.connect(self._handle_rebind)
        btn_layout.addWidget(self.rebind_btn)
        btn_layout.addStretch()

        layout.addLayout(btn_layout)
        layout.addStretch()

        self._refresh_ui()

    def _refresh_ui(self) -> None:
        if sys.platform == "win32":
            s = store.settings.get()
            k_id: int | None = getattr(s, "windows_keyboard_device", None)
            m_id: int | None = getattr(s, "windows_mouse_device", None)

            self.k_label.setText(
                f"Configured Keyboard ID: {k_id if k_id is not None else 'Unassigned'}"
            )
            self.m_label.setText(
                f"Configured Mouse ID:    {m_id if m_id is not None else 'Unassigned'}"
            )
            self.rebind_btn.setEnabled(True)
        else:
            self.k_label.setText("Virtual UInput subsystem active (Kernel-managed).")
            self.m_label.setText("Mouse movements routed via Linux evdev.")
            self.rebind_btn.setEnabled(False)

    def _handle_rebind(self) -> None:
        if sys.platform != "win32":
            return

        from modules.platforms.windows.query_interception_device import (
            select_keyboard_then_mouse,
        )

        devices = select_keyboard_then_mouse(parent=self)
        if not devices:
            logger.info(
                "\n[!] Error selecting device, re-selection likely cancelled by user."
            )
            return

        k_device, m_device = devices

        # 1. Update persistent store
        store.settings.update(
            windows_keyboard_device=k_device, windows_mouse_device=m_device
        )
        self._refresh_ui()

        # 2. Hot-reload active running engine
        self.dispatcher.dispatch(
            MapperEvent(
                action="ON_DEVICES_CHANGED",
                payload={"keyboard_id": k_device, "mouse_id": m_device},
            )
        )

        logger.info("Devices reloaded successfully: K=%d, M=%d", k_device, m_device)
        QMessageBox.information(
            self,
            "Devices Updated",
            f"Hardware reloaded:\nKeyboard ID: {k_device}\nMouse ID: {m_device}",
        )
