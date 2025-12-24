import configparser
from dataclasses import dataclass
import threading
import os
import threading
import keyboard
import mouse
import configparser
import os
import time
from load_csv import load_csv

@dataclass
class SystemConfig:
    circ_csv_path: str
    rect_csv_path: str

# @dataclass
# class DeviceConfig:
#     width: int
#     height: int
#     dpi: float

# @dataclass
# class GameConfig:
#     width: int
#     height: int
#     offset_x: int
#     offset_y: int

@dataclass
class MouseConfig:
    sensitivity: float
    invert_y: bool

@dataclass
class JoystickConfig:
    deadzone: float
    hysteresis: float
    # sprint_trigger: float


class CSV_Parser():
    def __init__(self):
        self.last_loaded_path = None
        self.last_loaded_timestamp = 0
        self.master_zones = {}

    def reset_inputs():
        """Releases mouse/keys to prevent ghosting."""
        mouse.release()
        # Add any specific key releases here if you track them

    def load_csv_data(self, path):
        self.master_zones = load_csv()

    def smart_reload():
        global last_loaded_path, last_loaded_timestamp
        
        print("\n[System] Checking for updates...")
        
        # READ INI (Fast, no lock needed yet)
        ini = configparser.ConfigParser()
        ini.read('settings.ini')
        
        new_path = ini.get('General', 'layout_path', fallback='')
        new_sens = ini.getfloat('General', 'sensitivity', fallback=1.0)
        
        # ANALYZE: Do we need a HARD RELOAD (CSV)?
        need_csv_reload = False
        current_file_time = 0
        
        if os.path.exists(new_path):
            current_file_time = os.path.getmtime(new_path)
            
        if new_path != last_loaded_path:
            print("[Update] Layout path changed.")
            need_csv_reload = True
        elif current_file_time != last_loaded_timestamp:
            print("[Update] CSV file modification detected.")
            need_csv_reload = True
            
        # 4. HARD RELOAD: Only run this block if CSV actually changed
        if need_csv_reload and os.path.exists(new_path):
            
            # A. Load data into memory FIRST (Don't stop the game yet)
            print("[System] Parsing new CSV...")
            new_shapes_list = load_csv_data(new_path)
            
            # B. CRITICAL SECTION (Stop the game briefly)
            with config_lock:
                print("[Safety] Locking engine & resetting inputs...")
                reset_inputs()
                
                # Swap the data
                current_config['shapes'] = new_shapes_list
                current_config['layout_path'] = new_path
                
                # Update trackers
                last_loaded_path = new_path
                last_loaded_timestamp = current_file_time
                
            print("[System] Layout swapped safely. Game resumed.")
        else:
            print("[System] No layout changes found.")
        

class ConfigReloadEventDispatcher:
    def __init__(self):    
        # The Registry
        self.callback_registry = {
            "ON_CONFIG_RELOAD": []
        }

    def register_callback(self, func):
        self.callback_registry["ON_CONFIG_RELOAD"].append(func)
    
    def unregister_callback(self, func):
        self.callback_registry["ON_CONFIG_RELOAD"].remove(func)

    def dispatch(self):
        for func in self.callback_registry["ON_CONFIG_RELOAD"]:
            func() # Execute the callback

class AppConfig(ConfigReloadEventDispatcher):
    def __init__(self, filename='settings.ini'):
        super().__init__()
        self.system = None
        # self.device = None
        # self.game = None
        self.mouse = None
        self.joystick = None
        self.filename = filename
        self.config_lock = threading.Lock()
        
        self.load_config(filename)

    def load_config(self, filename):
        if not os.path.exists(filename):
            print(f"Config file {filename} not found! Creating default...")
            self.create_default(filename)
            
        parser = configparser.ConfigParser()
        parser.read(filename)
        
        # LOAD SYSTEM
        self.system = SystemConfig(
            circ_csv_path=parser.get('SYSTEM', 'circ_csv_path', fallback="")
            rect_csv_path=parser.get('SYSTEM', 'rect_csv_path', fallback="")
        )
        # # LOAD DEVICE
        # self.device = DeviceConfig(
        #     width=parser.getint('DEVICE', 'width', fallback=2400),
        #     height=parser.getint('DEVICE', 'height', fallback=1080),
        #     dpi=parser.getfloat('DEVICE', 'dpi', fallback=400.0)
        # )

        # # LOAD GAME WINDOW
        # self.game = GameConfig(
        #     width=parser.getint('GAME_WINDOW', 'width', fallback=1920),
        #     height=parser.getint('GAME_WINDOW', 'height', fallback=1080),
        #     offset_x=parser.getint('GAME_WINDOW', 'offset_x', fallback=0),
        #     offset_y=parser.getint('GAME_WINDOW', 'offset_y', fallback=0)
        # )

        # LOAD MOUSE
        self.mouse = MouseConfig(
            sensitivity=parser.getfloat('MOUSE', 'sensitivity', fallback=15.0),
            invert_y=parser.getboolean('MOUSE', 'invert_y', fallback=False)
        )

        # LOAD JOYSTICK
        self.joystick = JoystickConfig(
            deadzone=parser.getfloat('JOYSTICK', 'deadzone', fallback=0.15),
            hysteresis=parser.getfloat('JOYSTICK', 'hysteresis', fallback=5.0),
            sprint_trigger=parser.getfloat('JOYSTICK', 'sprint_trigger', fallback=0.90)
        )
        print("Configuration loaded successfully.")

    def create_default(self, filename):
        # Generate a default file if missing
        parser = configparser.ConfigParser()
        # parser['DEVICE'] = {'width': '2400', 'height': '1080', 'dpi': '400.0'}
        # parser['GAME_WINDOW'] = {'width': '1920', 'height': '1080', 'offset_x': '0', 'offset_y': '0'}
        parser['MOUSE'] = {'sensitivity': '15.0', 'invert_y': 'False'}
        parser['JOYSTICK'] = {'deadzone': '0.15', 'hysteresis': '5.0', 'sprint_trigger': '0.90'}
        
        with open(filename, 'w') as f:
            parser.write(f)
    
    def reload_config(self):
        self.load_config(self.filename)
        self.dispatch()
        
    
    # --- F5 Listener ---
    keyboard.add_hotkey('f5', smart_reload, suppress=True)

    # --- Main Game Loop ---
    print("[Main] Engine Running...")
    while True:
        
        # We acquire lock to ensure the list doesn't vanish while reading
        with config_lock:
            
            # This loop uses the 'shapes' list
            # If sensitivity changed, we use the new value instantly
            sens = current_config['sensitivity'] 
            
            for shape in current_config['shapes']:
                # Your input mapping logic here
                pass
                
        time.sleep(0.01)
        