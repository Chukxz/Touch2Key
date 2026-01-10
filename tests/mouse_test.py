import time
import threading
import subprocess
import re
import keyboard
import os
from interception import Interception, KeyStroke, MouseStroke
import ctypes
import math


# import tkinter as tk
# from tkinter import filedialog
# import subprocess
# import os

# # Get location of this file: .../mapper_project/src/mapper_module
# CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))

# # Go up one level to 'src'
# SRC_DIR = os.path.dirname(CURRENT_DIR)

# # Go up another level to 'mapper_project' (Root)
# PROJECT_ROOT = os.path.dirname(SRC_DIR)

# # --- Path Assignments ---
# TOML_PATH = os.path.join(PROJECT_ROOT, "settings.toml")
# IMAGES_FOLDER = os.path.join(SRC_DIR, "resources", "images")
# JSONS_FOLDER = os.path.join(SRC_DIR, "resources", "jsons")

# --- Constants ---   

DEF_DPI = 160
CIRCLE = "CIRCLE"
RECT = "RECT"
RELOAD_DELAY = 0.01
M_LEFT = 0x9901
M_RIGHT = 0x9902
M_MIDDLE = 0x9903
SPRINT_DISTANCE_CODE = "F11"
MOUSE_WHEEL_CODE = "F12"
WINDOW_FIND_RETRIES = 100
WINDOW_FIND_DELAY = 1 # in seconds

SENSITIVITY = 1.0

DEADZONE = 0.2
HYSTERISIS = 15
MOUSE_WHEEL_RADIUS = 79.0
SPRINT_DISTANCE = 353.0

# --- Fallback Performance Constants ---
# Limits PRESSED events to 250 updates per second
DEFAULT_ADB_RATE_CAP = 250.0  

# Ignores key flickers faster than 10ms
DEFAULT_KEY_DEBOUNCE = 0.01

RES = [720, 1612]  # Example resolution
DPI = 320  # Example DPI

# DISP = [1366, 768]


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

class TouchMapperEvent:
    def __init__(self, slot, id, x, y, sx, sy, is_mouse, is_wasd):
        self.slot = slot
        self.id = id
        self.x = x
        self.y = y
        self.sx = sx
        self.sy = sy
        self.is_mouse = is_mouse
        self.is_wasd = is_wasd
        
    def log(self):
        return f"Slot: {self.slot}, ID: {self.id}, X: {self.x}, Y: {self.y}, SX: {self.sx}, SY: {self.sy}, isMouse: {self.is_mouse}, isWASD: {self.is_wasd}"

class MapperEvent:
    def __init__(self, action, touch: TouchMapperEvent | None = None):
        self.touch = touch
        self.action = action # UP, DOWN, PRESSED, CONFIG, JSON        
    
    def log(self):
        _ = self.touch.log() if self.touch is not None else ""
        return f"Action: {self.action}\n Touch: {_}"
        
class MapperEventDispatcher:
    def __init__(self):    
        # The Registry
        self.callback_registry = {
            "ON_TOUCH_DOWN": [],
            "ON_TOUCH_UP": [],
            "ON_TOUCH_PRESSED": [],
            "ON_CONFIG_RELOAD": [],
            "ON_JSON_RELOAD": [],
            "ON_WASD_BLOCK": [],
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
            "JSON": "ON_JSON_RELOAD",
            "WASD": "ON_WASD_BLOCK",
        }
        
        registry_key = action_map.get(event_object.action)
        
        if registry_key:
            for func in self.callback_registry[registry_key]:
                if event_object.action in ["CONFIG", "WASD", "JSON"]:
                    func()
                else:
                    func(event_object.touch)


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
    

# def select_image_file(base_dir = None):
#     # Create a root window and hide it immediately
#     root = tk.Tk()
#     root.withdraw() 
#     root.attributes('-topmost', True) # Bring to front

#     # Open the file selector
#     file_path = filedialog.askopenfilename(
#         initialdir=base_dir,
#         title="Select an Image",
#         filetypes=[
#             ("Image Files", "*.jpg *.jpeg *.png *.bmp"),
#             ("All Files", "*.*")
#         ]
#     )
    
#     # Destroy the hidden root explicitly after selection
#     root.destroy()
    
#     return file_path

def is_in_circle(px, py, cx, cy, r):
    return (px - cx)**2 + (py - cy)**2 <= r*r

def is_in_rect(px, py, left, right, top, bottom):
    return (left <= px <= right) and (top <= py <= bottom)




# Mouse event flags
MOUSE_MOVE_RELATIVE = 0x00
MOUSE_MOVE_ABSOLUTE = 0x01
MOUSE_VIRTUAL_DESKTOP = 0x02
MOUSE_ATTRIBUTES_CHANGED = 0x04
MOUSE_MOVE_NOCOALESCE = 0x08

LEFT_BUTTON_DOWN = 0x0001
LEFT_BUTTON_UP = 0x0002
RIGHT_BUTTON_DOWN = 0x0004
RIGHT_BUTTON_UP = 0x0008
MIDDLE_BUTTON_DOWN = 0x0010
MIDDLE_BUTTON_UP = 0x0020
X_BUTTON_DOWN = 0x0040
X_BUTTON_UP = 0x0080
X_BUTTON_2_DOWN = 0x0100
X_BUTTON_2_UP = 0x0200
MOUSE_V_WHEEL = 0x0400
MOUSE_HWHEEL = 0x0800
MOUSE_WHEEL_NEGATIVE = 0x1000

class InterceptionBridge:
    def __init__(self):
        self.ctx = Interception()
        # Access context properties directly
        self.mouse = self.ctx.mouse
        self.keyboard = self.ctx.keyboard

    def key_down(self, key_code):
        # KeyStroke(code, flags)
        ks = KeyStroke(key_code, 0) 
        self.ctx.send(self.keyboard, ks)
    
    def key_up(self, key_code):
        # KeyStroke(code, flags)
        ks = KeyStroke(key_code, 1)
        self.ctx.send(self.keyboard, ks)
        
    def hotkey_down(self, key_codes):
        for key_code in key_codes:
            self.key_down(key_code)
    
    def hotkey_up(self, key_codes):
        for key_code in reversed(key_codes):
            self.key_up(key_code)

    def mouse_move_rel(self, dx, dy):
        dx = int(dx)
        dy = int(dy)
        # MouseStroke(state, flags, rolling, x, y)
        ms = MouseStroke(0, MOUSE_MOVE_RELATIVE, 0, dx, dy)
        self.ctx.send(self.mouse, ms)

    def mouse_move_abs(self, x, y):
        screen_w = ctypes.windll.user32.GetSystemMetrics(0)
        screen_h = ctypes.windll.user32.GetSystemMetrics(1)

        abs_x = int((x * 65535) / screen_w)
        abs_y = int((y * 65535) / screen_h)
        
        flags = MOUSE_MOVE_ABSOLUTE | MOUSE_VIRTUAL_DESKTOP
        # FORCE MOUSE_MOVE_ABSOLUTE as state (Arg 1)
        ms = MouseStroke(MOUSE_MOVE_ABSOLUTE, flags, 0, abs_x, abs_y)
        self.ctx.send(self.mouse, ms)
        
    def left_click_down(self):
        ms = MouseStroke(LEFT_BUTTON_DOWN, MOUSE_MOVE_RELATIVE, 0, 0, 0)
        self.ctx.send(self.mouse, ms)

    def left_click_up(self):
        ms = MouseStroke(LEFT_BUTTON_UP, MOUSE_MOVE_RELATIVE, 0, 0, 0)
        self.ctx.send(self.mouse, ms)

    def right_click_down(self):
        ms = MouseStroke(RIGHT_BUTTON_DOWN, MOUSE_MOVE_RELATIVE, 0, 0, 0)
        self.ctx.send(self.mouse, ms)
        
    def right_click_up(self):
        ms = MouseStroke(RIGHT_BUTTON_UP, MOUSE_MOVE_RELATIVE, 0, 0, 0)
        self.ctx.send(self.mouse, ms)

    def middle_click_down(self):
        ms = MouseStroke(MIDDLE_BUTTON_DOWN, MOUSE_MOVE_RELATIVE, 0, 0, 0)
        self.ctx.send(self.mouse, ms)
        
    def middle_click_up(self):
        ms = MouseStroke(MIDDLE_BUTTON_UP, MOUSE_MOVE_RELATIVE, 0, 0, 0)
        self.ctx.send(self.mouse, ms)
        
    def release_all(self):
        """Releases every key defined in SCANCODES and all mouse buttons."""
        print("[Bridge] Emergency Release: Clearing all inputs...")
        
        # 1. Release all defined Keyboard keys
        # We iterate through the values of your SCANCODES dictionary
        for scancode in SCANCODES.values():
            # Skip mouse codes if they are in your SCANCODES dict (handled below)
            if scancode in [M_LEFT, M_RIGHT, M_MIDDLE]:
                continue
            self.key_up(scancode)

        # 2. Release Mouse Buttons (Static calls for safety)
        self.left_click_up()
        self.right_click_up()
        self.middle_click_up
        
        print("[Bridge] All inputs cleared.")








class TouchReader():
    def __init__(self, dispatcher):
        self.device = get_adb_device()
        self.device_touch_event = self.find_touch_device_event()

        if self.device_touch_event is None:
            raise RuntimeError("No touchscreen device found via ADB.")

        print(f"[INFO] Using touchscreen device: {self.device_touch_event}")
        self.adb_rate_cap = DEFAULT_ADB_RATE_CAP
        self.mapper_event_dispatcher = dispatcher

        # --- PERFORMANCE TUNING ---
        self.move_interval = 1.0 / self.adb_rate_cap if self.adb_rate_cap > 0 else 0
        self.last_dispatch_time = 0

        # 1. Physical Device Specs
        res = get_screen_size(self.device)
        if res is None:
            raise RuntimeError("Detected resolution invalid.")

        self.width, self.height = res

        # 2. Get Configured Specs
        json_res = RES
        json_dpi = DPI

        # 3. Strict Validation
        if self.width != json_res[0] or self.height != json_res[1]:
            _str = f"Resolution Mismatch! Physical: {self.width}x{self.height} vs Config: {json_res[0]}x{json_res[1]}"
            raise RuntimeError(_str)

        self.res_dpi = [json_res[0], json_res[1], json_dpi]       

        # State Tracking
        self.slots = {}
        self.active_touches = 0
        self.max_slots = self.get_max_slots()
        self.rotation = 0
        self.rotation_poll_interval = 0.5 
        self.lock = threading.Lock()
        self.running = True

        # Identity tracking
        self.side_limit = self.width // 2
        self.mouse_slot = None
        self.wasd_slot = None

        # --- SELF STARTING THREADS ---
        print(f"[INFO] TouchReader running at {self.adb_rate_cap}Hz Cap.")
        self.process = None
        threading.Thread(target=self.update_rotation, daemon=True).start()
        threading.Thread(target=self.get_touches, daemon=True).start()

    # --- FINGER IDENTITY LOGIC ---

    def _update_finger_identities(self):
        """
        Implements 'Upside' logic: Identify the oldest finger on each side
        to assign as the dedicated Mouse or WASD finger.
        """
        eligible_mouse = []
        eligible_wasd = []

        for slot, data in self.slots.items():
            if data['tid'] != -1 and data['start_x'] is not None:
                # Check which side the finger started on
                if data['start_x'] >= self.side_limit:
                    eligible_mouse.append((slot, data['timestamp']))
                else:
                    eligible_wasd.append((slot, data['timestamp']))
        

        # Use the finger with the earliest timestamp (oldest) for each role
        self.mouse_slot = min(eligible_mouse, key=lambda x: x[1])[0] if eligible_mouse else None
        self.wasd_slot = min(eligible_wasd, key=lambda x: x[1])[0] if eligible_wasd else None


    # --- CONFIG & SPECS ---

    def find_touch_device_event(self):
        try:
            result = subprocess.run(
                ["adb", "-s", self.device, "shell", "getevent", "-lp"],
                capture_output=True, text=True, timeout=2
            )
            lines = result.stdout.splitlines()
            current_device, block, devices = None, [], {}
            for line in lines:
                if line.startswith("add device"):
                    if current_device: devices[current_device] = "\n".join(block)
                    block = []
                    current_device = line.split(":")[1].strip()
                else: block.append(line)
            if current_device: devices[current_device] = "\n".join(block)

            for dev, txt in devices.items():
                if "ABS_MT_POSITION_X" in txt and "INPUT_PROP_DIRECT" in txt: return dev
            for dev, txt in devices.items():
                if "ABS_MT_POSITION_X" in txt: return dev
        except: pass
        return None

    def get_max_slots(self):
        try:
            result = subprocess.run(["adb", "-s", self.device, "shell", "getevent", "-p", self.device_touch_event], capture_output=True, text=True)
            for line in result.stdout.splitlines():
                if "ABS_MT_SLOT" in line and "max" in line:
                    return int(line.split("max")[1].strip().split(',')[0]) + 1
        except: pass
        return 10 


    def update_rotation(self):
        patterns = [r"mCurrentRotation=(\d+)", r"rotation=(\d+)", r"mCurrentOrientation=(\d+)"]
        while self.running:
            try:
                result = subprocess.run(["adb", "-s", self.device, "shell", "dumpsys", "display"], capture_output=True, text=True, timeout=1)
                for pat in patterns:
                    m = re.search(pat, result.stdout)
                    if m:
                        with self.lock: self.rotation = int(m.group(1)) % 4
                        break
            except: pass
            time.sleep(self.rotation_poll_interval)
            
    def rotate_coordinates(self, x, y):
        if x is None or y is None:
            return x, y
        
        with self.lock:
            if self.rotation == 1:
                self.side_limit = self.height // 2
                return y, self.width - x
            
            elif self.rotation == 2:
                self.side_limit = self.width // 2
                return self.width - x, self.height - y
            
            elif self.rotation == 3:
                self.side_limit = self.height // 2
                return self.height - y, x
            
            else:
                self.side_limit = self.width // 2            
                return x, y 
                  

    def _ensure_slot(self, slot):
        if slot not in self.slots:
            self.slots[slot] = {
                'x': 0, 'y': 0, 'start_x': None, 'start_y': None, 
                'tid': -1, 'state': 'IDLE', 'timestamp': 0
            }

    def parse_hex_signed(self, value_hex):
        val = int(value_hex, 16)
        return val if val < 0x80000000 else val - 0x100000000

    def get_touches(self):
        current_slot = 0
        while self.running:
            self.process = subprocess.Popen(
                ["adb", "-s", self.device, "shell", "getevent", "-l", self.device_touch_event],
                stdout=subprocess.PIPE, text=True, bufsize=0 
            )

            try:
                for line in self.process.stdout:
                    if not self.running: break
                    parts = line.strip().split()
                    if len(parts) < 3: continue

                    code, val_str = parts[1], parts[2]

                    if "ABS_MT_SLOT" == code:
                        current_slot = int(val_str, 16)
                        self._ensure_slot(current_slot)
                        
                    elif "ABS_MT_TRACKING_ID" == code:
                        tid = self.parse_hex_signed(val_str)
                        self._ensure_slot(current_slot)
                        prev_id = self.slots[current_slot]['tid']
                        self.slots[current_slot]['tid'] = tid
                        
                        if tid >= 0 and prev_id == -1:
                            self.slots[current_slot].update({
                                'state': 'DOWN', 
                                'start_x': None,
                                'timestamp': time.monotonic_ns()
                            })
                        elif tid == -1:
                            self.slots[current_slot]['state'] = 'UP'
                            
                    elif "ABS_MT_POSITION_X" == code:
                        val = int(val_str, 16)
                        self.slots[current_slot]['x'] = val                        
                        if self.slots[current_slot]['start_x'] is None:
                            tmp = self.rotate_coordinates(val, self.slots[current_slot]['start_y'])
                            self.slots[current_slot]['start_x'], self.slots[current_slot]['start_y'] = tmp
                            
                    elif "ABS_MT_POSITION_Y" == code:
                        val = int(val_str, 16)
                        self.slots[current_slot]['y'] = val                        
                        if self.slots[current_slot]['start_y'] is None:
                            tmp = self.rotate_coordinates(self.slots[current_slot]['start_x'], val)
                            self.slots[current_slot]['start_x'], self.slots[current_slot]['start_y'] = tmp

                    elif "SYN_REPORT" == code:
                        self.handle_sync()
                        
            except Exception: pass
            
            if self.running:
                self.stop_process()
                time.sleep(1.0)

    def handle_sync(self):
        now = time.perf_counter()
        
        # Determine who is the Mouse and who is the WASD before dispatching
        self._update_finger_identities()
        
        for slot, data in list(self.slots.items()):
            if data['state'] == 'IDLE': continue

            # Rate Limit for movement (PRESSED state) only
            if data['state'] == 'PRESSED':
                if (now - self.last_dispatch_time) < self.move_interval:
                    continue
                self.last_dispatch_time = now
            
            rx, ry = self.rotate_coordinates(data['x'], data['y'])

            event = MapperEvent(
                action=data['state'],
                touch=TouchMapperEvent(
                    slot=slot, 
                    id=data['tid'], 
                    x=rx, y = ry,
                    sx=data['start_x'], sy=data['start_y'], # Updated
                    is_mouse=(slot == self.mouse_slot), 
                    is_wasd=(slot == self.wasd_slot)
                )
            )                                   
            
            self.mapper_event_dispatcher.dispatch(event)

            if data['state'] == 'DOWN': 
                data['state'] = 'PRESSED'
            elif data['state'] == 'UP': 
                self.reset_slot(slot)

    def reset_slot(self, slot):
        self.slots[slot] = {
            'x': 0, 'y': 0, 'start_x': None, 'start_y': None, 
            'tid': -1, 'state': 'IDLE', 'timestamp': 0
        }

    def stop_process(self):
        if self.process:
            try:
                self.process.terminate()
                # Wait up to 2 seconds for clean exit
                self.process.wait(timeout=2)
            except Exception:
                # Force kill if it hangs
                if self.process:
                    self.process.kill()

    def stop(self):
        self.running = False
        self.stop_process()






class MouseMapper():
    def __init__(self, ev_dispatcher, interception_bridge):
        self.prev_x = None
        self.prev_y = None
        self.acc_x = 0.0
        self.acc_y = 0.0
        
        self.mapper_event_dispatcher = ev_dispatcher
        self.interception_bridge = interception_bridge

        base_sens = SENSITIVITY
        dpi_scale = DEF_DPI / DPI
        self.TOTAL_MULT = base_sens * dpi_scale
                
        self.mapper_event_dispatcher.register_callback("ON_TOUCH_DOWN", self.touch_down)  
        self.mapper_event_dispatcher.register_callback("ON_TOUCH_PRESSED", self.touch_pressed)
        self.mapper_event_dispatcher.register_callback("ON_TOUCH_UP", self.touch_up)


    def touch_down(self, event):
        if not event.is_mouse:
            return
        # Anchor new finger and clear math remainders
        self.prev_x = event.x
        self.prev_y = event.y
        self.acc_x = 0.0
        self.acc_y = 0.0

    def touch_pressed(self, event):
        if not event.is_mouse:
            return

        # Ensures no 'jumping' if a new finger takes over
        if self.prev_x is None:
            self.prev_x = event.x
            self.prev_y = event.y
            return

        raw_dx = event.x - self.prev_x
        raw_dy = event.y - self.prev_y

        # Sub-pixel precision (passes all tremors)
        calc_dx = (raw_dx * self.TOTAL_MULT) + self.acc_x
        calc_dy = (raw_dy * self.TOTAL_MULT) + self.acc_y

        final_dx = int(calc_dx)
        final_dy = int(calc_dy)

        # Store remainders
        self.acc_x = calc_dx - final_dx
        self.acc_y = calc_dy - final_dy

        if final_dx != 0 or final_dy != 0:
            self.interception_bridge.mouse_move_rel(final_dx, final_dy)

        self.prev_x = event.x
        self.prev_y = event.y

    def touch_up(self, event):
        # When any mouse finger is lifted, clear the state
        if event.is_mouse:
            self.prev_x = None
            self.prev_y = None
            self.acc_x = 0.0
            self.acc_y = 0.0
            
            
            
            
class WASDMapper():
    def __init__(self, ev_dispatcher, interception_bridge):
        
        # Interception Scan Codes (Retrieved from utils.py)
        # Note: keys in SCANCODES are lowercase as per your utils.py
        self.KEY_W = SCANCODES["w"]
        self.KEY_A = SCANCODES["a"]
        self.KEY_S = SCANCODES["s"]
        self.KEY_D = SCANCODES["d"]
        
        # State Tracking
        self.current_keys = set() 
        self.center_x = 0.0
        self.center_y = 0.0
        self.innerradius = 0.0
        self.outerradius = 0.0
        
        self.mapper_event_dispatcher = ev_dispatcher
        self.interception_bridge = interception_bridge
        
        self.DEADZONE = DEADZONE
        self.HYSTERESIS = HYSTERISIS 
        self.innerradius = MOUSE_WHEEL_RADIUS
        self.outerradius = SPRINT_DISTANCE
                
        # Register Callbacks
        self.mapper_event_dispatcher.register_callback("ON_TOUCH_DOWN", self.touch_down)  
        self.mapper_event_dispatcher.register_callback("ON_TOUCH_PRESSED", self.touch_pressed)
        self.mapper_event_dispatcher.register_callback("ON_TOUCH_UP", self.touch_up)
        # self.mapper_event_dispatcher.register_callback("ON_WASD_BLOCK", self.on_wasd_block)
    
    # def on_wasd_block(self):
    #     # If a button (like 'Reload') is placed on top of the joystick area,
    #     # we pause the joystick so you don't walk while reloading.
    #     if self.mapper.wasd_block > 0:
    #         self.release_all()
        
    def touch_down(self, event):
        if event.is_wasd: # and self.mapper.wasd_block == 0:
            # Re-center the joystick at the finger's landing position (Floating Joystick)
            self.center_x = event.x
            self.center_y = event.y
            self.release_all()

    def touch_pressed(self, event):
        if event.is_wasd: # and self.mapper.wasd_block == 0:
            # Vector from center to current finger
            vx_raw = event.x - self.center_x
            vy_raw = event.y - self.center_y
            
            # Distance
            d = (vx_raw*vx_raw + vy_raw*vy_raw)**0.5 
            
            # --- Leash Logic (Floating Follow) ---
            # If finger drags further than 'outerradius', pull the center along.
            
            if d > self.outerradius and self.outerradius > 0:
                scale = self.outerradius / d
                # Move center towards finger so distance is exactly outerradius
                self.center_x = event.x - (vx_raw * scale)
                self.center_y = event.y - (vy_raw * scale)                
                
                # Update vector and distance based on new center
                vx_raw = event.x - self.center_x
                vy_raw = event.y - self.center_y
                d = self.outerradius 

            # --- Deadzone Check ---
            # Normalized Magnitude (0.0 to 1.0+)
            if self.innerradius > 0:
                mag = d / self.innerradius
            else:
                mag = 0
                
            if mag < self.DEADZONE:
                self.release_all()
                return

            # --- Angle Calculation ---
            # FIX: math.atan2 takes (y, x), not (x, y)
            # This aligns 0 degrees with Right and -90 degrees with Up (Screen Y is down)
            angle = math.degrees(math.atan2(vy_raw, vx_raw))
            
            target_keys = self.get_keys_from_angle(angle)
            self.apply_keys(target_keys)
    
    def touch_up(self, event):
        if event.is_wasd:
            self.release_all()

    def get_keys_from_angle(self, angle):
        margin = self.HYSTERESIS
        keys = self.current_keys
        
        # 
        # Mapping for Screen Coordinates (Y is Down):
        # Up (-90), Right (0), Down (90), Left (180/-180)

        # --- HYSTERESIS CHECKS (Sticky State) ---
        # If we are already in a state, widen the angle check by 'margin'
        # to prevent rapid flickering at the boundaries.

        # STATE: UP (W) [-112.5 to -67.5]
        if self.KEY_W in keys and self.KEY_A not in keys and self.KEY_D not in keys:
            if -112.5 - margin <= angle < -67.5 + margin: return {self.KEY_W}

        # STATE: UP-RIGHT (WD) [-67.5 to -22.5]
        if self.KEY_W in keys and self.KEY_D in keys:
            if -67.5 - margin <= angle < -22.5 + margin: return {self.KEY_W, self.KEY_D}

        # STATE: RIGHT (D) [-22.5 to 22.5]
        if self.KEY_D in keys and self.KEY_W not in keys and self.KEY_S not in keys:
            if -22.5 - margin <= angle < 22.5 + margin: return {self.KEY_D}

        # STATE: DOWN-RIGHT (SD) [22.5 to 67.5]
        if self.KEY_S in keys and self.KEY_D in keys:
            if 22.5 - margin <= angle < 67.5 + margin: return {self.KEY_S, self.KEY_D}

        # STATE: DOWN (S) [67.5 to 112.5]
        if self.KEY_S in keys and self.KEY_A not in keys and self.KEY_D not in keys:
            if 67.5 - margin <= angle < 112.5 + margin: return {self.KEY_S}

        # STATE: DOWN-LEFT (SA) [112.5 to 157.5]
        if self.KEY_S in keys and self.KEY_A in keys:
            if 112.5 - margin <= angle < 157.5 + margin: return {self.KEY_S, self.KEY_A}

        # STATE: UP-LEFT (WA) [-157.5 to -112.5]
        if self.KEY_W in keys and self.KEY_A in keys:
            if -157.5 - margin <= angle < -112.5 + margin: return {self.KEY_W, self.KEY_A}

        # STATE: LEFT (A) [> 157.5 or < -157.5]
        if self.KEY_A in keys and self.KEY_W not in keys and self.KEY_S not in keys:
            limit = 157.5 - margin
            if angle >= limit or angle <= -limit: return {self.KEY_A}

        # --- FALLBACK (Strict State) ---
        return self._get_strict_keys(angle)

    def _get_strict_keys(self, angle):
        if -112.5 <= angle < -67.5:   return {self.KEY_W}
        elif -67.5 <= angle < -22.5:  return {self.KEY_W, self.KEY_D}
        elif -22.5 <= angle < 22.5:   return {self.KEY_D}
        elif 22.5 <= angle < 67.5:    return {self.KEY_S, self.KEY_D}
        elif 67.5 <= angle < 112.5:   return {self.KEY_S}
        elif 112.5 <= angle < 157.5:  return {self.KEY_S, self.KEY_A}
        elif -157.5 <= angle < -112.5: return {self.KEY_W, self.KEY_A}
        else: return {self.KEY_A}

    def apply_keys(self, target_keys):
        # Efficiently press/release only changed keys
        keys_to_press = target_keys - self.current_keys
        keys_to_release = self.current_keys - target_keys
        
        for k in keys_to_release:
            self.interception_bridge.key_up(k)
        for k in keys_to_press:
            self.interception_bridge.key_down(k)
            
        self.current_keys = keys_to_press
        _ = []
        for k in self.current_keys:
            if k == self.KEY_A:
                _.append("A")
            elif k == self.KEY_D:
                _.append("D")
            elif k == self.KEY_S:
                _.append("S")
            elif k == self.KEY_W:
                _.append("W")
                
        # print(f"Current WASD movement: {_}", end="\r", flush=True)

    def release_all(self):
        if not self.current_keys: return
        for k in self.current_keys:
            self.interception_bridge.key_up(k)
        self.current_keys = set()




def main():
    print("[System] Initializing Mapper... Press 'ESC' at any time to Stop.")

    # # --- Argument Parsing ---
    # # Usage: python main.py [rate_cap] [debounce_time]
    # # Example: python main.py 500 0.005
    # try:
    #     # Default to utils.py values if args are missing
    #     rate_cap = float(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_ADB_RATE_CAP
    #     debounce = float(sys.argv[2]) if len(sys.argv) > 2 else DEFAULT_KEY_DEBOUNCE
    # except ValueError:
    #     print("[!] Invalid command line arguments. Falling back to defaults.")
    #     rate_cap, debounce = DEFAULT_ADB_RATE_CAP, DEFAULT_KEY_DEBOUNCE

    # print(f"[Config] ADB Rate Cap: {rate_cap}Hz | Key Debounce: {debounce*1000}ms")

    # 1. Initialize Core Systems
    mapper_event_dispatcher = MapperEventDispatcher()
    # config = AppConfig(mapper_event_dispatcher)

    # 2. Initialize Bridge & Loader
    interception_bridge = InterceptionBridge()
    # json_loader = JSON_Loader(config)

    # 3. Initialize Touch Reader
    # Passing the custom rate_cap from sys.argv
    touch_reader = TouchReader(mapper_event_dispatcher)

    # 4. Initialize Mappers
    # The 'mapper' object tracks the game window
    # mapper_logic = Mapper(interception_bridge)

    # Initialize sub-mappers
    MouseMapper(mapper_event_dispatcher, interception_bridge)
    # Passing the custom debounce from sys.argv
    # KeyMapper(mapper_logic, debounce_time=debounce)
    WASDMapper(mapper_event_dispatcher, interception_bridge)


    # 5. Shutdown Logic
    def shutdown():
        print("\n[System] ESC detected. Cleaning up...")

        # Stop the window tracking thread in Mapper
        # mapper_logic.running = False

        # Stop the ADB stream in TouchReader
        touch_reader.stop()

        # Release all currently held keys to prevent "sticky keys" on exit
        interception_bridge.release_all()

        print("[System] Shutdown complete. Goodbye.")
        os._exit(0) # Force exit all threads

    # Register the escape key
    keyboard.add_hotkey('esc', shutdown)

    # 6. Keep Main Thread Alive
    keyboard.wait('esc')

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        os._exit(0)
