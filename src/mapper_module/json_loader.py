import json
import os
import time
import keyboard
import win32gui
from .utils import (
    MapperEvent, CIRCLE, RECT, RELOAD_DELAY,
    MOUSE_WHEEL_CODE, SPRINT_DISTANCE_CODE
    )

from .default_toml_helper import create_default_toml

class JSON_Loader():
    def __init__(self, config, foreground_window):
        self.config = config
        self.mapper_event_dispatcher = config.mapper_event_dispatcher
        self.foreground_window = foreground_window
        
        # State tracking
        self.last_loaded_json_path = None
        self.last_loaded_json_timestamp = 0
        self.json_data = {}
        self.last_reload_time = 0
        self.physical_dev_params = None
        
        # Load immediately
        self.load_json()
        self.physical_dev_params = self.width, self.height, self.dpi
        self.mapper_event_dispatcher.register_callback("ON_LOAD_JSON", self.set_physical_dev_params)
        
        # --- SELF REGISTER HOTKEY ---
        print("[INFO] Press F5 to hot reload json data.")
        keyboard.add_hotkey('f5', self.reload)
    
    def set_physical_dev_params(self, _physical_dev_params):
        self.physical_dev_params = _physical_dev_params

    def get_mouse_wheel(self, force=False):
        joystick_config = self.config.get('joystick')
        if not joystick_config:
            create_default_toml()
            raise RuntimeError("'joystick' section not found in configuration.")
            
        if not hasattr(self, 'mouse_wheel') or force:        
            for v in self.json_data.values():
                if v.get('name') == MOUSE_WHEEL_CODE:
                    self.mouse_wheel = v
                    return
            
            _str = f"Mouse Wheel zone ('{MOUSE_WHEEL_CODE}') not found in JSON layout."
            raise RuntimeError(_str)

    def get_mouse_wheel_radius(self):
        self.get_mouse_wheel()
        w, _, _ = self.physical_dev_params
        mouse_wheel_radius = self.mouse_wheel['r'] * w     
        
        with self.config.config_lock:
            if 'joystick' in self.config.config_data:
                self.config.config_data['joystick']['mouse_wheel_radius'] = mouse_wheel_radius                
        
        return mouse_wheel_radius   
        
    def get_sprint_distance(self):
        self.get_mouse_wheel()
        _, h, _ = self.physical_dev_params
        
        for v in self.json_data.values():
            if v.get('name') == SPRINT_DISTANCE_CODE:
                sprint_distance = (v['cy'] - self.mouse_wheel['cy']) * h
                
                with self.config.config_lock:
                    if 'joystick' in self.config.config_data:
                        self.config.config_data['joystick']['sprint_distance'] = sprint_distance
                return sprint_distance
        
        _str = f"Sprint Distance zone ('{SPRINT_DISTANCE_CODE}') not found in JSON layout."
        raise RuntimeError(_str)

    def load_json(self):
        system_config = self.config.get('system')
        if not system_config or 'json_path' not in system_config:
            create_default_toml()
            raise RuntimeError("JSON path not found or misconfigured (json_path).")

        current_path = system_config['json_path']
        
        self.json_data = self.process_json(current_path)
        
        self.last_loaded_json_path = current_path
        if os.path.exists(current_path):
            self.last_loaded_json_timestamp = os.path.getmtime(current_path)

    def should_reload(self, old_path, new_path, last_timestamp):
        need_reload = False
        current_file_time = 0
        
        if os.path.exists(new_path):
            current_file_time = os.path.getmtime(new_path)
                
            if new_path != old_path:
                print(f"[Update] Layout path changed: '{old_path}' -> '{new_path}'")
                need_reload = True
            elif current_file_time != last_timestamp:
                print(f"[Update] JSON file modification detected: '{new_path}'")
                need_reload = True
        
        return need_reload, current_file_time

    def reload(self):
        current_time = time.time()
        if current_time - self.last_reload_time < RELOAD_DELAY:
            return
        
        if not win32gui.GetForegroundWindow() == self.foreground_window:
            return
        
        self.last_reload_time = current_time
        
        system_config = self.config.get('system')
        if not system_config:
            create_default_toml()
            raise RuntimeError("'system' section not found in configuration")

        current_path = system_config.get('json_path')
        
        need_reload, current_file_time = self.should_reload(
            self.last_loaded_json_path, 
            current_path, 
            self.last_loaded_json_timestamp
        )
                    
        if need_reload:
            try:
                print("[System] Parsing new JSON...")
                new_data = self.process_json(current_path)
                
                with self.config.config_lock:
                    print("[System] Applying new layout...")
                    self.json_data = new_data
                    self.last_loaded_json_path = current_path
                    self.last_loaded_json_timestamp = current_file_time
                    self.get_mouse_wheel(force=True)                    
                    self.mapper_event_dispatcher.dispatch(MapperEvent(action="JSON"))
                    
                print("[System] Layout swapped safely. Game resumed.")
            except Exception as e:
                print(f"[Error] Failed to reload JSON layout: {e}")
        
        else:
            print("Hot reloading skipped as no file or file path changes were detected.")
        
    def normalize_json_data(self, file_path, screen_width, screen_height):
        normalized_zones = {}
        
        if not os.path.exists(file_path):
            _str = f"Error: File '{file_path}' not found."
            raise RuntimeError(_str)

        with open(file_path, mode='r', encoding='utf-8') as f:
            try:
                data = json.load(f)
            except json.JSONDecodeError as e:
                _str = f"Invalid JSON syntax in '{file_path}': {e}"
                raise RuntimeError(_str)

            for item in data:
                scancode = item.get("scancode")
                if scancode is None: 
                    continue
                                
                zone_type = item.get("type")
                is_circ = zone_type == CIRCLE
                is_rect = zone_type == RECT 

                zone_data = {}                
                zone_data['name'] = item.get('name', '')
                zone_data['type'] = zone_type
                
                try:
                    if is_circ:
                        zone_data['cx'] = float(item['cx']) / screen_width
                        zone_data['cy'] = float(item['cy']) / screen_height
                        zone_data['r'] = float(item['val1']) / screen_width
                        zone_data['val1'] = float(item['val1'])

                    elif is_rect:
                        zone_data['x1'] = float(item['val1']) / screen_width
                        zone_data['y1'] = float(item['val2']) / screen_height
                        zone_data['x2'] = float(item['val3']) / screen_width
                        zone_data['y2'] = float(item['val4']) / screen_height
                        
                        zone_data['val1'] = float(item['val1'])
                        zone_data['val2'] = float(item['val2'])
                        zone_data['val3'] = float(item['val3'])
                        zone_data['val4'] = float(item['val4'])
                    
                    normalized_zones[scancode] = zone_data
                    
                except (ValueError, KeyError) as e:
                    print(f"Skipping invalid item: {scancode}. Error: {e}")
                    continue

        return normalized_zones

    def process_json(self, json_path):
        system_config = self.config.get('system', {})
        res = system_config.get('json_dev_res')
        
        if not res or len(res) != 2:
            create_default_toml()
            raise RuntimeError("Resolution not found or misconfigured (json_dev_res).")
        
        w, h = res
        self.width = int(w)
        self.height = int(h)   
        
        self.dpi = int(system_config.get('json_dev_dpi', 160))
        
        return self.normalize_json_data(json_path, w, h)