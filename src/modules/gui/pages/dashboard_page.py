"""
Dashboard: engine state, active session summary, live engine telemetry and
quick navigation.

Wrapped in a scroll area like SettingsPage so this page never pins the window's
minimum height (which would stop the log dock from growing).

Telemetry has two sources, both read once a second while the engine runs (the
GUI process itself is sampled even when the engine is stopped):
  * the GUI process and the engine process tree, via psutil (CPU / memory /
    threads per process);
  * the snapshot the engine publishes (runtime_info): measured touch rate, ADB
    rate cap and PPS threshold as the engine is *actually* running with them,
    worker roles and respawn counts. Same data as `touch2key-stats`.

The UI is only re-rendered while the page is visible. A compact one-line
summary of each Nth sample is also written to the `telemetry` logger (see
_LOG_TELEMETRY / _LOG_INTERVAL_S), so it keeps logging while the page is hidden,
the window is minimized, or the engine is stopped.
"""

from __future__ import annotations

import datetime
import logging
import os
import sqlite3
import sys
import time
from typing import TYPE_CHECKING, Any

import psutil
from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QFontDatabase
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
from modules.scripts.runtime_info import (
    STALE_AFTER_S,
    labeled_processes,
    read_snapshot,
    snapshot_age,
)

from modules.utils import num_normalizer, parse_seq

if TYPE_CHECKING:
    from modules.utils import MapperEventDispatcher
    from modules.gui.main_window import EngineProcessController

logger = logging.getLogger("modules.gui.dashboard_page")
# Child logger: inherits the parent's handlers (file, log dock), but can be
# filtered or routed separately, e.g. logging.getLogger(
# "modules.gui.dashboard_page.telemetry").setLevel(logging.WARNING)
telemetry_logger = logging.getLogger("modules.gui.dashboard_page.telemetry")

_MB = 1024 * 1024
_LOGICAL_CORES = psutil.cpu_count() or 1
_TELEMETRY_INTERVAL_MS = 1000
_LOG_TELEMETRY = False  # False (no logging, sample only while visible)
_LOG_INTERVAL_S = 5  # one log line per this many seconds
_LOG_EVERY_N_TICKS = max(1, round(_LOG_INTERVAL_S * 1000 / _TELEMETRY_INTERVAL_MS))
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

    # Dispatcher callbacks may run on a non-GUI thread (debounced deliveries).
    # Emitting a signal queues the real work onto the GUI thread.
    _reload_requested = Signal()
    _target_window_changed = Signal()

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
        # The GUI process itself: parent of the engine, so not in the engine's tree.
        self._gui_proc = psutil.Process(os.getpid())
        self._tick = 0  # telemetry samples since the engine started (log throttle)
        # Reused psutil objects: cpu_percent() needs a previous call as baseline.
        self._procs: dict[int, psutil.Process] = {}

        self._telemetry_timer = QTimer(self)
        self._telemetry_timer.setInterval(_TELEMETRY_INTERVAL_MS)
        self._telemetry_timer.timeout.connect(self._update_telemetry)

        self._reload_requested.connect(self.refresh_state)
        self._target_window_changed.connect(self._refresh_target_label)

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
        # Ask the OS for its native fixed-pitch font (Consolas on Windows, DejaVu Sans Mono / monospace on Linux)
        self.telemetry_label.setFont(
            QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont)
        )
        # Fallback font stack in stylesheet
        self.telemetry_label.setStyleSheet(
            'font-family: "Consolas", "Courier New", monospace;'
        )
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
        if _LOG_TELEMETRY:
            self._telemetry_timer.start()

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------
    def _register_dispatcher_events(self) -> None:
        if not self.dispatcher:
            return
        self.dispatcher.register_callback("ON_RELOAD", self._on_reload_event)
        self.dispatcher.register_callback(
            "ON_TARGET_WINDOW_CHANGE", self._on_target_window_change
        )

    def _on_reload_event(self) -> None:
        """Dispatcher callback; may run on any thread."""
        self._reload_requested.emit()

    def on_page_shown(self) -> None:
        self.refresh_state()

    def _telemetry_wanted(self) -> bool:
        """Sample while the page is visible (UI) or logging is on (which must
        keep going while hidden / minimized / engine stopped)."""
        return self.isVisible() or _LOG_TELEMETRY

    def showEvent(self, event) -> None:
        super().showEvent(event)
        try:
            self._update_telemetry()
        except (
            psutil.NoSuchProcess,
            psutil.AccessDenied,
            psutil.ZombieProcess,
            OSError,
            RuntimeError,
        ):
            pass
        self._telemetry_timer.start()

    def hideEvent(self, event) -> None:
        # Stop sampling while hidden (also when the window is minimized), unless
        # telemetry logging needs the timer to keep running.
        if not _LOG_TELEMETRY:
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

        parsed_toggle_hotkeys = parse_seq(settings.toggle_hotkeys, ",")
        toggle_hotkeys = (
            ", ".join(parsed_toggle_hotkeys) if parsed_toggle_hotkeys else "Not set"
        )

        sprint = settings.sprint_key or "Not set"
        self.keys_label.setText(f"Toggle Hotkeys: {toggle_hotkeys}\nSprint: {sprint}")

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
        """Dispatcher callback; may run on any thread."""
        self._target_window_changed.emit()

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

        # Engine processes changed; keep the GUI process's CPU baseline.
        self._procs = {k: v for k, v in self._procs.items() if k == self._gui_proc.pid}
        self._tick = 0
        if self._telemetry_wanted():
            self._update_telemetry()
            self._telemetry_timer.start()
        else:
            self._telemetry_timer.stop()
            self._show_idle_telemetry()

    # ------------------------------------------------------------------
    # Telemetry
    # ------------------------------------------------------------------
    def _show_idle_telemetry(self) -> None:
        self.telemetry_label.setText("Engine is not running.")
        self.telemetry_label.setStyleSheet(
            'font-family: "Consolas", "Courier New", monospace;'
        )

    def _engine_pid(self) -> int | None:
        process = self.engine_controller.process
        if process is None:
            return None
        try:
            return process.pid if process.is_alive() else None
        except (ValueError, OSError):  # process handle already closed
            return None

    def _sample(
        self, proc: psutil.Process
    ) -> tuple[float | None, float, float, int] | None:
        """(cpu %, rss MB, private MB, threads); cpu is None on the first sample
        of a process (its baseline is being primed). None if the process is gone/inaccessible."""
        cached = self._procs.get(proc.pid)
        first = cached is None or cached != proc
        if first:
            self._procs[proc.pid] = cached = proc
        try:
            if cached is not None:
                with cached.oneshot():
                    raw_cpu = cached.cpu_percent(interval=None)
                    full_mem = cached.memory_full_info()
                    rss_mb = full_mem.rss / _MB
                    priv_mb = getattr(full_mem, "uss", full_mem.rss) / _MB
                    threads = cached.num_threads()

                    # Normalize across total logical cores
                    cpu = (raw_cpu / _LOGICAL_CORES) if raw_cpu is not None else None
            else:
                return None
        except psutil.Error:
            return None
        return (None if first else cpu), rss_mb, priv_mb, threads
    
    def _render_rate(
        self, engine_running: bool, snap: dict[str, Any] | None, has_visualizer: bool
    ) -> None:

        if not engine_running:
            self.rate_label.setText(
                f"Visualizer: {'Active' if has_visualizer else 'Not Active'}"
            )
            return

        if snap is None:
            self.rate_label.setText(
                f"Waiting for engine telemetry...<br>Visualizer: {'Active' if has_visualizer else 'Not Active'}"
            )
            return

        age = snapshot_age(snap)
        if age > STALE_AFTER_S:
            lines = [
                f"<span style='color:{_WARN}'>Telemetry stale ({age:.0f}s since last update) - engine may be unresponsive</span>",
                f"Visualizer: {'Active' if has_visualizer else 'Not Active'}",
            ]
            self.rate_label.setText("<br>".join(lines))
            return

        cap = snap.get("rate_cap_hz")
        threshold = snap.get("pps_threshold")
        cap_note = threshold_note = ""
        try:
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
        except (KeyError, ValueError, sqlite3.Error, AttributeError):
            logger.debug("Could not compare telemetry with settings", exc_info=True)

        rate = snap.get("rate_hz")
        rate_txt = "--" if rate is None else f"{rate:.1f} Hz"
        status = snap.get("rate_status") or "n/a"
        color = _STATUS_COLORS.get(status, _DOT_STOPPED)
        resp = snap.get("respawns") or {}
        vkb_pid = snap.get("workers", {}).get("vkb")

        lines = [
            f"Rate (5 s avg): <b>{rate_txt}</b> "
            f"<span style='color:{color}'>{status}</span> "
            f"&nbsp;(alert below {_num(threshold)} PPS{threshold_note})",
            f"ADB rate cap: <b>{_num(cap)} Hz</b>{cap_note} &nbsp;|&nbsp; "
            f"Cursor: {'Visible' if snap.get('menu_mode') else 'Not Visible'}",
            "Touch Events Count:",
            f"    DOWN {num_normalizer(int(snap.get('downs', 0)))}",
            f"    MOVE {num_normalizer(int(snap.get('moves', 0)))}",
            f"    UP   {num_normalizer(int(snap.get('ups', 0)))}",
            f"    ALL  {num_normalizer(int(snap.get('all', 0)))}",
            f"Worker respawns: Keyboard {resp.get('keyboard', 0)}, "
            f"Mouse {resp.get('mouse', 0)}",
            f"Virtual Kbd: {'Active' if vkb_pid else 'Not Active'}",
            f"Visualizer: {'Active' if has_visualizer else 'Not Active'}",
        ]
        if snap.get("window_lost"):
            lines.append(f"<span style='color:{_WARN}'>No target window found</span>")
        self.rate_label.setText("<br>".join(lines))

    def _build_rows(
        self,
        engine: psutil.Process | None,
        procs: list[tuple[str, psutil.Process]],
    ) -> tuple[str, list[str]]:
        """Header line and one row per process (shared by the UI and the log).
        The GUI process is always the first row."""
        procs = [
            ("gui", self._gui_proc),
            *[(role, p) for role, p in procs if p.pid != self._gui_proc.pid],
        ]
        live = {p.pid for _, p in procs}
        self._procs = {k: v for k, v in self._procs.items() if k in live}

        rows: list[str] = []
        total_cpu = 0.0
        total_rss = 0.0
        total_priv = 0.0

        for role, proc in procs:
            sample = self._sample(proc)
            if sample is None:
                rows.append(
                    f"{role:<12} {proc.pid:>7}  {'--':>7}  {'--':>10}  {'n/a':>10}  {'--':>4}"
                )
                continue

            cpu, rss_mb, priv_mb, threads = sample
            cpu_txt = "--" if cpu is None else f"{cpu:.1f}%"
            rss_txt = f"{rss_mb:.1f} MB"
            priv_txt = f"{priv_mb:.1f} MB"
            total_cpu += cpu or 0.0
            total_rss += rss_mb
            total_priv += priv_mb

            rows.append(
                f"{role:<12} {proc.pid:>7}  {cpu_txt:>7}  {rss_txt:>10}  {priv_txt:>10}  {threads:>4}"
            )

        now = time.time()

        # GUI uptime
        try:
            gui_uptime = str(
                datetime.timedelta(seconds=int(now - self._gui_proc.create_time()))
            )
        except psutil.Error:
            gui_uptime = "n/a"

        # Engine uptime (when running)
        engine_uptime = None
        if engine is not None:
            try:
                engine_uptime = str(
                    datetime.timedelta(seconds=int(now - engine.create_time()))
                )
            except psutil.Error:
                engine_uptime = "n/a"

        # Display both if running; show GUI uptime if engine is stopped
        if engine_uptime is not None:
            uptime_str = f"Engine: {engine_uptime} | GUI: {gui_uptime}"
        else:
            uptime_str = f"GUI: {gui_uptime}"

        summary_bar = (
            f"Uptime [{uptime_str}] | Procs: {len(procs)} | "
            f"CPU: {total_cpu:.1f}% | RSS: {total_rss:.1f} MB | PRIV: {total_priv:.1f} MB"
        )

        header_cols = f"{'ROLE':<12} {'PID':>7}  {'CPU':>7}  {'RSS':>10}  {'PRIV':>10}  {'THR':>4}"
        divider = f"{'-'*12} {'-'*7}  {'-'*7}  {'-'*10}  {'-'*10}  {'-'*4}"
        table_header = f"{summary_bar}\n{header_cols}\n{divider}"

        return table_header, rows

    def _log_telemetry(
        self,
        engine_running: bool,
        snap: dict[str, Any] | None,
        header: str,
        rows: list[str],
        has_visualizer: bool,
    ) -> None:
        """One plain-text line per call (no HTML, whitespace collapsed)."""
        summary = " ".join(header.split())
        if not engine_running:
            procs_txt = "; ".join(" ".join(row.split()) for row in rows)
            telemetry_logger.info("Engine not running | %s | %s", summary, procs_txt)
            return
        if snap is None:
            telemetry_logger.info("No engine snapshot yet | %s", summary)
            return

        age = snapshot_age(snap)
        if age > STALE_AFTER_S:
            telemetry_logger.warning(
                "Snapshot stale (%.0fs since last update), engine may be "
                "unresponsive | %s",
                age,
                summary,
            )
            return

        rate = snap.get("rate_hz")
        resp = snap.get("respawns") or {}
        workers = snap.get("workers") or {}
        procs_txt = "; ".join(" ".join(row.split()) for row in rows)
        telemetry_logger.info(
            "rate=%s Hz status=%s cap=%s Hz pps_alert=%s cursor=%s "
            "events(down/move/up/all)=%s/%s/%s/%s respawns(kb/mouse)=%s/%s "
            "vkb=%s visualizer=%s window_lost=%s | %s | %s",
            "--" if rate is None else f"{rate:.1f}",
            snap.get("rate_status") or "n/a",
            _num(snap.get("rate_cap_hz")),
            _num(snap.get("pps_threshold")),
            "visible" if snap.get("menu_mode") else "hidden",
            num_normalizer(int(snap.get("downs", 0))),
            num_normalizer(int(snap.get("moves", 0))),
            num_normalizer(int(snap.get("ups", 0))),
            num_normalizer(int(snap.get("all", 0))),
            resp.get("keyboard", 0),
            resp.get("mouse", 0),
            "on" if workers.get("vkb") is not None else "off",
            "on" if has_visualizer else "off",
            bool(snap.get("window_lost")),
            summary,
            procs_txt,
        )

    def _update_telemetry(self) -> None:
        pid = self._engine_pid()
        engine: psutil.Process | None = None
        snap: dict[str, Any] | None = None
        procs: list[tuple[str, psutil.Process]] = []

        if pid is not None:
            try:
                engine = psutil.Process(pid)
                snap = read_snapshot(expected_pid=pid)
                procs = labeled_processes(engine, snap)
            except psutil.Error:
                # Engine vanished mid-sample:
                # fall back to GUI-only telemetry and query procs for processes like visualizer that can run independently of the engine.
                engine, snap, procs = None, None, labeled_processes(None, None)

        else:
            # Engine is not running: query procs for processes like visualizer that can run independently of the engine.
            engine, snap, procs = None, None, labeled_processes(None, None)

        header, rows = self._build_rows(engine, procs)
        has_visualizer = any(role == "visualizer" for role, _ in procs)

        if self.isVisible():
            self._render_rate(engine is not None, snap, has_visualizer)

            if engine is None:
                body = ["Engine is not running.", header, *rows]
            else:
                body = [header, *rows]
            self.telemetry_label.setStyleSheet("font-family: monospace;")
            self.telemetry_label.setText("\n".join(body))

        self._tick += 1
        if _LOG_TELEMETRY and self._tick % _LOG_EVERY_N_TICKS == 0:
            self._log_telemetry(engine is not None, snap, header, rows, has_visualizer)
