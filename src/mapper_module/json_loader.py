import json
import os
import time
from utils import MapperEvent, CIRCLE, RECT, RELOAD_DELAY
from default_toml_helper import create_default_toml

class JSON_Loader():
    def __init__(self, config):
        self.last_loaded_path = None
        self.last_loaded_timestamp = 0
        self.master_zones = {}
        self.mapper_event_dispatcher = config.mapper_event_dispatcher
        self.config = config
        self.last_loaded_json_path = None
        self.last_loaded_json_timestamp = None
        self.load_json()
        
    def get_mouse_wheel_configuration(self):
        try:
            mouse_wheel_conf = self.config.config_data['key']['mouse_wheel_conf']
            return mouse_wheel_conf
        except:
            create_default_toml()
            raise RuntimeError("Mouse Wheel Configuration not found or misconfigured (mouse_wheel_conf).")

    def load_json(self):
        try:
            current_path = self.config.config_data['system']['json_path']
        except:
            create_default_toml()
            raise RuntimeError("JSON path not found or misconfigured (json_path).")

        self.json_data = self.process_json(current_path)
        
        self.last_loaded_json_path = current_path
        if os.path.exists(current_path):
            self.last_loaded_json_timestamp = os.path.getmtime(current_path)

        
    def should_reload(self, old_path, new_path, last_timestamp):
        # ANALYZE: Do we need a HARD RELOAD?
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
        
        return need_reload

    def reload(self):
        # print("\n[System] Checking for updates...")
        
        current_path = self.config.config_data['system']['json_path']
        
        # Check if reload is needed
        need_reload = self.should_reload(
            self.last_loaded_json_path, 
            current_path, 
            self.last_loaded_json_timestamp
        )
                    
        if need_reload:
            try:
                # Load data into memory FIRST (Don't stop the game yet)
                print("[System] Parsing new JSON...")
                # We call process_json directly here to test the data before applying
                new_data = self.process_json(current_path)
                
                # CRITICAL SECTION (Stop the game briefly)
                with self.config.config_lock:
                    print("[System] Applying new layout...")
                    self.json_data = new_data
                    self.last_loaded_json_path = current_path
                    self.last_loaded_json_timestamp = os.path.getmtime(current_path)
                    self.mapper_event_dispatcher.dispatch(MapperEvent(action="JSON", json_data=new_data))
                    
                print("[System] Layout swapped safely. Game resumed.")
            except Exception as e:
                print(f"[Error] Failed to reload JSON layout: {e}")
        
        time.sleep(RELOAD_DELAY)

    def normalize_json_data(self, file_path, screen_width, screen_height):
        """ 
        Reads a JSON file, normalizes all coordinates to 0.0-1.0.
        """
        normalized_zones = {}
        
        if not os.path.exists(file_path):
            # Return empty or raise depending on preference. Raising ensures you know it failed.
            raise RuntimeError(f"Error: File {file_path} not found.")

        with open(file_path, mode='r', encoding='utf-8') as f:
            try:
                data = json.load(f)
            except json.JSONDecodeError as e:
                raise RuntimeError(f"Invalid JSON syntax in {file_path}: {e}")
            
            for item in data:
                scancode = item.get("scancode")
                if scancode is None: 
                    continue
                                
                zone_type = item.get("type")

                is_circ = zone_type == CIRCLE
                is_rect = zone_type == RECT 

                zone_data = {}                
                zone_data['name'] = item['name']
                
                try:
                    if is_circ:
                        zone_data['type'] = CIRCLE
                        # Normalize Center
                        zone_data['cx'] = float(item['cx']) / screen_width
                        zone_data['cy'] = float(item['cy']) / screen_height
                        # Normalize Radius (using width for aspect ratio consistency)
                        zone_data['r'] = float(item['val1']) / screen_width

                    elif is_rect:
                        zone_data['type'] = RECT
                        zone_data['x1'] = float(item['val1']) / screen_width
                        zone_data['y1'] = float(item['val2']) / screen_height
                        zone_data['x2'] = float(item['val3']) / screen_width
                        zone_data['y2'] = float(item['val4']) / screen_height
                        
                    # Add to master dict
                    normalized_zones[scancode] = zone_data
                    
                except (ValueError, KeyError) as e:
                    print(f"Skipping invalid item: {scancode}. Error: {e}")
                    continue

        return normalized_zones

    def process_json(self, json_path):
        try:
            w, h = self.config.config_data['system']['json_dev_res']
            self.width = int(w)
            self.height = int(h)     
        except:
            create_default_toml()
            raise RuntimeError("Resolution not found or misconfigured (json_dev_res).")
        
        try:
            self.dpi = int(self.config.config_data['system']['json_dev_dpi'])
        except:
            create_default_toml()
            raise RuntimeError("DPI not found or misconfigured (json_dev_dpi).")
        
        return self.normalize_json_data(json_path, w, h)