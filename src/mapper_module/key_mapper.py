class KeyMapper():
    def __init__(self, mapper):
        self.mapper = mapper
        self.config = mapper.config
        self.mapper_event_dispatcher = self.mapper.mapper_event_dispatcher
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

        print(f"KeyMapper reloading...  New MouseWheel Mapping Code: {self.config.config_data['key']['mouse_wheel_mapping_code']}")
        
        self.MOUSE_WHEEL_CODE = self.config.config_data['key']['mouse_wheel_mapping_code']

    
    def touch_down(self, event):
        pass
    def touch_pressed(self, event):
        pass
    def touch_up(self, event):
        pass
    
    def accept_touch_event(self, event):       
        if event.is_wasd:...
            # Check if no HUD buttons are overlapping - Placeholder for actual check
        
        else:
            # Handle other key mappings here
            x = event.x
            y = event.y
            game_x, game_y = self.mapper.device_to_game_abs(x, y)

    def is_in_circle(self, px, py, cx, cy, r):
        return (px - cx)**2 + (py - cy)**2 <= r*r

    def is_in_rect(self, px, py, left, right, top, bottom):
        return (left <= px <= right) and (top <= py <= bottom)