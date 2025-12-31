class MouseMapper():
    def __init__(self, mapper):
        self.mapper = mapper
        self.prev_x = None
        self.prev_y = None
        self.config = mapper.config
        self.mapper_event_dispatcher = self.mapper.mapper_event_dispatcher
        self.interception_bridge = mapper.interception_bridge
        self.update_config()
        
        self.mapper_event_dispatcher.register_callback("ON_CONFIG_RELOAD", self.update_config)
        self.mapper_event_dispatcher.register_callback("ON_TOUCH_DOWN", self.touch_down)  
        self.mapper_event_dispatcher.register_callback("ON_TOUCH_PRESSED", self.touch_pressed)
        self.mapper_event_dispatcher.register_callback("ON_TOUCH_UP", self.touch_up)

    def update_config(self):
        """
        Call this whenever F5 is pressed.
        It snapshots the new values so the main loop is fast.
        """
        print(f"MouseMapper reloading... New Sens: {self.config.config_data['mouse']['sensitivity']}, Invert Y: {self.config.config_data['mouse']['invert_y']}")
        
        self.AIM_SENSITIVITY = self.config.config_data['mouse']['sensitivity']       
        # Pre-calculate the math so we don't do 'if' checks in the loop
        self.invert_mult = -1 if self.config.config_data['mouse']['invert_y'] else 1
    
    def touch_down(self, event):
        # Handle Touch Down (Reset Tracker)
        self.prev_x = event.x
        self.prev_y = event.y
        return # No movement on the very first frame
        
    def touch_pressed(self, event):
        # Handle Movement
        if self.prev_x is None:
            self.prev_x = event.x
            self.prev_y = event.y
            return

        # A. Calculate Delta (Current - Previous)
        raw_dx = event.x - self.prev_x
        raw_dy = event.y - self.prev_y
        
        # B. Convert to Physical Distance (DP)
        # We use the mapper's helper to sanitize density differences
        dpx = self.mapper.px_to_dp(raw_dx)
        dpy = self.mapper.px_to_dp(raw_dy)
        
        # C. Apply AIM_SENSITIVITY (Physical Mapping)
        # We SKIP 'device_to_game_rel' here because we want
        # 1 physical inch to always equal X degrees of rotation.
        # We don't care how wide the screen is for aiming.
        final_dx = int(dpx * self.AIM_SENSITIVITY)
        final_dy = int(dpy * self.AIM_SENSITIVITY)
        
        # D. Send to Output (Only if there is movement)
        if final_dx != 0 or final_dy != 0:
            self.interception_bridge.mouse_move_rel(final_dx, final_dy)
            
        # E. Update Previous (Critical for Delta Logic!)
        self.prev_x = event.x
        self.prev_y = event.y
            
    def touch_up(self, event):
        self.prev_x = None
        self.prev_y = None