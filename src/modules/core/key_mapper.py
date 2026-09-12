from __future__ import annotations
from typing import TYPE_CHECKING

import threading
from mapper_module.utils import (
    RECT,
    CIRCLE,
    M_LEFT,
    M_RIGHT,
    M_MIDDLE,
    MOUSE_WHEEL_CODE,
    SPRINT_DISTANCE_CODE,
    is_in_circle,
    is_in_rect,
    MapperEvent,
    DOWN,
    UP,
    PRESSED,
)

if TYPE_CHECKING:
    from .mapper import Mapper
    from mapper_module.utils import TouchEvent


class KeyMapper:
    def __init__(self, mapper: Mapper):
        self.mapper = mapper
        self.config = mapper.config
        self.mapper_event_dispatcher = self.mapper.mapper_event_dispatcher
        self.bridge = mapper.bridge

        # State Tracking: { slot_int: [[scancode(int), zone_data(dict), is_wasd_finger(bool), prevs(tuple[int, int])],...] }
        self.touch_events_dict: dict[int, list[tuple[int, dict, bool]]] = {}
        self.touch_events_prevs: dict[int, tuple[float, float]] = {}
        self.touch_events_lock = threading.Lock()
        self.scancode_ref_counts = {}  # Tracks how many fingers are pressing a scancode

        # Blacklist for O(1) filtering
        self.ignored_names = {MOUSE_WHEEL_CODE, SPRINT_DISTANCE_CODE}

        # Optimized List for the Touch Loop
        self.active_zones = []

        # Initialize data structures
        self._process_json_data()

        # Register callbacks
        self.mapper_event_dispatcher.register_callback(
            "ON_JSON_RELOAD", self._process_json_data
        )
        self.mapper_event_dispatcher.register_callback(
            "ON_WORKER_RESPAWN", self._on_worker_respawn
        )

    def _process_json_data(self):
        """Pre-processes JSON into a high-speed iteration list."""
        temp_zones: list[tuple[int, dict]] = []
        # Get raw data from the loader
        with self.config.config_lock:
            raw_data: list[tuple[str, dict]] = self.mapper.json_loader.json_data.copy()

        for scancode, value in raw_data:
            # Filter out ignored functional codes
            if value.get("name", "") in self.ignored_names:
                continue

            # Pre-convert scancodes to integers once to save CPU during gameplay
            try:
                s_int = (
                    int(scancode, 16) if isinstance(scancode, str) else int(scancode)
                )
                temp_zones.append((s_int, value))
            except (ValueError, TypeError):
                continue

        self.release_all()
        with self.touch_events_lock:
            self.active_zones = temp_zones

        print(f"\n[KEYMAPPER] - Hot-path ready: {len(self.active_zones)} zones active.")

    def _send_key_touch_event(self, scancode, down=True):
        """Prepares input to be dispatched to the Bridge."""
        if down:
            # Only dispatch key down if this is the first finger for this scancode
            count = self.scancode_ref_counts.get(scancode, 0)
            if count == 0:
                self._dispatch_to_bridge(scancode, True)
            self.scancode_ref_counts[scancode] = count + 1

        else:
            # Only dispatch key up if this is the last finger for this scancode
            count = self.scancode_ref_counts.get(scancode, 0)
            if count > 0:
                new_count = count - 1
                self.scancode_ref_counts[scancode] = new_count
                if new_count == 0:
                    self._dispatch_to_bridge(scancode, False)

    def _dispatch_to_bridge(self, scancode, down):
        """Dispatches input to the Bridge."""
        if down:
            if scancode == M_LEFT:
                self.bridge.left_click_down()
            elif scancode == M_RIGHT:
                self.bridge.right_click_down()
            elif scancode == M_MIDDLE:
                self.bridge.middle_click_down()
            else:
                self.bridge.key_down(scancode)
        else:
            if scancode == M_LEFT:
                self.bridge.left_click_up()
            elif scancode == M_RIGHT:
                self.bridge.right_click_up()
            elif scancode == M_MIDDLE:
                self.bridge.middle_click_up()
            else:
                self.bridge.key_up(scancode)

    def _touch_down(self, touch_event: TouchEvent, is_visible: bool):
        """Triggered on finger contact. Scans active_zones for a hit."""

        if self.mapper.device_width <= 0 or self.mapper.device_height <= 0:
            return

        # Normalize coordinates
        nx = touch_event.x / self.mapper.device_width
        ny = touch_event.y / self.mapper.device_height

        # Fast iteration through the pre-filtered list
        with self.touch_events_lock:
            for scancode, value in self.active_zones:
                hit = False
                v_type = value["type"]

                if v_type == CIRCLE:
                    if is_in_circle(nx, ny, value["cx"], value["cy"], value["r"]):
                        hit = True
                elif v_type == RECT:
                    if is_in_rect(
                        nx, ny, value["x1"], value["x2"], value["y1"], value["y2"]
                    ):
                        hit = True

                if is_visible:
                    if (
                        self.mapper.toggle_key_scancode is None
                        or scancode != self.mapper.toggle_key_scancode
                    ):
                        hit = False

                if hit:
                    self._send_key_touch_event(scancode, down=True)

                    if touch_event.slot not in self.touch_events_dict:
                        self.touch_events_dict[touch_event.slot] = []
                    self.touch_events_dict[touch_event.slot].append(
                        (scancode, value, touch_event.is_wasd)
                    )

                    # Skip aggregation for the identified mouse finger — it's
                    # already driven directly by MouseMapper. Registering it
                    # here too would double-dispatch REL for the same drag.
                    if value["move_camera"] and not touch_event.is_mouse:
                        if touch_event.slot not in self.touch_events_prevs:
                            self.touch_events_prevs[touch_event.slot] = (
                                touch_event.x,
                                touch_event.y,
                            )

                    if touch_event.is_wasd:
                        self.mapper.wasd_block += 1
                        self.mapper_event_dispatcher.dispatch(
                            MapperEvent(action="ON_WASD_BLOCK")
                        )


    def _touch_pressed(self, touch_event: TouchEvent):
        """O(1) Dictionary lookup to process deltas if any of the key(s) tied to a finger are mouse move enabled."""
        if touch_event.slot in self.touch_events_prevs:
            prev = self.touch_events_prevs[touch_event.slot]
            raw_dx = touch_event.x - prev[0]
            raw_dy = touch_event.y - prev[1]
            self.touch_events_prevs[touch_event.slot] = (touch_event.x, touch_event.y)
            with self.mapper.agg_lock:
                self.mapper.aggregated_mouse_moves.append((raw_dx, raw_dy))

    def _touch_up(self, touch_event: TouchEvent):
        """O(1) Dictionary lookup to release keys when finger lifts."""
        with self.touch_events_lock:
            data_list = self.touch_events_dict.pop(touch_event.slot, [])
            for scancode, _, is_wasd in data_list:
                self._send_key_touch_event(scancode, down=False)
                self.touch_events_prevs.pop(touch_event.slot, ())
                if is_wasd:
                    self.mapper.wasd_block = max(0, self.mapper.wasd_block - 1)
                    self.mapper_event_dispatcher.dispatch(
                        MapperEvent(action="ON_WASD_BLOCK")
                    )

    def process_touch(self, action, touch_event: TouchEvent, is_visible: bool):
        if action == PRESSED:
            self._touch_pressed(touch_event)

        elif action == DOWN:
            self._touch_down(touch_event, is_visible)

        elif action == UP:
            self._touch_up(touch_event)


    def _on_worker_respawn(self, worker_type: str):
        """touch_events_dict reflects ground truth — fingers never moved,
        only the downstream driver forgot. Re-arm the fresh worker for
        whatever's still tracked, without touching touch tracking itself."""
        with self.touch_events_lock:
            affected_counts: dict[int, int] = {}
            for entries in self.touch_events_dict.values():
                for scancode, _, __ in entries:
                    is_mouse_button = scancode in (M_LEFT, M_RIGHT, M_MIDDLE)
                    if (worker_type == "mouse") != is_mouse_button:
                        continue
                    affected_counts[scancode] = affected_counts.get(scancode, 0) + 1

            for scancode, count in affected_counts.items():
                self.scancode_ref_counts[scancode] = count
                self._dispatch_to_bridge(scancode, True)

    def release_all(self):
        """Flushes all current input states."""
        with self.touch_events_lock:
            for slot in list(self.touch_events_dict.keys()):
                data_list = self.touch_events_dict.pop(slot, [])
                for scancode, _, __ in data_list:
                    self._send_key_touch_event(scancode, down=False)
            self.touch_events_dict.clear()
            self.touch_events_prevs.clear()
            self.scancode_ref_counts.clear()
            self.mapper.wasd_block = 0
