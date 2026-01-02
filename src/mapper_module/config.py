import tomllib
import threading
import os
# Use relative imports since this is inside the mapper_module package
from .default_toml_helper import create_default_toml
from .utils import MapperEvent

class AppConfig:
    def __init__(self, filename, mapper_event_dispatcher):
        # super().__init__() is not needed for a base class
        self.filename = filename
        self.mapper_event_dispatcher = mapper_event_dispatcher
        
        # 1. Initialize the lock to protect config_data
        self.config_lock = threading.Lock()
        
        self.config_data = {}
        
        # 2. Load immediately
        self.load_config()
        print(f"Configuration loaded from {self.filename}")

    def load_config(self):
        """Loads TOML data safely. Creates default if missing."""
        try:
            # Check if file exists; if not, create it using your helper
            if not os.path.exists(self.filename):
                print(f"Config file {self.filename} not found! Creating default...")
                create_default_toml()

            # Read the file from disk
            with open(self.filename, "rb") as f:
                new_data = tomllib.load(f)

            # 3. CRITICAL: Use the lock when updating self.config_data
            # This prevents other threads (like KeyMapper) from reading partial data
            with self.config_lock:
                self.config_data = new_data
                
        except tomllib.TOMLDecodeError as e:
            print(f"CRITICAL: Failed to parse TOML. Keeping previous config. Error: {e}")
        except Exception as e:
            print(f"Error loading config: {e}")

    def reload_config(self):
        """Reloads from disk and notifies listeners."""
        print("Reloading TOML configuration...")
        self.load_config()
        
        # Dispatch event so other modules know config changed
        # Uses action="CONFIG" to match the dispatcher in utils.py
        if self.mapper_event_dispatcher:
            self.mapper_event_dispatcher.dispatch(MapperEvent(action="CONFIG"))

    def get(self, key, default=None):
        """
        Thread-safe helper to get values. 
        Use this in your Mappers: config.get("sensitivity")
        """
        with self.config_lock:
            return self.config_data.get(key, default)