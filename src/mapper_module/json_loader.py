from __future__ import annotations
from typing import TYPE_CHECKING

import json
import os
import time
import keyboard
import win32gui
from .utils import (
    MapperEvent, CIRCLE, RECT, RELOAD_DELAY,
    create_default_toml, update_toml
    )

if TYPE_CHECKING:
    from .config import AppConfig

class JSONLoader():
    def __init__(self, config:AppConfig, foreground_window:int):
        self.config = config
        self.mapper_event_dispatcher = config.mapper_event_dispatcher
        self.foreground_window = foreground_window
        
        # State tracking
        self.last_loaded_json_path = None
        self.last_loaded_json_timestamp = 0
        self.json_data = {}
        self.last_reload_time = 0
        
        # Load immediately
        self.load_json()
        
        # REGISTER HOTKEY
        print("[INFO] Press F5 to hot reload json data.")
        keyboard.add_hotkey('f5', self.reload)

    def get_mouse_wheel_info(self):
        return self.mouse_wheel_radius, self.sprint_distance

    def load_json(self):
        system_config = self.config.get('system')
        if not system_config or 'json_path' not in system_config:
            create_default_toml()
            raise RuntimeError("JSON path not found or misconfigured (json_path).")

        self.current_path = system_config['json_path']
        
        self.json_data = self.process_json(self.current_path)
        
        self.last_loaded_json_path = self.current_path
        if os.path.exists(self.current_path):
            self.last_loaded_json_timestamp = os.path.getmtime(self.current_path)

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
                new_data = self.process_json(self.current_path)
                
                with self.config.config_lock:
                    print("[System] Applying new layout...")
                    self.json_data = new_data
                    self.last_loaded_json_path = self.current_path
                    self.last_loaded_json_timestamp = current_file_time
                self.config.reload_config()
                self.mapper_event_dispatcher.dispatch(MapperEvent(action="ON_JSON_RELOAD"))
                    
                print("[System] Layout swapped safely. Game resumed.")
            except Exception as e:
                print(f"[Error] Failed to reload JSON layout: {e}")
        
        else:
            print("Hot reloading skipped as no file or file path changes were detected.")
        
    def process_json(self, json_file_path):
        normalized_zones = {}
        
        if not os.path.exists(json_file_path):
            _str = f"Error: File '{json_file_path}' not found."
            raise RuntimeError(_str)

        with open(json_file_path, mode='r', encoding='utf-8') as f:
            try:
                data = json.load(f)
            except json.JSONDecodeError as e:
                _str = f"Invalid JSON syntax in '{json_file_path}': {e}"
                raise RuntimeError(_str)

            try:
                metadata = data["metadata"]
                content = data["content"]
                screen_width = metadata["width"]
                screen_height = metadata["height"]
                self.dpi = metadata["dpi"]
                self.mouse_wheel_radius = metadata["mouse_wheel_radius"]
                self.sprint_distance = metadata["sprint_distance"]
            except:
                raise RuntimeError(f"Error loading json file")

            self.width = screen_width
            self.height = screen_height

            for item in content:
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
        
        update_toml(w=self.width, h=self.height, dpi=self.dpi, mouse_wheel_radius=self.mouse_wheel_radius, sprint_distance=self.sprint_distance, strict=True)
        return normalized_zones
