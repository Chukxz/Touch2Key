from __future__ import annotations
from typing import TYPE_CHECKING

from .utils import (
    DOWN, UP, PRESSED,
)

if TYPE_CHECKING:
    from .mapper import Mapper
    from .utils import TouchEvent

class MouseMapper():
    def __init__(self, mapper:Mapper):
        self.mapper = mapper
        self.mapper_event_dispatcher = self.mapper.mapper_event_dispatcher
        self.interception_bridge = mapper.interception_bridge
        self.config = mapper.config

        self.prev_x = None
        self.prev_y = None
        self.acc_x = 0.0
        self.acc_y = 0.0
        self.left_down = False
        self.scaling_factor = 1.0

        self.update_config()

        # Register Callbacks
        self.mapper_event_dispatcher.register_callback("ON_CONFIG_RELOAD", self.update_config)


    def update_config(self):
        """Pre-calculates sensitivity to keep the touch_pressed loop lean."""
        print(f"[Info] MouseMapper syncing sensitivity...")
        try:
            with self.config.config_lock:
                mouse_cfg = self.config.config_data.get('mouse', {})
                base_sens = mouse_cfg.get('sensitivity', 1.0)
                
                pc_w = self.mapper.screen_w
                dev_w = self.mapper.json_loader.width

                if dev_w > 0:
                    resolution_ratio = pc_w / dev_w
                else:
                    print("[Error] Device width is not a positive integer. Defaulting ratio to 1.0")
                    resolution_ratio = 1.0

                self.scaling_factor = base_sens * resolution_ratio
                
                print(f"[Mouse] Sync: PC width ({pc_w}px) / Phone width ({dev_w}px) = Ratio ({resolution_ratio:.2f})")
                print(f"[Mouse] Final Scaling Factor: {self.scaling_factor:.4f} (User Sensitivity: {base_sens}x)")

        except Exception as e:
            print(f"[Error] Mouse config update failed: {e}")
            self.scaling_factor = 1.0

    def touch_down(self, touch_event:TouchEvent, is_visible:bool):
        """
        Anchor the start position and reset precision accumulators
        """
        self.prev_x = touch_event.x
        self.prev_y = touch_event.y
        self.acc_x = 0.0
        self.acc_y = 0.0

        if is_visible:           
            _x, _y = self.mapper.device_to_game_abs(self.prev_x, self.prev_y)
            self.interception_bridge.mouse_move_abs(_x, _y)
            self.interception_bridge.left_click_down()
            self.left_down = True


    def touch_pressed(self, touch_event:TouchEvent, is_visible:bool):
        """
        The 'Hot Path'. This code runs hundreds of times per second.
        Optimized to minimize branching and float operations.
        """
        if self.prev_x is None or self.prev_y is None:
            self.touch_down(touch_event, is_visible)
            return

        # Calculate Raw Delta
        raw_dx = touch_event.x - self.prev_x
        raw_dy = touch_event.y - self.prev_y

        # Update anchors immediately
        self.prev_x = touch_event.x
        self.prev_y = touch_event.y

        # Apply Multiplier and add previous remainders (Sub-pixel precision)
        # Using float math here is necessary for 1:1 feel
        calc_dx = (raw_dx * self.scaling_factor) + self.acc_x
        calc_dy = (raw_dy * self.scaling_factor) + self.acc_y

        # Truncate to Integer (Actual pixels to move)
        final_dx = int(calc_dx)
        final_dy = int(calc_dy)

        # Fast-Exit for Noise
        # If the delta is less than 1 physical pixel, just keep the remainder and exit.
        if final_dx == 0 and final_dy == 0:
            self.acc_x = calc_dx
            self.acc_y = calc_dy
            return

        # Save remainders for next packet
        self.acc_x = calc_dx - final_dx
        self.acc_y = calc_dy - final_dy

        # Physical movement execution
        self.interception_bridge.mouse_move_rel(final_dx, final_dy)

    def touch_up(self):
        self.prev_x = None
        self.prev_y = None
        self.acc_x = 0.0
        self.acc_y = 0.0
        if self.left_down:
            self.interception_bridge.left_click_up()
            self.left_down = False


    def process_touch(self, action, touch_event:TouchEvent, is_visible:bool):
        if action == PRESSED:
            self.touch_pressed(touch_event, is_visible)

        elif action == DOWN:
            self.touch_down(touch_event, is_visible)

        elif action == UP:
            self.touch_up()
