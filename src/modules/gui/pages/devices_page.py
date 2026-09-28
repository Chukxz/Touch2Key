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
from modules.scripts.list_windows import select_window

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
            "Assign target application windows and physical input hardware. "
            "Target window selection is supported across all platforms, while low-level "
            "Interception driver rebinding applies to Windows."
        )
        desc.setWordWrap(True)
        layout.addWidget(desc)

        # Status Display Box
        self.info_frame = QFrame()
        self.info_frame.setFrameShape(QFrame.Shape.StyledPanel)
        frame_layout = QVBoxLayout(self.info_frame)

        self.w_label = QLabel("Target Window: None")
        self.k_label = QLabel("Configured Keyboard: None")
        self.m_label = QLabel("Configured Mouse: None")

        frame_layout.addWidget(self.w_label)
        frame_layout.addWidget(self.k_label)
        frame_layout.addWidget(self.m_label)
        layout.addWidget(self.info_frame)

        # Action Buttons
        btn_layout = QHBoxLayout()

        # Window selection works cross-platform
        self.select_window_btn = QPushButton("Select Target Window")
        self.select_window_btn.clicked.connect(self._handle_window_selection)
        btn_layout.addWidget(self.select_window_btn)

        # Interception driver selection is Windows-specific
        self.rebind_hw_btn = QPushButton("Detect & Rebind Hardware")
        self.rebind_hw_btn.clicked.connect(self._handle_hardware_rebind)
        btn_layout.addWidget(self.rebind_hw_btn)

        btn_layout.addStretch()
        layout.addLayout(btn_layout)
        layout.addStretch()
        
        self.w_id: int | None = None
        self.w_title = ""
        self.k_id: int | None = None
        self.m_id: int | None = None

        self._refresh_ui()

    def _refresh_ui(self) -> None:
        s = store.settings.get()

        # Target window is universally visible and active
        self.w_label.setText(
            f"Target Window ID:       {self.w_id if self.w_id is not None else 'Unassigned'} ({self.w_title})"
        )
        self.select_window_btn.setEnabled(True)

        if sys.platform == "win32":
            self.k_label.setText(
                f"Configured Keyboard ID: {self.k_id if self.k_id is not None else 'Unassigned'}"
            )
            self.m_label.setText(
                f"Configured Mouse ID:    {self.m_id if self.m_id is not None else 'Unassigned'}"
            )
            self.rebind_hw_btn.setEnabled(True)
        else:
            self.k_label.setText(
                "Keyboard Subsystem:     Virtual UInput / Evdev (Kernel-managed)"
            )
            self.m_label.setText(
                "Mouse Subsystem:        Evdev Pointer (Kernel-managed)"
            )
            self.rebind_hw_btn.setEnabled(False)
            self.rebind_hw_btn.setToolTip(
                "Interception device filtering is only applicable on Windows."
            )

    def _handle_window_selection(self) -> None:
        window_result = select_window()
        if not window_result:
            logger.info("Window selection cancelled by user.")
            return

        self.w_id, self.w_title = window_result
        self._refresh_ui()

        self.dispatcher.dispatch(
            MapperEvent(
                action="ON_TARGET_WINDOW_CHANGE",
                target_window_id=self.w_id,
                target_window_title=self.w_title,
            )
        )

        logger.info("Target window set: ID=%s (%s)", self.w_id, self.w_title)
        QMessageBox.information(
            self,
            "Target Window Updated",
            f"Active target window set:\nID: {self.w_id}\nTitle: {self.w_title}",
        )

    def _handle_hardware_rebind(self) -> None:
        if sys.platform != "win32":
            return

        from modules.platforms.windows.query_interception_device import (
            select_keyboard_then_mouse,
        )

        devices = select_keyboard_then_mouse(parent=self)
        if not devices:
            logger.info("Hardware selection cancelled by user.")
            return

        self.k_id, self.m_id = devices
        
        self._refresh_ui()

        self.dispatcher.dispatch(
            MapperEvent(
                action="ON_DEVICES_CHANGE",
                keyboard_device_id=self.k_id,
                mouse_device_id=self.m_id,
            )
        )

        logger.info("Devices reloaded successfully: K=%d, M=%d", self.k_id, self.m_id)
        QMessageBox.information(
            self,
            "Devices Updated",
            f"Hardware reloaded:\nKeyboard ID: {self.k_id}\nMouse ID: {self.m_id}",
        )
