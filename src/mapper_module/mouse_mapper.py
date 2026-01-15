import time
from .utils import (
    DEF_DPI, DOWN, UP, PRESSED,
    DOUBLE_TAP_DELAY
)

class MouseMapper():
    def __init__(self, mapper):
        self.mapper = mapper
        self.prev_x = None
        self.prev_y = None
        self.acc_x = 0.0
        self.acc_y = 0.0
        self.last_touch = 0
        self.double_tap = False

        self.config = mapper.config
        self.mapper_event_dispatcher = self.mapper.mapper_event_dispatcher
        self.interception_bridge = mapper.interception_bridge

        self.TOTAL_MULT = 1.0
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
                # Ensure we don't divide by zero
                device_dpi = self.mapper.dpi if self.mapper.dpi > 0 else DEF_DPI
                dpi_scale = DEF_DPI / device_dpi
                self.TOTAL_MULT = base_sens * dpi_scale
        except Exception as e:
            print(f"[Error] Mouse config update failed: {e}")

    def touch_down(self, touch_event, is_visible):
        """
        Anchor the start position and reset precision accumulators
        """
        self.prev_x = touch_event.x
        self.prev_y = touch_event.y
        self.acc_x = 0.0
        self.acc_y = 0.0

        if is_visible:
            self.double_tap = False
            now = time.monotonic()
            if now - self.last_touch < DOUBLE_TAP_DELAY:
                self.double_tap = True
            
            _x, _y = self.mapper.device_to_game_abs(self.prev_x, self.prev_y)
            self.interception_bridge.mouse_move_abs(_x, _y)
            
            self.last_touch = now
            if self.double_tap:
                self.interception_bridge.right_click_down()
            else:
                self.interception_bridge.left_click_down()
        

    def touch_pressed(self, touch_event, is_visible):
        """
        The 'Hot Path'. This code runs hundreds of times per second.
        Optimized to minimize branching and float operations.
        """
        if self.prev_x is None or self.prev_y is None:
            self.touch_down(touch_event, is_visible)
            return      
            
        # 1. Calculate Raw Delta
        raw_dx = touch_event.x - self.prev_x
        raw_dy = touch_event.y - self.prev_y

        # 2. Update anchors immediately
        self.prev_x = touch_event.x
        self.prev_y = touch_event.y

        # 3. Apply Multiplier and add previous remainders (Sub-pixel precision)
        # Using float math here is necessary for 1:1 feel
        calc_dx = (raw_dx * self.TOTAL_MULT) + self.acc_x
        calc_dy = (raw_dy * self.TOTAL_MULT) + self.acc_y

        # 4. Truncate to Integer (Actual pixels to move)
        final_dx = int(calc_dx)
        final_dy = int(calc_dy)

        # 5. Fast-Exit for Noise
        # If the delta is less than 1 physical pixel, just keep the remainder and exit.
        # This prevents the Interception Bridge from being flooded with 0-pixel movements.
        if final_dx == 0 and final_dy == 0:
            self.acc_x = calc_dx
            self.acc_y = calc_dy
            return

        # 6. Save remainders for next packet
        self.acc_x = calc_dx - final_dx
        self.acc_y = calc_dy - final_dy

        # 7. Physical movement execution
        self.interception_bridge.mouse_move_rel(final_dx, final_dy)
        
    def touch_up(self):
        """Clears state."""
        self.prev_x = None
        self.prev_y = None
        self.acc_x = 0.0
        self.acc_y = 0.0
        self.double_tap = False
        self.interception_bridge.left_click_up()
        self.interception_bridge.right_click_up()

    def process_touch(self, action, touch_event, is_visible):
        if action == PRESSED:
            self.touch_pressed(touch_event, is_visible)
            
        elif action == DOWN:
            self.touch_down(touch_event, is_visible)
        
        elif action == UP:
            self.touch_up() 