from __future__ import annotations

import logging
import threading
import time
from typing import TYPE_CHECKING

from modules.platforms import get_platform
from modules.utils import (
    DEF_DPI,
    LONG_DELAY,
    WINDOW_UPDATE_INTERVAL,
    SCANCODES,
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
        self.config = self.layout_loader.config
        self.mapper_event_dispatcher = self.layout_loader.mapper_event_dispatcher
        self.touch_reader = touch_reader
        self.bridge = bridge
        self.emulator = emulator
        self.pps = pps
        self.event_count = 0
        self.last_pulse_time = time.perf_counter()
        self.engine_ref = ref
        self.is_floating_joystick: bool = True

        self.window_manager = get_platform().WindowManager()
        self.screen_w, self.screen_h = self.window_manager.get_screen_dimensions()
        self.lock = threading.Lock()
        self.agg_lock = threading.Lock()
        self.last_cursor_state = True
        self.last_cursor_check_time = 0
        self.window_update_interval = WINDOW_UPDATE_INTERVAL

        # Safe Target Window Resolution (Fallback to active foreground window)
        if window_id and self.window_manager.is_window_valid(window_id):
            self.window_id = window_id
        else:
            self.window_id = self.window_manager.get_foreground_window()
            logger.info("Defaulting to foreground target window: HWND %s", self.window_id)

        self.game_window_class_name: str | None = (
            self.window_manager.get_window_class_name(self.window_id) if self.window_id else None
        )
        self.game_window_info: dict | None = {
            "window_id": self.window_id,
            "left": 0,
            "top": 0,
            "width": self.screen_w,
            "height": self.screen_h,
        } if self.window_id else None

        self.window_lost = self.window_id is None
        self.wasd_block = 0
        self.toggle_key_scancode: int | None = None

        self._update_config()

        self.mapper_event_dispatcher.register_callback(
            "ON_CONFIG_RELOAD", self._update_config
        )

        self.running = True
        self.window_thread = threading.Thread(
            target=self._update_game_window_info, daemon=True
        )
        self.window_thread.start()

        self.acc_x = 0.0
        self.acc_y = 0.0
        self.aggregated_mouse_moves: list[tuple[float, float]] = []
        self.aggregate_mouse_moves_thread = threading.Thread(
            target=self._aggregate_mouse_moves, daemon=True
        )
        self.aggregate_mouse_moves_thread.start()

        self.mapper_event_dispatcher.dispatch(
            MapperEvent(action="ON_MENU_MODE_TOGGLE", is_visible=self.last_cursor_state)
        )
        self.bridge.set_respawn_callback(self._on_worker_respawn)

    def _update_config(self) -> None:
        with self.lock:
            self.device_width = self.layout_loader.width
            self.device_height = self.layout_loader.height
            self.dpi = self.layout_loader.dpi

            # Hot-reload PPS warning threshold
            s = self.config.settings
            if hasattr(s, "pps_alert_threshold") and s.pps_alert_threshold > 0:
                self.pps = float(s.pps_alert_threshold)

            # Hot-reload Menu Toggle Key
            if hasattr(s, "toggle_key") and s.toggle_key:
                self.emulator["toggle_key"] = s.toggle_key
                self.toggle_key_scancode = SCANCODES.get(s.toggle_key)

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
        while self.running:
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

            time.sleep(LONG_DELAY if self.window_lost else self.window_update_interval)

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
        return (x / rot_dev_w) * self.screen_w, (y / rot_dev_h) * self.screen_h

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

    def _aggregate_mouse_moves(self) -> None:
        while self.running:
            start_time = time.perf_counter()
            if self.touch_reader.active_touches > 0:
                with self.agg_lock:
                    snapshot = self.aggregated_mouse_moves.copy()
                    self.aggregated_mouse_moves = []

                sum_dx = sum(v[0] for v in snapshot)
                sum_dy = sum(v[1] for v in snapshot)
                self.mapper_event_dispatcher.dispatch(
                    MapperEvent(
                        action="ON_AGGREGATION",
                        sum_dx=sum_dx,
                        sum_dy=sum_dy,
                        acc_x=self.acc_x,
                        acc_y=self.acc_y,
                    )
                )
            else:
                self.acc_x = 0.0
                self.acc_y = 0.0

            elapsed = time.perf_counter() - start_time
            sleep_duration = max(0.0, self.touch_reader.move_interval - elapsed)
            time.sleep(sleep_duration)

    def _on_worker_respawn(self, worker_type: str) -> None:
        self.mapper_event_dispatcher.dispatch(
            MapperEvent(action="ON_WORKER_RESPAWN", worker_type=worker_type)
        )
