from __future__ import annotations
from typing import TYPE_CHECKING

import json
import os
import time
import keyboard

from modules.platforms import get_platform

from modules.utils import (
    MapperEvent,
    CIRCLE,
    RECTANGLE,
    RELOAD_DELAY,
    create_default_toml,
    update_toml,
)

if TYPE_CHECKING:
    from .config import AppConfig


class JSONLoader:
    def __init__(self, config: AppConfig, foreground_window):
        self.window_manager = get_platform().WindowManager()

        self.config = config
        self.mapper_event_dispatcher = config.mapper_event_dispatcher
        self.foreground_window = foreground_window

        # State tracking
        self.last_loaded_json_path = None
        self.last_loaded_json_timestamp = 0
        self.json_data: list[tuple[str, dict]] = []
        self.last_reload_time = 0

        # Default values
        self.width, self.height = self.config.get("system", {}).get(
            "json_dev_res", [360, 800]
        )
        self.dpi = self.config.get("system", {}).get("json_dev_dpi", 160)
        self.mouse_wheel_radius = self.config.get("joystick", {}).get(
            "mouse_wheel_radius", 50.0
        )
        self.sprint_distance = self.config.get("joystick", {}).get(
            "sprint_distance", 10.0
        )

        # Load immediately
        self._load_json()

        # REGISTER HOTKEY
        print(
            "\n[JSONLOADER] - Press F8 to hot _reload json data (always reloads config)."
        )
        keyboard.add_hotkey("f8", self._reload)

    def get_mouse_wheel_info(self):
        return self.mouse_wheel_radius, self.sprint_distance

    def _load_json(self):
        system_config = self.config.get("system")
        if not system_config or "json_path" not in system_config:
            create_default_toml()
            raise RuntimeError("\n[JSONLOADER] - JSON path not found or misconfigured.")

        current_path = system_config["json_path"]
        new_data = self._process_json(current_path)

        with self.config.config_lock:
            self.json_data = new_data
            self.last_loaded_json_path = current_path
            if os.path.exists(current_path):
                self.last_loaded_json_timestamp = os.path.getmtime(current_path)

    def _should_reload(self, old_path, new_path, last_timestamp):
        need_reload = False
        current_file_time = 0

        if os.path.exists(new_path):
            current_file_time = os.path.getmtime(new_path)

            if new_path != old_path:
                print(
                    f"\n[JSONLOADER] - Layout path changed: '{old_path}' -> '{new_path}'."
                )
                need_reload = True
            elif current_file_time != last_timestamp:
                print(
                    f"\n[JSONLOADER] - JSON file modification detected: '{new_path}'."
                )
                need_reload = True

        return need_reload, current_file_time

    def _reload(self):
        current_time = time.time()
        if current_time - self.last_reload_time < RELOAD_DELAY:
            return

        if not self.window_manager.get_foreground_window() == self.foreground_window:
            return

        self.last_reload_time = current_time

        system_config = self.config.get("system")
        if not system_config:
            create_default_toml()
            raise RuntimeError(
                "\n[JSONLOADER] - 'system' section not found in configuration."
            )

        current_path = system_config.get("json_path")

        need_reload, current_file_time = self._should_reload(
            self.last_loaded_json_path, current_path, self.last_loaded_json_timestamp
        )

        if need_reload:
            try:
                print("\n[JSONLOADER] - Parsing new JSON...")
                new_data = self._process_json(current_path)

                with self.config.config_lock:
                    print("\n[JSONLOADER] - Applying new layout...")
                    self.json_data = new_data
                    self.last_loaded_json_path = current_path
                    self.last_loaded_json_timestamp = current_file_time
                self.mapper_event_dispatcher.dispatch(
                    MapperEvent(action="ON_JSON_RELOAD")
                )

                print("\n[JSONLOADER] - Layout swapped safely. Game resumed.")
            except Exception as e:
                print(f"\n[JSONLOADER] - Failed to _reload JSON layout: {e}.")

        else:
            print(
                "\n[JSONLOADER] - JSON hot reloading skipped as no file or file path changes were detected."
            )

        self.config.reload_config()

    def _process_json(self, json_file_path):
        normalized_zones: list[tuple[str, dict]] = []
        data = {}

        try:
            if not os.path.exists(json_file_path):
                _str = f"\n[JSONLOADER] - Error: File '{json_file_path}' not found."
                raise FileNotFoundError(_str)

            with open(json_file_path, mode="r", encoding="utf-8", newline="") as f:
                try:
                    data = json.load(f)
                except json.JSONDecodeError as e:
                    _str = f"\n[JSONLOADER] - Invalid JSON syntax in '{json_file_path}': {e}."
                    raise SyntaxError(_str)

        except (FileNotFoundError, SyntaxError) as e:
            print(e)

        content = []

        try:
            metadata = data["metadata"]
            content = data["content"]
            self.width = metadata["width"]
            self.height = metadata["height"]
            self.dpi = metadata["dpi"]
            self.mouse_wheel_radius = metadata["mouse_wheel_radius"]
            self.sprint_distance = metadata["sprint_distance"]

        except (KeyError, TypeError) as e:
            print(f"\n[JSONLOADER] - Error parsing JSON: {e} not found.")

        for item in content:
            scancode: str | None = item.get("scancode")
            if scancode is None:
                continue

            zone_type = item.get("type")
            is_circle = zone_type == CIRCLE
            is_rectangle = zone_type == RECTANGLE

            zone_data = {}
            zone_data["name"] = item.get("name", "")
            zone_data["type"] = zone_type

            try:
                if is_circle:
                    zone_data["cx"] = float(item["cx"]) / self.width
                    zone_data["cy"] = float(item["cy"]) / self.height
                    zone_data["r"] = float(item["val1"]) / self.width

                elif is_rectangle:
                    zone_data["x1"] = float(item["val1"]) / self.width
                    zone_data["y1"] = float(item["val2"]) / self.height
                    zone_data["x2"] = float(item["val3"]) / self.width
                    zone_data["y2"] = float(item["val4"]) / self.height

                zone_data["move_camera"] = bool(item.get("move_camera", False))

                normalized_zones.append((scancode, zone_data))

            except (ValueError, KeyError) as e:
                print(
                    f"\n[JSONLOADER] - Skipping invalid item: {scancode} with name: {zone_data['name']}. Error: {e}."
                )
                continue

        update_toml(
            w=self.width,
            h=self.height,
            dpi=self.dpi,
            mouse_wheel_radius=self.mouse_wheel_radius,
            sprint_distance=self.sprint_distance,
            strict=True,
        )

        return normalized_zones
