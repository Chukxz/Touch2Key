class KeyMapper():
    def __init__(self, mapper, config, touch_event_dispatcher):
        self.mapper = mapper
        
        # self.update_config(mapper.config.key)
        config.register_callback(self.update_config)
        touch_event_dispatcher.register_callback("ON_TOUCH_DOWN", self.touch_down)  
        touch_event_dispatcher.register_callback("ON_TOUCH_PRESSED", self.touch_pressed)
        touch_event_dispatcher.register_callback("ON_TOUCH_UP", self.touch_up)
    
    def update_config(self, key_config):
        """
        Call this whenever F5 is pressed.
        It snapshots the new values so the main loop is fast.
        """
        print(f"KeyMapper reloading...")
    
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