from __future__ import annotations
from typing import TYPE_CHECKING

import math
from enum import IntFlag
import threading

from mapper_module.utils import SCANCODES, UP, DOWN, PRESSED

if TYPE_CHECKING:
    from .mapper import Mapper
    from mapper_module.utils import TouchEvent


class _State(IntFlag):
    NONE = 0
    W = 1 << 0
    A = 1 << 1
    S = 1 << 2
    D = 1 << 3


class WASDMapper:
    def __init__(self, mapper: Mapper):
        self.mapper = mapper
        self.bridge = mapper.bridge
        self.json_loader = mapper.json_loader
        self.config = mapper.config
        self.mapper_event_dispatcher = self.mapper.mapper_event_dispatcher
        sprint_key = mapper.emulator["sprint_key"]
        self.sprint_key_code = None
        self.wasd_lock = threading.Lock()

        if sprint_key is not None:
            try:
                scancode_value = SCANCODES[sprint_key]
                self.sprint_key_code = (
                    int(scancode_value, 16)
                    if isinstance(scancode_value, str)
                    else int(scancode_value)
                )
            except (KeyError, ValueError, TypeError):
                self.sprint_key_code = None

        # Pre-convert scancodes
        self.KEY_W = (
            int(SCANCODES["w"], 16)
            if isinstance(SCANCODES["w"], str)
            else int(SCANCODES["w"])
        )
        self.KEY_A = (
            int(SCANCODES["a"], 16)
            if isinstance(SCANCODES["a"], str)
            else int(SCANCODES["a"])
        )
        self.KEY_S = (
            int(SCANCODES["s"], 16)
            if isinstance(SCANCODES["s"], str)
            else int(SCANCODES["s"])
        )
        self.KEY_D = (
            int(SCANCODES["d"], 16)
            if isinstance(SCANCODES["d"], str)
            else int(SCANCODES["d"])
        )

        self.sector_to_state = {
            0: _State.D,  # 0: Right
            1: _State.S | _State.D,  # 1: Down-Right
            2: _State.S,  # 2: Down
            3: _State.S | _State.A,  # 3: Down-Left
            4: _State.A,  # 4: Left
            5: _State.W | _State.A,  # 5: Up-Left
            6: _State.W,  # 6: Up
            7: _State.W | _State.D,  # 7: Up-Right
        }

        self.state_value_to_key = {
            1: self.KEY_W,
            2: self.KEY_A,
            4: self.KEY_S,
            8: self.KEY_D,
        }

        self.ALL_DIRECTIONS = (_State.W, _State.A, _State.S, _State.D)

        self.PI_8 = math.pi / 8
        self.INV_PI_4 = 1.0 / (math.pi / 4.0)
        self.sprinting = False
        self.current_mask = _State.NONE
        self.center_x = 0.0
        self.center_y = 0.0
        self.last_sector = None

        # Radius Placeholders
        self.raw_inner_radius = 100.0
        self.raw_outer_radius = 150.0
        self.inner_radius_sq = 10000.0
        self.outer_radius_sq = 22500.0
        self.outer_radius = 150.0
        self.deadzone = 10
        self.deadzone_sq = 100.0
        self.sensitivity = 1.0

        # Init (Order matters: MouseWheel -> Recalc -> Config -> Recalc (again))
        self._update_mouse_wheel()
        self._update_config()

        # Register callbacks
        self.mapper_event_dispatcher.register_callback(
            "ON_CONFIG_RELOAD", self._update_config
        )
        self.mapper_event_dispatcher.register_callback(
            "ON_JSON_RELOAD", self._update_mouse_wheel
        )
        self.mapper_event_dispatcher.register_callback(
            "ON_WASD_BLOCK", self._on_wasd_block
        )
        self.mapper_event_dispatcher.register_callback(
            "ON_WORKER_RESPAWN", self._on_worker_respawn
        )

    def _update_config(self):
        print(f"\n[WASDMAPPER] - Reloading config...")
        try:
            with self.config.config_lock:
                # Get Joystick Settings (Deadzone, Hysteresis)
                joystick_conf = self.config.config_data.get("joystick", {})
                self.deadzone = joystick_conf.get("deadzone", 0.1)
                self.hysteresis = math.radians(joystick_conf.get("hysteresis", 5.0))

                # Get Mouse Settings (Sensitivity)
                # We reuse the mouse sensitivity here!
                mouse_conf = self.config.config_data.get("mouse", {})
                self.sensitivity = mouse_conf.get("sensitivity", 1.0)

                # Recalculate Thresholds
                self._recalc_thresholds()

        except Exception as e:
            print(f"\n[WASDMAPPER] - Joystick config error: {e}")

    def _update_mouse_wheel(self):
        with self.config.config_lock:
            print(f"\n[WASDMAPPER] - Updating mousewheel radius...")
            self.raw_inner_radius, d_radius = self.json_loader.get_mouse_wheel_info()
            self.raw_outer_radius = self.raw_inner_radius + d_radius

            # Recalculate based on current sensitivity
            self._recalc_thresholds()

    def _recalc_thresholds(self):
        """
        Applies Mouse Sensitivity to the raw JSON radii.
        Higher Sensitivity = Smaller mechanical radius = Less physical movement required.
        """
        # Protect against Zero Division or negative sens
        sens = max(0.1, self.sensitivity)

        # Scale down the required movement distance
        # e.g. Radius 200px / Sens 2.0 = Effective 100px activation
        inner_radius = self.raw_inner_radius / sens
        self.outer_radius = self.raw_outer_radius / sens

        # Calculate Sprint Threshold (Squared)
        self.inner_radius_sq = inner_radius * inner_radius

        # Calculate Deadzone Threshold (Squared)
        # Deadzone is % of the EFFECTIVE radius.
        dz_px = inner_radius * self.deadzone
        self.deadzone_sq = dz_px * dz_px

        # Calculate Outer radius squared for Leash Logic
        self.outer_radius_sq = self.outer_radius * self.outer_radius

        print(
            f"\n[WASDMAPPER] - Shared Sensitivity: {sens}x\
                \n             - Walk Distance: {inner_radius:.1f}px (was {self.raw_inner_radius:.1f}px)\
                \n             - Sprint Distance: {self.outer_radius:.1f}px (was {self.raw_outer_radius:.1f}px)"
        )

    def _on_wasd_block(self):
        if self.mapper.wasd_block > 0:
            self.touch_up()

    def _touch_down(self, touch_event: TouchEvent, is_visible: bool):
        if self.mapper.wasd_block == 0 and not is_visible:
            self.center_x = touch_event.x
            self.center_y = touch_event.y

    def _touch_pressed(self, touch_event: TouchEvent, is_visible: bool):
        if self.mapper.wasd_block > 0 or is_visible:
            self.touch_up()
            return

        vx = touch_event.x - self.center_x
        vy = touch_event.y - self.center_y
        dist_sq = vx * vx + vy * vy

        # Deadzone Check (Optimized)
        if dist_sq < self.deadzone_sq:
            # If we are inside deadzone, lift keys
            if self.current_mask != _State.NONE:
                self.touch_up()
            return

        # Leash Logic (Floating Joystick center follow)
        # We use RAW outer radius for leashing so the joystick center visually
        # follows your thumb naturally, even if sensitivity is high.
        if dist_sq > self.outer_radius_sq and self.outer_radius_sq > 0:
            dist = math.sqrt(dist_sq)
            scale = self.outer_radius / dist
            self.center_x = touch_event.x - (vx * scale)
            self.center_y = touch_event.y - (vy * scale)
            vx = touch_event.x - self.center_x
            vy = touch_event.y - self.center_y

        # Angle Calculation
        angle_rad = math.atan2(vy, vx)
        if angle_rad < 0:
            angle_rad += 2 * math.pi
        new_sector = int((angle_rad + self.PI_8) * self.INV_PI_4) % 8

        # Hysteresis Logic
        if self.last_sector is not None:
            current_sector_center = self.last_sector * (math.pi / 4)
            angle_diff = (angle_rad - current_sector_center + math.pi) % (
                2 * math.pi
            ) - math.pi
            if abs(angle_diff) < (self.PI_8 + self.hysteresis):
                new_sector = self.last_sector

        self.last_sector = new_sector

        # Sprint Check
        # Uses the SENSITIVITY-SCALED threshold
        sprint = False
        if self.sprint_key_code is not None:
            if dist_sq > self.inner_radius_sq:
                sprint = True

        self._apply_keys(new_sector, sprint)

    def touch_up(self):
        with self.wasd_lock:
            for key_flag in self.ALL_DIRECTIONS:
                if key_flag in self.current_mask:
                    self.bridge.key_up(self.state_value_to_key[key_flag.value])

            if self.sprint_key_code is not None and self.sprinting:
                self.bridge.key_up(self.sprint_key_code)

            self.sprinting = False
            self.current_mask = _State.NONE
            self.center_x = 0.0
            self.center_y = 0.0
            self.last_sector = None

    def _apply_keys(self, sector, sprint=False):
        with self.wasd_lock:
            target_mask = self.sector_to_state[sector]

            # Identify which directional keys to change
            to_release = self.current_mask & ~target_mask
            to_press = target_mask & ~self.current_mask

            # Release directional keys no longer needed
            for key_flag in self.ALL_DIRECTIONS:
                if key_flag in to_release:
                    self.bridge.key_up(self.state_value_to_key[key_flag.value])

            # Handle Sprint (Shift)
            # Ensure sprint only triggers if we are actually moving
            should_sprint = sprint and target_mask

            if self.sprint_key_code is not None:
                if self.sprinting and not should_sprint:
                    self.bridge.key_up(self.sprint_key_code)
                    self.sprinting = False
                elif not self.sprinting and should_sprint:
                    self.bridge.key_down(self.sprint_key_code)
                    self.sprinting = True

            # Press new directional keys
            for key_flag in self.ALL_DIRECTIONS:
                if key_flag in to_press:
                    self.bridge.key_down(self.state_value_to_key[key_flag.value])

            self.current_mask = target_mask

    def process_touch(self, action, touch_event: TouchEvent, is_visible: bool):
        if action == PRESSED:
            self._touch_pressed(touch_event, is_visible)

        elif action == DOWN:
            self._touch_down(touch_event, is_visible)

        elif action == UP:
            self.touch_up()

    def _on_worker_respawn(self, worker_type: str):
        """Keyboard-only — WASD/sprint both go through key_down/key_up.
        Reset mask/sprint, not the joystick anchor (center_x/center_y/
        last_sector), so the finger's still-live position stays valid and
        the next _touch_pressed tick re-diffs against a clean mask."""
        if worker_type != "keyboard":
            return
        with self.wasd_lock:
            self.current_mask = _State.NONE
            self.sprinting = False
