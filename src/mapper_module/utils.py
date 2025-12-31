import tkinter as tk
from tkinter import filedialog

DEF_DPI = 160
CSV_FOLDER_NAME = "CSV"
CIRCLE = "CIRCLE"
RECT = "RECT"

TOML_PATH = "./settings.toml"

SCANCODES = {
    "ESC": 0x01,
    "1": 0x02,
    "2": 0x03,
    "3": 0x04,
    "4": 0x05,
    "5": 0x06,
    "6": 0x07,
    "7": 0x08,
    "8": 0x09,
    "9": 0x0A,
    "0": 0x0B,
    "MINUS": 0x0C,
    "EQUAL": 0x0D,
    "BACKSPACE": 0x0E,
    "TAB": 0x0F,

    "q": 0x10,
    "w": 0x11,
    "e": 0x12,
    "r": 0x13,
    "t": 0x14,
    "y": 0x15,
    "u": 0x16,
    "i": 0x17,
    "o": 0x18,
    "p": 0x19,
    "LEFT_BRACKET": 0x1A,
    "RIGHT_BRACKET": 0x1B,
    "ENTER": 0x1C,
    "LCTRL": 0x1D,

    "a": 0x1E,
    "s": 0x1F,
    "d": 0x20,
    "f": 0x21,
    "g": 0x22,
    "h": 0x23,
    "j": 0x24,
    "k": 0x25,
    "l": 0x26,
    "SEMICOLON": 0x27,
    "APOSTROPHE": 0x28,
    "GRAVE": 0x29,

    "LSHIFT": 0x2A,
    "BACKSLASH": 0x2B,

    "z": 0x2C,
    "x": 0x2D,
    "c": 0x2E,
    "v": 0x2F,
    "b": 0x30,
    "n": 0x31,
    "m": 0x32,
    "COMMA": 0x33,
    "DOT": 0x34,
    "SLASH": 0x35,

    "RSHIFT": 0x36,
    "NUM_MULTIPLY": 0x37,
    "LALT": 0x38,
    "SPACE": 0x39,
    "CAPSLOCK": 0x3A,

    "F1": 0x3B,
    "F2": 0x3C,
    "F3": 0x3D,
    "F4": 0x3E,
    "F5": 0x3F,
    "F6": 0x40,
    "F7": 0x41,
    "F8": 0x42,
    "F9": 0x43,
    "F10": 0x44,

    "NUMLOCK": 0x45,
    "SCROLLLOCK": 0x46,

    "NUM_7": 0x47,
    "NUM_8": 0x48,
    "NUM_9": 0x49,
    "NUM_MINUS": 0x4A,
    "NUM_4": 0x4B,
    "NUM_5": 0x4C,
    "NUM_6": 0x4D,
    "NUM_PLUS": 0x4E,
    "NUM_1": 0x4F,
    "NUM_2": 0x50,
    "NUM_3": 0x51,
    "NUM_0": 0x52,
    "NUM_DOT": 0x53,

    "F11": 0x57,
    "F12": 0x58,

    # Extended (E0 prefixed)

    "E0_HOME": 0xE047,
    "E0_UP": 0xE048,
    "E0_PAGEUP": 0xE049,
    "E0_PAGEDOWN": 0xE051,
    "E0_LEFT": 0xE04B,
    "E0_RIGHT": 0xE04D,
    "E0_END": 0xE04F,
    "E0_DOWN": 0xE050,
    "E0_INSERT": 0xE052,
    "E0_DELETE": 0xE053,

    "RCTRL": 0xE01D,
    "RALT": 0xE038,
    "E0_ENTER": 0xE01C,
    "E0_SLASH": 0xE035,
    "E0_NUM_ENTER": 0xE01C,
}

# Note: Non standard, just for internal recognition
SCANCODES.update({
    "MOUSE_LEFT":   0x9901, 
    "MOUSE_RIGHT":  0x9902, 
    "MOUSE_MIDDLE": 0x9903
})

class TouchMapperEvent:
    def __init__(self, slot, tracking_id, x, y, sx, sy, is_mouse, is_wasd):
        self.slot = slot
        self.id = tracking_id
        self.x = x
        self.y = y
        self.sx = sx
        self.sy = sy
        self.is_mouse = is_mouse
        self.is_wasd = is_wasd

class MapperEvent:
    def __init__(self, action, touch: TouchMapperEvent | None = None):
        self.touch = touch
        self.action = action # UP, DOWN, PRESSED, CONFIG, CSV
        
class MapperEventDispatcher:
    def __init__(self):    
        # The Registry
        self.callback_registry = {
            "ON_TOUCH_DOWN": [],
            "ON_TOUCH_UP": [],
            "ON_TOUCH_PRESSED": [],
            "ON_CONFIG_RELOAD": [],
            "ON_CSV_RELOAD": []
        }

    def register_callback(self, event_type, func):
        if event_type in self.callback_registry:
            self.callback_registry[event_type].append(func)
        else:
            print(f"[Warning] Attempted to register unknown event: {event_type}")
    
    def unregister_callback(self, event_type, func):
        if event_type in self.callback_registry:
            if func in self.callback_registry[event_type]:
                self.callback_registry[event_type].remove(func)
            else:
                print(f"[Warning] Function {func.__name__} was not registered for {event_type}")

    def dispatch(self, event_object: MapperEvent):
        # Map simple action names to full registry keys
        action_map = {
            "DOWN": "ON_TOUCH_DOWN",
            "UP": "ON_TOUCH_UP",
            "PRESSED": "ON_TOUCH_PRESSED",
            "CONFIG": "ON_CONFIG_RELOAD",
            "CSV": "ON_CSV_RELOAD"
        }
        
        registry_key = action_map.get(event_object.action)
        
        if registry_key:
            for func in self.callback_registry[registry_key]:
                # Input events need the touch object; System events (Config/CSV) do not.
                if event_object.action in ["CONFIG", "CSV"]:
                    func()
                else:
                    func(event_object.touch)
                    

def select_image_file():
    # Create a root window and hide it immediately
    root = tk.Tk()
    root.withdraw() 
    
    # Open the file selector
    file_path = filedialog.askopenfilename(
        title="Select an Image",
        filetypes=[
            ("Image Files", "*.jpg *.jpeg *.png *.bmp"),
            # ("All Files", "*.*")
        ]
    )
    
    # Destroy the hidden root explicitly after selection
    root.destroy()
    
    return file_path
