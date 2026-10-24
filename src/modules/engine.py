from __future__ import annotations

import logging
import multiprocessing
import os
import sys
import threading
import time
from typing import TYPE_CHECKING, Any

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
from modules.cli.key_capture import capture_keys, capture_performance_settings
from modules.database import store
from modules.gui.overlays import virtual_keyboard_worker
from modules.log_manager import AppLogManager
from modules.platforms import get_platform
from modules.scripts.list_windows import select_window
from modules.utils import (
    ADB_RATE_CAP_MAX,
    ADB_RATE_CAP_MIN,
    DEFAULT_ADB_RATE_CAP,
    DEFAULT_PPS,
    IPC_CMD_START,
    PPS_ALERT_MAX,
    PPS_ALERT_MIN,
    READ_ATTEMPTS,
    VISUALIZER_RUNTIME_FILE,
    CurveType,
    IpcMapperEventDispatcher,
    InputCurve,
    MapperEvent,
    MapperEventDispatcher,
    TouchEvent,
    TouchEventCount,
    TouchPhase,
    clamp,
    unpack_ipc_start_cmd,
)
from modules.runtime_info import TelemetryPublisher

logger = logging.getLogger("modules.engine")

if TYPE_CHECKING:
    from multiprocessing.connection import Connection
    from multiprocessing.queues import Queue

_HOTKEY_POLL_INTERVAL = 0.005  # 5 ms key-state polling
_ADJUST_COMMIT_INTERVAL = 0.25  # coalesce DB write + reload while held
_ONESHOT_COOLDOWN = 0.35  # F5 / F6 cooldown


class Engine:
    def __init__(
        self,
        headless: bool = False,
        dispatcher: MapperEventDispatcher | None = None,
    ):
        platform_mod = get_platform()
        self.headless = headless
        self.system_config = platform_mod.SystemConfig()
        self.system_config.set_high_priority(os.getpid(), "Main")
        self.system_config.set_dpi_awareness()
        self.system_config.set_timer_resolution()

        self.window_manager = platform_mod.WindowManager()
        self.foreground_window = self.window_manager.get_foreground_window()
        self.bridge = platform_mod.Bridge(self.window_manager, self.system_config)

        self.touch_event_counter = TouchEventCount()
        self._publisher: TelemetryPublisher | None = None
        self._respawns: dict[str, int] = {"keyboard": 0, "mouse": 0}

        self.touch_reader: TouchReader | None = None
        self.layout_loader: LayoutLoader | None = None
        self.mapper: Mapper | None = None
        self.output_sink: BridgeOutputSink | None = None
        self.bezel_mapper: BezelMapper | None = None
        self.mouse_mapper: MouseMapper | None = None
        self.key_mapper: KeyMapper | None = None
        self.wheel_mapper: WheelMapper | None = None

        self._tiers: list[list[Pipeline]] = []
        # Ownership is fixed at DOWN; MOVE/UP never get offered to a new tier.
        self._contact_owners: dict[int, tuple[Pipeline, ...]] = {}
        self._cursor_contacts: set[int] = set()
        self._dispatch_generation = 0

        self.is_visible = False
        self.lock = threading.RLock()
        self.is_shutting_down = False
        self._stop_event = threading.Event()
        self.mapper_event_dispatcher = dispatcher or MapperEventDispatcher()
        self.two_finger_tap_tracker = TwoFingerTapTracker()

        self.vkb_reader, self.vkb_writer = multiprocessing.Pipe(duplex=False)
        self.vkb_process: multiprocessing.Process | None = None

        self.two_finger_tap_enabled = True
        self.bezel_toggle_enabled = True
        self._mouse_flush_thread: threading.Thread | None = None

        # --- CLI hotkey state ---
        self.rate_cap: float = ADB_RATE_CAP_MIN
        self.pps: float = PPS_ALERT_MIN
        self._adjust_lock = threading.Lock()
        self._settings_dirty = False
        self._last_commit_time = 0.0
        self._live_shown = False
        self._live_active = False
        self._live_text = ""

        # One-shot (non-typematic) keys: shared 350 ms cooldown.
        self._last_hotkey_time = 0.0
        self._hotkey_cooldown = _ONESHOT_COOLDOWN
        self._oneshot_prev: dict[str, bool] = {"f5": False, "f6": False}
        self._oneshot_actions = {
            "f5": self._toggle_handedness_cli,
            "f6": self._reload_cli,
        }

        # Typematic keys: one cubic InputCurve per key.
        self._adjust_curves: dict[str, InputCurve] = {
            key: InputCurve(CurveType.CUBIC) for key in ("left", "right", "down", "up")
        }
        self._adjust_actions = {
            "left": lambda: self._adjust_rate_cap_cli(-10.0),
            "right": lambda: self._adjust_rate_cap_cli(10.0),
            "down": lambda: self._adjust_pps_cli(-5.0),
            "up": lambda: self._adjust_pps_cli(5.0),
        }

        self._terminal_window_handle = None
        self._hotkey_thread: threading.Thread | None = None

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
                    "[F6] Reload | [Left/Right] Rate Cap (-/+ 10) | [Down/Up] PPS (-/+ 5)"
                )
            except Exception as exc:
                logger.debug(
                    "Failed to register CLI global hotkeys: %s", exc, exc_info=True
                )
        else:
            logger.info(
                "[Headless / GUI Worker Launch] Background engine active (terminal hotkeys bypassed)."
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
                "Foreground verification failed for hotkey: %s", exc, exc_info=True
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

        # Opposing keys on the same axis cancel: treat both as released so
        # their curves reset instead of drifting.
        for a, b in (("left", "right"), ("down", "up")):
            if pressed[a] and pressed[b]:
                pressed[a] = pressed[b] = False

        # Typematic: cubic curve drives repeat timing (OS auto-repeat ignored).
        for key, curve in self._adjust_curves.items():
            if curve.check_input(now, pressed[key]):
                if self._adjust_actions[key]():
                    self._settings_dirty = True

        # Live status line: only after a key has been held past the curve's
        # initial delay (taps never enter live mode), until all keys release.
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
            if text != self._live_text:  # redraw only on change
                self._live_text = text
                AppLogManager.live_line(text)
        elif not adjusting and self._live_active:
            self._live_active = False
            AppLogManager.end_live_line()
            AppLogManager.resume_console()  # replays held logs

        # Non-typematic: act on rising edge only, 350 ms cooldown.
        for key, action in self._oneshot_actions.items():
            down = pressed[key]
            if down and not self._oneshot_prev[key]:
                action()
            self._oneshot_prev[key] = down

        # Coalesced persistence for rate/PPS (trailing, also fires after release).
        if (
            self._settings_dirty
            and now - self._last_commit_time >= _ADJUST_COMMIT_INTERVAL
        ):
            self._commit_adjustments(now)

    def _check_debounce(self) -> bool:
        """350 ms cooldown for one-shot hotkeys (F5 / F6)."""
        now = time.perf_counter()
        if now - self._last_hotkey_time < self._hotkey_cooldown:
            return False
        self._last_hotkey_time = now
        return True

    # ------------------------------------------------------------------
    # Typematic: rate cap / PPS (in-memory per tick, persisted coalesced)
    # ------------------------------------------------------------------
    def _adjust_rate_cap_cli(self, delta: float) -> bool:
        with self._adjust_lock:
            new_rate = clamp(self.rate_cap + delta, ADB_RATE_CAP_MIN, ADB_RATE_CAP_MAX)
            if new_rate == self.rate_cap:
                return False

            self.rate_cap = new_rate
            if self.touch_reader is not None:
                self.touch_reader.set_rate_cap(new_rate)
            return True

    def _adjust_pps_cli(self, delta: float) -> bool:
        with self._adjust_lock:
            new_pps = clamp(self.pps + delta, PPS_ALERT_MIN, PPS_ALERT_MAX)
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
            store.settings.update(adb_rate_cap=rate, pps_alert_threshold=pps)
        except Exception as exc:
            logger.error("Failed to commit rate/PPS update to DB: %s", exc)
            self._settings_dirty = True  # retry after next interval
            return
        if self._live_shown:
            logger.debug("Committed rate cap %.1f Hz, PPS %.1f.", rate, pps)
            if not self._live_active:  # final commit after release
                self._live_shown = False
        else:
            logger.info("Rate Cap %.1f Hz | PPS %.1f\n", rate, pps)
        self.mapper_event_dispatcher.dispatch(
            MapperEvent(action="ON_RELOAD", cooldown=1.0)
        )

    # ------------------------------------------------------------------
    # One-shot: handedness / reload (350 ms, non-typematic)
    # ------------------------------------------------------------------
    def _toggle_handedness_cli(self) -> None:
        if not self._check_debounce():
            return
        try:
            settings = store.settings.get()
            new_val = not settings.left_handed
            store.settings.update(left_handed=new_val)
            logger.info(
                "CLI Triggered [F5]: Left-Handed mode set to %s, reload event dispatched.",
                new_val,
            )
            self.mapper_event_dispatcher.dispatch(MapperEvent(action="ON_RELOAD"))
        except Exception as exc:
            logger.error(
                "Failed to toggle handedness via hotkey: %s", exc, exc_info=True
            )

    def _reload_cli(self) -> None:
        if not self._check_debounce():
            return
        self.mapper_event_dispatcher.dispatch(MapperEvent(action="ON_RELOAD"))
        logger.info("CLI Triggered [F6]: Reload event dispatched.")

    def _on_devices_change(
        self,
        k_id: int | None = None,
        m_id: int | None = None,
        *,
        keyboard_device_id: int | None = None,
        mouse_device_id: int | None = None,
    ) -> None:
        if not self.bridge or self.bridge.k_proc is None:
            return
        self.bridge.reload_devices(
            keyboard_device_id if keyboard_device_id is not None else k_id,
            mouse_device_id if mouse_device_id is not None else m_id,
        )

    def _release_active_inputs(self) -> None:
        """Clear pipeline ownership and release held outputs once on a state boundary."""
        self._dispatch_generation += 1
        self._contact_owners.clear()
        self._cursor_contacts.clear()
        self.two_finger_tap_tracker.reset()

        if self.output_sink:
            for tier in self._tiers:
                for pipeline in tier:
                    try:
                        pipeline.reset(self.output_sink)
                    except Exception:
                        logger.exception(
                            "Failed to reset pipeline during state transition"
                        )

            if self.bezel_mapper:
                self.bezel_mapper.release_all()
            if self.key_mapper:
                self.key_mapper.release_all()
            if self.wheel_mapper:
                self.wheel_mapper.touch_up()
            if self.mouse_mapper:
                self.mouse_mapper.touch_up()

    def toggle_mode(self) -> None:
        with self.lock:
            new_state = not self.is_visible
        self._apply_visibility(new_state)
        self.mapper_event_dispatcher.dispatch(
            MapperEvent(action="ON_MENU_MODE_TOGGLE", is_visible=new_state)
        )

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
            logger.debug("Bridge health check failed during mode switch", exc_info=True)

    def _on_reload(self) -> None:
        settings = store.settings.get()
        self.two_finger_tap_enabled = settings.two_finger_tap_enabled
        self.bezel_toggle_enabled = settings.bezel_toggle_enabled

        with self._adjust_lock:
            # Uncommitted hotkey steps are newer than the DB; keep them.
            if not self._settings_dirty:
                self.rate_cap = settings.adb_rate_cap or DEFAULT_ADB_RATE_CAP
                self.pps = settings.pps_alert_threshold or DEFAULT_PPS

        if self.touch_reader is not None:
            self.touch_reader.set_rate_cap(rate)

        with self.lock:
            self._release_active_inputs()
            self._tiers = self._build_pipeline_tiers()
        logger.info(
            "Engine reloaded: Rate Cap=%.1f Hz, PPS Threshold=%.1f PPS",
            self.rate_cap,
            self.pps,
        )

    @staticmethod
    def _pipeline_precedence(pipeline: Pipeline) -> int:
        # System status is authoritative even if a factory forgot to set its
        # explicit type_precedence metadata.
        if getattr(pipeline, "is_system", False):
            return max(4, int(getattr(pipeline, "type_precedence", 0)))
        return int(getattr(pipeline, "type_precedence", 0))

    def _build_pipeline_tiers(self) -> list[list[Pipeline]]:
        all_pipelines: list[Pipeline] = []
        if self.key_mapper:
            all_pipelines.extend(self.key_mapper.pipelines)
        if self.wheel_mapper and self.wheel_mapper.pipeline:
            all_pipelines.append(self.wheel_mapper.pipeline)
        if self.mouse_mapper and self.mouse_mapper.pipeline:
            all_pipelines.append(self.mouse_mapper.pipeline)
        if self.bezel_mapper:
            all_pipelines.extend(self.bezel_mapper.pipelines)

        # Type precedence is absolute: SystemToggle > Button > Joystick > Pointer.
        # Priority only orders pipelines within a type.
        all_pipelines.sort(
            key=lambda p: (
                -self._pipeline_precedence(p),
                -p.priority,
                -int(getattr(p, "allow_multi_claim", False)),
                getattr(getattr(p, "region", None), "area", 0.0),
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
            interval = 1.0 / max(float(self.rate_cap), float(ADB_RATE_CAP_MIN))
            if self._stop_event.wait(interval):
                break

    def _dispatch_cursor(self, event: TouchEvent) -> None:
        if not self.mapper:
            return
        gx, gy = self.mapper.device_to_game_abs(event.position.x, event.position.y)
        if event.phase is TouchPhase.DOWN:
            self._cursor_contacts.add(event.contact_id)
            self.mapper.bridge.mouse_move_abs(int(round(gx)), int(round(gy)))
            self.mapper.bridge.left_click_down()
        elif event.phase is TouchPhase.MOVE:
            self.mapper.bridge.mouse_move_abs(int(round(gx)), int(round(gy)))
        elif event.phase is TouchPhase.UP:
            self.mapper.bridge.left_click_up()
            self._cursor_contacts.discard(event.contact_id)

    def _dispatch_normal(self, event: TouchEvent) -> None:
        """Dispatch one event without running gesture recognition."""
        output_sink = self.output_sink
        if output_sink is None:
            return

        cid = event.contact_id
        generation = self._dispatch_generation

        # Existing contacts are routed only to the pipelines that claimed DOWN.
        owners = self._contact_owners.get(cid)
        if owners:
            for pipeline in owners:
                pipeline.process(event, output_sink)
                if generation != self._dispatch_generation:
                    return

            if event.phase is TouchPhase.UP:
                self._contact_owners.pop(cid, None)
            return

        # A cursor contact owns its entire lifecycle once the fallback claims DOWN.
        if cid in self._cursor_contacts:
            self._dispatch_cursor(event)
            return

        if event.phase is TouchPhase.DOWN:
            for tier in self._tiers or self._build_pipeline_tiers():
                claimed: list[Pipeline] = []
                allow_multi = bool(getattr(tier[0], "allow_multi_claim", False))

                for pipeline in tier:
                    if (
                        getattr(pipeline, "is_system", False)
                        and not self.bezel_toggle_enabled
                    ):
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

            # Cursor fallback is lower than every configured pipeline.
            if self.is_visible and cid == 0:
                self._dispatch_cursor(event)
            return

        # Unowned MOVE/UP are ignored.

    def _process_touch_event(self, touch_event: TouchEvent) -> None:
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
            self.mapper.event_count += 1

        if self.is_visible and self.two_finger_tap_enabled:
            decision = self.two_finger_tap_tracker.observe(touch_event)
            if decision.status is GestureStatus.RECOGNIZED:
                self.toggle_mode()
                return
            if decision.status is GestureStatus.PENDING:
                return
            if decision.status is GestureStatus.REJECTED:
                # Replay once through normal dispatch, bypassing gesture tracking.
                for buffered_event in decision.replay:
                    self._dispatch_normal(buffered_event)
                return

        self._dispatch_normal(touch_event)

    def start_virtual_keyboard(self) -> None:
        with self.lock:
            if self.vkb_process is not None and self.vkb_process.is_alive():
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
        with self.lock:
            if self.vkb_process is not None:
                if self.vkb_process.is_alive():
                    self.vkb_process.terminate()
                    self.vkb_process.join(timeout=1.0)
                    if self.vkb_process.is_alive():
                        self.vkb_process.kill()
                self.vkb_process = None

    def toggle_virtual_keyboard(self) -> None:
        if self.vkb_process is not None and self.vkb_process.is_alive():
            self.close_virtual_keyboard()
        else:
            self.start_virtual_keyboard()

    def start_headless(
        self,
        window_id: int | None,
        toggle_key: str | None = None,
        sprint_key: str | None = None,
        rate_cap: float | None = None,
        pps: float | None = None,
        k_device_handle: int = 0,
        m_device_handle: int = 10,
        **kwargs: Any,
    ) -> None:
        settings = store.settings.get()
        toggle_key = toggle_key or settings.toggle_key
        sprint_key = sprint_key or settings.sprint_key
        self.rate_cap = max(
            ADB_RATE_CAP_MIN,
            min(
                ADB_RATE_CAP_MAX,
                float(rate_cap or settings.adb_rate_cap or DEFAULT_ADB_RATE_CAP),
            ),
        )
        self.pps = max(
            PPS_ALERT_MIN,
            min(
                PPS_ALERT_MAX, float(pps or settings.pps_alert_threshold or DEFAULT_PPS)
            ),
        )

        if window_id is None:
            logger.warning(
                "No window ID provided. Engine will run without a target window."
            )
        logger.info(
            "Headless: %s, Window ID: %s, Rate Cap: %s, PPS: %s, Toggle Key: %s, Sprint Key: %s",
            self.headless,
            window_id,
            self.rate_cap,
            self.pps,
            toggle_key,
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
            "Keyboard Handle: %s, Mouse Handle: %s", k_device_handle, m_device_handle
        )

        self.two_finger_tap_enabled = settings.two_finger_tap_enabled
        self.bezel_toggle_enabled = settings.bezel_toggle_enabled
        self.layout_loader = LayoutLoader(
            self.mapper_event_dispatcher,
            foreground_window=self.foreground_window,
            toggle_mode_callback=self.toggle_mode,
        )
        self.touch_reader = TouchReader(self.mapper_event_dispatcher, self.rate_cap)
        self.mapper = Mapper(
            self.layout_loader,
            self.touch_reader,
            self.bridge,
            self.pps,
            {"toggle_key": toggle_key, "sprint_key": sprint_key},
            window_id,
            self,
        )
        self.output_sink = BridgeOutputSink(
            bridge=self.mapper.bridge,
            toggle_mode=self.toggle_mode,
            toggle_vkb=self.toggle_virtual_keyboard,
        )
        self.bezel_mapper = BezelMapper(self.mapper, self.output_sink)
        self.mouse_mapper = MouseMapper(self.mapper, self.output_sink)
        self.key_mapper = KeyMapper(self.mapper, self.output_sink)
        self.wheel_mapper = WheelMapper(self.mapper, self.output_sink)
        self._tiers = self._build_pipeline_tiers()

        self.touch_reader.bind_touch_event(self._process_touch_event)
        self.mapper_event_dispatcher.register_callback(
            "ON_MENU_MODE_TOGGLE", self._apply_visibility
        )
        self.mapper_event_dispatcher.register_callback("ON_RELOAD", self._on_reload)
        self.mapper_event_dispatcher.register_callback(
            "ON_DEVICES_CHANGE", self._on_devices_change
        )
        self.mapper_event_dispatcher.register_callback(
            "ON_WORKER_RESPAWN", self._count_respawn
        )

        self.bridge.start_worker_processes(k_device_handle, m_device_handle)
        self._mouse_flush_thread = threading.Thread(
            target=self._mouse_flush_loop, daemon=True, name="MouseFlushThread"
        )
        self._mouse_flush_thread.start()

        try:
            self._publisher = TelemetryPublisher(self._telemetry_snapshots)
            self._publisher.start()
        except Exception:
            logger.exception("Telemetry publisher failed to start.")

    def _start(self, config_str: str | None = None) -> None:
        if config_str is not None:
            config = parse_config_arg(config_str)
            store.settings.update(
                adb_rate_cap=config["rate_cap"],
                pps_alert_threshold=config["pps"],
                toggle_key=config["toggle_key"],
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
        captured_keys = capture_keys()
        if captured_keys is None:
            return
        toggle_key, sprint_key = captured_keys
        performance = capture_performance_settings()
        if performance is None:
            return
        rate_cap, pps = performance
        if rate_cap is None or pps is None:
            return
        store.settings.update(
            adb_rate_cap=rate_cap,
            pps_alert_threshold=pps,
            toggle_key=toggle_key,
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
            toggle_key=toggle_key,
            sprint_key=sprint_key,
            rate_cap=rate_cap,
            pps=pps,
            k_device_handle=k_device_handle if k_device_handle is not None else 0,
            m_device_handle=m_device_handle if m_device_handle is not None else 10,
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
                logger.exception("Failed to unhook keyboard hotkeys", exc_info=True)

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
                    logger.warning("Mouse flush thread did not stop within timeout")
            if self.touch_reader is not None:
                self.touch_reader.stop()
            if self.mapper is not None:
                self.mapper.stop()
            if self.bridge is not None:
                self.bridge.shutdown()
            self.close_virtual_keyboard()
            try:
                self.vkb_reader.close()
                self.vkb_writer.close()
            except Exception:
                pass
            self.mapper_event_dispatcher.unregister_all()
        except Exception as exc:
            logger.exception("Exception during engine teardown: %s", exc, exc_info=True)
        finally:
            self.touch_event_counter.reset()
            store.close()

    def _count_respawn(self, worker_type: str | None = None) -> None:
        if worker_type:
            self._respawns[worker_type] = self._respawns.get(worker_type, 0) + 1

    def _telemetry_snapshots(self) -> dict[str, Any]:
        mapper = self.mapper
        if mapper is not None:
            mapper._pulse_status()  # keep the rate fresh when window tracking is idle

        def alive_pid(proc) -> int | None:
            try:
                return proc.pid if proc is not None and proc.is_alive() else None
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
            "workers": {
                "keyboard": alive_pid(getattr(bridge, "k_proc", None)),
                "mouse": alive_pid(getattr(bridge, "m_proc", None)),
                "vkb": alive_pid(self.vkb_process),
                "visualizer": _read_visualizer(),
            },
            "respawns": dict(self._respawns),
        }


def _read_visualizer() -> int | None:
    for _ in range(READ_ATTEMPTS):
        try:
            data = VISUALIZER_RUNTIME_FILE.read_text(encoding="utf-8")
            return int(data) if data.isnumeric() and int(data) > 0 else None
        except FileNotFoundError:
            return None
        except (OSError, ValueError):
            time.sleep(0.01)  # writer is mid-replace; retry
    return None


def run_engine_process(conn: Connection, log_queue: Queue) -> None:
    AppLogManager.setup_logging(is_gui=True, log_prefix="engine", log_queue=log_queue)
    dispatcher = IpcMapperEventDispatcher(conn)
    engine: Engine | None = None
    try:
        start_payload = conn.recv_bytes()
        if not start_payload or start_payload[0] != IPC_CMD_START:
            got = start_payload[0] if start_payload else None
            dispatcher.send_error(f"Expected IPC_CMD_START, got {got!r}")
            return
        config = unpack_ipc_start_cmd(start_payload)
        engine = Engine(headless=True, dispatcher=dispatcher)
        engine.start_headless(**config)
        dispatcher.send_started()
    except KeyboardInterrupt:
        logger.info("Engine received shutdown signal, exiting cleanly.")
        shutdown_engine_process(engine, dispatcher, conn)
    except Exception as exc:
        logger.error("[ENGINE PROCESS] Startup failure: %s", exc, exc_info=True)
        dispatcher.send_error(str(exc))
        shutdown_engine_process(engine, dispatcher, conn)
    dispatcher.run_command_loop()
    shutdown_engine_process(engine, dispatcher, conn)


def shutdown_engine_process(
    engine: Engine | None, dispatcher: IpcMapperEventDispatcher, conn: Connection
) -> None:
    try:
        if engine is not None:
            engine._shutdown()
    except Exception as exc:
        logger.error("[ENGINE PROCESS] Shutdown failure: %s", exc, exc_info=True)
        dispatcher.send_error(str(exc))
    finally:
        dispatcher.send_stopped()
        try:
            conn.close()
        except OSError:
            pass


def parse_config_arg(config_str: str) -> dict:
    """Parse comma-separated settings and clamp performance values."""
    settings = store.settings.get()
    parts = [part.strip() for part in config_str.split(",")]
    while len(parts) < 7:
        parts.append("")

    def parse_value(value, target_type, default):
        if not value:
            return default
        try:
            return target_type(value)
        except (ValueError, TypeError):
            return default

    window_id = parse_value(parts[0], int, None)
    toggle_key = parse_value(parts[1], str, settings.toggle_key or "")
    sprint_key = parse_value(parts[2], str, settings.sprint_key or "")
    raw_rate = parse_value(
        parts[3], float, settings.adb_rate_cap or DEFAULT_ADB_RATE_CAP
    )
    rate_cap = clamp(raw_rate, ADB_RATE_CAP_MIN, ADB_RATE_CAP_MAX)
    raw_pps = parse_value(parts[4], float, settings.pps_alert_threshold or DEFAULT_PPS)
    pps = clamp(raw_pps, PPS_ALERT_MIN, PPS_ALERT_MAX)
    k_device_handle = parse_value(parts[5], int, 0)
    m_device_handle = parse_value(parts[6], int, 10)
    logger.info(
        "Parsed config: window_id=%s, toggle_key=%s, sprint_key=%s, rate_cap=%.1f, pps=%.1f, k_device_handle=%s, m_device_handle=%s",
        window_id,
        toggle_key,
        sprint_key,
        rate_cap,
        pps,
        k_device_handle,
        m_device_handle,
    )
    return {
        "window_id": window_id,
        "toggle_key": toggle_key,
        "sprint_key": sprint_key,
        "rate_cap": rate_cap,
        "pps": pps,
        "k_device_handle": k_device_handle,
        "m_device_handle": m_device_handle,
    }
