from __future__ import annotations
from typing import TYPE_CHECKING

import time
import threading

from mapper_module.platforms import get_platform
from mapper_module.utils import (
    DEF_DPI,
    LONG_DELAY,
    WINDOW_UPDATE_INTERVAL,
    SCANCODES,
    MapperEvent,
    rotate_resolution,
)

if TYPE_CHECKING:
    from .json_loader import JSONLoader
    from .touch_reader import TouchReader
    from mapper_module.platforms.base import AbstractBridge


class Mapper:
    def __init__(
        self,
        json_loader: JSONLoader,
        touch_reader: TouchReader,
        bridge: AbstractBridge,
        pps: float,
        emulator: dict[str, str | None],
        window_id: int,
    ):

        # Setup Dependencies
        self.json_loader = json_loader
        self.config = self.json_loader.config
        self.mapper_event_dispatcher = self.json_loader.mapper_event_dispatcher
        self.touch_reader = touch_reader
        self.bridge = bridge
        self.emulator = emulator
        self.pps = pps
        self.event_count = 0
        self.last_pulse_time = time.perf_counter()

        # Toggle key — required but guard defensively
        toggle_key = emulator.get("toggle_key")
        self.toggle_key_scancode: int | None = (
            SCANCODES.get(toggle_key) if toggle_key else None
        )

        # Window Tracking Setup
        self.window_manager = get_platform().WindowManager()
        self.screen_w, self.screen_h = self.window_manager.get_screen_dimensions()
        self.lock = threading.Lock()
        self.agg_lock = threading.Lock()
        self.last_cursor_state = True  # Cursor showing (Default)
        self.last_cursor_check_time = 0
        self.window_update_interval = WINDOW_UPDATE_INTERVAL

        # Use the selected window ID directly instead of scanning by title
        self.window_id: int = window_id
        self.game_window_class_name: str | None = (
            self.window_manager.get_window_class_name(self.window_id)
        )

        if not self.game_window_class_name:
            self.game_window_class_name = None

        # Seed with the selected window so the tracker doesn't start in lost state
        self.game_window_info: dict | None = {
            "window_id": self.window_id,
            "left": 0,
            "top": 0,
            "width": 0,
            "height": 0,
        }
        self.window_lost = False

        # Config & State
        self.wasd_block = 0
        self._update_config()

        # Register Callbacks
        self.mapper_event_dispatcher.register_callback(
            "ON_CONFIG_RELOAD", self._update_config
        )

        # Start the window tracking thread
        self.running = True
        self.window_thread = threading.Thread(
            target=self._update_game_window_info, daemon=True
        )
        self.window_thread.start()

        # Mouse moves aggregation
        self.acc_x = 0.0
        self.acc_y = 0.0
        self.aggregated_mouse_moves: list[tuple[float, float]] = []
        self.aggregate_mouse_moves_thread = threading.Thread(
            target=self._aggregate_mouse_moves, daemon=True
        )
        self.aggregate_mouse_moves_thread.start()

        # Register and dispatch callbacks
        self.mapper_event_dispatcher.dispatch(
            MapperEvent(action="ON_MENU_MODE_TOGGLE", is_visible=self.last_cursor_state)
        )
        self.bridge.set_respawn_callback(self._on_worker_respawn)

    def _update_config(self):
        with self.lock:
            self.device_width = self.json_loader.width
            self.device_height = self.json_loader.height
            self.dpi = self.json_loader.dpi
            print(
                f"\n[MAPPER] - Mapping from Device synced to Resolution: {self.device_width}x{self.device_height}, DPI: {self.dpi}."
            )
            print(
                f"\n[MAPPER] - Current Screen Resolution: {self.screen_w}x{self.screen_h}."
            )

    # Window Management
    def _get_window_info(self, window_id: int) -> dict:
        width, height = self.window_manager.get_window_dimensions(window_id)
        x, y = self.window_manager.get_window_position(window_id)

        self._pulse_status()

        # Check cursor visibility
        # GAME MODE - cursor hidden
        # MENU MODE - cursor visible
        is_visible, self.last_cursor_check_time = self.window_manager.is_cursor_visible(
            self.last_cursor_state, self.last_cursor_check_time
        )

        if not is_visible == self.last_cursor_state:
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

    def _update_game_window_info(self):
        """Background thread for updating the game window info."""
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

                    if self.window_lost:
                        print(f"\n[MAPPER] - Acquired game window!")

                    with self.lock:
                        self.game_window_info = new_info
                        self.window_lost = False

                else:
                    if not self.window_lost:
                        print(
                            "\n[MAPPER] - Game window lost! Scanning for new window..."
                        )
                        with self.lock:
                            self.window_lost = True
                            self.game_window_info = None

                    try:
                        # Re-scan by class name (survives window handle changes)
                        if not self.game_window_class_name:
                            raise RuntimeError(
                                f"\n[MAPPER] - No class name available to scan for window."
                            )

                        discovered_info = self._get_game_window_info()

                        with self.lock:
                            self.game_window_info = discovered_info
                            self.window_lost = False
                        print("\n[MAPPER] - New window handle bound.")

                    except RuntimeError as e:
                        print(e)
                        with self.lock:
                            self.game_window_info = None

            except Exception as e:
                print(f"\n[MAPPER] - Window tracking error: {e}.")

            sleep_time = LONG_DELAY if self.window_lost else self.window_update_interval
            time.sleep(sleep_time)

    def _get_game_window_info(self) -> dict:
        """Scans all windows matching the known class name and picks the largest visible one."""
        window_ids = self.window_manager.find_window_ids_by_class(
            self.game_window_class_name
        )
        target_info = None
        max_diag = 0

        for window_id in window_ids:
            if not self.window_manager.is_window_visible(window_id):
                continue

            info = self._get_window_info(window_id)
            w, h = info["width"], info["height"]
            diag = (w * w + h * h) ** 0.5

            if diag > max_diag:
                max_diag = diag
                target_info = info

        if target_info is None:
            raise RuntimeError(
                f"\n[MAPPER] - No visible window found for class: '{self.game_window_class_name}'."
            )

        return target_info

    def device_to_game_abs(self, x, y):
        """Thread-safe absolute mapping."""
        rot = self.touch_reader.get_rotation()
        rot_dev_w, rot_dev_h = rotate_resolution(
            self.device_width, self.device_height, rot
        )
        return (x / rot_dev_w) * self.screen_w, (y / rot_dev_h) * self.screen_h

    def dp_to_px(self, dp):
        return dp * (self.dpi / DEF_DPI)

    def px_to_dp(self, px):
        return px * (DEF_DPI / self.dpi)

    def _pulse_status(self):
        now = time.perf_counter()
        elapsed = now - self.last_pulse_time

        if elapsed >= 5.0:
            current_count = self.event_count
            self.event_count = 0
            self.last_pulse_time = now
            pps = current_count / elapsed

            status = "HEALTHY" if pps >= self.pps else "LOW RATE"
            if pps == 0:
                status = "IDLE/DISCONNECTED"
            block_indicator = (
                f"[BLOCK ON ({self.wasd_block})]" if self.wasd_block > 0 else "[OPEN]"
            )

            print(
                f"\n[MAPPER] - Rate: {pps:>5.1f} Hz | Status: {status:<15} | WASD: {block_indicator:<12}"
            )

    def _aggregate_mouse_moves(self):
        """Background thread for aggregating secondary mouse input."""
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
            sleep_duration = max(0, self.touch_reader.move_interval - elapsed)
            time.sleep(sleep_duration)

    def _on_worker_respawn(self, worker_type: str):
        """Fired from the bridge's respawn thread. Re-broadcasts as a
        MapperEvent so KeyMapper/MouseMapper/WASDMapper can resync their
        held-input bookkeeping against the fresh, empty worker state."""
        self.mapper_event_dispatcher.dispatch(
            MapperEvent(action="ON_WORKER_RESPAWN", worker_type=worker_type)
        )
