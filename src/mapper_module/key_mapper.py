from .utils import RECT, CIRCLE, M_LEFT, M_RIGHT, M_MIDDLE, SCANCODES, MOUSE_WHEEL_CODE, SPRINT_DISTANCE_CODE, is_in_circle, is_in_rect, MapperEvent

class KeyMapper():
    def __init__(self, mapper):
        self.mapper = mapper
        self.config = mapper.config
        self.mapper_event_dispatcher = self.mapper.mapper_event_dispatcher
        self.interception_bridge = mapper.interception_bridge
        
        # Format: { slot_id: [scancode, zone_data, is_wasd_finger] }
        self.events_dict = {} 
                
        self.mapper_event_dispatcher.register_callback("ON_JSON_RELOAD", self.update_json_data)
        self.mapper_event_dispatcher.register_callback("ON_TOUCH_DOWN", self.touch_down)  
        self.mapper_event_dispatcher.register_callback("ON_TOUCH_PRESSED", self.touch_pressed)
        self.mapper_event_dispatcher.register_callback("ON_TOUCH_UP", self.touch_up)

    def update_json_data(self):
        self.release_all()
        self.events_dict.clear()
        
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
        try:
            s_int = int(scancode, 16) if isinstance(scancode, str) else int(scancode)

            if s_int == M_LEFT:
                self.interception_bridge.left_click_down()
            elif s_int == M_RIGHT:
                self.interception_bridge.right_click_down()
            elif s_int == M_MIDDLE:
                self.interception_bridge.middle_click_down()
            else:
                self.interception_bridge.key_down(s_int)
        except ValueError:
            print(f"[KeyMapper] Invalid scancode: {scancode}")

    def key_up(self, scancode):
        try:
            s_int = int(scancode, 16) if isinstance(scancode, str) else int(scancode)

            if s_int == M_LEFT:
                self.interception_bridge.left_click_up()
            elif s_int == M_RIGHT:
                self.interception_bridge.right_click_up()
            elif s_int == M_MIDDLE:
                self.interception_bridge.middle_click_up()
            else:
                self.interception_bridge.key_up(s_int)   
        except ValueError:
            pass

    def touch_down(self, event):
        # 1. Normalize Coordinates (Raw Pixels -> 0.0-1.0)
        if self.mapper.device_width == 0 or self.mapper.device_height == 0:
            return

        norm_x = event.x / self.mapper.device_width
        norm_y = event.y / self.mapper.device_height

        # Thread-safe read of JSON data
        with self.mapper.config.config_lock:
            # We access the loader directly. .items() returns a view, which is safe to iterate.
            json_items = self.mapper.json_loader.json_data.items()
        
        try:
            for scancode, value in json_items:
                _type = value['type']
                name = value.get('name', '')
                
                hit = False
                
                # Check Normalized Geometry
                if _type == CIRCLE:
                    # cx, cy, r are normalized in JSON_Loader
                    if is_in_circle(norm_x, norm_y, value['cx'], value['cy'], value['r']):
                        hit = True
                elif _type == RECT:
                    # x1, x2, y1, y2 are normalized in JSON_Loader
                    if is_in_rect(norm_x, norm_y, value['x1'], value['x2'], value['y1'], value['y2']):
                        hit = True

                if hit:
                    # Ignore special zones handled by other mappers
                    if name == MOUSE_WHEEL_CODE or name == SPRINT_DISTANCE_CODE:
                        continue
                    
                    # Action
                    self.key_down(scancode)
                    
                    # Track State: [scancode, zone_data, is_wasd_finger]
                    self.events_dict[event.slot] = [scancode, value, event.is_wasd]
                    
                    # Update WASD Block
                    if event.is_wasd:
                        self.mapper.wasd_block += 1
                        self.mapper_event_dispatcher.dispatch(MapperEvent(action="WASD"))
                    
                    # Stop checking (First valid hit wins)
                    return 

        except Exception as e:
            print(f"[KeyMapper] Error in touch_down: {e}")

    def touch_pressed(self, event):
        # "Slide Off" Logic: Release key if finger leaves the button
        if event.slot not in self.events_dict:
            return

        scancode, value, is_wasd = self.events_dict[event.slot]
        
        # Normalize current position
        norm_x = event.x / self.mapper.device_width
        norm_y = event.y / self.mapper.device_height
        
        should_release = False
        
        if value['type'] == CIRCLE:
            if not is_in_circle(norm_x, norm_y, value['cx'], value['cy'], value['r']):
                should_release = True
        elif value['type'] == RECT:
            if not is_in_rect(norm_x, norm_y, value['x1'], value['x2'], value['y1'], value['y2']):
                should_release = True

        if should_release:
            self.key_up(scancode)
            self.events_dict.pop(event.slot, None)
            
            if is_wasd:
                self.mapper.wasd_block = max(0, self.mapper.wasd_block - 1)
                self.mapper_event_dispatcher.dispatch(MapperEvent(action="WASD"))

    def touch_up(self, event):
        if event.slot in self.events_dict:
            scancode, _, is_wasd = self.events_dict[event.slot]
            
            self.key_up(scancode)
            self.events_dict.pop(event.slot, None)
            
            if is_wasd:
                self.mapper.wasd_block = max(0, self.mapper.wasd_block - 1)
                self.mapper_event_dispatcher.dispatch(MapperEvent(action="WASD"))