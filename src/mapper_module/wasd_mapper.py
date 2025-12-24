import math

class WASDMapper():
    def __init__(self, mapper, config, touch_event_dispatcher):
        self.mapper = mapper        
        # Interception Scan Codes
        self.KEY_W = 0x11
        self.KEY_A = 0x1E
        self.KEY_S = 0x1F
        self.KEY_D = 0x20
        
        # State Tracking
        self.current_keys = set() # {'W', 'A'}
        self.center_x = 0.0
        self.center_y = 0.0
        self.radius = 0.0
        self.update_config(mapper.config.joystick)
        
        config.register_callback(self.update_config)
        touch_event_dispatcher.register_callback("ON_TOUCH_DOWN", self.touch_down)  
        touch_event_dispatcher.register_callback("ON_TOUCH_PRESSED", self.touch_pressed)
        touch_event_dispatcher.register_callback("ON_TOUCH_UP", self.touch_up)

    def update_config(self, joystick_config):
        """
        Call this whenever F5 is pressed.
        It snapshots the new values so the main loop is fast.
        """
        print(f"JoystickMapper reloading... New Deadzone: {joystick_config.deadzone}, Hysteresis: {joystick_config.hysteresis}, Fixed Center: {joystick_config.fixed_center}")
        
        self.DEADZONE = joystick_config.deadzone
        self.HYSTERESIS = joystick_config.hysteresis        
        self.FIXED_CENTER = joystick_config.fixed_center

    def set_zone(self, cx, cy, radius):
        """Define the physical location of the joystick on phone."""
        self.center_x = cx
        self.center_y = cy
        self.radius = radius
        
    def touch_down(self, event):
        # On Touch Down, we can optionally recenter the joystick
        if not self.FIXED_CENTER:
            self.center_x = event.x
            self.center_y = event.y
        self.release_all()

    def touch_pressed(self, event):
        # Normalize Vector (-1.0 to 1.0)
        # Note: We divide by radius to get 'tilt percentage'
        dx = (event.x - self.center_x) / self.radius
        dy = (event.y - self.center_y) / self.radius
        
        # Calculate Magnitude (0.0 to 1.0+)
        mag = math.sqrt(dx*dx + dy*dy)
        
        # Deadzone Check
        if mag < self.DEADZONE:
            self.release_all()
            return

        # Calculate Angle (Degrees)
        # 0 is Right (East), 90 is Down (South), -90 is Up (North)
        angle = math.degrees(math.atan2(dy, dx))
        
        # Determine Target Keys based on Angle
        target_keys = self.get_keys_from_angle(angle)
        
        # Apply Key Changes
        self.apply_keys(target_keys)
    
    def touch_up(self, event):
        self.release_all()

    def get_keys_from_angle(self, angle):
        margin = self.HYSTERESIS
        keys = self.current_keys
        
        # --- HYSTERESIS CHECKS (Sticky State) ---
        # We only check the specific range for the state we are CURRENTLY in.
        # If we are in that state, we widen the valid angle window by 'margin'.

        # STATE: UP (W) [-112.5 to -67.5]
        if self.KEY_W in keys and self.KEY_A not in keys and self.KEY_D not in keys:
            if -112.5 - margin <= angle < -67.5 + margin:
                return {self.KEY_W}

        # STATE: UP-RIGHT (WD) [-67.5 to -22.5]
        if self.KEY_W in keys and self.KEY_D in keys:
            if -67.5 - margin <= angle < -22.5 + margin:
                return {self.KEY_W, self.KEY_D}

        # STATE: RIGHT (D) [-22.5 to 22.5]
        if self.KEY_D in keys and self.KEY_W not in keys and self.KEY_S not in keys:
            if -22.5 - margin <= angle < 22.5 + margin:
                return {self.KEY_D}

        # STATE: DOWN-RIGHT (SD) [22.5 to 67.5]
        if self.KEY_S in keys and self.KEY_D in keys:
            if 22.5 - margin <= angle < 67.5 + margin:
                return {self.KEY_S, self.KEY_D}

        # STATE: DOWN (S) [67.5 to 112.5]
        if self.KEY_S in keys and self.KEY_A not in keys and self.KEY_D not in keys:
            if 67.5 - margin <= angle < 112.5 + margin:
                return {self.KEY_S}

        # STATE: DOWN-LEFT (SA) [112.5 to 157.5]
        if self.KEY_S in keys and self.KEY_A in keys:
            if 112.5 - margin <= angle < 157.5 + margin:
                return {self.KEY_S, self.KEY_A}

        # STATE: UP-LEFT (WA) [-157.5 to -112.5]
        if self.KEY_W in keys and self.KEY_A in keys:
            if -157.5 - margin <= angle < -112.5 + margin:
                return {self.KEY_W, self.KEY_A}

        # STATE: LEFT (A) [157.5 to 180] AND [-180 to -157.5]
        # This one is tricky because of the +/- 180 wrap-around.
        if self.KEY_A in keys and self.KEY_W not in keys and self.KEY_S not in keys:
            # We widen the boundary towards 0. 
            # Strict limit is +/- 157.5. Hysteresis allows it to drop to e.g. 152.5.
            limit = 157.5 - margin
            if angle >= limit or angle <= -limit:
                return {self.KEY_A}

        # --- 2. FALLBACK (Strict State Switch) ---
        # If we failed the "Keep State" checks above (meaning the finger moved 
        # significantly into a new zone), we calculate the new state strictly.
        return self._get_strict_keys(angle)

    def _get_strict_keys(self, angle):
        """
        The standard lookup table without margins.
        Used when entering a new state.
        """
        if -112.5 <= angle < -67.5:   return {self.KEY_W}
        elif -67.5 <= angle < -22.5:  return {self.KEY_W, self.KEY_D}
        elif -22.5 <= angle < 22.5:   return {self.KEY_D}
        elif 22.5 <= angle < 67.5:    return {self.KEY_S, self.KEY_D}
        elif 67.5 <= angle < 112.5:   return {self.KEY_S}
        elif 112.5 <= angle < 157.5:  return {self.KEY_S, self.KEY_A}
        elif -157.5 <= angle < -112.5: return {self.KEY_W, self.KEY_A}
        # Left handles the wrap-around
        else: return {self.KEY_A}

    def apply_keys(self, target_keys):
        """
        Diffs the current keys vs target keys to minimize API calls.
        Also handles the 'Hysteresis' by not switching if target is 
        oscillating rapidly (optional, but standard logic above is usually stable enough).
        """
        # Identify changes
        keys_to_press = target_keys - self.current_keys
        keys_to_release = self.current_keys - target_keys
        
        # Execute
        for k in keys_to_release:
            self.mapper.send_key_up(k)
        for k in keys_to_press:
            self.mapper.send_key_down(k)
            
        self.current_keys = target_keys

    def release_all(self):
        if not self.current_keys:
            return
        for k in self.current_keys:
            self.mapper.send_key_up(k)
        self.current_keys = set()
            
    
# Also handle auto sprint