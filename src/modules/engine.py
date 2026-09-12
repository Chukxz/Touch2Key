from __future__ import annotations
from typing import TYPE_CHECKING

import multiprocessing
import keyboard
import os
import threading
import time
import sys
from PySide6.QtWidgets import QApplication
from mapper_module.platforms import check_single_instance, get_platform

from mapper_module.utils import (
    ADB,
    SHORT_DELAY,
    SYSTEM,
)

from mapper_module import (
    MapperEventDispatcher,
    AppConfig,
    JSONLoader,
    TouchReader,
    Mapper,
    MouseMapper,
    KeyMapper,
    WASDMapper,
)

from mapper_module.scripts.pre_flight import run as pre_flight_run
from mapper_module.core.list_windows import select_window
from mapper_module.core.key_capture import capture_keys, capture_performance_settings

from mapper_module.utils import PROJECT_ROOT

NAME = "Touch2Key_Engine"

if TYPE_CHECKING:
    from cProfile import Profile
    from mapper_module.utils import TouchEvent
    from argparse import ArgumentParser

profiler: Profile | None = None


class Engine:
    def __init__(self):
        _Platform = get_platform()

        print("\n[ENGINE] - Initializing Touch2Key... Press 'ESC' to Stop.")
        print(f"\n[ENGINE] - ADB Executable File Path: {ADB}.")
        keyboard.add_hotkey("esc", self._shutdown)

        self.system_config = _Platform.SystemConfig()
        self.system_config.set_high_priority(os.getpid(), "Main")
        self.system_config.set_dpi_awareness()
        self.system_config.set_timer_resolution()

        self.window_manager = _Platform.WindowManager()
        self.foreground_window = self.window_manager.get_foreground_window()

        self.bridge_class = _Platform.Bridge(self.window_manager, self.system_config)

        self.touch_reader: TouchReader | None = None
        self.mapper: Mapper | None = None
        self.mouse_mapper: MouseMapper | None = None
        self.key_mapper: KeyMapper | None = None
        self.wasd_mapper: WASDMapper | None = None
        self.is_visible: bool = True
        self.lock: threading.Lock = threading.Lock()
        self.is_shutting_down: bool = False

    def _set_is_visible(self, _is_visible: bool):
        with self.lock:
            self.is_visible = _is_visible
            assert self.mouse_mapper is not None
            assert self.key_mapper is not None
            assert self.wasd_mapper is not None
            self.bridge_class.health_check()
            self.mouse_mapper.touch_up()
            self.key_mapper.release_all()
            self.wasd_mapper.touch_up()

    def _process_touch_event(self, action, touch_event: TouchEvent):
        assert self.mouse_mapper is not None
        assert self.key_mapper is not None
        assert self.wasd_mapper is not None
        assert self.mapper is not None

        local_visible = self.is_visible
        self.mapper.event_count += 1

        self.key_mapper.process_touch(action, touch_event, local_visible)

        if touch_event.is_mouse:
            self.mouse_mapper.process_touch(action, touch_event, local_visible)

        if touch_event.is_wasd:
            self.wasd_mapper.process_touch(action, touch_event, self.is_visible)

    def _start(self):
        w_result = select_window()
        if w_result is None:
            print("\n[ENGINE] - No window selected.")

            return
        
        selected_window_id, selected_window_title = w_result
        print(f"\n[ENGINE] - Selected window ID: {selected_window_id}, Selected window title: {selected_window_title}.")

        c_result = capture_keys()
        if c_result is None:
            print("\n[ENGINE] - Key configuration cancelled.")

            return
        toggle_key, sprint_key = c_result

        if not toggle_key:
            print(
                "\n[ENGINE] - No toggle key set. Touch zones if disabled by the cursor state can only be re-enabled via the keyboard/mouse."
            )
        else:
            print(f"\n[ENGINE] - Selected toggle key: {toggle_key}.")
        
        if not sprint_key:
            print("\n[ENGINE] - No sprint key set.")
        else:
            print(f"\n[ENGINE] - Selected sprint key: {sprint_key}.")

        emulator = {
            "toggle_key": toggle_key,
            "sprint_key": sprint_key,
        }

        perf_result = capture_performance_settings()
        if perf_result is None:
            print("\n[ENGINE] - Performance configuration cancelled.")

            return
        rate_cap, pps = perf_result

        if rate_cap is None or pps is None:
            print("\n[ENGINE] - Invalid performance settings.")

            return

        print(f"\n[ENGINE] - ADB Cap: {rate_cap}Hz | Alert Threshold: {pps}PPS.")

        k_device_handle: int | None = None
        m_device_handle: int | None = None

        if SYSTEM == "Windows":
            from mapper_module.platforms.windows import select_keyboard_then_mouse

            s_result = select_keyboard_then_mouse()
            if s_result is None:
                print("\n[ENGINE] Interception device querying cancelled.")

                return
            k_device_handle, m_device_handle = s_result

            print(f"\nKeyboard device handle: {k_device_handle}")
            print(f"\nMouse device handle: {m_device_handle}")

        mapper_event_dispatcher = MapperEventDispatcher()
        config = AppConfig(mapper_event_dispatcher)

        time.sleep(SHORT_DELAY)

        json_loader = JSONLoader(config, self.foreground_window)
        self.touch_reader = TouchReader(config, mapper_event_dispatcher, rate_cap)
        self.mapper = Mapper(
            json_loader,
            self.touch_reader,
            self.bridge_class,
            pps,
            emulator,
            selected_window_id,
        )

        self.mouse_mapper = MouseMapper(self.mapper)
        self.key_mapper = KeyMapper(self.mapper)
        self.wasd_mapper = WASDMapper(self.mapper)

        self.touch_reader.bind_touch_event(self._process_touch_event)
        mapper_event_dispatcher.register_callback(
            "ON_MENU_MODE_TOGGLE", self._set_is_visible
        )
        self.bridge_class.start_worker_processes(k_device_handle, m_device_handle)

        keyboard.wait()

    def _shutdown(self):
        if self.window_manager.get_foreground_window() != self.foreground_window:
            return
        if self.is_shutting_down:
            return
        self.is_shutting_down = True

        print("\n[ENGINE] - 'ESC' detected. Cleaning up...")
        try:
            if self.touch_reader is not None:
                self.touch_reader.stop()
            if self.mapper is not None:
                self.mapper.running = False
            if self.bridge_class is not None:
                self.bridge_class.shutdown()  # stop the heartbeat thread first
                self.bridge_class.release_all()

                procs = [
                    p
                    for p in (
                        getattr(self.bridge_class, "k_proc", None),
                        getattr(self.bridge_class, "m_proc", None),
                    )
                    if p is not None
                ]

                # Signal both to terminate before waiting on either.
                for p in procs:
                    if p.is_alive():
                        p.terminate()

                for p in procs:
                    p.join(timeout=1.0)
                    if p.is_alive():
                        p.kill()
                        p.join(timeout=1.0)

        except Exception:
            pass

        profiler_cleanup(profiler)
        print("\n[ENGINE] - Shutdown complete. Goodbye.")
        os._exit(0)


def profiler_cleanup(profiler: Profile | None):
    if profiler:
        profiler.disable()
        profiler.dump_stats(PROJECT_ROOT / "touch2key.prof")
        print("\n[ENGINE] - Profiling data saved to 'touch2key.prof'.")


def run(parser: ArgumentParser):
    global profiler
    args = parser.parse_args()

    if args.profile:
        import cProfile

        profiler = cProfile.Profile()
        profiler.enable()

    if not pre_flight_run():
        profiler_cleanup(profiler)
        sys.exit(1)

    try:
        multiprocessing.set_start_method("spawn", force=True)
    except RuntimeError:
        pass

    try:
        success, _instance_handle = check_single_instance(NAME)
    except RuntimeError as e:
        print(f"[ENGINE] - {e}")
        profiler_cleanup(profiler)
        os._exit(0)

    if not success:
        print(
            "[ENGINE] - Another instance of Touch2Key is already running. Exiting this instance."
        )
        profiler_cleanup(profiler)
        os._exit(0)

    _app = QApplication(sys.argv)
    _app.setQuitOnLastWindowClosed(True)
    _engine = Engine()
    try:
        _engine._start()
    except KeyboardInterrupt:
        _app.closeAllWindows()
        _engine._shutdown()
