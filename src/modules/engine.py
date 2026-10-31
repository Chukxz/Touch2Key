
from __future__ import annotations

import logging
import multiprocessing
import os
import sys
import threading
import time
from typing import TYPE_CHECKING, Any, Optional

from modules import (
    BezelMapper,
    BridgeOutputSink,
    GestureStatus,
    KeyMapper,
    LayoutLoader,
    Mapper,
    MouseMapper,
    Pipeline,
    TouchReader,
    TwoFingerTapTracker,
    WheelMapper,
)
from modules.cli.key_capture import capture_sprint_key, capture_performance_settings
from modules.database import store
from modules.gui.overlays import virtual_keyboard_worker
from modules.log_manager import AppLogManager
from modules.platforms import get_platform
from modules.runtime_info import TelemetryPublisher, read_process
from modules.scripts.list_windows import select_window
from modules.utils import (
    ADB_RATE_CAP_MAX,
    ADB_RATE_CAP_MIN,
    BASELINE_DPI,
    CURSOR_SLOP_DP,
    DEFAULT_ADB_RATE_CAP,
    DEFAULT_PPS,
    IPC_CMD_START,
    M_LEFT,
    PPS_ALERT_MAX,
    PPS_ALERT_MIN,
    VISUALIZER_RUNTIME_FILE,
    CurveType,
    InputCurve,
    IpcMapperEventDispatcher,
    MapperEvent,
    MapperEventDispatcher,
    Point,
    TouchEvent,
    TouchEventCount,
    TouchPhase,
    clamp,
    dp_to_px,
    unpack_ipc_start_cmd,
)

logger = logging.getLogger("modules.engine")

if TYPE_CHECKING:
    from multiprocessing.connection import Connection
    from multiprocessing.queues import Queue

_HOTKEY_POLL_INTERVAL = 0.005  # 5 ms key-state polling
_ADJUST_COMMIT_INTERVAL = 0.25  # coalesce DB write + reload while held
_ONESHOT_COOLDOWN = 0.35  # F5 / F6 / F8 cooldown
_ADJUST_KEYS = ("left", "right", "down", "up")


class Engine:
    def __init__(
        self,
        headless: bool = False,
        dispatcher: Optional[MapperEventDispatcher | IpcMapperEventDispatcher] = None,
        conn: Optional[Connection] = None,
    ):
        platform_mod = get_platform()
        self.headless = headless
        self.conn = conn
        self.dispatcher = dispatcher or MapperEventDispatcher()

        self.system_config = platform_mod.SystemConfig()
        self.system_config.set_high_priority(os.getpid(), "Main")
        self.system_config.set_dpi_awareness()
        self.system_config.set_timer_resolution()

        self.window_manager = platform_mod.WindowManager()
        self.foreground_window = self.window_manager.get_foreground_window()
        self.bridge = platform_mod.Bridge(self.window_manager, self.system_config)

        self.touch_event_counter = TouchEventCount()
        self._publisher: Optional[TelemetryPublisher] = None
        self._respawns: dict[str, int] = {"keyboard": 0, "mouse": 0}

        self.touch_reader: Optional[TouchReader] = None
        self.layout_loader: Optional[LayoutLoader] = None
        self.mapper: Optional[Mapper] = None
        self.output_sink: Optional[BridgeOutputSink] = None
        self.bezel_mapper: Optional[BezelMapper] = None
        self.mouse_mapper: Optional[MouseMapper] = None
        self.key_mapper: Optional[KeyMapper] = None
        self.wheel_mapper: Optional[WheelMapper] = None
        self.two_finger_tap_tracker = TwoFingerTapTracker()

        self.fallback_mouse_pipeline: Optional[Pipeline] = None
        self._cursor_down_pos: Optional[Point] = None
        self._cursor_drag_started: bool = False
        self._cursor_down_time: float = 0.0
        self._cursor_slop_sq: int = 0

        self._tiers: list[list[Pipeline]] = []

        # Ownership is fixed at DOWN; MOVE/UP never get offered to a new tier.
        self._contact_owners: dict[int, tuple[Pipeline, ...]] = {}
        self._dispatch_generation = 0

        self.is_visible = False
        self.lock = threading.RLock()
        self.vkb_lock = threading.Lock()
        self.is_shutting_down = False
        self._stop_event = threading.Event()

        self.vkb_reader, self.vkb_writer = multiprocessing.Pipe(duplex=False)
        self.vkb_process: Optional[multiprocessing.Process] = None

        self.two_finger_tap_enabled = True
        self.bezel_toggle_enabled = True
        self._mouse_flush_thread: Optional[threading.Thread] = None

        # --- CLI hotkey state ---
        self.rate_cap: float = ADB_RATE_CAP_MIN
        self.pps: float = PPS_ALERT_MIN
        self._adjust_lock = threading.Lock()
        self._settings_dirty = False
        self._last_commit_time = 0.0
        self._live_shown = False
        self._live_active = False
        self._live_text = ""

        # Input curve cycling state (defaults to CUBIC on startup).
        self._curve_types: tuple[CurveType, ...] = tuple(CurveType)
        self._curve_idx: int = self._curve_types.index(CurveType.CUBIC)
        self._current_curve: CurveType = self._curve_types[self._curve_idx]

        # One-shot (non-typematic) keys: shared 350 ms cooldown.
        self._last_hotkey_time = 0.0
        self._hotkey_cooldown = _ONESHOT_COOLDOWN
        self._oneshot_prev: dict[str, bool] = {
            "f5": False,
            "f6": False,
            "f8": False,
        }
        self._oneshot_actions = {
            "f5": self._toggle_handedness_cli,
            "f6": self._reload_cli,
            "f8": self._cycle_input_curve_cli,
        }

        # Typematic keys: one InputCurve per key initialized to default curve.
        self._adjust_curves: dict[str, InputCurve] = {
            key: InputCurve(self._current_curve) for key in _ADJUST_KEYS
        }

        # Each action receives n = increments due this poll.
        self._adjust_actions = {
            "left": lambda n: self._adjust_rate_cap_cli(-10.0 * n),
            "right": lambda n: self._adjust_rate_cap_cli(10.0 * n),
            "down": lambda n: self._adjust_pps_cli(-5.0 * n),
            "up": lambda n: self._adjust_pps_cli(5.0 * n),
        }

        self._terminal_window_handle = None
        self._hotkey_thread: Optional[threading.Thread] = None

        if not self.headless:
            try:
                import keyboard

                self._terminal_window_handle = (
                    self.window_manager.get_foreground_window()
                )

                def _guarded_shutdown():
                    if self._is_terminal_focused():
                        self._shutdown()

                keyboard.add_hotkey("esc", _guarded_shutdown)

                self._hotkey_thread = threading.Thread(
                    target=self._hotkey_loop,
                    daemon=True,
                    name="CLIHotkeyPoller",
                )
                self._hotkey_thread.start()

                logger.info(
                    "[CLI Interactive Launch] Active Hotkeys: [Esc] Exit | [F5] Handedness | "
                    "[F6] Reload | [F8] Input Curve | [Left/Right] Rate Cap (-/+ 10) | [Down/Up] PPS (-/+ 5)"
                )
                logger.info(
                    "[CLI Interactive Launch] Default Input Curve: %s",
                    self._current_curve.name,
                )
            except Exception as exc:
                logger.debug(
                    "Failed to register CLI global hotkeys: %s",
                    exc,
                    exc_info=True,
                )
        else:
            logger.info(
                "[Headless / GUI Worker Launch] Background engine active "
                "(terminal hotkeys bypassed)."
            )

    # ------------------------------------------------------------------
    # Hotkey infrastructure
    # ------------------------------------------------------------------
    def _is_terminal_focused(self) -> bool:
        try:
            return (
                self.window_manager.get_foreground_window()
                == self._terminal_window_handle
            )
        except Exception as exc:
            logger.debug(
                "Foreground verification failed for hotkey: %s",
                exc,
                exc_info=True,
            )
            return False

    def _hotkey_loop(self) -> None:
        import keyboard

        while not self._stop_event.is_set():
            try:
                self._poll_hotkeys(keyboard)
            except Exception:
                logger.debug("Hotkey poll failed", exc_info=True)

            self._stop_event.wait(_HOTKEY_POLL_INTERVAL)

        if self._live_active:
            self._live_active = False
            AppLogManager.end_live_line()
            AppLogManager.resume_console()

    def _poll_hotkeys(self, keyboard) -> None:
        now = time.perf_counter()
        keys = (*self._adjust_curves, *self._oneshot_actions)
        pressed = {k: keyboard.is_pressed(k) for k in keys}

        # Losing terminal focus counts as release: resets curves and edges.
        if any(pressed.values()) and not self._is_terminal_focused():
            pressed = dict.fromkeys(keys, False)

        # Opposing keys on the same axis cancel.
        for a, b in (("left", "right"), ("down", "up")):
            if pressed[a] and pressed[b]:
                pressed[a] = pressed[b] = False

        # Typematic: active InputCurve drives repeat timing.
        for key, curve in self._adjust_curves.items():
            count = curve.check_input(now, pressed[key])
            if count and self._adjust_actions[key](count):
                self._settings_dirty = True

        # Live status line: only after a key has been held past initial delay.
        adjusting = any(pressed[k] for k in self._adjust_curves)
        held_long = any(
            c.is_held and (now - c.hold_start_time) >= c.initial_delay
            for c in self._adjust_curves.values()
        )

        if adjusting and (self._live_active or held_long):
            if not self._live_active:
                AppLogManager.suspend_console()
                self._live_shown = True
                self._live_active = True
                self._live_text = ""

            text = f"Rate Cap {self.rate_cap:.1f} Hz | PPS {self.pps:.1f}"
            if text != self._live_text:
                self._live_text = text
                AppLogManager.live_line(text)

        elif not adjusting and self._live_active:
            self._live_active = False
            AppLogManager.end_live_line()
            AppLogManager.resume_console()

        # Non-typematic: act on rising edge only.
        for key, action in self._oneshot_actions.items():
            down = pressed[key]
            if down and not self._oneshot_prev[key]:
                action()
            self._oneshot_prev[key] = down

        # Coalesced persistence for rate/PPS.
        if (
            self._settings_dirty
            and now - self._last_commit_time >= _ADJUST_COMMIT_INTERVAL
        ):
            self._commit_adjustments(now)

    def _check_debounce(self) -> bool:
        """350 ms cooldown for one-shot hotkeys (F5 / F6 / F8)."""
        now = time.perf_counter()
        if now - self._last_hotkey_time < self._hotkey_cooldown:
            return False

        self._last_hotkey_time = now
        return True

    # ------------------------------------------------------------------
    # Typematic: rate cap / PPS
    # ------------------------------------------------------------------
    def _adjust_rate_cap_cli(self, delta: float) -> bool:
        with self._adjust_lock:
            new_rate = clamp(
                self.rate_cap + delta,
                ADB_RATE_CAP_MIN,
                ADB_RATE_CAP_MAX,
            )
            if new_rate == self.rate_cap:
                return False

            self.rate_cap = new_rate
            if self.touch_reader is not None:
                self.touch_reader.set_rate_cap(self.rate_cap)

            return True

    def _adjust_pps_cli(self, delta: float) -> bool:
        with self._adjust_lock:
            new_pps = clamp(
                self.pps + delta,
                PPS_ALERT_MIN,
                PPS_ALERT_MAX,
            )
            if new_pps == self.pps:
                return False

            self.pps = new_pps
            return True

    def _commit_adjustments(self, now: float) -> None:
        with self._adjust_lock:
            rate, pps = self.rate_cap, self.pps
            self._settings_dirty = False

        self._last_commit_time = now

        try:
            store.settings.update(
                adb_rate_cap=rate,
                pps_alert_threshold=pps,
            )
        except Exception as exc:
            logger.error("Failed to commit rate/PPS update to DB: %s", exc)
            self._settings_dirty = True
            return

        if self._live_shown:
            logger.debug(
                "Committed rate cap %.1f Hz, PPS %.1f.",
                rate,
                pps,
            )
            if not self._live_active:
                self._live_shown = False
        else:
            logger.info("Rate Cap %.1f Hz | PPS %.1f\n", rate, pps)

        self.dispatcher.dispatch(
            MapperEvent(action="ON_RELOAD", cooldown=1.0)
        )

    # ------------------------------------------------------------------
    # One-shot: handedness / reload / input curve
    # ------------------------------------------------------------------
    def _toggle_handedness_cli(self) -> None:
        if not self._check_debounce():
            return

        try:
            settings = store.settings.get()
            new_val = not settings.left_handed
            store.settings.update(left_handed=new_val)

            logger.info(
                "CLI Triggered [F5]: Left-Handed mode set to %s, "
                "reload event dispatched.",
                new_val,
            )
            self.dispatcher.dispatch(MapperEvent(action="ON_RELOAD"))

        except Exception as exc:
            logger.error(
                "Failed to toggle handedness via hotkey: %s",
                exc,
                exc_info=True,
            )

    def _reload_cli(self) -> None:
        if not self._check_debounce():
            return

        self.dispatcher.dispatch(MapperEvent(action="ON_RELOAD"))
        logger.info("CLI Triggered [F6]: Reload event dispatched.")

    def _cycle_input_curve_cli(self) -> None:
        if not self._check_debounce():
            return

        with self._adjust_lock:
            self._curve_idx = (
                self._curve_idx + 1
            ) % len(self._curve_types)
            self._current_curve = self._curve_types[self._curve_idx]

            for key in _ADJUST_KEYS:
                self._adjust_curves[key] = InputCurve(self._current_curve)

        logger.info(
            "CLI Triggered [F8]: Input curve set to %s.",
            self._current_curve.name,
        )

    def _on_devices_change(
        self,
        k_id: Optional[int] = None,
        m_id: Optional[int] = None,
        *,
        keyboard_device_id: Optional[int] = None,
        mouse_device_id: Optional[int] = None,
    ) -> None:
        if not self.bridge or self.bridge.k_proc is None:
            return

        self.bridge.reload_devices(
            keyboard_device_id if keyboard_device_id is not None else k_id,
            mouse_device_id if mouse_device_id is not None else m_id,
        )

    def _release_active_inputs(self) -> None:
        """Clear pipeline ownership and release held outputs on a state boundary."""
        self._dispatch_generation += 1
        self._contact_owners.clear()
        self.two_finger_tap_tracker.reset()

        self._cursor_down_pos = None
        self._cursor_drag_started = False
        self._cursor_slop_sq = 0

        if self.fallback_mouse_pipeline and self.output_sink:
            self.fallback_mouse_pipeline.reset(self.output_sink)

        if self.output_sink:
            for tier in self._tiers:
                for pipeline in tier:
                    try:
                        pipeline.reset(self.output_sink)
                    except Exception:
                        logger.exception(
                            "Failed to reset pipeline during state transition",
                            exc_info=True,
                        )

            if self.bezel_mapper:
                self.bezel_mapper.release_all()

            if self.key_mapper:
                self.key_mapper.release_all()

            if self.wheel_mapper:
                self.wheel_mapper.touch_up()

            if self.mouse_mapper:
                self.mouse_mapper.touch_up()

    def _apply_visibility(self, visible: bool) -> None:
        with self.lock:
            visible = bool(visible)
            if self.is_visible == visible:
                return

            self.is_visible = visible
            self._release_active_inputs()

        try:
            self.bridge.health_check()
        except Exception:
            logger.debug(
                "Bridge health check failed during mode switch",
                exc_info=True,
            )

    def _on_reload(self) -> None:
        """Reload engine and submapper pipelines in a single lock transaction."""
        with self.lock:
            # Refresh layout snapshot first.
            snap = None

            if self.layout_loader is not None:
                self.layout_loader.load_layout()
                snap = self.layout_loader.snapshot
                settings = (
                    snap.settings
                    if snap is not None
                    else store.settings.get()
                )
            else:
                settings = store.settings.get()

            # Update Engine and TouchReader settings.
            self.two_finger_tap_enabled = settings.two_finger_tap_enabled
            self.bezel_toggle_enabled = settings.bezel_toggle_enabled

            # Dynamically scale the two-finger tap drift threshold.
            if snap is not None:
                self.two_finger_tap_tracker.update_dpi(snap.dpi)

            with self._adjust_lock:
                # Uncommitted hotkey steps are newer than the DB; keep them.
                if not self._settings_dirty:
                    self.rate_cap = (
                        settings.adb_rate_cap or DEFAULT_ADB_RATE_CAP
                    )
                    self.pps = (
                        settings.pps_alert_threshold or DEFAULT_PPS
                    )

            if self.touch_reader is not None:
                self.touch_reader.on_reload()
                self.touch_reader.set_rate_cap(self.rate_cap)

            # Release active ownership and held outputs before rebuilding.
            self._release_active_inputs()

            if self.mapper is not None:
                self.mapper.reload()

            if self.bezel_mapper is not None:
                self.bezel_mapper.rebuild_pipelines()

            if self.mouse_mapper is not None:
                self.mouse_mapper.rebuild_pipeline()

            if self.key_mapper is not None:
                self.key_mapper.update_bridge_typematics()
                self.key_mapper.rebuild_pipelines()

            if self.wheel_mapper is not None:
                self.wheel_mapper.rebuild_pipeline()

            self._tiers = self._build_pipeline_tiers()

        logger.info(
            "Engine reloaded: Rate Cap=%.1f Hz, PPS Threshold=%.1f PPS",
            self.rate_cap,
            self.pps,
        )

    @staticmethod
    def _pipeline_precedence(pipeline: Pipeline) -> int:
        # System status is authoritative even if a factory forgot metadata.
        if getattr(pipeline, "is_bezel", False):
            return max(
                4,
                int(getattr(pipeline, "type_precedence", 0)),
            )

        return int(getattr(pipeline, "type_precedence", 0))

    def _build_pipeline_tiers(self) -> list[list[Pipeline]]:
        all_pipelines: list[Pipeline] = []

        if self.key_mapper:
            all_pipelines.extend(self.key_mapper.pipelines)

        if self.wheel_mapper and self.wheel_mapper.pipeline:
            all_pipelines.append(self.wheel_mapper.pipeline)

        if self.mouse_mapper and self.mouse_mapper.pipeline:
            all_pipelines.append(self.mouse_mapper.pipeline)

            if (
                self.fallback_mouse_pipeline is not None
                and self.output_sink is not None
            ):
                self.fallback_mouse_pipeline.reset(self.output_sink)

            self.fallback_mouse_pipeline = (
                self.mouse_mapper.get_fallback_mouse_pipeline()
            )

        if self.bezel_mapper:
            all_pipelines.extend(self.bezel_mapper.pipelines)

        # Type precedence is absolute: SystemToggle > Button > Joystick > Pointer.
        # Priority only orders pipelines within a type.
        all_pipelines.sort(
            key=lambda p: (
                -self._pipeline_precedence(p),
                -p.priority,
                -int(getattr(p, "allow_multi_claim", False)),
                getattr(
                    getattr(p, "region", None),
                    "area",
                    0.0,
                ),
                getattr(p, "creation_id", 0),
            )
        )

        tiers: list[list[Pipeline]] = []

        for pipeline in all_pipelines:
            key = (
                self._pipeline_precedence(pipeline),
                pipeline.priority,
                bool(getattr(pipeline, "allow_multi_claim", False)),
            )

            if tiers:
                first = tiers[-1][0]
                first_key = (
                    self._pipeline_precedence(first),
                    first.priority,
                    bool(getattr(first, "allow_multi_claim", False)),
                )

                if key == first_key:
                    tiers[-1].append(pipeline)
                    continue

            tiers.append([pipeline])

        return tiers

    def _mouse_flush_loop(self) -> None:
        while not self._stop_event.is_set():
            if self.output_sink:
                self.output_sink.flush_mouse_move()

                if (
                    self.touch_reader
                    and getattr(self.touch_reader, "active_touches", 1) == 0
                ):
                    self.output_sink.reset_mouse_accumulators()

            interval = 1.0 / max(
                float(self.rate_cap),
                float(ADB_RATE_CAP_MIN),
            )

            if self._stop_event.wait(interval):
                break

    def _dispatch_cursor(self, event: TouchEvent) -> None:
        if not self.output_sink:
            return

        # DOWN establishes the cursor contact and initializes the fallback
        # pipeline's ownership/origin state.
        if event.phase is TouchPhase.DOWN:
            self._cursor_down_pos = event.position
            self._cursor_drag_started = False
            self._cursor_down_time = event.timestamp

            dpi = BASELINE_DPI
            if (
                self.layout_loader is not None
                and self.layout_loader.snapshot is not None
            ):
                dpi = self.layout_loader.snapshot.dpi

            slop_px = dp_to_px(CURSOR_SLOP_DP, dpi)
            self._cursor_slop_sq = slop_px * slop_px

            self.output_sink.mouse_move_abs(
                event.position.x,
                event.position.y,
            )
            self.output_sink.mouse_down(M_LEFT)

            if self.fallback_mouse_pipeline is not None:
                self.fallback_mouse_pipeline.process(
                    event,
                    self.output_sink,
                )

            return

        # Ignore MOVE/UP events that do not belong to an active cursor contact.
        if self._cursor_down_pos is None:
            return

        # MOVE applies a radial deadzone measured from the original DOWN.
        if event.phase is TouchPhase.MOVE:
            if not self._cursor_drag_started:
                delta = event.position - self._cursor_down_pos

                # Compare squared distances to avoid calculating a square root.
                if delta.magnitude_squared < self._cursor_slop_sq:
                    return

                self._cursor_drag_started = True

            # The fallback pipeline received DOWN already, so its first
            # forwarded MOVE includes the displacement accumulated during slop.
            if self.fallback_mouse_pipeline is not None:
                self.fallback_mouse_pipeline.process(
                    event,
                    self.output_sink,
                )

        # UP releases pipeline ownership and the held mouse button.
        elif event.phase is TouchPhase.UP:
            if self.fallback_mouse_pipeline is not None:
                self.fallback_mouse_pipeline.process(
                    event,
                    self.output_sink,
                )

            # If the finger barely moved, preserve click placement at DOWN.
            if not self._cursor_drag_started:
                self.output_sink.mouse_move_abs(
                    self._cursor_down_pos.x,
                    self._cursor_down_pos.y,
                )

            self.output_sink.mouse_up(M_LEFT)

            self._cursor_down_pos = None
            self._cursor_drag_started = False
            self._cursor_slop_sq = 0

    def _dispatch_normal(self, event: TouchEvent) -> None:
        """Dispatch one event without running gesture recognition."""
        output_sink = self.output_sink
        if output_sink is None:
            return

        cid = event.contact_id
        generation = self._dispatch_generation

        # Existing contacts are routed only to pipelines that claimed DOWN.
        owners = self._contact_owners.get(cid)

        if owners:
            for pipeline in owners:
                pipeline.process(event, output_sink)

                if generation != self._dispatch_generation:
                    return

            if event.phase is TouchPhase.UP:
                self._contact_owners.pop(cid, None)

            return

        # Cursor fallback is lower than every configured pipeline.
        if self.is_visible:
            self._dispatch_cursor(event)

        if event.phase is TouchPhase.DOWN:
            for tier in self._tiers or self._build_pipeline_tiers():
                claimed: list[Pipeline] = []
                allow_multi = bool(
                    getattr(tier[0], "allow_multi_claim", False)
                )

                for pipeline in tier:
                    is_bezel = getattr(pipeline, "is_bezel", False)

                    if is_bezel and not self.bezel_toggle_enabled:
                        continue

                    if self.is_visible and not is_bezel:
                        continue

                    if not pipeline.claims(event):
                        continue

                    pipeline.process(event, output_sink)

                    if generation != self._dispatch_generation:
                        return

                    claimed.append(pipeline)

                    if not allow_multi:
                        break

                if claimed:
                    self._contact_owners[cid] = tuple(claimed)
                    return

            return

        # Unowned MOVE/UP are ignored.

    def _process_touch_event(self, touch_event: TouchEvent) -> None:
        should_shutdown = False

        with self.lock:
            if self.is_shutting_down:
                return

            if not all(
                (
                    self.mouse_mapper,
                    self.key_mapper,
                    self.wheel_mapper,
                    self.bezel_mapper,
                    self.mapper,
                    self.output_sink,
                )
            ):
                return

            self.touch_event_counter.record(touch_event)

            if self.mapper is not None:
                with self.mapper._pulse_lock:
                    self.mapper.event_count += 1

            if self.is_visible and self.two_finger_tap_enabled:
                decision = self.two_finger_tap_tracker.observe(touch_event)

                if decision.status is GestureStatus.PENDING:
                    return

                if decision.status is GestureStatus.RECOGNIZED:
                    should_shutdown = True

                elif decision.status is GestureStatus.REJECTED:
                    # Replay buffered events through normal dispatch.
                    for buffered_event in decision.replay:
                        self._dispatch_normal(buffered_event)

                    return

                else:
                    self._dispatch_normal(touch_event)
                    return

            else:
                self._dispatch_normal(touch_event)
                return

        if should_shutdown:
            shutdown_thread = threading.Thread(
                target=self._request_engine_shutdown,
                daemon=True,
                name="ShutdownThread",
            )
            shutdown_thread.start()
            shutdown_thread.join(timeout=2.0)
            return

    def start_virtual_keyboard(self) -> None:
        with self.vkb_lock:
            if (
                self.vkb_process is not None
                and self.vkb_process.is_alive()
            ):
                return

            while self.vkb_reader.poll():
                try:
                    self.vkb_reader.recv_bytes()
                except Exception:
                    break

            self.vkb_process = multiprocessing.Process(
                target=virtual_keyboard_worker,
                name="Virtual Keyboard",
                args=(self.vkb_writer,),
                daemon=True,
            )
            self.vkb_process.start()

    def close_virtual_keyboard(self) -> None:
        with self.vkb_lock:
            if self.vkb_process is not None:
                if self.vkb_process.is_alive():
                    self.vkb_process.terminate()
                    self.vkb_process.join(timeout=1.0)

                    if self.vkb_process.is_alive():
                        self.vkb_process.kill()

                self.vkb_process = None

            if self.mapper:
                self.mapper.release_vkb_keys()

    def toggle_virtual_keyboard(self) -> None:
        if (
            self.vkb_process is not None
            and self.vkb_process.is_alive()
        ):
            self.close_virtual_keyboard()
        else:
            self.start_virtual_keyboard()

    def start_headless(
        self,
        window_id: int,
        sprint_key: Optional[str] = None,
        rate_cap: Optional[float] = None,
        pps: Optional[float] = None,
        k_device_handle: int = 0,
        m_device_handle: int = 10,
    ) -> None:
        settings = store.settings.get()
        toggle_hotkeys = settings.toggle_hotkeys

        sprint_key = sprint_key or settings.sprint_key

        self.rate_cap = max(
            ADB_RATE_CAP_MIN,
            min(
                ADB_RATE_CAP_MAX,
                float(
                    rate_cap
                    or settings.adb_rate_cap
                    or DEFAULT_ADB_RATE_CAP
                ),
            ),
        )

        self.pps = max(
            PPS_ALERT_MIN,
            min(
                PPS_ALERT_MAX,
                float(
                    pps
                    or settings.pps_alert_threshold
                    or DEFAULT_PPS
                ),
            ),
        )

        if window_id is None:
            logger.warning(
                "No window ID provided. Engine will run without a target window."
            )

        logger.info(
            "Headless: %s, Window ID: %s, Rate Cap: %s, PPS: %s, "
            "Toggle Key: %s, Sprint Key: %s",
            self.headless,
            window_id,
            self.rate_cap,
            self.pps,
            toggle_hotkeys,
            sprint_key,
        )

        logger.info(
            "Typematic Enabled: %s, Delay (ms): %s, Rate (Hz): %s, Excluded: %s",
            settings.typematic_enabled,
            settings.typematic_delay_ms,
            settings.typematic_rate_hz,
            settings.typematic_excluded_keys,
        )

        logger.info(
            "Keyboard Handle: %s, Mouse Handle: %s",
            k_device_handle,
            m_device_handle,
        )

        self.two_finger_tap_enabled = settings.two_finger_tap_enabled
        self.bezel_toggle_enabled = settings.bezel_toggle_enabled

        self.dispatcher.register_callback(
            "ON_MENU_MODE_TOGGLE",
            self._apply_visibility,
        )
        self.dispatcher.register_callback(
            "ON_WORKER_RESPAWN",
            self._count_respawn,
        )

        # Instantiate TouchReader first so it can be passed to LayoutLoader.
        self.touch_reader = TouchReader(
            self.dispatcher,
            self.rate_cap,
        )

        self.layout_loader = LayoutLoader(
            self.dispatcher,
            self.touch_reader,
        )

        # Apply initial DPI to the gesture tracker.
        self.two_finger_tap_tracker.update_dpi(
            self.layout_loader.snapshot.dpi
        )

        self.mapper = Mapper(
            self.touch_reader,
            self.bridge,
            self.pps,
            window_id,
            self,
        )

        self.output_sink = BridgeOutputSink(
            bridge=self.mapper.bridge,
        )

        self.output_sink.set_viewport_callback(
            self.mapper.get_viewport_info
        )

        self.bezel_mapper = BezelMapper(
            self.mapper,
            self.output_sink,
        )
        self.mouse_mapper = MouseMapper(
            self.mapper,
            self.output_sink,
        )
        self.key_mapper = KeyMapper(
            self.mapper,
            self.output_sink,
        )
        self.wheel_mapper = WheelMapper(
            self.mapper,
            self.output_sink,
        )

        self._tiers = self._build_pipeline_tiers()

        self.bridge.start_worker_processes(
            k_device_handle,
            m_device_handle,
        )

        self._mouse_flush_thread = threading.Thread(
            target=self._mouse_flush_loop,
            daemon=True,
            name="MouseFlushThread",
        )
        self._mouse_flush_thread.start()

        self.dispatcher.register_callback(
            "ON_RELOAD",
            self._on_reload,
        )
        self.dispatcher.register_callback(
            "ON_DEVICES_CHANGE",
            self._on_devices_change,
        )

        try:
            self._publisher = TelemetryPublisher(
                self._telemetry_snapshots
            )
            self._publisher.start()
        except Exception:
            logger.exception("Telemetry publisher failed to start.")

        self.touch_reader.bind_touch_event(
            self._process_touch_event
        )

    def _start(self, config_str: Optional[str] = None) -> None:
        if config_str is not None:
            config = parse_config_arg(config_str)
            store.settings.update(
                adb_rate_cap=config["rate_cap"],
                pps_alert_threshold=config["pps"],
                sprint_key=config["sprint_key"],
            )

            self.start_headless(**config)

            if not self.headless:
                self._stop_event.wait()

            return

        window_result = select_window()
        if window_result is None:
            return

        selected_window_id, _ = window_result

        sprint_key = capture_sprint_key()
        if sprint_key is None:
            return

        performance = capture_performance_settings()
        if performance is None:
            return

        rate_cap, pps = performance
        if rate_cap is None or pps is None:
            return

        store.settings.update(
            adb_rate_cap=rate_cap,
            pps_alert_threshold=pps,
            sprint_key=sprint_key,
        )

        k_device_handle = m_device_handle = None

        if sys.platform == "win32":
            from modules.platforms.windows.query_interception_device import (
                select_keyboard_then_mouse,
            )

            result = select_keyboard_then_mouse()
            if result:
                k_device_handle, m_device_handle = result

        self.start_headless(
            window_id=selected_window_id,
            sprint_key=sprint_key,
            rate_cap=rate_cap,
            pps=pps,
            k_device_handle=(
                k_device_handle
                if k_device_handle is not None
                else 0
            ),
            m_device_handle=(
                m_device_handle
                if m_device_handle is not None
                else 10
            ),
        )

        if not self.headless:
            self._stop_event.wait()

    def _shutdown(self) -> None:
        with self.lock:
            if self.is_shutting_down:
                return

            self.is_shutting_down = True
            self._stop_event.set()
            self._release_active_inputs()

        logger.info("Engine shutting down...")

        if not self.headless:
            try:
                import keyboard

                keyboard.unhook_all_hotkeys()
            except Exception:
                logger.exception(
                    "Failed to unhook keyboard hotkeys",
                    exc_info=True,
                )

        try:
            if self._publisher is not None:
                self._publisher.stop()

            thread = self._mouse_flush_thread

            if (
                thread is not None
                and thread.is_alive()
                and threading.current_thread() is not thread
            ):
                thread.join(timeout=2.0)

                if thread.is_alive():
                    logger.warning(
                        "Mouse flush thread did not stop within timeout"
                    )

            self.close_virtual_keyboard()

            if self.touch_reader is not None:
                self.touch_reader.stop()

            if self.mapper is not None:
                self.mapper.stop()

            if self.bridge is not None:
                self.bridge.shutdown()

            try:
                self.vkb_reader.close()
                self.vkb_writer.close()
            except Exception:
                pass

            self.dispatcher.unregister_all()

        except Exception as exc:
            logger.exception(
                "Exception during engine teardown: %s",
                exc,
                exc_info=True,
            )

        finally:
            self.touch_event_counter.reset()
            store.close()

    def _request_engine_shutdown(self):
        if (
            self.conn is not None
            and isinstance(
                self.dispatcher,
                IpcMapperEventDispatcher,
            )
        ):
            shutdown_engine_process(
                self,
                self.dispatcher,
                self.conn,
            )
        else:
            self._shutdown()

    def _count_respawn(self, worker_type: Optional[str] = None) -> None:
        if worker_type:
            self._respawns[worker_type] = (
                self._respawns.get(worker_type, 0) + 1
            )

    def _telemetry_snapshots(self) -> dict[str, Any]:
        mapper = self.mapper

        if mapper is not None:
            mapper._pulse_status()

        touch_reader = self.touch_reader

        if touch_reader is not None:
            dev_w, dev_h = touch_reader.get_oriented_dimensions()
            rotation = touch_reader.get_rotation()
        else:
            dev_w, dev_h, rotation = 1920, 1080, 0

        def alive_pid(proc) -> Optional[int]:
            try:
                return (
                    proc.pid
                    if proc is not None and proc.is_alive()
                    else None
                )
            except (ValueError, OSError):
                return None

        bridge = self.bridge

        return {
            "rate_cap_hz": self.rate_cap,
            "pps_threshold": self.pps,
            "rate_hz": getattr(mapper, "last_rate", None),
            "rate_status": getattr(mapper, "last_status", None),
            "menu_mode": self.is_visible,
            "window_lost": getattr(mapper, "window_lost", None),
            "downs": self.touch_event_counter.event_count_down,
            "moves": self.touch_event_counter.event_count_move,
            "ups": self.touch_event_counter.event_count_up,
            "all": self.touch_event_counter.event_count,
            "device_width": dev_w,
            "device_height": dev_h,
            "device_rotation": rotation,
            "workers": {
                "keyboard": alive_pid(
                    getattr(bridge, "k_proc", None)
                ),
                "mouse": alive_pid(
                    getattr(bridge, "m_proc", None)
                ),
                "vkb": alive_pid(self.vkb_process),
                "visualizer": _read_visualizer(),
            },
            "respawns": dict(self._respawns),
        }


def _read_visualizer() -> Optional[int]:
    proc = read_process(VISUALIZER_RUNTIME_FILE)
    return proc.pid if proc is not None else None


def run_engine_process(
    conn: Connection,
    log_queue: Queue,
) -> None:
    AppLogManager.setup_logging(
        log_prefix="engine",
        log_queue=log_queue,
        console="auto",
    )

    dispatcher = IpcMapperEventDispatcher(conn)
    engine: Optional[Engine] = None

    try:
        start_payload = conn.recv_bytes()

        if not start_payload or start_payload[0] != IPC_CMD_START:
            got = start_payload[0] if start_payload else None
            dispatcher.send_error(
                f"Expected IPC_CMD_START, got {got!r}"
            )
            return

        config = unpack_ipc_start_cmd(start_payload)

        engine = Engine(
            headless=True,
            dispatcher=dispatcher,
            conn=conn,
        )

        engine.start_headless(**config)
        dispatcher.send_started()

    except KeyboardInterrupt:
        logger.info(
            "Engine received shutdown signal, exiting cleanly."
        )
        shutdown_engine_process(
            engine,
            dispatcher,
            conn,
        )
        return

    except Exception as exc:
        logger.error(
            "[ENGINE PROCESS] Startup failure: %s",
            exc,
            exc_info=True,
        )
        dispatcher.send_error(str(exc))
        shutdown_engine_process(
            engine,
            dispatcher,
            conn,
        )
        return

    dispatcher.run_command_loop()
    shutdown_engine_process(
        engine,
        dispatcher,
        conn,
    )


def shutdown_engine_process(
    engine: Optional[Engine],
    dispatcher: IpcMapperEventDispatcher,
    conn: Connection,
) -> None:
    try:
        if engine is not None:
            engine._shutdown()

    except Exception as exc:
        logger.error(
            "[ENGINE PROCESS] Shutdown failure: %s",
            exc,
            exc_info=True,
        )
        dispatcher.send_error(str(exc))

    finally:
        try:
            dispatcher.send_stopped()
        except OSError as exc:
            logger.error(
                "[ENGINE PROCESS] Connection closed: %s",
                exc,
                exc_info=True,
            )


def parse_config_arg(config_str: str) -> dict:
    """Parse comma-separated settings and clamp performance values."""
    settings = store.settings.get()
    parts = [
        part.strip()
        for part in config_str.split(",")
    ]

    while len(parts) < 6:
        parts.append("")

    def parse_value(value, target_type, default):
        if not value:
            return default

        try:
            return target_type(value)
        except (ValueError, TypeError):
            return default

    window_id = parse_value(parts[0], int, None)
    sprint_key = parse_value(
        parts[1],
        str,
        settings.sprint_key or "",
    )

    raw_rate = parse_value(
        parts[2],
        float,
        settings.adb_rate_cap or DEFAULT_ADB_RATE_CAP,
    )
    rate_cap = clamp(
        raw_rate,
        ADB_RATE_CAP_MIN,
        ADB_RATE_CAP_MAX,
    )

    raw_pps = parse_value(
        parts[3],
        float,
        settings.pps_alert_threshold or DEFAULT_PPS,
    )
    pps = clamp(
        raw_pps,
        PPS_ALERT_MIN,
        PPS_ALERT_MAX,
    )

    k_device_handle = parse_value(parts[4], int, 0)
    m_device_handle = parse_value(parts[5], int, 10)

    logger.info(
        "Parsed config: window_id=%s, sprint_key=%s, rate_cap=%.1f, "
        "pps=%.1f, k_device_handle=%s, m_device_handle=%s",
        window_id,
        sprint_key,
        rate_cap,
        pps,
        k_device_handle,
        m_device_handle,
    )

    return {
        "window_id": window_id,
        "sprint_key": sprint_key,
        "rate_cap": rate_cap,
        "pps": pps,
        "k_device_handle": k_device_handle,
        "m_device_handle": m_device_handle,
    }
