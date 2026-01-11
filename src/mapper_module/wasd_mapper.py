import math
import threading
from .utils import (
    SCANCODES, DOWN, PRESSED
)

class WASDMapper():
    def __init__(self, mapper):
        self.mapper = mapper
        self.interception_bridge = mapper.interception_bridge
        
        # Pre-convert scancodes to Integers once for faster Bridge interaction
        self.KEY_W = int(SCANCODES["w"], 16) if isinstance(SCANCODES["w"], str) else int(SCANCODES["w"])
        self.KEY_A = int(SCANCODES["a"], 16) if isinstance(SCANCODES["a"], str) else int(SCANCODES["a"])
        self.KEY_S = int(SCANCODES["s"], 16) if isinstance(SCANCODES["s"], str) else int(SCANCODES["s"])
        self.KEY_D = int(SCANCODES["d"], 16) if isinstance(SCANCODES["d"], str) else int(SCANCODES["d"])
        
        # State Tracking
        self.current_keys = set() 
        self.center_x = 0.0
        self.center_y = 0.0
        self.innerradius = 0.0
        self.outerradius = 0.0
        
        # O(1) Lookup Table: Maps sector index (0-7) to physical key sets
        self.DIRECTION_LOOKUP = [
            {self.KEY_D},               # 0: Right (-22.5° to 22.5°)
            {self.KEY_S, self.KEY_D},    # 1: Down-Right
            {self.KEY_S},               # 2: Down
            {self.KEY_S, self.KEY_A},    # 3: Down-Left
            {self.KEY_A},               # 4: Left
            {self.KEY_W, self.KEY_A},    # 5: Up-Left
            {self.KEY_W},               # 6: Up
            {self.KEY_W, self.KEY_D}     # 7: Up-Right
        ]

        self.json_loader = mapper.json_loader
        self.config = mapper.config
        self.mapper_event_dispatcher = self.mapper.mapper_event_dispatcher
        
        # Initial Load
        self.update_config()
        self.updateMouseWheel()
                
        # Register Callbacks
        self.mapper_event_dispatcher.register_callback("ON_CONFIG_RELOAD", self.update_config)
        self.mapper_event_dispatcher.register_callback("ON_JSON_RELOAD", self.updateMouseWheel)
        self.mapper_event_dispatcher.register_callback("ON_WASD_BLOCK", self.on_wasd_block)

    def update_config(self):
        print(f"[Info] WASDMapper reloading config...")
        try:
            with self.config.config_lock:
                conf = self.config.config_data.get('joystick', {})
                self.DEADZONE = conf.get('deadzone', 0.1)
                self.HYSTERESIS = conf.get('hysteresis', 5.0)
        except Exception as e:
            _str = f"Error loading joystick config: {e}"
            raise RuntimeError(_str)

    def updateMouseWheel(self):
        print(f"[Info] WASDMapper updating mousewheel...")
        self.innerradius = self.json_loader.get_mouse_wheel_radius()
        self.outerradius = self.json_loader.get_sprint_distance()
    
    def on_wasd_block(self):
        if self.mapper.wasd_block > 0:
            self.release_all()
        
    def touch_down(self, touch_event):
        if self.mapper.wasd_block == 0:
            self.center_x = touch_event.x
            self.center_y = touch_event.y
            self.release_all()

    def touch_pressed(self, touch_event):
        if self.mapper.wasd_block > 0:
            self.release_all()
            return

        vx = touch_event.x - self.center_x
        vy = touch_event.y - self.center_y
        dist_sq = vx*vx + vy*vy
        
        # Optimization: Deadzone check using squared distance avoids math.sqrt()
        dz_px = self.innerradius * self.DEADZONE
        if dist_sq < (dz_px * dz_px):
            self.release_all()
            return

        dist = dist_sq**0.5

        # Leash Logic (Floating Joystick center follow)
        if dist > self.outerradius and self.outerradius > 0:
            scale = self.outerradius / dist
            self.center_x = touch_event.x - (vx * scale)
            self.center_y = touch_event.y - (vy * scale)
            vx = touch_event.x - self.center_x
            vy = touch_event.y - self.center_y
            # dist is now effectively self.outerradius

        # FAST ANGLE TO SECTOR INDEX
        # atan2 gives -pi to pi; we shift to 0 to 2pi and offset by pi/8 (22.5°)
        angle_rad = math.atan2(vy, vx)
        if angle_rad < 0: angle_rad += 2 * math.pi
        
        # Divide circle into 8 segments of 45°
        sector = int((angle_rad + (math.pi / 8)) / (math.pi / 4)) % 8
        self.apply_keys(self.DIRECTION_LOOKUP[sector])

    def touch_up(self):
        # Only release if the finger that lifted is the designated WASD finger (handled in main.py)
        # OR if we have keys down and want to be safe (Emergency release)
        if self.current_keys:
            self.release_all()

    def apply_keys(self, target_keys):
        if target_keys == self.current_keys:
            return

        # Bitmask-style diffing to minimize Interception Bridge overhead
        to_release = self.current_keys - target_keys
        to_press = target_keys - self.current_keys

        for k in to_release: self.interception_bridge.key_up(k)
        for k in to_press: self.interception_bridge.key_down(k)
            
        self.current_keys = target_keys

    def process_touch(self, action, touch_event):
        if action == PRESSED:
            self.touch_pressed(touch_event)
            
        elif action == DOWN:
            self.touch_down(touch_event)

    def release_all(self):
        if not self.current_keys: return
        for k in self.current_keys:
            self.interception_bridge.key_up(k)
        self.current_keys = set()