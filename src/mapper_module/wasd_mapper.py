import math
from .utils import SCANCODES

class WASDMapper():
    def __init__(self, mapper):
        self.mapper = mapper
        self.interception_bridge = mapper.interception_bridge
        
        # Interception Scan Codes (Retrieved from utils.py)
        # Note: keys in SCANCODES are lowercase as per your utils.py
        self.KEY_W = SCANCODES["w"]
        self.KEY_A = SCANCODES["a"]
        self.KEY_S = SCANCODES["s"]
        self.KEY_D = SCANCODES["d"]
        
        # State Tracking
        self.current_keys = set() 
        self.center_x = 0.0
        self.center_y = 0.0
        self.innerradius = 0.0
        self.outerradius = 0.0
        
        # Dependencies
        self.json_loader = mapper.json_loader
        self.config = mapper.config
        self.mapper_event_dispatcher = self.mapper.mapper_event_dispatcher
        
        # Initial Load
        self.update_config()
        self.updateMouseWheel()
                
        # Register Callbacks
        self.mapper_event_dispatcher.register_callback("ON_CONFIG_RELOAD", self.update_config)
        self.mapper_event_dispatcher.register_callback("ON_JSON_RELOAD", self.updateMouseWheel)
        self.mapper_event_dispatcher.register_callback("ON_TOUCH_DOWN", self.touch_down)  
        self.mapper_event_dispatcher.register_callback("ON_TOUCH_PRESSED", self.touch_pressed)
        self.mapper_event_dispatcher.register_callback("ON_TOUCH_UP", self.touch_up)
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
        # Refreshes geometry from the JSON loader
        # This ensures if you resize the joystick in JSON, the logic updates immediately
        self.innerradius = self.json_loader.get_mouse_wheel_radius()
        self.outerradius = self.json_loader.get_sprint_distance()
    
    def on_wasd_block(self):
        # If a button (like 'Reload') is placed on top of the joystick area,
        # we pause the joystick so you don't walk while reloading.
        if self.mapper.wasd_block > 0:
            self.release_all()
        
    def touch_down(self, event):
        if event.is_wasd and self.mapper.wasd_block == 0:
            # Re-center the joystick at the finger's landing position (Floating Joystick)
            self.center_x = event.x
            self.center_y = event.y
            self.release_all()

    def touch_pressed(self, event):
        if event.is_wasd and self.mapper.wasd_block == 0:
            # Vector from center to current finger
            vx_raw = event.x - self.center_x
            vy_raw = event.y - self.center_y
            
            # Distance
            d = (vx_raw*vx_raw + vy_raw*vy_raw)**0.5 
            
            # --- Leash Logic (Floating Follow) ---
            # If finger drags further than 'outerradius', pull the center along.
            if d > self.outerradius and self.outerradius > 0:
                scale = self.outerradius / d
                # Move center towards finger so distance is exactly outerradius
                self.center_x = event.x - (vx_raw * scale)
                self.center_y = event.y - (vy_raw * scale)
                
                # Update vector and distance based on new center
                vx_raw = event.x - self.center_x
                vy_raw = event.y - self.center_y
                d = self.outerradius 

            # --- Deadzone Check ---
            # Normalized Magnitude (0.0 to 1.0+)
            if self.innerradius > 0:
                mag = d / self.innerradius
            else:
                mag = 0

            if mag < self.DEADZONE:
                self.release_all()
                return

            # --- Angle Calculation ---
            # FIX: math.atan2 takes (y, x), not (x, y)
            # This aligns 0 degrees with Right and -90 degrees with Up (Screen Y is down)
            angle = math.degrees(math.atan2(vy_raw, vx_raw))
            
            target_keys = self.get_keys_from_angle(angle)
            self.apply_keys(target_keys)
    
    def touch_up(self, event):
            # Check if the slot that just went UP was the one we were tracking
            # or if we simply have keys down and no more WASD finger exists.
            if event.is_wasd or self.current_keys:
                self.release_all()

    def get_keys_from_angle(self, angle):
        margin = self.HYSTERESIS
        keys = self.current_keys
        
        # 
        # Mapping for Screen Coordinates (Y is Down):
        # Up (-90), Right (0), Down (90), Left (180/-180)

        # --- HYSTERESIS CHECKS (Sticky State) ---
        # If we are already in a state, widen the angle check by 'margin'
        # to prevent rapid flickering at the boundaries.

        # STATE: UP (W) [-112.5 to -67.5]
        if self.KEY_W in keys and self.KEY_A not in keys and self.KEY_D not in keys:
            if -112.5 - margin <= angle < -67.5 + margin: return {self.KEY_W}

        # STATE: UP-RIGHT (WD) [-67.5 to -22.5]
        if self.KEY_W in keys and self.KEY_D in keys:
            if -67.5 - margin <= angle < -22.5 + margin: return {self.KEY_W, self.KEY_D}

        # STATE: RIGHT (D) [-22.5 to 22.5]
        if self.KEY_D in keys and self.KEY_W not in keys and self.KEY_S not in keys:
            if -22.5 - margin <= angle < 22.5 + margin: return {self.KEY_D}

        # STATE: DOWN-RIGHT (SD) [22.5 to 67.5]
        if self.KEY_S in keys and self.KEY_D in keys:
            if 22.5 - margin <= angle < 67.5 + margin: return {self.KEY_S, self.KEY_D}

        # STATE: DOWN (S) [67.5 to 112.5]
        if self.KEY_S in keys and self.KEY_A not in keys and self.KEY_D not in keys:
            if 67.5 - margin <= angle < 112.5 + margin: return {self.KEY_S}

        # STATE: DOWN-LEFT (SA) [112.5 to 157.5]
        if self.KEY_S in keys and self.KEY_A in keys:
            if 112.5 - margin <= angle < 157.5 + margin: return {self.KEY_S, self.KEY_A}

        # STATE: UP-LEFT (WA) [-157.5 to -112.5]
        if self.KEY_W in keys and self.KEY_A in keys:
            if -157.5 - margin <= angle < -112.5 + margin: return {self.KEY_W, self.KEY_A}

        # STATE: LEFT (A) [> 157.5 or < -157.5]
        if self.KEY_A in keys and self.KEY_W not in keys and self.KEY_S not in keys:
            limit = 157.5 - margin
            if angle >= limit or angle <= -limit: return {self.KEY_A}

        # --- FALLBACK (Strict State) ---
        return self._get_strict_keys(angle)

    def _get_strict_keys(self, angle):
        if -112.5 <= angle < -67.5:   return {self.KEY_W}
        elif -67.5 <= angle < -22.5:  return {self.KEY_W, self.KEY_D}
        elif -22.5 <= angle < 22.5:   return {self.KEY_D}
        elif 22.5 <= angle < 67.5:    return {self.KEY_S, self.KEY_D}
        elif 67.5 <= angle < 112.5:   return {self.KEY_S}
        elif 112.5 <= angle < 157.5:  return {self.KEY_S, self.KEY_A}
        elif -157.5 <= angle < -112.5: return {self.KEY_W, self.KEY_A}
        else: return {self.KEY_A}

    def apply_keys(self, target_keys):
        # Add a safety check: if WASD is blocked mid-movement, kill keys
        if self.mapper.wasd_block > 0:
            self.release_all()
            return

        keys_to_press = target_keys - self.current_keys
        keys_to_release = self.current_keys - target_keys
        
        for k in keys_to_release:
            self.interception_bridge.key_up(k)
        for k in keys_to_press:
            self.interception_bridge.key_down(k)
            
        self.current_keys = target_keys

    def release_all(self):
        if not self.current_keys: return
        for k in self.current_keys:
            self.mapper.interception_bridge.key_up(k)
        self.current_keys = set()
