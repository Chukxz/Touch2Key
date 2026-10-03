from __future__ import annotations

import logging
import threading
import time
from typing import TYPE_CHECKING

from modules.database import store
from modules.platforms import get_platform
from modules.utils import (
    LONG_DELAY,
    WINDOW_UPDATE_INTERVAL,
    SCANCODES,
    VKB_STRUCT,
    VKB_SLEEP_TIME,
    TOP_BEZEL_ID,
    M_LEFT,
    M_MIDDLE,
    M_RIGHT,
    MapperEvent,
    rotate_resolution,
)

if TYPE_CHECKING:
    from .layout_loader import LayoutLoader
    from .touch_reader import TouchReader
    from modules.platforms.base import AbstractBridge
    from modules.engine import Engine

logger = logging.getLogger("modules.core.mapper")


class Mapper:
    def __init__(
        self,
        layout_loader: LayoutLoader,
        touch_reader: TouchReader,
        bridge: AbstractBridge,
        pps: float,
        emulator: dict[str, str | None],
        window_id: int | None,
        ref: Engine,
    ):
        self.layout_loader = layout_loader
        self.mapper_event_dispatcher = self.layout_loader.mapper_event_dispatcher
        self.touch_reader = touch_reader
        self.bridge = bridge
        self.emulator = emulator
        self.pps = pps
        self.event_count = 0
        self.last_pulse_time = time.perf_counter()
        self.engine_ref = ref

        self.window_manager = get_platform().WindowManager()
        self.screen_w, self.screen_h = self.window_manager.get_screen_dimensions()
        self.lock = threading.Lock()
        self.stop_event = threading.Event()
        self.last_cursor_state = True
        self.last_cursor_check_time = 0
        self.window_update_interval = WINDOW_UPDATE_INTERVAL

        # Safe Target Window Resolution (Fallback to active foreground window)
        if window_id and self.window_manager.is_window_valid(window_id):
            self.window_id = window_id
        else:
            self.window_id = self.window_manager.get_foreground_window()
            logger.info(
                "Defaulting to foreground target window: HWND %s", self.window_id
            )

        self.game_window_class_name: str | None = (
            self.window_manager.get_window_class_name(self.window_id)
            if self.window_id
            else None
        )
        self.game_window_info: dict | None = (
            {
                "window_id": self.window_id,
                "left": 0,
                "top": 0,
                "width": self.screen_w,
                "height": self.screen_h,
            }
            if self.window_id
            else None
        )

        self.window_lost = self.window_id is None
        self.wasd_block = 0
        self.toggle_key_scancode: int | None = None

        self._update_config()

        self.mapper_event_dispatcher.register_callback(
            "ON_CONFIG_RELOAD", self._update_config
        )
        self.mapper_event_dispatcher.register_callback(
            "ON_TARGET_WINDOW_CHANGE", self.rebind_target_window
        )

        self.running = True
        self.window_thread = threading.Thread(
            target=self._update_game_window_info, daemon=True
        )
        self.window_thread.start()

        self.vkb_listener = threading.Thread(
            target=self._virtual_keyboard_listener, daemon=True
        )
        self.vkb_listener.start()

        self.mapper_event_dispatcher.dispatch(
            MapperEvent(action="ON_MENU_MODE_TOGGLE", is_visible=self.last_cursor_state)
        )
        self.bridge.set_respawn_callback(self._on_worker_respawn)

    def _update_config(self) -> None:
        settings = store.settings.get()
        layout = store.get_active_layout()
        if layout is None:
            logger.warning(
                "No active layout found in SQLite database. Mapper configuration update aborted."
            )
            return

        self.device_width = layout.width
        self.device_height = layout.height
        self.dpi = layout.dpi

        if settings.pps_alert_threshold > 0:
            self.pps = float(settings.pps_alert_threshold)
        if settings.toggle_key:
            self.emulator["toggle_key"] = settings.toggle_key
            self.toggle_key_scancode = SCANCODES.get(settings.toggle_key)

    def rebind_target_window(
        self, new_window_id: int | None, new_window_title: str
    ) -> None:
        with self.lock:
            if new_window_id and self.window_manager.is_window_valid(new_window_id):
                self.window_id = new_window_id
                self.game_window_class_name = self.window_manager.get_window_class_name(
                    new_window_id
                )
                self.game_window_info = self._get_window_info(new_window_id)
                self.window_lost = False
                logger.info(
                    "Engine live-rebound to Window ID: %s (%s)",
                    self.window_id,
                    self.game_window_class_name,
                )
            else:
                self.window_id = self.window_manager.get_foreground_window()
                self.game_window_class_name = (
                    self.window_manager.get_window_class_name(self.window_id)
                    if self.window_id
                    else None
                )
                self.game_window_info = (
                    self._get_window_info(self.window_id) if self.window_id else None
                )
                self.window_lost = self.window_id is None
                logger.warning(
                    "Target window invalidated. Rebound to foreground HWND: %s",
                    self.window_id,
                )

    def _get_window_info(self, window_id: int) -> dict:
        width, height = self.window_manager.get_window_dimensions(window_id)
        x, y = self.window_manager.get_window_position(window_id)

        self._pulse_status()

        is_visible, self.last_cursor_check_time = self.window_manager.is_cursor_visible(
            self.last_cursor_state, self.last_cursor_check_time
        )
        if is_visible != self.last_cursor_state:
            self.last_cursor_state = is_visible
            self.mapper_event_dispatcher.dispatch(
                MapperEvent(action="ON_MENU_MODE_TOGGLE", is_visible=is_visible)
            )

        return {
            "window_id": window_id,
            "left": x,
            "top": y,
            "width": width,
            "height": height,
        }

    def _update_game_window_info(self) -> None:
        while self.running and not self.stop_event.is_set():
            try:
                current_window_id = None
                with self.lock:
                    if self.game_window_info:
                        current_window_id = self.game_window_info.get("window_id")

                if current_window_id and self.window_manager.is_window_valid(
                    current_window_id
                ):
                    new_info = self._get_window_info(current_window_id)
                    with self.lock:
                        self.game_window_info = new_info
                        self.window_lost = False
                else:
                    if not self.window_lost:
                        with self.lock:
                            self.window_lost = True
                            self.game_window_info = None

                    try:
                        if self.game_window_class_name:
                            discovered = self._get_game_window_info()
                            with self.lock:
                                self.game_window_info = discovered
                                self.window_lost = False
                    except Exception:
                        with self.lock:
                            self.game_window_info = None

            except Exception as e:
                logger.debug("Window tracking exception: %s", e)

            sleep_duration = (
                LONG_DELAY if self.window_lost else self.window_update_interval
            )
            self.stop_event.wait(sleep_duration)

    def _get_game_window_info(self) -> dict:
        window_ids = self.window_manager.find_window_ids_by_class(
            self.game_window_class_name
        )
        target_info = None
        max_diag = 0

        for wid in window_ids:
            if not self.window_manager.is_window_visible(wid):
                continue
            info = self._get_window_info(wid)
            w, h = info["width"], info["height"]
            diag = (w * w + h * h) ** 0.5
            if diag > max_diag:
                max_diag = diag
                target_info = info

        if target_info is None:
            raise RuntimeError(
                f"No visible window found for class: '{self.game_window_class_name}'."
            )
        return target_info

    def device_to_game_abs(self, x: float, y: float) -> tuple[float, float]:
        rot = self.touch_reader.get_rotation()
        rot_dev_w, rot_dev_h = rotate_resolution(
            self.device_width, self.device_height, rot
        )
        rot_dev_w = max(1.0, float(rot_dev_w))
        rot_dev_h = max(1.0, float(rot_dev_h))

        norm_x = x / rot_dev_w
        norm_y = y / rot_dev_h

        with self.lock:
            win = self.game_window_info

        if win:
            target_x = win["left"] + norm_x * win["width"]
            target_y = win["top"] + norm_y * win["height"]
        else:
            target_x = norm_x * self.screen_w
            target_y = norm_y * self.screen_h

        return target_x, target_y

    def _pulse_status(self) -> None:
        now = time.perf_counter()
        elapsed = now - self.last_pulse_time
        if elapsed >= 5.0:
            current_count = self.event_count
            self.event_count = 0
            self.last_pulse_time = now
            pps = current_count / elapsed
            status = (
                "HEALTHY" if pps >= self.pps else ("IDLE" if pps == 0 else "LOW RATE")
            )
            logger.info(
                "Rate: %5.1f Hz | Status: %s | WASD Block: %d",
                pps,
                status,
                self.wasd_block,
            )

    def _virtual_keyboard_listener(self) -> None:
        while self.running and not self.stop_event.is_set():
            try:
                payload = self.engine_ref.vkb_reader.recv_bytes()
                state, scancode = VKB_STRUCT.unpack(payload)

                is_toggle_mode = scancode == TOP_BEZEL_ID
                is_mouse_left = scancode == M_LEFT
                is_mouse_middle = scancode == M_MIDDLE
                is_mouse_right = scancode == M_RIGHT

                if state == 0:
                    if is_toggle_mode:
                        self.engine_ref.toggle_mode()
                    elif is_mouse_left:
                        self.bridge.left_click_down()
                    elif is_mouse_middle:
                        self.bridge.middle_click_down()
                    elif is_mouse_right:
                        self.bridge.right_click_down()
                    else:
                        self.bridge.key_down(scancode)

                elif state == 1:
                    if is_toggle_mode:
                        pass
                    elif is_mouse_left:
                        self.bridge.left_click_up()
                    elif is_mouse_middle:
                        self.bridge.middle_click_up()
                    elif is_mouse_right:
                        self.bridge.right_click_up()
                    else:
                        self.bridge.key_up(scancode)

            except EOFError:
                self.stop_event.wait(VKB_SLEEP_TIME)
            except Exception as e:
                logger.warning("Virtual Keyboard worker exception: %s", e)
                self.stop_event.wait(VKB_SLEEP_TIME)

    def _on_worker_respawn(self, worker_type: str) -> None:
        self.mapper_event_dispatcher.dispatch(
            MapperEvent(action="ON_WORKER_RESPAWN", worker_type=worker_type)
        )

    def stop(self) -> None:
        self.running = False
        self.stop_event.set()
