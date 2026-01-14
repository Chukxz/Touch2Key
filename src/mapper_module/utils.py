import tkinter as tk
from tkinter import filedialog
import subprocess
import os
import ctypes

# Get location of this file: .../mapper_project/src/mapper_module
CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))

# Go up one level to 'src'
SRC_DIR = os.path.dirname(CURRENT_DIR)

# Go up another level to 'mapper_project' (Root)
PROJECT_ROOT = os.path.dirname(SRC_DIR)

# --- Path Assignments ---
TOML_PATH = os.path.join(PROJECT_ROOT, "settings.toml")
IMAGES_FOLDER = os.path.join(SRC_DIR, "resources", "images")
JSONS_FOLDER = os.path.join(SRC_DIR, "resources", "jsons")

# --- Constants ---   

DEF_DPI = 160

DOWN = "DOWN"
UP = "UP"
PRESSED = "PRESSED"
IDLE = "IDLE"

CIRCLE = "CIRCLE"
RECT = "RECT"
RELOAD_DELAY = 0.5
M_LEFT = 0x9901
M_RIGHT = 0x9902
M_MIDDLE = 0x9903
SPRINT_DISTANCE_CODE = "F11"
MOUSE_WHEEL_CODE = "F12"
WINDOW_FIND_DELAY = 1 # in seconds

# --- Fallback Performance Constants ---
# Limits PRESSED events to 250 updates per second
DEFAULT_ADB_RATE_CAP = 250.0  

# Ignores key flickers faster than 10ms
KEY_DEBOUNCE = 0.01

# Default ADB latency threshold
DEFAULT_LATENCY_THRESHOLD = 0.05

DOUBLE_TAP_DELAY = 0.25

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
    "MOUSE_LEFT":   M_LEFT,
    "MOUSE_RIGHT":  M_RIGHT, 
    "MOUSE_MIDDLE": M_MIDDLE,
})


class TouchEvent:
    def __init__(self, slot, id, x, y, sx, sy, is_mouse, is_wasd):
        self.slot = slot
        self.id = id
        self.x = x
        self.y = y
        self.sx = sx
        self.sy = sy
        self.is_mouse = is_mouse
        self.is_wasd = is_wasd
        self.is_key = not self.is_mouse
        
    def show(self):
        return f"Slot: {self.slot}, ID: {self.id}, X: {self.x}, Y: {self.y}, SX: {self.sx}, SY: {self.sy}, isMouse: {self.is_mouse}, isWASD: {self.is_wasd}"

class MapperEvent:
    def __init__(self, action, pac_t = None, pac_n = None, is_visible=True):
        self.action = action # UP, DOWN, PRESSED, CONFIG, JSON, NETWORK
        self.pac_t = pac_t
        self.pac_n = pac_n
        self.is_visible = is_visible
    
    def show(self):
        _ = self.touch.log() if self.touch is not None else ""
        return f"Action: {self.action}\n Touch: {_}\n Packets (N: {self.pac_n}, Avg Time(1s dur): {self.pac_t})"
        
class MapperEventDispatcher:
    def __init__(self):    
        # The Registry
        self.callback_registry = {
            "ON_CONFIG_RELOAD":     [],
            "ON_JSON_RELOAD":       [],
            "ON_WASD_BLOCK":        [],
            "ON_NETWORK_LAG":       [],
            "ON_MENU_MODE_TOGGLE":  [],
        }
        
        # Map simple action names to full registry keys
        self.action_map = {
            "CONFIG":           "ON_CONFIG_RELOAD",
            "JSON":             "ON_JSON_RELOAD",
            "WASD":             "ON_WASD_BLOCK",
            "NETWORK":          "ON_NETWORK_LAG",
            "MENU_MODE_TOGGLE": "ON_MENU_MODE_TOGGLE",
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
        registry_key = self.action_map.get(event_object.action)
        
        if registry_key:
            for func in self.callback_registry[registry_key]:
                if event_object.action in ["CONFIG", "JSON", "WASD"]:
                    func()
                elif event_object.action in ["NETWORK"]:
                    func(event_object.pac_n, event_object.pac_t)
                elif event_object.action in ["MENU_MODE_TOGGLE"]:
                    func(event_object.is_visible)


def get_adb_device():
    out = subprocess.check_output(["adb", "devices"]).decode().splitlines()
    real = [l.split()[0] for l in out[1:] if "device" in l and not l.startswith("emulator-")]

    if not real:
        raise RuntimeError("No real device detected")
    else:
        return real[0]
    

def get_screen_size(device):
    """Detect screen resolution (portrait natural)."""
    result = subprocess.run(
        ["adb", "-s", device, "shell", "wm", "size"], capture_output=True, text=True
    )
    output = result.stdout.strip()
    if "Physical size" in output:
        w, h = map(int, output.split(":")[-1].strip().split("x"))
        return w, h

    return None


def get_dpi(device):
    """Detect screen DPI, fallback to 160."""
    try:
        result = subprocess.run(["adb", "-s", device, "shell", "getprop", "ro.sf.lcd_density"],
                                capture_output=True, text=True, timeout=1)
        val = result.stdout.strip()
        return int(val) if val else DEF_DPI
    except Exception:
        return DEF_DPI

def is_device_online(device):
    try:
        res = subprocess.run(["adb", "-s", device, "get-state"], 
                            capture_output=True, text=True, timeout=1)
        return "device" in res.stdout
    except:
        return False

def set_dpi_awareness():
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(1) 
    except Exception:
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except: pass

def select_image_file(base_dir = None):
    # Create a root window and hide it immediately
    root = tk.Tk()
    root.withdraw() 
    root.attributes('-topmost', True) # Bring to front

    # Open the file selector
    file_path = filedialog.askopenfilename(
        initialdir=base_dir,
        title="Select an Image",
        filetypes=[
            ("Image Files", "*.jpg *.jpeg *.png *.bmp *.webp"),
            ("All Files", "*.*")
        ]
    )
    
    # Destroy the hidden root explicitly after selection
    root.destroy()
    
    return file_path

def is_in_circle(px, py, cx, cy, r):
    return (px - cx)**2 + (py - cy)**2 <= r*r

def is_in_rect(px, py, left, right, top, bottom):
    return (left <= px <= right) and (top <= py <= bottom)

def configure_config(w, h, dpi, image_path):
    try:
        if not os.path.exists(TOML_PATH):
            create_default_toml()

        with open(TOML_PATH, "r", encoding="utf-8") as f:
            doc = tomlkit.load(f)

        if "system" not in doc: 
            doc.add("system", tomlkit.table())

        # Update TOML settings
        doc["system"]["json_dev_res"] = [w, h]
        doc["system"]["json_dev_dpi"] = dpi
        doc["system"]["hud_image_path"] = os.path.normpath(image_path)

        with open(TOML_PATH, "w", encoding="utf-8") as f:
            tomlkit.dump(doc, f)
    except Exception as e:
        raise RuntimeError(e)