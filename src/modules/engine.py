import os
import sys
import subprocess
import threading

from modules.database import store
from modules.platforms import get_platform
from modules.utils import (
    MapperEvent,
    MapperEventDispatcher,
    TouchEvent,
    TouchPhase,
)

from modules.core import (
    AppConfig,
    LayoutLoader,
    TouchReader,
    Mapper,
    BezelMapper,
    MouseMapper,
    KeyMapper,
    WASDMapper,
    Pipeline,
    TwoFingerTapTracker,
)

from modules.cli.list_windows import select_window
from modules.cli.key_capture import capture_keys, capture_performance_settings


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
        self.bezel_mapper: BezelMapper | None = None
        self.mouse_mapper: MouseMapper | None = None
        self.key_mapper: KeyMapper | None = None
        self.wasd_mapper: WASDMapper | None = None

        self.is_visible = False
        self.lock = threading.Lock()
        self.is_shutting_down = False
        self.mapper_event_dispatcher = dispatcher or MapperEventDispatcher()
        self.two_finger_tap_tracker = TwoFingerTapTracker()

        self.vkb_process = None
        self.vkb_pipe_name = (
            r"\\.\pipe\touch2key_vkb"
            if sys.platform == "win32"
            else "/tmp/touch2key_vkb"
        )

        if not self.headless:
            try:
                import keyboard

                keyboard.add_hotkey("esc", self._shutdown)
            except Exception:
                pass

    def _on_devices_changed(self, event: MapperEvent) -> None:
        if not self.bridge_class or self.bridge_class.k_proc is None:
            return
        payload = getattr(event, "payload", {}) or {}
        k_id = payload.get("keyboard_id")
        m_id = payload.get("mouse_id")
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

    def toggle_virtual_keyboard(self) -> None:
        if self.vkb_process and self.vkb_process.poll() is None:
            try:
                self.vkb_process.terminate()
                self.vkb_process.wait(timeout=0.5)
            except (subprocess.TimeoutExpired, ProcessLookupError, Exception):
                self.vkb_process.kill()
            self.vkb_process = None
        else:
            self.vkb_process = subprocess.Popen(
                [
                    sys.executable,
                    "-m",
                    "modules.gui.virtual_keyboard",
                    "--pipe",
                    self.vkb_pipe_name,
                    "--pid",
                    str(os.getpid()),
                ]
            )

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
        if self.layout_loader is not None:
            self.layout_loader.reload()

    def _build_pipeline_tiers(self) -> list[list[Pipeline]]:
        all_pipelines: list[Pipeline] = []

        if self.key_mapper:
            all_pipelines.extend(self.key_mapper.pipelines)
        if self.wasd_mapper and self.wasd_mapper.pipeline:
            all_pipelines.append(self.wasd_mapper.pipeline)
        if self.mouse_mapper and self.mouse_mapper.pipeline:
            all_pipelines.append(self.mouse_mapper.pipeline)

        if self.layout_loader and self.layout_loader.custom_pipelines:
            all_pipelines.extend(self.layout_loader.custom_pipelines)

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
            self.mouse_mapper and self.key_mapper and self.wasd_mapper and self.mapper
        ):
            return

        tiers = self._build_pipeline_tiers()
        sink = self.key_mapper.output_sink

        if self.is_visible:
            if self.two_finger_tap_tracker.process(touch_event):
                self.toggle_mode()
                return

            # Allow system pipelines (Bezels) to intercept touches even in Menu mode
            for tier in tiers:
                for p in tier:
                    if p.is_system and p.claims(touch_event):
                        p.process(touch_event, sink)
                        return

            if (
                touch_event.contact_id == 0
                and not self.two_finger_tap_tracker._contacts
            ):
                self.mouse_mapper.process_touch(touch_event, self.is_visible)

        # --- Game Mode Pipeline Dispatch ---
        claimed_existing = False
        for tier in tiers:
            for p in tier:
                if p.owns(touch_event.contact_id):
                    p.process(touch_event, sink)
                    claimed_existing = True

        if claimed_existing:
            return

        if touch_event.phase is TouchPhase.DOWN:
            for tier in tiers:
                tier_claimed = False
                for p in tier:
                    if p.claims(touch_event):
                        p.process(touch_event, sink)
                        tier_claimed = True
                        if not p.allow_multi_claim:
                            return
                if tier_claimed:
                    return

    def start_headless(
        self,
        window_id: int | None,
        rate_cap: float = 250.0,
        pps: float = 60.0,
        toggle_key: str | None = None,
        sprint_key: str | None = None,
        typematic_enabled: bool = True,
        typematic_delay_ms: float = 250.0,
        typematic_rate_hz: float = 30.0,
        typematic_exclude_keys: str | None = None,
    ) -> None:
        k_device_handle: int | None = None
        m_device_handle: int | None = None

        if sys.platform == "win32":
            from modules.platforms.windows.query_interception_device import (
                select_keyboard_then_mouse,
            )

            res = select_keyboard_then_mouse()
            if res:
                k_device_handle, m_device_handle = res

        config = AppConfig(self.mapper_event_dispatcher)
        self.layout_loader = LayoutLoader(
            config=config,
            foreground_window=self.foreground_window,
            toggle_mode_callback=self.toggle_mode,
        )
        self.touch_reader = TouchReader(config, self.mapper_event_dispatcher, rate_cap)

        emulator_map = {"toggle_key": toggle_key, "sprint_key": sprint_key}
        self.mapper = Mapper(
            self.layout_loader,
            self.touch_reader,
            self.bridge_class,
            pps,
            emulator_map,
            window_id,
            self,
        )

        self.bezel_mapper = BezelMapper(
            self.mapper, self.toggle_mode, self.toggle_virtual_keyboard
        )
        self.mouse_mapper = MouseMapper(self.mapper)
        self.key_mapper = KeyMapper(
            self.mapper,
            typematic_enabled=typematic_enabled,
            typematic_delay_ms=typematic_delay_ms,
            typematic_rate_hz=typematic_rate_hz,
            typematic_exclude_keys=typematic_exclude_keys,
        )
        self.wasd_mapper = WASDMapper(self.mapper)

        self.touch_reader.bind_touch_event(self._process_touch_event)
        self.mapper_event_dispatcher.register_callback(
            "ON_MENU_MODE_TOGGLE", self._set_is_visible
        )
        self.mapper_event_dispatcher.register_callback(
            "ON_LAYOUT_RELOAD", self._on_layout_reload
        )
        self.mapper_event_dispatcher.register_callback(
            "ON_DEVICES_CHANGED", self._on_devices_changed
        )

        self.bridge_class.start_worker_processes(k_device_handle, m_device_handle)

    def _start(self) -> None:
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

        settings = store.settings.get()

        self.start_headless(
            window_id=selected_window_id,
            rate_cap=rate_cap,
            pps=pps,
            toggle_key=toggle_key,
            sprint_key=sprint_key,
            typematic_enabled=settings.typematic_enabled,
            typematic_delay_ms=settings.typematic_delay_ms,
            typematic_rate_hz=settings.typematic_rate_hz,
            typematic_exclude_keys=settings.typematic_exclude_keys,
        )

        if not self.headless:
            try:
                import keyboard

                keyboard.wait()
            except Exception:
                pass

    def _shutdown(self) -> None:
        if self.is_shutting_down:
            return
        self.is_shutting_down = True

        self.mapper_event_dispatcher.unregister_all()

        if not self.headless:
            try:
                import keyboard

                keyboard.unhook_all_hotkeys()
            except Exception:
                pass

        try:
            if self.vkb_process and self.vkb_process.poll() is None:
                self.vkb_process.terminate()
                self.vkb_process.wait(timeout=1.0)

            if self.touch_reader is not None:
                self.touch_reader.stop()
            if self.mapper is not None:
                self.mapper.running = False
            if self.bridge_class is not None:
                self.bridge_class.shutdown()
                self.bridge_class.release_all()

            procs = [
                p
                for p in (
                    self.bridge_class.k_proc,
                    self.bridge_class.m_proc,
                )
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

        if not self.headless:
            sys.exit(0)
