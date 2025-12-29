import tomllib
import threading
import os
from default_toml_helper import create_default_toml
from utils import MapperEvent

class AppConfig():
    def __init__(self, filename, mapper_event_dispacher):
        super().__init__()
        self.system = None
        # self.device = None
        # self.game = None
        self.mouse = None
        self.joystick = None
        self.filename = filename
        self.mapper_event_dispacher = mapper_event_dispacher
        self.config_lock = threading.Lock()
        self.config_data = {}
        self.load_config(filename)
        print("Configuration loaded successfully.")

    def load_config(self):
        data = {}
        
        if not os.path.exists(self.filename):
            print(f"Config file {self.filename} not found! Creating default...")
            data = self.create_default(self.filename)
            
        with open(self.filename, "rb") as f:
            data = tomllib.load(f)
        
        self.config_data = data

    def create_default(self, filename):
        data = {}        
        create_default_toml()        
        with open(filename, "rb") as f:
            data = tomllib.load(f)
        
        return data
    
    def reload_config(self):
        self.load_config()
        print("Configuration reloaded successfully.")
        self.mapper_event_dispacher.dispatch(MapperEvent(action="CONFIG"))
        