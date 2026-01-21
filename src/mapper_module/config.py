from __future__ import annotations
from typing import TYPE_CHECKING

import tomllib
import threading
from pathlib import Path
from .utils import  MapperEvent, TOML_PATH, create_default_toml

if TYPE_CHECKING:
    from .utils import MapperEventDispatcher

class AppConfig:
    def __init__(self, mapper_event_dispatcher:MapperEventDispatcher):
        self.mapper_event_dispatcher = mapper_event_dispatcher
        
        # Initialize the lock to protect config_data
        self.config_lock = threading.Lock()
        
        self.config_data = {}
        
        # Load immediately
        self.load_config()
        print(f"Configuration loaded from {TOML_PATH}")

    def load_config(self):
        """Loads TOML data safely. Creates default if missing."""
        try:
            # Check if file exists, if not create it using your helper
            toml_path = Path(TOML_PATH)
            if not Path.exists(TOML_PATH):
                print(f"Config file {TOML_PATH} not found! Creating default...")
                create_default_toml()

            # Read the file from disk
            with toml_path.open("rb") as f:
                new_data = tomllib.load(f)

            with self.config_lock:
                self.config_data = new_data
                
        except tomllib.TOMLDecodeError as e:
            print(f"CRITICAL: Failed to parse TOML. Keeping previous config. Error: {e}")
        except Exception as e:
            print(f"Error loading config: {e}")

    def reload_config(self):
        """Reloads from disk and notifies listeners."""
        print(f"Reloading TOML configuration from {TOML_PATH}...")
        self.load_config()
        
        # Dispatch event so other modules know config changed
        self.mapper_event_dispatcher.dispatch(MapperEvent(action="ON_CONFIG_RELOAD"))

    def get(self, key, default={}):
        return self.config_data.get(key, default)
