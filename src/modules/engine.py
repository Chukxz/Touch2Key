from __future__ import annotations

import os
import sys
import multiprocessing
import threading
import logging
import time
from typing import TYPE_CHECKING

from modules.database import store
from modules.log_manager import AppLogManager
from modules.platforms import get_platform
from modules.utils import (
    MapperEvent,
    MapperEventDispatcher,
    TouchEvent,
    TouchPhase,
    IpcMapperEventDispatcher,
    DEFAULT_ADB_RATE_CAP,
    DEFAULT_PPS,
    IPC_CMD_START,
    unpack_ipc_start_cmd,
)

from modules import (
    LayoutLoader,
    TouchReader,
    Mapper,
    BezelMapper,
    MouseMapper,
    KeyMapper,
    WASDMapper,
    Pipeline,
    TwoFingerTapTracker,
    BridgeOutputSink,
)

from modules.scripts.list_windows import select_window
from modules.cli.key_capture import capture_keys, capture_performance_settings
from modules.gui.overlays import virtual_keyboard_worker

logger = logging.getLogger("modules.engine")


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

        # Debounce tracking for hotkeys
        self._last_hotkey_time = 0.0
        self._hotkey_cooldown = 0.4

        # Dynamic launch context logging & global hotkey binding
        if not self.headless:
            try:
                import keyboard

                # Capture the current terminal/console window handle upon startup
                self._terminal_window_handle = (
                    self.window_manager.get_foreground_window()
                )

                def _guard_hotkey(callback):
                    """Wraps hotkey callbacks to ensure they only fire if the terminal window is focused."""
                    try:
                        current_fg = self.window_manager.get_foreground_window()
                        if current_fg == self._terminal_window_handle:
                            callback()
                    except Exception as exc:
                        logger.debug(
                            "Failed to verify foreground window for hotkey: %s", exc
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

                logger.info(
                    "[CLI Interactive Launch] Active Global Hotkeys (Terminal-Focused): [Esc] Exit Engine | [F5] Toggle Handedness | [F6] Reload Layout | [F7] Reload Config"
                )
            except Exception as exc:
                logger.debug("Failed to register CLI global hotkeys: %s", exc)
        else:
            logger.info(
                "[Headless / GUI Worker Launch] Engine running in background worker mode (terminal hotkeys bypassed)."
            )

    def _check_debounce(self) -> bool:
        """Enforces a strict cooldown between hotkey triggers."""
        now = time.perf_counter()
        if now - self._last_hotkey_time < self._hotkey_cooldown:
            return False
        self._last_hotkey_time = now
        return True

    def _toggle_handedness_cli(self) -> None:
        if not self._check_debounce():
            return
        try:
            s = store.settings.get()
            new_val = not s.left_handed
            store.settings.update(left_handed=new_val)
            logger.info(
                "CLI Hotkey Triggered [F5]: Left-Handed mode set to %s", new_val
            )
            self.mapper_event_dispatcher.dispatch(
                MapperEvent(action="ON_CONFIG_RELOAD")
            )
        except Exception as exc:
            logger.error("Failed to toggle handedness via hotkey: %s", exc)

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
            self.two_finger_tap_tracker.reset()

    def _on_layout_reload(self) -> None:
        self._tiers = self._build_pipeline_tiers()

    def _on_config_reload(self) -> None:
        settings = store.settings.get()
        self.double_tap_enabled = settings.double_tap_enabled
        self.bezel_toggle_enabled = settings.bezel_toggle_enabled
        self._tiers = self._build_pipeline_tiers()

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

        # --- Game Mode Pipeline Dispatch ---
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

        # Dynamically push any mouse deltas accumulated by MouseMapper / Track-Fire Buttons to the OS
        self.output_sink.flush_mouse_move()

        if (
            touch_event.phase is TouchPhase.UP
            and getattr(self.touch_reader, "active_touches", 1) == 0
        ):
            self.output_sink.reset_mouse_accumulators()

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
        rate_cap = rate_cap or settings.adb_rate_cap
        pps = pps or settings.pps_alert_threshold

        if window_id is None:
            logger.warning(
                "No window ID provided. Engine will run without a target window."
            )

        logger.info(
            f"Headless: {self.headless}, Window ID: {window_id}, Rate Cap: {rate_cap}, PPS: {pps}, Toggle Key: {toggle_key}, Sprint Key: {sprint_key}"
        )
        logger.info(
            f"Typematic Enabled: {settings.typematic_enabled}, Typematic Delay (ms): {settings.typematic_delay_ms}, Typematic Rate (Hz): {settings.typematic_rate_hz}, Typematic Excluded Keys: {settings.typematic_excluded_keys}"
        )
        logger.info(
            f"Keyboard Device Handle: {k_device_handle}, Mouse Device Handle: {m_device_handle}"
        )

        self.double_tap_enabled = settings.double_tap_enabled
        self.bezel_toggle_enabled = settings.bezel_toggle_enabled

        print(f"Double-Tap enabled: {self.double_tap_enabled}")
        print(f"Bezel toggling enabled: {self.bezel_toggle_enabled}")

        self.layout_loader = LayoutLoader(
            self.mapper_event_dispatcher,
            foreground_window=self.foreground_window,
            toggle_mode_callback=self.toggle_mode,
        )
        self.touch_reader = TouchReader(self.mapper_event_dispatcher, rate_cap)

        self.mapper = Mapper(
            self.layout_loader,
            self.touch_reader,
            self.bridge_class,
            pps,
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

    def _start(self, config_str: str | None = None) -> None:
        if config_str is not None:
            config = parse_config_arg(config_str)
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
        is_gui=True, log_prefix="touch2key_engine", log_queue=log_queue
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
        print(f"[ENGINE PROCESS] Startup failure: {exc}")
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
        print(f"[ENGINE PROCESS] Shutdown failure: {exc}")
        dispatcher.send_error(str(exc))
    finally:
        dispatcher.send_stopped()
        try:
            conn.close()
        except OSError:
            pass


def parse_config_arg(config_str: str) -> dict:
    settings = store.settings.get()

    """Parses a comma-separated config string into engine parameters.
    Format: window_id, toggle_key, sprint_key, rate_cap, pps, k_device_handle, m_device_handle
    """
    # Split by comma and strip whitespace from each part
    parts = [p.strip() for p in config_str.split(",")]

    # Pad out missing trailing values up to 7 items
    while len(parts) < 7:
        parts.append("")

    def _parse_val(val, target_type, default):
        if not val:  # Handles empty strings like ,,
            return default
        try:
            return target_type(val)
        except (ValueError, TypeError):
            return default

    window_id = _parse_val(parts[0], int, None)
    toggle_key = _parse_val(parts[1], str, settings.toggle_key or "")
    sprint_key = _parse_val(parts[2], str, settings.sprint_key or "")
    rate_cap = _parse_val(
        parts[3], float, settings.adb_rate_cap or DEFAULT_ADB_RATE_CAP
    )
    pps = _parse_val(parts[4], float, settings.pps_alert_threshold or DEFAULT_PPS)
    k_device_handle = _parse_val(parts[5], int, 0)
    m_device_handle = _parse_val(parts[6], int, 10)

    logger.info(
        "Parsed config: window_id=%s, toggle_key=%s, sprint_key=%s, rate_cap=%s, pps=%s, k_device_handle=%s, m_device_handle=%s",
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
