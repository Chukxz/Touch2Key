from .utils import DEF_DPI  # Importing DEF_DPI for the calculation

class MouseMapper():
    def __init__(self, mapper):
        self.mapper = mapper
        self.prev_x = None
        self.prev_y = None
        
        # Accumulators ensure even the smallest tremors are eventually sent
        self.acc_x = 0.0
        self.acc_y = 0.0
        
        self.config = mapper.config
        self.mapper_event_dispatcher = self.mapper.mapper_event_dispatcher
        self.interception_bridge = mapper.interception_bridge

        # Initial config load
        self.update_config()

        # Callbacks
        self.mapper_event_dispatcher.register_callback("ON_CONFIG_RELOAD", self.update_config)
        self.mapper_event_dispatcher.register_callback("ON_TOUCH_DOWN", self.touch_down)  
        self.mapper_event_dispatcher.register_callback("ON_TOUCH_PRESSED", self.touch_pressed)
        self.mapper_event_dispatcher.register_callback("ON_TOUCH_UP", self.touch_up)

    def update_config(self):
        """
        Refreshes sensitivity and scaling values.
        """
        with self.config.config_lock:
            mouse_cfg = self.config.config_data.get('mouse', {})
            base_sens = mouse_cfg.get('sensitivity', 1.0)

            if self.mapper.dpi > 0:
                dpi_scale = DEF_DPI / self.mapper.dpi
            else:
                dpi_scale = 1.0 

            self.TOTAL_MULT = base_sens * dpi_scale

    def touch_down(self, event):
        """
        Reset state on new touch.
        """
        if not event.is_mouse:
            return

        self.prev_x = event.x
        self.prev_y = event.y
        # Clear accumulators so a new touch doesn't inherit tremors from the last finger
        self.acc_x = 0.0
        self.acc_y = 0.0

    def touch_pressed(self, event):
        if not event.is_mouse:
            return

        # Issue No. 1 Fix: Ensure we have a starting point
        if self.prev_x is None:
            self.prev_x = event.x
            self.prev_y = event.y
            return

        # A. Calculate Delta
        raw_dx = event.x - self.prev_x
        raw_dy = event.y - self.prev_y

        # B. Issue No. 3 Fix: The Accumulator
        # This allows "tremors" (small floats) to be preserved.
        calc_dx = (raw_dx * self.TOTAL_MULT) + self.acc_x
        calc_dy = (raw_dy * self.TOTAL_MULT) + self.acc_y

        # C. Integer casting for the OS
        final_dx = int(calc_dx)
        final_dy = int(calc_dy)

        # D. Save the remainder
        # Even if final_dx is 0, the tremor is saved in acc_x for the next frame.
        self.acc_x = calc_dx - final_dx
        self.acc_y = calc_dy - final_dy

        # E. Send movement if a whole pixel threshold is met
        if final_dx != 0 or final_dy != 0:
            self.interception_bridge.mouse_move_rel(final_dx, final_dy)

        # F. Update previous
        self.prev_x = event.x
        self.prev_y = event.y

    def touch_up(self, event):
        """
        Issue No. 1 Fix: Release state to prevent coordinate jumps.
        """
        if event.is_mouse:
            self.prev_x = None
            self.prev_y = None
            self.acc_x = 0.0
            self.acc_y = 0.0
