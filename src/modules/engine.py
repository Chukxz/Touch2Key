from __future__ import annotations

import logging
import multiprocessing
import os
import sys
import threading
import time
from typing import TYPE_CHECKING

from modules import (
    BezelMapper,
    BridgeOutputSink,
    KeyMapper,
    LayoutLoader,
    Mapper,
    MouseMapper,
    Pipeline,
    TouchReader,
    TwoFingerTapTracker,
    WASDMapper,
)
from modules.cli.key_capture import capture_keys, capture_performance_settings
from modules.database import store
from modules.gui.overlays import virtual_keyboard_worker
from modules.log_manager import AppLogManager
from modules.platforms import get_platform
from modules.scripts.list_windows import select_window
from modules.utils import (
    DEFAULT_ADB_RATE_CAP,
    DEFAULT_PPS,
    IPC_CMD_START,
    IpcMapperEventDispatcher,
    MapperEvent,
    MapperEventDispatcher,
    TouchEvent,
    TouchPhase,
    unpack_ipc_start_cmd,
)

logger = logging.getLogger("modules.engine")

# ==========================================
# Performance Threshold Bounds
# ==========================================
RATE_CAP_MIN: float = 30.0
RATE_CAP_MAX: float = 1000.0
PPS_MIN: float = 10.0
PPS_MAX: float = 500.0


if TYPE_CHECKING:
    from multiprocessing.connection import Connection
    from multiprocessing.queues import Queue


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
        self.bridge_class = platform_mod.Bridge(self.window_manager, self.system_config)

        self.touch_reader: TouchReader | None = None
        self.layout_loader: LayoutLoader | None = None
        self.mapper: Mapper | None = None
        self.output_sink: BridgeOutputSink | None = None
        self.bezel_mapper: BezelMapper | None = None
        self.mouse_mapper: MouseMapper | None = None
        self.key_mapper: KeyMapper | None = None
        self.wasd_mapper: WASDMapper | None = None
        self._tiers: list[list[Pipeline]] = []

        self.is_visible = False
        self.lock = threading.Lock()
        self.is_shutting_down = False
        self._stop_event = threading.Event()
        self.mapper_event_dispatcher = dispatcher or MapperEventDispatcher()
        self.two_finger_tap_tracker = TwoFingerTapTracker()

        self.vkb_reader, self.vkb_writer = multiprocessing.Pipe()
        self.vkb_process: multiprocessing.Process | None = None

        self.double_tap_enabled = True
        self.bezel_toggle_enabled = True

        # Dynamic performance parameters
        self.rate_cap: float = RATE_CAP_MIN
        self.pps: float = PPS_MIN

        # Debounce tracking for hotkeys
        self._last_hotkey_time = 0.0
        self._hotkey_cooldown = 0.35

        # Terminal-specific global hotkey bindings
        if not self.headless:
            try:
                import keyboard

                self._terminal_window_handle = (
                    self.window_manager.get_foreground_window()
                )

                def _guard_hotkey(callback):
                    """Restricts hotkey triggers exclusively to active terminal focus."""
                    try:
                        current_fg = self.window_manager.get_foreground_window()
                        if current_fg == self._terminal_window_handle:
                            callback()
                    except Exception as exc:
                        logger.debug(
                            "Foreground verification failed for hotkey: %s",
                            exc,
                            exc_info=True,
                        )

                keyboard.add_hotkey("esc", lambda: _guard_hotkey(self._shutdown))
                keyboard.add_hotkey(
                    "f5", lambda: _guard_hotkey(self._toggle_handedness_cli)
                )
                keyboard.add_hotkey(
                    "f6", lambda: _guard_hotkey(self._reload_layout_cli)
                )
                keyboard.add_hotkey(
                    "f7", lambda: _guard_hotkey(self._reload_config_cli)
                )

                # Arrow key hotkeys for dynamic performance threshold tuning
                keyboard.add_hotkey(
                    "left",
                    lambda: _guard_hotkey(lambda: self._adjust_rate_cap_cli(-10.0)),
                    suppress=False,
                )
                keyboard.add_hotkey(
                    "right",
                    lambda: _guard_hotkey(lambda: self._adjust_rate_cap_cli(10.0)),
                    suppress=False,
                )
                keyboard.add_hotkey(
                    "down",
                    lambda: _guard_hotkey(lambda: self._adjust_pps_cli(-5.0)),
                    suppress=False,
                )
                keyboard.add_hotkey(
                    "up",
                    lambda: _guard_hotkey(lambda: self._adjust_pps_cli(5.0)),
                    suppress=False,
                )

                logger.info(
                    "[CLI Interactive Launch] Active Hotkeys: [Esc] Exit | [F5] Handedness | "
                    "[F6] Reload Layout | [F7] Reload Config | [Left/Right] Rate Cap (-/+ 10) | "
                    "[Down/Up] PPS (-/+ 5)"
                )
            except Exception as exc:
                logger.debug("Failed to register CLI global hotkeys: %s", exc, exc_info=True)
        else:
            logger.info(
                "[Headless / GUI Worker Launch] Background engine active (terminal hotkeys bypassed)."
            )

    def _check_debounce(self) -> bool:
        """Enforces a strict cooldown between hotkey triggers."""
        now = time.perf_counter()
        if now - self._last_hotkey_time < self._hotkey_cooldown:
            return False
        self._last_hotkey_time = now
        return True

    def _adjust_rate_cap_cli(self, delta: float) -> None:
        """Dynamically tunes the ADB polling rate cap, enforcing bounds and committing to SQLite."""
        if not self._check_debounce():
            return

        new_rate = max(RATE_CAP_MIN, min(RATE_CAP_MAX, self.rate_cap + delta))
        if new_rate == self.rate_cap:
            return

        self.rate_cap = new_rate
        if self.touch_reader and hasattr(self.touch_reader, "rate_cap"):
            self.touch_reader.rate_cap = new_rate

        try:
            store.settings.update(adb_rate_cap=new_rate)
            logger.info("CLI Hotkey: Rate Cap set to %.1f Hz (DB synced)", new_rate)
        except Exception as exc:
            logger.error("Failed to commit rate cap update to DB: %s", exc)

    def _adjust_pps_cli(self, delta: float) -> None:
        """Dynamically tunes the PPS alert threshold, enforcing bounds and committing to SQLite."""
        if not self._check_debounce():
            return

        new_pps = max(PPS_MIN, min(PPS_MAX, self.pps + delta))
        if new_pps == self.pps:
            return

        self.pps = new_pps
        if self.mapper:
            if hasattr(self.mapper, "pps_threshold"):
                self.mapper.pps_threshold = new_pps
            elif hasattr(self.mapper, "pps"):
                self.mapper.pps = new_pps

        try:
            store.settings.update(pps_alert_threshold=new_pps)
            logger.info("CLI Hotkey: PPS Alert Threshold set to %.1f PPS (DB synced)", new_pps)
        except Exception as exc:
            logger.error("Failed to commit PPS update to DB: %s", exc)

    def _toggle_handedness_cli(self) -> None:
        if not self._check_debounce():
            return
        try:
            s = store.settings.get()
            new_val = not s.left_handed
            store.settings.update(left_handed=new_val)
            logger.info("CLI Hotkey Triggered [F5]: Left-Handed mode set to %s", new_val)
            self.mapper_event_dispatcher.dispatch(MapperEvent(action="ON_CONFIG_RELOAD"))
        except Exception as exc:
            logger.error("Failed to toggle handedness via hotkey: %s", exc, exc_info=True)

    def _reload_layout_cli(self) -> None:
        if not self._check_debounce():
            return
        self.mapper_event_dispatcher.dispatch(MapperEvent(action="ON_LAYOUT_RELOAD"))
        logger.info("CLI Hotkey Triggered [F6]: Layout reload event dispatched.")

    def _reload_config_cli(self) -> None:
        if not self._check_debounce():
            return
        self.mapper_event_dispatcher.dispatch(MapperEvent(action="ON_CONFIG_RELOAD"))
        logger.info("CLI Hotkey Triggered [F7]: Configuration reload event dispatched.")

    def _on_devices_change(self, k_id: int | None, m_id: int | None) -> None:
        if not self.bridge_class or self.bridge_class.k_proc is None:
            return
        self.bridge_class.reload_devices(k_id, m_id)

    def toggle_mode(self) -> None:
        with self.lock:
            self.is_visible = not self.is_visible
            new_state = self.is_visible

        self.bridge_class.health_check()
        if self.mouse_mapper:
            self.mouse_mapper.touch_up()
        if self.key_mapper:
            self.key_mapper.release_all()
        if self.wasd_mapper:
            self.wasd_mapper.touch_up()
        if self.bezel_mapper:
            self.bezel_mapper.release_all()
        self.two_finger_tap_tracker.reset()

        self.mapper_event_dispatcher.dispatch(
            MapperEvent(action="ON_MENU_MODE_TOGGLE", is_visible=new_state)
        )

    def start_virtual_keyboard(self):
        self.vkb_reader.close()
        self.vkb_writer.close()

        self.vkb_reader, self.vkb_writer = multiprocessing.Pipe(duplex=False)
        self.vkb_process = multiprocessing.Process(
            target=virtual_keyboard_worker,
            name="Virtual Keyboard",
            args=(self.vkb_writer,),
            daemon=True,
        )
        self.vkb_process.start()
        self.vkb_writer.close()

    def close_virtual_keyboard(self):
        if self.vkb_process is not None and self.vkb_process.is_alive():
            self.vkb_process.terminate()
            self.vkb_process.join(timeout=1.0)
            if self.vkb_process.is_alive():
                self.vkb_process.kill()

            self.vkb_reader.close()
            self.vkb_writer.close()

    def toggle_virtual_keyboard(self) -> None:
        if self.vkb_process is not None and self.vkb_process.is_alive():
            self.close_virtual_keyboard()
        else:
            self.start_virtual_keyboard()

    def _set_is_visible(self, is_visible: bool = True) -> None:
        with self.lock:
            self.is_visible = is_visible
            if self.mouse_mapper:
                self.mouse_mapper.touch_up()
            if self.key_mapper:
                self.key_mapper.release_all()
            if self.wasd_mapper:
                self.wasd_mapper.touch_up()
            if self.bezel_mapper:
                self.bezel_mapper.release_all()
            self.two_finger_tap_tracker.reset()

    def _on_layout_reload(self) -> None:
        logger.info("Executing layout reload across loader and pipelines...")
        try:
            if self.layout_loader and hasattr(self.layout_loader, "reload"):
                self.layout_loader.reload()
            if self.mapper and hasattr(self.mapper, "reload_layout"):
                self.mapper.reload_layout()
            if self.key_mapper and hasattr(self.key_mapper, "rebuild_pipelines"):
                self.key_mapper.rebuild_pipelines()
            if self.bezel_mapper and hasattr(self.bezel_mapper, "rebuild_pipelines"):
                self.bezel_mapper.rebuild_pipelines()
            if self.wasd_mapper and hasattr(self.wasd_mapper, "rebuild_pipeline"):
                self.wasd_mapper.rebuild_pipeline()
            if self.mouse_mapper and hasattr(self.mouse_mapper, "rebuild_pipeline"):
                self.mouse_mapper.rebuild_pipeline()

            self._tiers = self._build_pipeline_tiers()
            logger.info("Layout reload completed successfully.")
        except Exception as exc:
            logger.error("Error during layout reload execution: %s", exc, exc_info=True)

    def _on_config_reload(self) -> None:
        settings = store.settings.get()
        self.double_tap_enabled = settings.double_tap_enabled
        self.bezel_toggle_enabled = settings.bezel_toggle_enabled

        # Update and clamp rate cap
        self.rate_cap = max(
            RATE_CAP_MIN,
            min(RATE_CAP_MAX, float(settings.adb_rate_cap or DEFAULT_ADB_RATE_CAP)),
        )
        if self.touch_reader and hasattr(self.touch_reader, "rate_cap"):
            self.touch_reader.rate_cap = self.rate_cap

        # Update and clamp PPS threshold
        self.pps = max(
            PPS_MIN,
            min(PPS_MAX, float(settings.pps_alert_threshold or DEFAULT_PPS)),
        )
        if self.mapper:
            if hasattr(self.mapper, "pps_threshold"):
                self.mapper.pps_threshold = self.pps
            elif hasattr(self.mapper, "pps"):
                self.mapper.pps = self.pps

        self._tiers = self._build_pipeline_tiers()
        logger.info(
            "Engine config reloaded: Rate Cap=%.1f Hz, PPS Threshold=%.1f PPS",
            self.rate_cap,
            self.pps,
        )

    def _build_pipeline_tiers(self) -> list[list[Pipeline]]:
        all_pipelines: list[Pipeline] = []

        if self.key_mapper:
            all_pipelines.extend(self.key_mapper.pipelines)
        if self.wasd_mapper and self.wasd_mapper.pipeline:
            all_pipelines.append(self.wasd_mapper.pipeline)
        if self.mouse_mapper and self.mouse_mapper.pipeline:
            all_pipelines.append(self.mouse_mapper.pipeline)
        if self.bezel_mapper:
            all_pipelines.extend(self.bezel_mapper.pipelines)

        all_pipelines.sort(
            key=lambda p: (
                -p.priority,
                -getattr(p, "type_precedence", 0),
                getattr(p.region, "area", 0.0),
                getattr(p, "creation_id", 0),
            )
        )

        tiers: list[list[Pipeline]] = []
        for p in all_pipelines:
            if not tiers:
                tiers.append([p])
            else:
                last_tier = tiers[-1]
                if p.priority == last_tier[0].priority and getattr(
                    p, "type_precedence", 0
                ) == getattr(last_tier[0], "type_precedence", 0):
                    last_tier.append(p)
                else:
                    tiers.append([p])

        return tiers

    def _mouse_flush_loop(self) -> None:
        """Dedicated background loop flushing accumulated mouse movements dynamically."""
        while not self._stop_event.is_set():
            if self.output_sink:
                self.output_sink.flush_mouse_move()
                if self.touch_reader and getattr(self.touch_reader, "active_touches", 1) == 0:
                    self.output_sink.reset_mouse_accumulators()

            active_cap = max(RATE_CAP_MIN, self.rate_cap)
            time.sleep(1.0 / active_cap)

    def _process_touch_event(self, touch_event: TouchEvent) -> None:
        if not (
            self.mouse_mapper
            and self.key_mapper
            and self.wasd_mapper
            and self.bezel_mapper
            and self.mapper
            and self.output_sink
        ):
            return

        tiers = self._tiers or self._build_pipeline_tiers()
        output_sink = self.output_sink

        if self.is_visible:
            if self.double_tap_enabled and self.two_finger_tap_tracker.process(
                touch_event
            ):
                self.toggle_mode()
                return

            for tier in tiers:
                for p in tier:
                    if (
                        p.is_system
                        and self.bezel_toggle_enabled
                        and p.claims(touch_event)
                    ):
                        p.process(touch_event, output_sink)
                        return

            if (
                touch_event.contact_id == 0
                and not self.two_finger_tap_tracker._contacts
            ):
                gx, gy = self.mapper.device_to_game_abs(
                    touch_event.position.x, touch_event.position.y
                )

                if touch_event.phase is TouchPhase.DOWN:
                    self.mapper.bridge.mouse_move_abs(int(round(gx)), int(round(gy)))
                    self.mapper.bridge.left_click_down()
                elif touch_event.phase is TouchPhase.MOVE:
                    self.mapper.bridge.mouse_move_abs(int(round(gx)), int(round(gy)))
                elif touch_event.phase is TouchPhase.UP:
                    self.mapper.bridge.left_click_up()
                return

        # Game Mode Pipeline Dispatch
        claimed_existing = False
        for tier in tiers:
            for p in tier:
                if p.is_system and not self.bezel_toggle_enabled:
                    continue
                if p.owns(touch_event.contact_id):
                    p.process(touch_event, output_sink)
                    claimed_existing = True

        if not claimed_existing and touch_event.phase is TouchPhase.DOWN:
            for tier in tiers:
                tier_claimed = False
                for p in tier:
                    if p.is_system and not self.bezel_toggle_enabled:
                        continue
                    if p.claims(touch_event):
                        p.process(touch_event, output_sink)
                        tier_claimed = True
                        if not p.allow_multi_claim:
                            break
                if tier_claimed:
                    break

    def start_headless(
        self,
        window_id: int | None,
        toggle_key: str | None = None,
        sprint_key: str | None = None,
        rate_cap: float | None = None,
        pps: float | None = None,
        k_device_handle: int = 0,
        m_device_handle: int = 10,
    ) -> None:
        settings = store.settings.get()
        toggle_key = toggle_key or settings.toggle_key
        sprint_key = sprint_key or settings.sprint_key

        # Strictly enforce bounds on dynamic runtime properties
        self.rate_cap = max(
            RATE_CAP_MIN,
            min(RATE_CAP_MAX, float(rate_cap or settings.adb_rate_cap or DEFAULT_ADB_RATE_CAP)),
        )
        self.pps = max(
            PPS_MIN,
            min(PPS_MAX, float(pps or settings.pps_alert_threshold or DEFAULT_PPS)),
        )

        if window_id is None:
            logger.warning(
                "No window ID provided. Engine will run without a target window."
            )

        logger.info(
            f"Headless: {self.headless}, Window ID: {window_id}, Rate Cap: {self.rate_cap}, "
            f"PPS: {self.pps}, Toggle Key: {toggle_key}, Sprint Key: {sprint_key}"
        )
        logger.info(
            f"Typematic Enabled: {settings.typematic_enabled}, Delay (ms): {settings.typematic_delay_ms}, "
            f"Rate (Hz): {settings.typematic_rate_hz}, Excluded: {settings.typematic_excluded_keys}"
        )
        logger.info(
            f"Keyboard Handle: {k_device_handle}, Mouse Handle: {m_device_handle}"
        )

        self.double_tap_enabled = settings.double_tap_enabled
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
            self.bridge_class,
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
        self.key_mapper = KeyMapper(
            self.mapper,
            self.output_sink,
            typematic_enabled=settings.typematic_enabled,
            typematic_delay_ms=settings.typematic_delay_ms,
            typematic_rate_hz=settings.typematic_rate_hz,
            typematic_excluded_keys=settings.typematic_excluded_keys,
        )
        self.wasd_mapper = WASDMapper(self.mapper, self.output_sink)

        self._tiers = self._build_pipeline_tiers()

        self.touch_reader.bind_touch_event(self._process_touch_event)
        self.mapper_event_dispatcher.register_callback(
            "ON_MENU_MODE_TOGGLE", self._set_is_visible
        )
        self.mapper_event_dispatcher.register_callback(
            "ON_LAYOUT_RELOAD", self._on_layout_reload
        )
        self.mapper_event_dispatcher.register_callback(
            "ON_CONFIG_RELOAD", self._on_config_reload
        )
        self.mapper_event_dispatcher.register_callback(
            "ON_DEVICES_CHANGE", self._on_devices_change
        )

        self.bridge_class.start_worker_processes(k_device_handle, m_device_handle)

        # Start dynamic mouse accumulator flush thread
        threading.Thread(
            target=self._mouse_flush_loop,
            daemon=True,
            name="MouseFlushThread",
        ).start()

    def _start(self, config_str: str | None = None) -> None:
        if config_str is not None:
            config = parse_config_arg(config_str)
            # Sync parameters to SQLite to persist across reloads
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

        w_result = select_window()
        if w_result is None:
            return
        selected_window_id, _ = w_result

        c_result = capture_keys()
        if c_result is None:
            return
        toggle_key, sprint_key = c_result

        perf_result = capture_performance_settings()
        if perf_result is None:
            return
        rate_cap, pps = perf_result

        if rate_cap is None or pps is None:
            return

        # Commit interactive CLI selections to SQLite prior to engine initialization
        store.settings.update(
            adb_rate_cap=rate_cap,
            pps_alert_threshold=pps,
            toggle_key=toggle_key,
            sprint_key=sprint_key,
        )

        k_device_handle = None
        m_device_handle = None

        if sys.platform == "win32":
            from modules.platforms.windows.query_interception_device import (
                select_keyboard_then_mouse,
            )

            res = select_keyboard_then_mouse()
            if res:
                k_device_handle, m_device_handle = res

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
        if self.is_shutting_down:
            return
        self.is_shutting_down = True
        self._stop_event.set()

        self.mapper_event_dispatcher.unregister_all()

        if not self.headless:
            try:
                import keyboard

                keyboard.unhook_all_hotkeys()
            except Exception:
                pass

        try:
            self.close_virtual_keyboard()

            # Reset pipelines to release virtual down-states
            if self.output_sink:
                for tier in self._tiers:
                    for p in tier:
                        p.reset(self.output_sink)

            if self.touch_reader is not None:
                self.touch_reader.stop()
            if self.key_mapper is not None:
                self.key_mapper.release_all()
            if self.wasd_mapper is not None:
                self.wasd_mapper.touch_up()
            if self.mouse_mapper is not None:
                self.mouse_mapper.touch_up()
            if self.bezel_mapper is not None:
                self.bezel_mapper.release_all()
            if self.mapper is not None:
                self.mapper.stop()

            if self.bridge_class is not None:
                self.bridge_class.shutdown()
                self.bridge_class.release_all()

            procs = [
                p
                for p in (self.bridge_class.k_proc, self.bridge_class.m_proc)
                if p is not None
            ]

            for p in procs:
                if p.is_alive():
                    p.terminate()
            for p in procs:
                p.join(timeout=1.0)
                if p.is_alive():
                    p.kill()
        except Exception:
            pass

        store.close()


def run_engine_process(conn: Connection, log_queue: Queue) -> None:
    AppLogManager.setup_logging(
        is_gui=True, log_prefix="engine", log_queue=log_queue
    )
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
        engine.start_headless(
            window_id=config["window_id"],
        )
        dispatcher.send_started()

    except KeyboardInterrupt:
        logger.info("Engine received shutdown signal, exiting cleanly.")
        sys.exit(0)

    except Exception as exc:
        logger.error("[ENGINE PROCESS] Startup failure: %s", exc, exc_info=True)
        dispatcher.send_error(str(exc))
        if engine is not None:
            try:
                engine._shutdown()
            except Exception:
                pass
        try:
            conn.close()
        except OSError:
            pass
        return

    dispatcher.run_command_loop()

    try:
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
    """Parses a comma-separated config string, enforcing performance bounds."""
    settings = store.settings.get()
    parts = [p.strip() for p in config_str.split(",")]

    while len(parts) < 7:
        parts.append("")

    def _parse_val(val, target_type, default):
        if not val:
            return default
        try:
            return target_type(val)
        except (ValueError, TypeError):
            return default

    window_id = _parse_val(parts[0], int, None)
    toggle_key = _parse_val(parts[1], str, settings.toggle_key or "")
    sprint_key = _parse_val(parts[2], str, settings.sprint_key or "")

    raw_rate = _parse_val(
        parts[3], float, settings.adb_rate_cap or DEFAULT_ADB_RATE_CAP
    )
    rate_cap = max(RATE_CAP_MIN, min(RATE_CAP_MAX, raw_rate))

    raw_pps = _parse_val(
        parts[4], float, settings.pps_alert_threshold or DEFAULT_PPS
    )
    pps = max(PPS_MIN, min(PPS_MAX, raw_pps))

    k_device_handle = _parse_val(parts[5], int, 0)
    m_device_handle = _parse_val(parts[6], int, 10)

    logger.info(
        "Parsed config: window_id=%s, toggle_key=%s, sprint_key=%s, "
        "rate_cap=%.1f, pps=%.1f, k_device_handle=%s, m_device_handle=%s",
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
