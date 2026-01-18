from __future__ import annotations
from typing import TYPE_CHECKING

import time
from .utils import (
    RECT, CIRCLE, M_LEFT, M_RIGHT, M_MIDDLE,
    MOUSE_WHEEL_CODE, SPRINT_DISTANCE_CODE, 
    is_in_circle, is_in_rect, MapperEvent,
    DOWN, UP
)

if TYPE_CHECKING:
    from .mapper import Mapper
    from .utils import TouchEvent
    
class KeyMapper():
    def __init__(self, mapper:Mapper, debounce_time:float):
        self.mapper = mapper
        self.config = mapper.config
        self.mapper_event_dispatcher = self.mapper.mapper_event_dispatcher
        self.interception_bridge = mapper.interception_bridge

        # Performance: Debouncing logic
        self.debounce_interval = debounce_time  
        self.last_action_times = {} # { scancode_int: float_timestamp }

        # State Tracking: { slot_id: [scancode_int, zone_data, is_wasd_finger] }
        self.events_dict = {} 
        
        # 1. Blacklist for O(1) filtering
        self.ignored_names = {MOUSE_WHEEL_CODE, SPRINT_DISTANCE_CODE}
        
        # 2. Optimized List for the Touch Loop
        self.active_zones = []
        
        # Initialize data structures
        self.process_json_data()
        self.mapper_event_dispatcher.register_callback("ON_JSON_RELOAD", self.process_json_data)

    def process_json_data(self):
        """Pre-processes JSON into a high-speed iteration list."""
        self.release_all()
        self.events_dict.clear()
        
        temp_zones = []
        # Get raw data from the loader
        raw_data = self.mapper.json_loader.json_data
        
        for scancode, value in raw_data.items():
            # Filter out ignored functional codes
            if value.get('name') in self.ignored_names:
                continue
            
            # Pre-convert scancodes to integers once to save CPU during gameplay
            try:
                s_int = int(scancode, 16) if isinstance(scancode, str) else int(scancode)
                temp_zones.append((s_int, value))
            except (ValueError, TypeError):
                continue
        
        self.active_zones = temp_zones
        print(f"[KeyMapper] Hot-path ready: {len(self.active_zones)} zones active.")

    def _send_key_event(self, scancode, down=True, force=False):
        """Dispatches input to Interception Bridge with debounce filtering."""
        now = time.perf_counter()

        if not force:
            # Check if this specific key is 'flickering' too fast
            last_time = self.last_action_times.get(scancode, 0)
            if (now - last_time) < self.debounce_interval:
                return False 

        self.last_action_times[scancode] = now

        # Map internal codes to Bridge methods
        if down:
            if scancode == M_LEFT: self.interception_bridge.left_click_down()
            elif scancode == M_RIGHT: self.interception_bridge.right_click_down()
            elif scancode == M_MIDDLE: self.interception_bridge.middle_click_down()
            else: self.interception_bridge.key_down(scancode)
        else:
            if scancode == M_LEFT: self.interception_bridge.left_click_up()
            elif scancode == M_RIGHT: self.interception_bridge.right_click_up()
            elif scancode == M_MIDDLE: self.interception_bridge.middle_click_up()
            else: self.interception_bridge.key_up(scancode)
        
        return True

    def touch_down(self, event:TouchEvent):        
        """Triggered on finger contact. Scans active_zones for a hit."""
        if self.mapper.device_width <= 0 or self.mapper.device_height <= 0:
            return

        # Normalize coordinates
        nx = event.x / self.mapper.device_width
        ny = event.y / self.mapper.device_height

        # Fast iteration through the pre-filtered list
        for scancode_int, value in self.active_zones:
            hit = False
            v_type = value['type']
            
            if v_type == CIRCLE:
                if is_in_circle(nx, ny, value['cx'], value['cy'], value['r']):
                    hit = True
            elif v_type == RECT:
                if is_in_rect(nx, ny, value['x1'], value['x2'], value['y1'], value['y2']):
                    hit = True

            if hit:
                # Successfully mapped finger to key
                if self._send_key_event(scancode_int, down=True):
                    self.events_dict[event.slot] = [scancode_int, value, event.is_wasd]
                    if event.is_wasd:
                        self.mapper.wasd_block += 1
                        self.mapper_event_dispatcher.dispatch(MapperEvent(action="ON_WASD_BLOCK"))
                return # Stop searching once hit is found


    def touch_up(self, event:TouchEvent):        
        """O(1) Dictionary lookup to release keys when finger lifts."""
        data = self.events_dict.pop(event.slot, None)
        if data:
            scancode_int, _, is_wasd = data
            self._send_key_event(scancode_int, down=False)
            if is_wasd:
                self.mapper.wasd_block = max(0, self.mapper.wasd_block - 1)
                self.mapper_event_dispatcher.dispatch(MapperEvent(action="ON_WASD_BLOCK"))
    
    def process_touch(self, action, touch_event:TouchEvent):
        if action == DOWN:
            self.touch_down(touch_event)
        
        elif action == UP:
            self.touch_up(touch_event)        

    def release_all(self):
        """Flushes all current input states."""
        # We iterate over last_action_times to catch every key that was touched
        for scancode in list(self.last_action_times.keys()):
            self._send_key_event(scancode, down=False, force=True)
        self.last_action_times.clear()
        self.mapper.wasd_block = 0
        