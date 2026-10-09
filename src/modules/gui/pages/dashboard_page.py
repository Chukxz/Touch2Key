from __future__ import annotations

from typing import TYPE_CHECKING, Any
from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from modules.database import store
from modules.utils import MapperEvent

if TYPE_CHECKING:
    from modules.utils import MapperEventDispatcher


class DashboardPage(QWidget):
    """Primary overview dashboard displaying active layout, target window, and engine state."""

    title = "Dashboard"
    start_requested = Signal()
    stop_requested = Signal()

    def __init__(
        self,
        dispatcher: MapperEventDispatcher | None = None,
        parent=None,
    ):
        super().__init__(parent)
        self.dispatcher = dispatcher

        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(16, 16, 16, 16)
        main_layout.setSpacing(12)

        self._running = False
        self._target_id: int | None = None
        self._target_title = ""

        info_box = QGroupBox("Active Session")
        info_layout = QVBoxLayout(info_box)

        self.status_label = QLabel("Engine: Stopped")
        self.status_label.setStyleSheet("font-weight: bold;")
        self.active_profile_label = QLabel("Active Layout: None")
        self.target_window_label = QLabel("Target Window: None")

        info_layout.addWidget(self.status_label)
        info_layout.addWidget(self.active_profile_label)
        info_layout.addWidget(self.target_window_label)
        main_layout.addWidget(info_box)

        btn_row = QHBoxLayout()
        self.start_btn = QPushButton("Start Engine")
        self.stop_btn = QPushButton("Stop Engine")
        self.stop_btn.setEnabled(False)

        self.start_btn.clicked.connect(self.start_requested)
        self.stop_btn.clicked.connect(self.stop_requested)

        btn_row.addWidget(self.start_btn)
        btn_row.addWidget(self.stop_btn)

        main_layout.addLayout(btn_row)
        main_layout.addStretch()

        self._register_dispatcher_events()
        self.refresh_state()

    def _register_dispatcher_events(self) -> None:
        if not self.dispatcher:
            return
        self.dispatcher.register_callback("ON_LAYOUT_RELOAD", self._on_layout_reload)
        self.dispatcher.register_callback("ON_CONFIG_RELOAD", self._on_layout_reload)
        self.dispatcher.register_callback(
            "ON_TARGET_WINDOW_CHANGE", self._on_target_window_change
        )

    def on_page_shown(self) -> None:
        self.refresh_state()

    def refresh_state(self) -> None:
        self._refresh_layout_label()
        self._sync_target_window_from_siblings()
        self._refresh_target_label()

    def _sync_target_window_from_siblings(self) -> None:
        """Pulls window details from SettingsPage if not yet captured via events."""
        if not self._target_title:
            main_win = self.window()
            if hasattr(main_win, "pages") and "Settings" in main_win.pages:  # type: ignore
                settings_pg = main_win.pages["Settings"]  # type: ignore
                if getattr(settings_pg, "w_title", ""):
                    self._target_title = settings_pg.w_title
                    self._target_id = settings_pg.w_id

    def _refresh_layout_label(self) -> None:
        active_layout = store.get_active_layout()
        if active_layout:
            self.active_profile_label.setText(
                f"Active Layout: {active_layout.name} (ID: {active_layout.id})"
            )
        else:
            self.active_profile_label.setText("Active Layout: None")

    def _refresh_target_label(self) -> None:
        if self._target_title:
            id_str = f" (ID: {self._target_id})" if self._target_id is not None else ""
            self.target_window_label.setText(
                f"Target Window: {self._target_title}{id_str}"
            )
        elif self._target_id is not None:
            self.target_window_label.setText(f"Target Window: HWND {self._target_id}")
        else:
            self.target_window_label.setText(
                "Target Window: None (Foreground Active Window)"
            )

    def _on_layout_reload(self, *args: Any, **kwargs: Any) -> None:
        self._refresh_layout_label()

    def _on_target_window_change(self, *args: Any, **kwargs: Any) -> None:
        wid = None
        wtitle = ""

        if args and isinstance(args[0], MapperEvent):
            wid = getattr(args[0], "target_window_id", None)
            wtitle = getattr(args[0], "target_window_title", "")
        elif args:
            wid = args[0]
            if len(args) > 1 and isinstance(args[1], str):
                wtitle = args[1]

        if "target_window_id" in kwargs:
            wid = kwargs["target_window_id"]
        if "target_window_title" in kwargs:
            wtitle = kwargs["target_window_title"]

        self._target_id = wid
        self._target_title = wtitle or ""
        self._refresh_target_label()

    def set_running(
        self,
        running: bool,
        window_title: str | None = None,
        window_id: int | None = None,
    ) -> None:
        self._running = running
        if window_title is not None:
            self._target_title = window_title
        if window_id is not None:
            self._target_id = window_id

        self.start_btn.setEnabled(not running)
        self.stop_btn.setEnabled(running)
        self.status_label.setText("Engine: Running" if running else "Engine: Stopped")
        self._refresh_target_label()
