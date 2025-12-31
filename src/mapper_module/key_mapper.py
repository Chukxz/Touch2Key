from utils import RECT, CIRCLE, M_LEFT, M_RIGHT, M_MIDDLE, SCANCODES, is_in_circle, is_in_rect
from bridge import InterceptionBridge

class KeyMapper():
    def __init__(self, mapper):
        self.mapper = mapper
        self.config = mapper.config
        self.mapper_event_dispatcher = self.mapper.mapper_event_dispatcher
        self.interception_bridge = mapper.interception_bridge
        self.update_config()
        self.events_dict = {}
        
        self.mapper_event_dispatcher.register_callback("ON_JSON_RELOAD", self.update_json_data)
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
    
    def update_json_data(self, json_data):
        self.json_data = json_data   
        
    def release_all(self):
        for v in SCANCODES.values():
            if v == M_LEFT:
                self.interception_bridge.left_click_up()
            elif v == M_RIGHT:
                self.interception_bridge.right_click_up()
            elif v == M_MIDDLE:
                self.interception_bridge.middle_click_up()         
            else:
                self.interception_bridge.key_up(v)

    def key_down(self, scancode):
        if scancode == hex(M_LEFT):
            self.interception_bridge.left_click_down()
        elif scancode == hex(M_RIGHT):
            self.interception_bridge.right_click_down()
        elif scancode == hex(M_MIDDLE):
            self.interception_bridge.middle_click_down()
        else:
            self.interception_bridge.key_down(int(scancode, 16))
                
    def key_pressed(self, cur_event):
        if cur_event.slot in self.events_dict:
            event, scancode, value = self.events_dict[cur_event.slot]        
            

    def key_up(self, scancode):
        if scancode == hex(M_LEFT):
            self.interception_bridge.left_click_up()
        elif scancode == hex(M_RIGHT):
            self.interception_bridge.right_click_up()
        elif scancode == hex(M_MIDDLE):
            self.interception_bridge.middle_click_up()
        else:
            self.interception_bridge.key_up(int(scancode, 16))   

    
    def touch_down(self, event):
        json_data = self.mapper.json_loader.json_data
        
        with self.mapper.config.config_lock:
            try:
                for scancode, value in json_data.items():
                    _type = value['type']
                    name = value['name']
                    
                    if _type == CIRCLE:
                        cx = value['cx']
                        cy = value['cy']
                        r = value['val1']                        
                        if is_in_circle(event.x, event.y, cx, cy, r):
                            if name != self.MOUSE_WHEEL_CODE:
                                self.key_down(scancode)
                                self.events_dict[event.slot] = [event, scancode, value]                     
                                
                    elif _type == RECT:
                        left = value['val1']
                        top = value['val2']
                        right = value['val3']
                        bottom = value['val4']
                        if is_in_rect(event.x, event.y, left, right, top, bottom):
                            self.key_down(scancode)
                            self.events_dict[event.slot] = [event, scancode, value]
            
            except Exception as e:
                print(f"[KeyMapper] Error in touch_down: {e}")
                return
                        
            
    def touch_pressed(self, event):
        self.key_pressed(event)
    
    def touch_up(self, event):
        json_data = self.mapper.json_loader.json_data
        
        with self.mapper.config.config_lock:
            try:
                for scancode, value in json_data.items():
                    _type = value['type']
                    name = value['name']
                    
                    if _type == CIRCLE:
                        cx = value['cx']
                        cy = value['cy']
                        r = value['val1']                        
                        if is_in_circle(event.x, event.y, cx, cy, r):
                            if name != self.MOUSE_WHEEL_CODE:
                                self.key_up(scancode)
                                self.events_dict.pop(event.slot, None)                                                  
                                
                    elif _type == RECT:
                        left = value['val1']
                        top = value['val2']
                        right = value['val3']
                        bottom = value['val4']
                        if is_in_rect(event.x, event.y, left, right, top, bottom):
                            self.key_up(scancode)
                            self.events_dict.pop(event.slot, None)
            
            except Exception as e:
                print(f"[KeyMapper] Error in touch_up: {e}")
                return
                
    # def accept_touch_event(self, event):       
    #     if event.is_wasd:...
    #         # Check if no HUD buttons are overlapping - Placeholder for actual check
        
    #     else:
    #         # Handle other key mappings here
    #         x = event.x
    #         y = event.y
    #         game_x, game_y = self.mapper.device_to_game_abs(x, y)

    # def is_in_circle(self, px, py, cx, cy, r):
    #     return (px - cx)**2 + (py - cy)**2 <= r*r

    # def is_in_rect(self, px, py, left, right, top, bottom):
    #     return (left <= px <= right) and (top <= py <= bottom)