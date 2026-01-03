from .utils import DEF_DPI 

class MouseMapper():
    def __init__(self, mapper):
        self.mapper = mapper
        self.prev_x = None
        self.prev_y = None
        self.acc_x = 0.0
        self.acc_y = 0.0
        
        self.config = mapper.config
        self.mapper_event_dispatcher = self.mapper.mapper_event_dispatcher
        self.interception_bridge = mapper.interception_bridge

        self.update_config()

        self.mapper_event_dispatcher.register_callback("ON_CONFIG_RELOAD", self.update_config)
        self.mapper_event_dispatcher.register_callback("ON_TOUCH_DOWN", self.touch_down)  
        self.mapper_event_dispatcher.register_callback("ON_TOUCH_PRESSED", self.touch_pressed)
        self.mapper_event_dispatcher.register_callback("ON_TOUCH_UP", self.touch_up)

    def update_config(self):
        try:
            with self.config.config_lock:
                mouse_cfg = self.config.config_data.get('mouse', {})
                base_sens = mouse_cfg.get('sensitivity', 1.0)
                dpi_scale = DEF_DPI / self.mapper.dpi if self.mapper.dpi > 0 else 1.0
                self.TOTAL_MULT = base_sens * dpi_scale
        except Exception as e:
            raise RuntimeError(f"Error loading mouse config: {e}")

    def touch_down(self, event):
        if not event.is_mouse:
            return
        # Anchor new finger and clear math remainders
        self.prev_x = event.x
        self.prev_y = event.y
        self.acc_x = 0.0
        self.acc_y = 0.0

    def touch_pressed(self, event):
        if not event.is_mouse:
            return

        # Ensures no 'jumping' if a new finger takes over
        if self.prev_x is None:
            self.prev_x = event.x
            self.prev_y = event.y
            return

        raw_dx = event.x - self.prev_x
        raw_dy = event.y - self.prev_y

        # Sub-pixel precision (passes all tremors)
        calc_dx = (raw_dx * self.TOTAL_MULT) + self.acc_x
        calc_dy = (raw_dy * self.TOTAL_MULT) + self.acc_y

        final_dx = int(calc_dx)
        final_dy = int(calc_dy)

        # Store remainders
        self.acc_x = calc_dx - final_dx
        self.acc_y = calc_dy - final_dy

        if final_dx != 0 or final_dy != 0:
            self.interception_bridge.mouse_move_rel(final_dx, final_dy)

        self.prev_x = event.x
        self.prev_y = event.y

    def touch_up(self, event):
        # When any mouse finger is lifted, clear the state
        if event.is_mouse:
            self.prev_x = None
            self.prev_y = None
            self.acc_x = 0.0
            self.acc_y = 0.0
