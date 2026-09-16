from __future__ import annotations

import argparse
import multiprocessing
import os
import sys
import threading
from typing import TYPE_CHECKING
from PySide6.QtWidgets import QApplication

from modules.database import store
from modules.platforms import check_single_instance, get_platform
from modules.utils import (
    ADB,
    SHORT_DELAY,
    SYSTEM,
    PROJECT_ROOT,
    MapperEvent,
    MapperEventDispatcher,
    TouchEvent,
    TouchPhase,
)
from modules.core.config import AppConfig
from modules.core.layout_loader import LayoutLoader
from modules.core.touch_reader import TouchReader
from modules.core.mapper import Mapper
from modules.core.mouse_mapper import MouseMapper
from modules.core.key_mapper import KeyMapper
from modules.core.wasd_mapper import WASDMapper
from modules.core.pipeline import BezelReturnToggle, Pipeline
from modules.scripts.pre_flight import run as pre_flight_run
from modules.core.gestures import TwoFingerTapTracker
from modules.cli.list_windows import select_window
from modules.cli.key_capture import capture_keys, capture_performance_settings

NAME = "Touch2Key_Engine"
profiler: Profile | None = None

if TYPE_CHECKING:
    from cProfile import Profile


class Engine:
    def __init__(self, headless: bool = False):
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
        self.mouse_mapper: MouseMapper | None = None
        self.key_mapper: KeyMapper | None = None
        self.wasd_mapper: WASDMapper | None = None
        self.bezel_pipeline: Pipeline | None = None

        self.is_visible = False  # Start in Game Mode (cursor hidden)
        self.lock = threading.Lock()
        self.is_shutting_down = False
        self.mapper_event_dispatcher = MapperEventDispatcher()
        self.two_finger_tap_tracker = TwoFingerTapTracker()

        # ONLY register global keyboard hotkeys when running pure CLI mode
        if not self.headless:
            import keyboard
            keyboard.add_hotkey("esc", self._shutdown)

    def toggle_mode(self) -> None:
        """Toggles between Game Mode and Menu/Cursor Mode."""
        with self.lock:
            self.is_visible = not self.is_visible
            new_state = self.is_visible

        # Reset hardware keys & trackers on transition
        self.bridge_class.health_check()
        if self.mouse_mapper:
            self.mouse_mapper.touch_up()
        if self.key_mapper:
            self.key_mapper.release_all()
        if self.wasd_mapper:
            self.wasd_mapper.touch_up()
        self.two_finger_tap_tracker.reset()

        # Dispatch state change across engine and Qt Signal Bridge
        self.mapper_event_dispatcher.dispatch(
            MapperEvent(action="ON_MENU_MODE_TOGGLE", is_visible=new_state)
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
        """Rebuilds resolution-dependent boundaries such as the top bezel gate."""
        if self.layout_loader is not None:
            dev_w = float(self.layout_loader.width)
            self.bezel_pipeline = BezelReturnToggle(screen_width=dev_w, bezel_height=14.0)

    def _build_pipeline_tiers(self) -> list[list[Pipeline]]:
        all_pipelines: list[Pipeline] = []

        if self.bezel_pipeline:
            all_pipelines.append(self.bezel_pipeline)
        if self.key_mapper:
            all_pipelines.extend(self.key_mapper.pipelines)
        if self.wasd_mapper and self.wasd_mapper.pipeline:
            all_pipelines.append(self.wasd_mapper.pipeline)
        if self.mouse_mapper and self.mouse_mapper.pipeline:
            all_pipelines.append(self.mouse_mapper.pipeline)

        # 4-Key Sort: (-priority, -type_precedence, area, creation_id)
        all_pipelines.sort(
            key=lambda p: (
                -p.priority,
                -p.type_precedence,
                p.region.area,
                p.creation_id,
            )
        )

        # Group into strict dispatch tiers
        tiers: list[list[Pipeline]] = []
        for p in all_pipelines:
            if not tiers:
                tiers.append([p])
            else:
                last_tier = tiers[-1]
                if (
                    p.priority == last_tier[0].priority
                    and p.type_precedence == last_tier[0].type_precedence
                ):
                    last_tier.append(p)
                else:
                    tiers.append([p])

        return tiers

    def _process_touch_event(self, touch_event: TouchEvent) -> None:
        if not (self.mouse_mapper and self.key_mapper and self.wasd_mapper and self.mapper):
            return

        # -------------------------------------------------------------------
        # 1. MENU MODE (Cursor Visible) NAVIGATION & RETURN GATES
        # -------------------------------------------------------------------
        if self.is_visible:
            # Evaluate strict stationary two-finger tap
            if self.two_finger_tap_tracker.process(touch_event):
                self.toggle_mode()
                return

            # Bezel notch fallback
            if self.bezel_pipeline and self.bezel_pipeline.claims(touch_event):
                self.two_finger_tap_tracker.reset()
                self.toggle_mode()
                return

            # Pass-through relative mapping to OS cursor for UI navigation
            if touch_event.contact_id == 0 and not self.two_finger_tap_tracker._contacts:
                gx, gy = self.mapper.device_to_game_abs(
                    touch_event.position.x, touch_event.position.y
                )
                if touch_event.phase is TouchPhase.DOWN:
                    self.bridge_class.mouse_move_abs(int(round(gx)), int(round(gy)))
                    self.bridge_class.left_click_down()
                elif touch_event.phase is TouchPhase.MOVE:
                    self.bridge_class.mouse_move_abs(int(round(gx)), int(round(gy)))
                elif touch_event.phase is TouchPhase.UP:
                    self.bridge_class.left_click_up()
            return

        # -------------------------------------------------------------------
        # 2. GAME MODE (Cursor Hidden) PIPELINE DISPATCH
        # -------------------------------------------------------------------
        self.mapper.event_count += 1
        tiers = self._build_pipeline_tiers()
        sink = self.key_mapper.output_sink

        # Routing for already active touches
        claimed_existing = False
        for tier in tiers:
            for p in tier:
                if p.owns(touch_event.contact_id):
                    p.process(touch_event, sink)
                    claimed_existing = True

        if claimed_existing:
            return

        # Evaluation for new touches (DOWN)
        if touch_event.phase is TouchPhase.DOWN:
            for tier in tiers:
                tier_claimed = False
                for p in tier:
                    if p.claims(touch_event):
                        if p == self.bezel_pipeline:
                            self.toggle_mode()
                            return

                        p.process(touch_event, sink)
                        tier_claimed = True

                        if not p.allow_multi_claim:
                            return

                if tier_claimed:
                    return

    def start_headless(
        self,
        window_id: int,
        rate_cap: float = 250.0,
        pps: float = 60.0,
        toggle_key: str | None = None,
        sprint_key: str | None = None,
    ) -> None:
        k_device_handle: int | None = None
        m_device_handle: int | None = None

        if SYSTEM == "Windows":
            from modules.platforms.windows import select_keyboard_then_mouse

            res = select_keyboard_then_mouse()
            if res:
                k_device_handle, m_device_handle = res

        config = AppConfig(self.mapper_event_dispatcher)
        self.layout_loader = LayoutLoader(config, self.foreground_window)
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

        dev_w = float(self.layout_loader.width)
        self.bezel_pipeline = BezelReturnToggle(screen_width=dev_w, bezel_height=14.0)

        self.mouse_mapper = MouseMapper(self.mapper)
        self.key_mapper = KeyMapper(self.mapper, on_toggle_mode=self.toggle_mode)
        self.wasd_mapper = WASDMapper(self.mapper)

        self.touch_reader.bind_touch_event(self._process_touch_event)
        self.mapper_event_dispatcher.register_callback(
            "ON_MENU_MODE_TOGGLE", self._set_is_visible
        )
        self.mapper_event_dispatcher.register_callback(
            "ON_LAYOUT_RELOAD", self._on_layout_reload
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

        self.start_headless(
            window_id=selected_window_id,
            rate_cap=rate_cap,
            pps=pps,
            toggle_key=toggle_key,
            sprint_key=sprint_key,
        )

        if not self.headless:
           import keyboard
           keyboard.wait()


class Engine:
    def __init__(self, headless: bool = False):
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
        self.mouse_mapper: MouseMapper | None = None
        self.key_mapper: KeyMapper | None = None
        self.wasd_mapper: WASDMapper | None = None
        self.bezel_pipeline: Pipeline | None = None

        self.is_visible = False  # Start in Game Mode (cursor hidden)
        self.lock = threading.Lock()
        self.is_shutting_down = False
        self.mapper_event_dispatcher = MapperEventDispatcher()
        self.two_finger_tap_tracker = TwoFingerTapTracker()

        # ONLY register global keyboard hotkeys when running pure CLI mode
        if not self.headless:
            import keyboard
            keyboard.add_hotkey("esc", self._shutdown)

    def _shutdown(self) -> None:
        if self.is_shutting_down:
            return
        self.is_shutting_down = True

        # Unhook global keyboard hotkeys strictly in CLI mode
        if not self.headless:
            try:
                import keyboard
                keyboard.unhook_all_hotkeys()
            except Exception:
                pass

        try:
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
                    getattr(self.bridge_class, "k_proc", None),
                    getattr(self.bridge_class, "m_proc", None),
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

        profiler_cleanup(profiler)
        store.close()
        
        # Hard terminate only if CLI mode; keep host process alive in GUI mode
        if not self.headless:
            os._exit(0)


def profiler_cleanup(prof: Profile | None) -> None:
    if prof:
        prof.disable()
        prof.dump_stats(PROJECT_ROOT / "touch2key_cli.prof")


def run(parser: argparse.ArgumentParser | None = None) -> None:
    global profiler
    if parser is None:
        parser = argparse.ArgumentParser(description="Touch2Key Engine")
        parser.add_argument("--profile", action="store_true", help="Enable profiling")

    args = parser.parse_args()
    if args.profile:
        import cProfile

        profiler = cProfile.Profile()
        profiler.enable()

    if not pre_flight_run():
        sys.exit(1)

    try:
        multiprocessing.set_start_method("spawn", force=True)
    except RuntimeError:
        pass

    success, _ = check_single_instance(NAME)
    if not success:
        sys.exit(0)

    app = QApplication.instance() or QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(True)
    engine = Engine()
    try:
        engine._start()
    except KeyboardInterrupt:
        engine._shutdown()


if __name__ == "__main__":
    run()