import configparser
from dataclasses import dataclass
import os

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
    def __init__(self, filename='config.ini'):
        super().__init__()
        # self.device = None
        # self.game = None
        self.mouse = None
        self.joystick = None
        self.filename = filename
        
        self.load_config(filename)

    def load_config(self, filename):
        if not os.path.exists(filename):
            print(f"Config file {filename} not found! Creating default...")
            self.create_default(filename)
            
        parser = configparser.ConfigParser()
        parser.read(filename)

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
        