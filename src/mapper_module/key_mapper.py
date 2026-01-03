import time
from .utils import (
    RECT, CIRCLE, M_LEFT, M_RIGHT, M_MIDDLE, 
    SCANCODES, MOUSE_WHEEL_CODE, SPRINT_DISTANCE_CODE, 
    is_in_circle, is_in_rect, MapperEvent
    )

class KeyMapper():
    def __init__(self, mapper, debounce_time=0.01):
        self.mapper = mapper
        self.config = mapper.config
        self.mapper_event_dispatcher = self.mapper.mapper_event_dispatcher
        self.interception_bridge = mapper.interception_bridge

        # Performance: Debouncing logic
        self.debounce_interval = debounce_time  # in seconds (e.g., 0.01 = 10ms)
        self.last_action_times = {} # { scancode: float_timestamp }

        # Format: { slot_id: [scancode, zone_data, is_wasd_finger] }
        self.events_dict = {} 

        self.mapper_event_dispatcher.register_callback("ON_JSON_RELOAD", self.update_json_data)
        self.mapper_event_dispatcher.register_callback("ON_TOUCH_DOWN", self.touch_down)  
        self.mapper_event_dispatcher.register_callback("ON_TOUCH_PRESSED", self.touch_pressed)
        self.mapper_event_dispatcher.register_callback("ON_TOUCH_UP", self.touch_up)

    def update_json_data(self):
        self.release_all()
        self.events_dict.clear()
        self.last_action_times.clear()

    def release_all(self):
        """Release all keys and reset debounce timers."""
        for v in SCANCODES.values():
            self._send_key_event(v, down=False, force=True)
        self.last_action_times.clear()

    def _send_key_event(self, scancode, down=True, force=False):
        """
        Internal helper with debouncing logic.
        Ensures a key doesn't toggle faster than the debounce_interval.
        """
        try:
            s_int = int(scancode, 16) if isinstance(scancode, str) else int(scancode)
            now = time.perf_counter()

            # Debounce check
            if not force:
                last_time = self.last_action_times.get(s_int, 0)
                if (now - last_time) < self.debounce_interval:
                    return False # Too fast, ignore this request

            # Update timestamp
            self.last_action_times[s_int] = now

            # Execute via Bridge
            if down:
                if s_int == M_LEFT: self.interception_bridge.left_click_down()
                elif s_int == M_RIGHT: self.interception_bridge.right_click_down()
                elif s_int == M_MIDDLE: self.interception_bridge.middle_click_down()
                else: self.interception_bridge.key_down(s_int)
            else:
                if s_int == M_LEFT: self.interception_bridge.left_click_up()
                elif s_int == M_RIGHT: self.interception_bridge.right_click_up()
                elif s_int == M_MIDDLE: self.interception_bridge.middle_click_up()
                else: self.interception_bridge.key_up(s_int)
            
            return True
        except ValueError:
            return False

    def touch_down(self, event):
        if self.mapper.device_width == 0 or self.mapper.device_height == 0:
            return

        norm_x = event.x / self.mapper.device_width
        norm_y = event.y / self.mapper.device_height

        with self.mapper.config.config_lock:
            json_items = list(self.mapper.json_loader.json_data.items())

        for scancode, value in json_items:
            name = value.get('name', '')
            if name == MOUSE_WHEEL_CODE or name == SPRINT_DISTANCE_CODE:
                continue

            hit = False
            if value['type'] == CIRCLE:
                if is_in_circle(norm_x, norm_y, value['cx'], value['cy'], value['r']):
                    hit = True
            elif value['type'] == RECT:
                if is_in_rect(norm_x, norm_y, value['x1'], value['x2'], value['y1'], value['y2']):
                    hit = True

            if hit:
                # Attempt to press (subject to debounce)
                if self._send_key_event(scancode, down=True):
                    self.events_dict[event.slot] = [scancode, value, event.is_wasd]
                    if event.is_wasd:
                        self.mapper.wasd_block += 1
                        self.mapper_event_dispatcher.dispatch(MapperEvent(action="WASD"))
                return 

    def touch_pressed(self, event):
        """Handle 'Slide-Off' logic with debouncing."""
        if event.slot not in self.events_dict:
            return

        scancode, value, is_wasd = self.events_dict[event.slot]
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
            # Attempt to release (subject to debounce)
            if self._send_key_event(scancode, down=False):
                self.events_dict.pop(event.slot, None)
                if is_wasd:
                    self.mapper.wasd_block = max(0, self.mapper.wasd_block - 1)
                    self.mapper_event_dispatcher.dispatch(MapperEvent(action="WASD"))

    def touch_up(self, event):
        if event.slot in self.events_dict:
            scancode, _, is_wasd = self.events_dict[event.slot]

            # Attempt to release (subject to debounce)
            if self._send_key_event(scancode, down=False):
                self.events_dict.pop(event.slot, None)
                if is_wasd:
                    self.mapper.wasd_block = max(0, self.mapper.wasd_block - 1)
                    self.mapper_event_dispatcher.dispatch(MapperEvent(action="WASD"))

