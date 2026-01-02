from .utils import DEF_DPI  # Importing DEF_DPI for the calculation

class MouseMapper():
    def __init__(self, mapper):
        self.mapper = mapper
        self.prev_x = None
        self.prev_y = None
        self.config = mapper.config
        self.mapper_event_dispatcher = self.mapper.mapper_event_dispatcher
        self.interception_bridge = mapper.interception_bridge
        
        # Initial config load
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
        print(f"[Info] MouseMapper reloading...")
        
        # Thread-safe config access
        with self.config.config_lock:
            mouse_cfg = self.config.config_data.get('mouse', {})
            base_sens = mouse_cfg.get('sensitivity', 1.0)
            
            # Pre-calculate the entire multiplier: (Sensitivity * (160 / Device_DPI))
            # We use DEF_DPI (160) as the baseline.
            if self.mapper.dpi > 0:
                dpi_scale = DEF_DPI / self.mapper.dpi
            else:
                dpi_scale = 1.0 # Fallback to prevent divide by zero
                
            self.TOTAL_MULT = base_sens * dpi_scale
    
    def touch_down(self, event):
        # 1. CRITICAL: Only process the mouse finger
        if not event.is_mouse:
            return

        # Handle Touch Down (Reset Tracker)
        self.prev_x = event.x
        self.prev_y = event.y
        
    def touch_pressed(self, event):
        # 1. CRITICAL: Only process the mouse finger
        if not event.is_mouse:
            return

        # Handle Movement
        if self.prev_x is None:
            self.prev_x = event.x
            self.prev_y = event.y
            return

        # A. Calculate Delta (Current - Previous)
        raw_dx = event.x - self.prev_x
        raw_dy = event.y - self.prev_y
        
        # B. Apply Optimized Multiplier
        final_dx = int(raw_dx * self.TOTAL_MULT)
        final_dy = int(raw_dy * self.TOTAL_MULT)
        
        # C. Send to Output (Only if there is movement)
        if final_dx != 0 or final_dy != 0:
            self.interception_bridge.mouse_move_rel(final_dx, final_dy)
            
        # D. Update Previous (Critical for Delta Logic!)
        self.prev_x = event.x
        self.prev_y = event.y
            
    def touch_up(self, event):
        # Only reset if the mouse finger lifted
        if event.is_mouse:
            self.prev_x = None
            self.prev_y = None