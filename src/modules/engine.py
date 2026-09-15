from __future__ import annotations

import argparse
import multiprocessing
import os
import sys
import threading
from typing import TYPE_CHECKING

import keyboard
from PySide6.QtWidgets import QApplication

from modules.database import store
from modules.platforms import check_single_instance, get_platform
from modules.utils import ADB, SHORT_DELAY, SYSTEM, PROJECT_ROOT, MapperEventDispatcher
from modules.core.config import AppConfig
from modules.core.layout_loader import LayoutLoader
from modules.core.touch_reader import TouchReader
from modules.core.mapper import Mapper
from modules.core.mouse_mapper import MouseMapper
from modules.core.key_mapper import KeyMapper
from modules.core.wasd_mapper import WASDMapper
from modules.scripts.pre_flight import run as pre_flight_run
from modules.core.list_windows import select_window
from modules.core.key_capture import capture_keys, capture_performance_settings

NAME = "Touch2Key_Engine"
profiler: Profile | None = None

if TYPE_CHECKING:
    from cProfile import Profile
    from modules.utils import TouchEvent, TouchPhase
    from modules.core.input_semantics import Pipeline


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
        self.mapper: Mapper | None = None
        self.mouse_mapper: MouseMapper | None = None
        self.key_mapper: KeyMapper | None = None
        self.wasd_mapper: WASDMapper | None = None

        self.is_visible = True
        self.lock = threading.Lock()
        self.is_shutting_down = False
        self.mapper_event_dispatcher = MapperEventDispatcher()

        keyboard.add_hotkey("esc", self._shutdown)

    def _set_is_visible(self, is_visible: bool) -> None:
        with self.lock:
            self.is_visible = is_visible
            self.bridge_class.health_check()
            if self.mouse_mapper:
                self.mouse_mapper.touch_up()
            if self.key_mapper:
                self.key_mapper.release_all()
            if self.wasd_mapper:
                self.wasd_mapper.touch_up()

    def _build_pipeline_tiers(self) -> list[list[Pipeline]]:
        """Gathers all active pipelines, sorts them across all 4 keys,
        and groups them into tiers using ONLY (priority, type_precedence).

        Within each tier, pipelines are ordered deterministically by
        (region.area, creation_id) so overlapping buttons in the same tier
        can claim and fire concurrently.
        """
        all_pipelines: list[Pipeline] = []

        if self.key_mapper:
            all_pipelines.extend(self.key_mapper.pipelines)
        if self.wasd_mapper and self.wasd_mapper.pipeline:
            all_pipelines.append(self.wasd_mapper.pipeline)
        if self.mouse_mapper and self.mouse_mapper.pipeline:
            all_pipelines.append(self.mouse_mapper.pipeline)

        # Full 4-key deterministic sort
        all_pipelines.sort(
            key=lambda p: (
                -p.priority,  # Key 1: Explicit priority (descending)
                -p.type_precedence,  # Key 2: Button (2) > Joystick (1) > Mouse (0)
                p.region.area,  # Key 3: Specificity/Hitbox area (ascending)
                p.creation_id,  # Key 4: Creation order (ascending)
            )
        )

        # Group into tiers matching on the first 2 keys ONLY
        tiers: list[list[Pipeline]] = []
        for p in all_pipelines:
            if not tiers:
                tiers.append([p])
            else:
                last_tier = tiers[-1]
                # Compare ONLY priority and type_precedence for grouping
                if (
                    p.priority == last_tier[0].priority
                    and p.type_precedence == last_tier[0].type_precedence
                ):
                    last_tier.append(p)
                else:
                    tiers.append([p])

        return tiers

    def _process_touch_event(self, touch_event: TouchEvent) -> None:
        if not (
            self.mouse_mapper and self.key_mapper and self.wasd_mapper and self.mapper
        ):
            return

        if self.is_visible:
            self.mouse_mapper.process_touch(touch_event, is_visible=True)
            return

        self.mapper.event_count += 1
        tiers = self._build_pipeline_tiers()
        sink = self.key_mapper.output_sink

        # -------------------------------------------------------------------
        # 1. Existing Active Touch Routing (MOVE / UP)
        # -------------------------------------------------------------------
        claimed_existing = False
        for tier in tiers:
            for p in tier:
                if p.owns(touch_event.contact_id):
                    p.process(touch_event, sink)
                    claimed_existing = True

        if claimed_existing:
            return

        # -------------------------------------------------------------------
        # 2. Fresh Touch Claiming (DOWN) with Defensive Category Guards
        # -------------------------------------------------------------------
        if touch_event.phase is TouchPhase.DOWN:
            for tier in tiers:
                tier_claimed = False

                for p in tier:
                    if p.claims(touch_event):
                        # Defensive Check: If a Joystick or Mouse is ALREADY active with another finger,
                        # ignore duplicate instances to prevent hardware buffer contention.
                        if not p.allow_multi_claim and any(
                            other._owned_contact is not None for other in tier
                        ):
                            continue

                        p.process(touch_event, sink)
                        tier_claimed = True

                        # If this pipeline does not allow multi-claim (Joystick/Mouse),
                        # the winning candidate (via 4-key sort) exclusively consumes the tier.
                        if not p.allow_multi_claim:
                            return

                # If any button in this tier claimed the touch, consume and halt fallthrough
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
        layout_loader = LayoutLoader(config, self.foreground_window)
        self.touch_reader = TouchReader(config, self.mapper_event_dispatcher, rate_cap)

        emulator_map = {"toggle_key": toggle_key, "sprint_key": sprint_key}
        self.mapper = Mapper(
            layout_loader,
            self.touch_reader,
            self.bridge_class,
            pps,
            emulator_map,
            window_id,
        )

        self.mouse_mapper = MouseMapper(self.mapper)
        self.key_mapper = KeyMapper(self.mapper)
        self.wasd_mapper = WASDMapper(self.mapper)

        self.touch_reader.bind_touch_event(self._process_touch_event)
        self.mapper_event_dispatcher.register_callback(
            "ON_MENU_MODE_TOGGLE", self._set_is_visible
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
        keyboard.wait()

    def _shutdown(self) -> None:
        if self.is_shutting_down:
            return
        self.is_shutting_down = True

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
        if not self.headless:
            os._exit(0)


def profiler_cleanup(prof: Profile | None) -> None:
    if prof:
        prof.disable()
        prof.dump_stats(PROJECT_ROOT / "touch2key.prof")


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
