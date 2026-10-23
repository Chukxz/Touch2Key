"""
Dashboard: engine state, active session summary, live engine telemetry and
quick navigation.

Wrapped in a scroll area like SettingsPage so this page never pins the window's
minimum height (which would stop the log dock from growing).

Telemetry has two sources, both read once a second while the page is visible:
  * the engine process tree, via psutil (CPU / memory / threads per process);
  * the snapshot the engine publishes (runtime_info): measured touch rate, ADB
    rate cap and PPS threshold as the engine is *actually* running with them,
    worker roles and respawn counts. Same data as `touch2key-stats`.
"""

from __future__ import annotations

import datetime
import logging
import sys
import time
from typing import TYPE_CHECKING, Any

import psutil
from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QFormLayout,
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from modules.database import store
from modules.runtime_info import (
    STALE_AFTER_S,
    labeled_processes,
    read_snapshot,
    snapshot_age,
)

if TYPE_CHECKING:
    from modules.utils import MapperEventDispatcher
    from modules.gui.main_window import EngineProcessController

logger = logging.getLogger("modules.gui.dashboard_page")

_MB = 1024 * 1024
_TELEMETRY_INTERVAL_MS = 1000
_DOT_RUNNING = "#43a047"
_DOT_STOPPED = "#9e9e9e"
_WARN = "#fb8c00"
_STATUS_COLORS = {"HEALTHY": _DOT_RUNNING, "LOW RATE": _WARN, "IDLE": _DOT_STOPPED}


def _num(value: Any) -> str:
    return "--" if value is None else f"{value:g}"


class DashboardPage(QWidget):
    """Primary overview: engine state, active session, telemetry, navigation."""

    title = "Dashboard"
    start_requested = Signal()
    stop_requested = Signal()
    navigate_requested = Signal(str)  # page title, e.g. "Settings"

    def __init__(
        self,
        engine_controller: EngineProcessController,
        dispatcher: MapperEventDispatcher | None = None,
        parent=None,
    ):
        super().__init__(parent)
        self.engine_controller = engine_controller
        self.dispatcher = dispatcher

        self._running = False
        # Reused psutil objects: cpu_percent() needs a previous call as baseline.
        self._procs: dict[int, psutil.Process] = {}

        self._telemetry_timer = QTimer(self)
        self._telemetry_timer.setInterval(_TELEMETRY_INTERVAL_MS)
        self._telemetry_timer.timeout.connect(self._update_telemetry)

        root_layout = QVBoxLayout(self)
        root_layout.setContentsMargins(0, 0, 0, 0)

        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setFrameShape(QFrame.Shape.NoFrame)

        content = QWidget()
        main_layout = QVBoxLayout(content)
        main_layout.setContentsMargins(16, 16, 16, 16)
        main_layout.setSpacing(12)

        # -- Engine ------------------------------------------------------
        engine_box = QGroupBox("Engine")
        engine_row = QHBoxLayout(engine_box)

        self.status_dot = QLabel("●")
        self.status_label = QLabel("Engine: Stopped")
        self.status_label.setStyleSheet("font-weight: bold;")

        self.start_btn = QPushButton("Start Engine")
        self.stop_btn = QPushButton("Stop Engine")
        self.stop_btn.setEnabled(False)
        self.start_btn.clicked.connect(self.start_requested)
        self.stop_btn.clicked.connect(self.stop_requested)

        engine_row.addWidget(self.status_dot)
        engine_row.addWidget(self.status_label)
        engine_row.addStretch()
        engine_row.addWidget(self.start_btn)
        engine_row.addWidget(self.stop_btn)
        main_layout.addWidget(engine_box)

        # -- Active session ----------------------------------------------
        session_box = QGroupBox("Active Session")
        session_form = QFormLayout(session_box)

        self.active_profile_label = QLabel()
        self.zones_label = QLabel()
        self.target_window_label = QLabel()
        self.keys_label = QLabel()
        self.devices_label = QLabel()
        for label in (
            self.active_profile_label,
            self.zones_label,
            self.target_window_label,
            self.keys_label,
            self.devices_label,
        ):
            label.setWordWrap(True)

        session_form.addRow("Layout:", self.active_profile_label)
        session_form.addRow("Zones:", self.zones_label)
        session_form.addRow("Target window:", self.target_window_label)
        session_form.addRow("Keys:", self.keys_label)
        session_form.addRow("Input devices:", self.devices_label)
        main_layout.addWidget(session_box)

        # -- Telemetry ---------------------------------------------------
        telemetry_box = QGroupBox("Engine Telemetry")
        telemetry_layout = QVBoxLayout(telemetry_box)

        self.rate_label = QLabel()
        self.rate_label.setTextFormat(Qt.TextFormat.RichText)
        self.rate_label.setWordWrap(True)
        telemetry_layout.addWidget(self.rate_label)

        self.telemetry_label = QLabel()
        self.telemetry_label.setStyleSheet("font-family: monospace;")
        self.telemetry_label.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )
        telemetry_layout.addWidget(self.telemetry_label)
        main_layout.addWidget(telemetry_box)

        # -- Quick actions -----------------------------------------------
        actions_row = QHBoxLayout()
        self.open_studio_btn = QPushButton("Open Layout Studio")
        self.open_settings_btn = QPushButton("Open Settings")
        self.open_studio_btn.clicked.connect(
            lambda: self.navigate_requested.emit("Layout Studio")
        )
        self.open_settings_btn.clicked.connect(
            lambda: self.navigate_requested.emit("Settings")
        )
        actions_row.addWidget(self.open_studio_btn)
        actions_row.addWidget(self.open_settings_btn)
        actions_row.addStretch()
        main_layout.addLayout(actions_row)

        main_layout.addStretch()
        scroll_area.setWidget(content)
        root_layout.addWidget(scroll_area)

        self._apply_status(False)
        self._show_idle_telemetry()
        self._register_dispatcher_events()
        self.refresh_state()

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------
    def _register_dispatcher_events(self) -> None:
        if not self.dispatcher:
            return
        self.dispatcher.register_callback("ON_RELOAD", self.refresh_state)
        self.dispatcher.register_callback(
            "ON_TARGET_WINDOW_CHANGE", self._on_target_window_change
        )

    def on_page_shown(self) -> None:
        self.refresh_state()

    def showEvent(self, event) -> None:
        super().showEvent(event)
        if self._running:
            self._update_telemetry()
            self._telemetry_timer.start()

    def hideEvent(self, event) -> None:
        # Sample only while visible (also stops when the window is minimized).
        self._telemetry_timer.stop()
        super().hideEvent(event)

    # ------------------------------------------------------------------
    # Session summary
    # ------------------------------------------------------------------
    def refresh_state(self) -> None:
        try:
            self._refresh_layout_labels()
            self._refresh_keys_label()
        except Exception:
            logger.exception("Failed to refresh dashboard session summary")
        self._refresh_devices_label()
        self._refresh_target_label()

    def _refresh_layout_labels(self) -> None:
        active_layout = store.get_active_layout()
        if active_layout:
            zone_count = store.zones.count_by_layout().get(active_layout.id, 0)
            self.active_profile_label.setText(
                f"{active_layout.name} (ID: {active_layout.id})"
            )
            self.zones_label.setText(str(zone_count))
        else:
            self.active_profile_label.setText("None")
            self.zones_label.setText("-")

    def _refresh_keys_label(self) -> None:
        settings = store.settings.get()
        toggle = settings.toggle_key or "Not set"
        sprint = settings.sprint_key or "Not set"
        self.keys_label.setText(f"Toggle: {toggle}   |   Sprint: {sprint}")

    def _refresh_devices_label(self) -> None:
        if sys.platform != "win32":
            self.devices_label.setText("UInput / Evdev (kernel-managed)")
            return

        with self.engine_controller.lock:
            k_id = self.engine_controller.k_id
            m_id = self.engine_controller.m_id
        self.devices_label.setText(
            f"Keyboard: {'Unassigned' if k_id is None else k_id}   |   "
            f"Mouse: {'Unassigned' if m_id is None else m_id}"
        )

    def _refresh_target_label(self) -> None:
        if self.engine_controller.window_title:
            id_str = (
                f" (ID: {self.engine_controller.window_id})"
                if self.engine_controller.window_id is not None
                else ""
            )
            self.target_window_label.setText(
                f"{self.engine_controller.window_title}{id_str}"
            )
        elif self.engine_controller.window_id is not None:
            self.target_window_label.setText(f"HWND {self.engine_controller.window_id}")
        else:
            self.target_window_label.setText("None (Foreground Active Window)")

    def _on_target_window_change(self, *args: Any, **kwargs: Any) -> None:
        self._refresh_target_label()

    # ------------------------------------------------------------------
    # Engine state
    # ------------------------------------------------------------------
    def _apply_status(self, running: bool) -> None:
        color = _DOT_RUNNING if running else _DOT_STOPPED
        self.status_dot.setStyleSheet(f"color: {color}; font-size: 18px;")
        self.status_label.setText("Engine: Running" if running else "Engine: Stopped")

    def set_running(
        self,
        running: bool,
    ) -> None:
        self._running = running
        self.start_btn.setEnabled(not running)
        self.stop_btn.setEnabled(running)
        self._apply_status(running)
        self._refresh_target_label()

        self._procs.clear()
        if not running:
            self._telemetry_timer.stop()
            self._show_idle_telemetry()
        elif self.isVisible():
            self._update_telemetry()
            self._telemetry_timer.start()

    # ------------------------------------------------------------------
    # Telemetry
    # ------------------------------------------------------------------
    def _show_idle_telemetry(self) -> None:
        self.rate_label.setVisible(False)
        self.telemetry_label.setText("Engine is not running.")
        self.telemetry_label.setStyleSheet(
            "font-family: monospace; color: palette(placeholder-text);"
        )

    def _engine_pid(self) -> int | None:
        process = self.engine_controller.process
        if process is None:
            return None
        try:
            return process.pid if process.is_alive() else None
        except (ValueError, OSError):  # process handle already closed
            return None

    def _sample(self, proc: psutil.Process) -> tuple[float | None, float, int] | None:
        """(cpu %, rss MB, threads); cpu is None on the first sample of a process
        (its baseline is being primed). None if the process is gone/inaccessible."""
        cached = self._procs.get(proc.pid)
        first = cached is None or cached != proc
        if first:
            self._procs[proc.pid] = cached = proc
        try:
            if cached is not None:
                with cached.oneshot():
                    cpu = cached.cpu_percent(interval=None)
                    rss_mb = cached.memory_info().rss / _MB
                    threads = cached.num_threads()
            else:
                return None
        except psutil.Error:
            return None
        return (None if first else cpu), rss_mb, threads

    def _render_rate(self, snap: dict[str, Any] | None) -> None:
        self.rate_label.setVisible(True)
        if snap is None:
            self.rate_label.setText("Waiting for engine telemetry...")
            return

        age = snapshot_age(snap)
        if age > STALE_AFTER_S:
            self.rate_label.setText(
                f"<span style='color:{_WARN}'>Telemetry stale ({age:.0f}s since "
                f"last update) - engine may be unresponsive</span>"
            )
            return

        cap = snap.get("rate_cap_hz")
        threshold = snap.get("pps_threshold")
        cap_note = threshold_note = ""
        try:
            # The engine's effective values can differ from the database: another
            # process may have edited it without the engine reloading, and the
            # engine clamps what it reads.
            settings = store.settings.get()
            cfg_cap = float(settings.adb_rate_cap or 0)
            cfg_pps = float(settings.pps_alert_threshold or 0)
            if cap is not None and abs(cfg_cap - cap) > 0.5:
                cap_note = (
                    f" <span style='color:{_WARN}'>(settings: {cfg_cap:g})</span>"
                )
            if threshold is not None and abs(cfg_pps - threshold) > 0.5:
                threshold_note = (
                    f" <span style='color:{_WARN}'>(settings: {cfg_pps:g})</span>"
                )
        except Exception:
            logger.debug("Could not compare telemetry with settings", exc_info=True)

        rate = snap.get("rate_hz")
        rate_txt = "--" if rate is None else f"{rate:.1f} Hz"
        status = snap.get("rate_status") or "n/a"
        color = _STATUS_COLORS.get(status, _DOT_STOPPED)
        resp = snap.get("respawns") or {}
        vkb_pid = snap.get("workers", {}).get("vkb")
        visualizer_pid = snap.get("workers", {}).get("visualizer")
        lines = [
            f"Rate (5 s avg): <b>{rate_txt}</b> "
            f"<span style='color:{color}'>{status}</span> "
            f"&nbsp;(alert below {_num(threshold)} PPS{threshold_note})",
            f"ADB rate cap: <b>{_num(cap)} Hz</b>{cap_note} &nbsp;|&nbsp; "
            f"Cursor: {'Visible' if snap.get('menu_mode') else 'Not Visible'}",
            f"Touch Events Count:",
            f"    DOWN {snap.get("downs", 0)}",
            f"    MOVE {snap.get("moves", 0)}",
            f"    UP {snap.get("ups", 0)}",
            f"    ALL {snap.get("all", 0)}",
            f"Worker respawns: Keyboard {resp.get('keyboard', 0)}, "
            f"Mouse {resp.get('mouse', 0)}",
            f"Virtual Kbd {'Not Active' if vkb_pid is None else 'Active'}",
            f"Visualizer {'Not Active' if visualizer_pid is None else 'Active'}",
        ]
        if snap.get("window_lost"):
            lines.append(f"<span style='color:{_WARN}'>No target window found</span>")
        self.rate_label.setText("<br>".join(lines))

    def _update_telemetry(self) -> None:
        pid = self._engine_pid()
        if pid is None:
            self._show_idle_telemetry()
            return

        try:
            engine = psutil.Process(pid)
            snap = read_snapshot(expected_pid=pid)
            procs = labeled_processes(engine, snap)
        except psutil.Error:
            self._show_idle_telemetry()
            return

        self._render_rate(snap)

        live = {p.pid for _, p in procs}
        self._procs = {k: v for k, v in self._procs.items() if k in live}

        rows: list[str] = []
        total_cpu = 0.0
        total_rss = 0.0
        for role, proc in procs:
            sample = self._sample(proc)
            if sample is None:
                rows.append(f"{role:<8} pid {proc.pid:<7} n/a")
                continue
            cpu, rss_mb, threads = sample
            cpu_txt = "--" if cpu is None else f"{cpu:.1f}%"
            total_cpu += cpu or 0.0
            total_rss += rss_mb
            rows.append(
                f"{role:<8} pid {proc.pid:<7} cpu {cpu_txt:>6}  "
                f"rss {rss_mb:7.1f} MB  thr {threads:3d}"
            )

        try:
            uptime = str(
                datetime.timedelta(seconds=int(time.time() - engine.create_time()))
            )
        except psutil.Error:
            uptime = "n/a"

        header = (
            f"Uptime {uptime}   Processes {len(procs)}   "
            f"CPU {total_cpu:.1f}%   RSS {total_rss:.1f} MB"
        )
        self.telemetry_label.setStyleSheet("font-family: monospace;")
        self.telemetry_label.setText("\n".join([header, *rows]))
