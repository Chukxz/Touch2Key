from __future__ import annotations
from typing import TYPE_CHECKING

import tkinter as tk
from tkinter import filedialog
import subprocess
import os
import ctypes
import tomlkit
import re
import psutil
import time
import multiprocessing
from datetime import datetime as _datetime
from typing import Literal
import random
from pathlib import Path
import colorsys

if TYPE_CHECKING:
    from multiprocessing import Process
    from multiprocessing import Queue
    from .bridge import InterceptionBridge

# Get location of this file: .../mapper_project/src/mapper_module
CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))

# Go up one level to 'src'
SRC_DIR = os.path.dirname(CURRENT_DIR)

# Go up another level to 'mapper_project' (Root)
PROJECT_ROOT = os.path.dirname(SRC_DIR)

# Path Assignments
ADB_EXE = os.path.join(PROJECT_ROOT, "bin", "platform-tools", "adb.exe")
TOML_PATH = os.path.join(PROJECT_ROOT, "settings.toml")
IMAGES_FOLDER = os.path.join(SRC_DIR, "resources", "images")
JSONS_FOLDER = os.path.join(SRC_DIR, "resources", "jsons")

# Constants   

DEF_DPI = 160

DOWN = "DOWN"
UP = "UP"
PRESSED = "PRESSED"
IDLE = "IDLE"

CIRCLE = "CIRCLE"
RECT = "RECT"
M_LEFT = 0x9901
M_RIGHT = 0x9902
M_MIDDLE = 0x9903
SPRINT_DISTANCE_CODE = "F11"
MOUSE_WHEEL_CODE = "F12"

# Delays (in seconds)
RELOAD_DELAY = 0.5 
SHORT_DELAY = 1.0
LONG_DELAY = 2.0
WINDOW_UPDATE_INTERVAL = 0.05
ROTATION_POLL_INTERVAL = 0.5

#  1ms (10,000 units of 100ns)
NT_TIMER_RES = 10000

# Fallback Performance Constants
# Limits PRESSED events to 250 updates per second
DEFAULT_ADB_RATE_CAP = 250
PPS = 60

MOUSE_MOVE_RELATIVE = 0x00
MOUSE_MOVE_ABSOLUTE = 0x01
MOUSE_VIRTUAL_DESKTOP = 0x02

LEFT_BUTTON_DOWN, LEFT_BUTTON_UP = 0x0001, 0x0002
RIGHT_BUTTON_DOWN, RIGHT_BUTTON_UP = 0x0004, 0x0008
MIDDLE_BUTTON_DOWN, MIDDLE_BUTTON_UP = 0x0010, 0x0020

DEF_EMULATOR_ID = 0
EMULATORS = {
    "GameLoop": {
        "window_title": "Gameloop(64beta)",
        "sprint_key": None,
        "toggle_key": "LCTRL",
    },
    # "BlueStacks": {
    #     "window_title": "BlueStacks App Player",
    #     "sprint_key": "LSHIFT",
    # }
}

PORT = '5555'

EVENT_TYPE = Literal["ON_CONFIG_RELOAD", "ON_JSON_RELOAD", "ON_WASD_BLOCK", "ON_MENU_MODE_TOGGLE"]

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
    def __init__(self, slot:float, id:float, x:float, y:float, sx:float, sy:float, is_mouse:bool, is_wasd:bool):
        self.slot = slot
        self.id = id
        self.x = x
        self.y = y
        self.sx = sx
        self.sy = sy
        self.is_mouse = is_mouse
        self.is_wasd = is_wasd
        
    def show(self):
        return f"Slot: {self.slot}, ID: {self.id}, X: {self.x}, Y: {self.y}, SX: {self.sx}, SY: {self.sy}, isMouse: {self.is_mouse}, isWASD: {self.is_wasd}"

class MapperEvent:
    def __init__(self, action:EVENT_TYPE, is_visible=True):
        self.action: EVENT_TYPE = action # CONFIG, JSON, WASD_BLOCK, MENU_MODE_TOGGLE
        self.is_visible = is_visible
    
    def show(self):
        return f"Action: {self.action}\n Cursor Visible: {self.is_visible})"
    
class MapperEventDispatcher:
    def __init__(self):    
        # The Registry
        self.callback_registry = {
            "ON_CONFIG_RELOAD":     [],
            "ON_JSON_RELOAD":       [],
            "ON_WASD_BLOCK":        [],
            "ON_MENU_MODE_TOGGLE":  [],
        }

    def register_callback(self, event_type:EVENT_TYPE, func):
        if event_type in self.callback_registry:
            self.callback_registry[event_type].append(func)
        else:
            print(f"[Warning] Attempted to register unknown event: {event_type}")
    
    def unregister_callback(self, event_type:EVENT_TYPE, func):
        if event_type in self.callback_registry:
            if func in self.callback_registry[event_type]:
                self.callback_registry[event_type].remove(func)
            else:
                print(f"[Warning] Function {func.__name__} was not registered for {event_type}")

    def dispatch(self, event_object: MapperEvent):       
        registry_key = event_object.action
        
        if registry_key:
            for func in self.callback_registry[registry_key]:
                if event_object.action in ["ON_CONFIG_RELOAD", "ON_JSON_RELOAD", "ON_WASD_BLOCK"]:
                    func()
                elif event_object.action in ["ON_MENU_MODE_TOGGLE"]:
                    func(event_object.is_visible)


def get_adb_device():
    out = subprocess.check_output([ADB_EXE, "devices"]).decode().splitlines()
    real = [d.split()[0] for d in out[1:] if "device" in d and not d.startswith("emulator-")]

    if not real:
        raise RuntimeError("No real device detected")
    else:
        return real[0]
    

def get_screen_size(device:str):
    result = subprocess.run([ADB_EXE, "-s", device, "shell", "wm", "size"], capture_output=True, text=True)
    output = result.stdout.strip().splitlines()
    
    # Check for "Override size" first, then fallback to "Physical size"
    # This ensures we use the ACTUAL resolution being rendered
    size_line = output[-1] 
    if ":" in size_line:
        w, h = map(int, size_line.split(":")[-1].strip().split("x"))
        return w, h
    return None


def get_dpi(device:str):
    """Detect screen DPI, fallback to 160."""
    try:
        result = subprocess.run([ADB_EXE, "-s", device, "shell", "getprop", "ro.sf.lcd_density"],
                                capture_output=True, text=True, timeout=1)
        val = result.stdout.strip()
        return int(val) if val else DEF_DPI
    except Exception:
        return DEF_DPI

def is_device_online(device:str):
    try:
        res = subprocess.run([ADB_EXE, "-s", device, "get-state"], 
                            capture_output=True, text=True, timeout=1)
        return "device" in res.stdout
    except:
        return False

def wireless_connect(device:str|None=None, continous=True):
    running = True
    device = None
    error_1 = False
    error_2 = False
    
    while running:        
        if not device:
            try:
                device = get_adb_device()
                
            except RuntimeError:
                if continous:
                    if not error_1:
                        print("No adb devices detected.")
                        print("Retrying...")
                        error_1 = True
                    time.sleep(SHORT_DELAY)
                    continue
                else:
                    return True, ''
        
            error_1 = False
        
        try:
            routes = subprocess.check_output([ADB_EXE,  "-s", device, "shell", "ip", "route"]).decode().splitlines()
            socket = [s.split()[-1] for s in routes if "dev ap0" in s or "dev wlan0" in s]
            
            if not socket:
                raise RuntimeError(f"No sockets found for device: {device}")
            socket_path = socket[0] + ":" + PORT

            if device == socket_path:
                print(f"Connected successfully to device: {socket_path}.")
            else:
                subprocess.run([ADB_EXE, "-s", device, "tcpip", PORT])
                final = subprocess.check_output([ADB_EXE,  "-s", device, "connect", socket_path]).decode().splitlines()[0] # If there's an error its supposed to be raised here.
                
                if "(10065)" in final: # Default fallback if no errors were raised in previous line
                    raise RuntimeError(f"cannot connect to {socket_path}: A socket operation was attempted to an unreachable host. (10065)")
            
                print(f"Connected successfully to device: {device} on socket: {socket_path}, device now set to: {socket_path}.")
                
            if continous:
                running = False
            else:
                return False, socket_path
                    
        except Exception as e:
            if continous:
                if not error_2:
                    print(e)
                    print("Retrying...")
                    error_2 = True
                time.sleep(SHORT_DELAY)
                continue
            else:
                return True, ''
    
        error_2 = False

def set_dpi_awareness():
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(1) 
    except Exception:
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except: pass

def select_image_file(base_dir:str|None = None):
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

def is_in_circle(px:float, py:float, cx:float, cy:float, r:float):
    return (px - cx)**2 + (py - cy)**2 <= r*r

def is_in_rect(px:float, py:float, left:float, right:float, top:float, bottom:float):
    return (left <= px <= right) and (top <= py <= bottom)

def create_default_toml():
    """Wipes the existing settings.toml and creates a fresh default configuration."""
    print(f"Resetting '{TOML_PATH}' to default (Minimally Viable Version).")
    
    # Create the TOML structure in memory
    doc = tomlkit.document()
    
    # [system] - Core paths and hardware baseline
    system = tomlkit.table()
    system.add("hud_image_path", "")
    system.add("json_path", "")
    system.add("json_dev_res", [2400, 1080]) # Default fallback resolution
    system.add("json_dev_dpi", 160)
    doc.add("system", system)

    # [mouse] - Sensitivity settings
    mouse = tomlkit.table()
    mouse.add("sensitivity", 1.0)
    doc.add("mouse", mouse)

    # [joystick] - Movement and radius settings
    joystick = tomlkit.table()
    joystick.add("deadzone", 0.1)
    joystick.add("hysteresis", 5.0)
    joystick.add("mouse_wheel_radius", 0.0)
    joystick.add("sprint_distance", 0.0)
    doc.add("joystick", joystick)

    try:
        # Opening with "w" automatically clears (truncates) the file before writing
        with open(TOML_PATH, "w", encoding="utf-8") as f:
            tomlkit.dump(doc, f)
        print(f"[System] Successfully reset and created settings.toml at '{TOML_PATH}'")
    except Exception as e:
        print(f"[Error] Failed to create settings.toml: {e}")

def update_toml(w=None, h=None, dpi=None, image_path=None, json_path=None, mouse_wheel_radius=None, sprint_distance=None, strict=False):
    try:
        if not os.path.exists(TOML_PATH):
            create_default_toml()

        with open(TOML_PATH, "r", encoding="utf-8") as f:
            doc = tomlkit.load(f)

        if "system" not in doc: doc.add("system", tomlkit.table())
        if "joystick" not in doc: doc.add("joystick", tomlkit.table())
        
        if mouse_wheel_radius:
            doc["joystick"]["mouse_wheel_radius"] = mouse_wheel_radius
        if sprint_distance:
            doc["joystick"]["sprint_distance"] = sprint_distance 
                       
        if w and h:
            doc["system"]["json_dev_res"] = [w, h]            
        if dpi:
            doc["system"]["json_dev_dpi"] = dpi        
        if image_path is not None:
            doc["system"]["hud_image_path"] = Path(image_path).as_posix() if image_path else ""           
        if json_path is not None:
            doc["system"]["json_path"] = Path(json_path).as_posix() if json_path else ""

        with open(TOML_PATH, "w", encoding="utf-8") as f:
            tomlkit.dump(doc, f)
            
    except Exception as e:
        if os.path.exists(TOML_PATH):
            os.replace(TOML_PATH, TOML_PATH + ".bak")
            print(f"[System] Settings were corrupted and reset. Backup created.")
        create_default_toml()
        print("Resetting to defaults...")
        if strict:
            raise e
        else:
            print(f"[ERROR] Could not update Toml: {e}")

def get_rotation(device):
    rotation = 0
    patterns = [r"mCurrentRotation=(\d+)", r"rotation=(\d+)", r"mCurrentOrientation=(\d+)", r"mUserRotation=(\d+)"]
    try:
        result = subprocess.run([ADB_EXE, "-s", device, "shell", "dumpsys", "display"], capture_output=True, text=True, timeout=1)
        for pat in patterns:
            m = re.search(pat, result.stdout)
            if m:
                rotation = int(m.group(1)) % 4
                break
    except: pass

    return rotation


def rotate_resolution(x, y, rotation):
    if x is None or y is None:
        return x, y

    # Initialize result with current values as a fallback
    res_x, res_y = x, y 

    # Device in landscape, rotate back to potrait.
    if rotation == 1 or rotation == 3:
        return res_y, res_x

    return res_x, res_y

def set_high_priority(pid, label, priority_level=psutil.HIGH_PRIORITY_CLASS):
    try:
        p = psutil.Process(pid)
        p.nice(priority_level)
        p.cpu_affinity(list(range(psutil.cpu_count())))
        
        print(f"[Priority] {label} set to HIGH (Floating Affinity)")
    except Exception as e:
        print(f"[Priority] Warning: {e}")
        

# Worker: Keyboard (Isolated)
def keyboard_worker(k_queue:Queue):
    """ Dedicated process for Keyboard events only. """
    from interception import Interception, KeyStroke
    k_ctx = Interception()
    k_handle = k_ctx.keyboard
    # Keep track of keys we've pressed so we know what to release
    pressed_keys = set()
    running = True
    
    while running:
        try:
            # 15.0 seconds timeout: If no heartbeat/input from Main, release everything
            code, state = k_queue.get(timeout=15.0)

            # state 0 = Down, 1 = Up (Interception standard)
            if state == 0:
                pressed_keys.add(code)
            else:
                pressed_keys.discard(code)
            
            k_ctx.send(k_handle, KeyStroke(code, state))
  
        except Exception:
            # This triggers if k_queue.get(timeout=15.0) times out
            if pressed_keys:
                print(f"[Watchdog] Keyboard worker timeout. Releasing {len(pressed_keys)} keys.")
                for code in list(pressed_keys):
                    k_ctx.send(k_handle, KeyStroke(code, 1))
                pressed_keys.clear()
            running = False
                            

# Worker: Mouse (Isolated with Coalescing)
def mouse_worker(m_queue:Queue):
    """ Dedicated process for Mouse events only. """
    ctypes.windll.ntdll.NtSetTimerResolution(NT_TIMER_RES, 1, ctypes.byref(ctypes.c_ulong()))
        
    from interception import Interception, MouseStroke
    import time
    import random

    _sleep = time.sleep
    _random = random.random

    m_ctx = Interception()
    m_handle = m_ctx.mouse
    
    acc_dx, acc_dy = 0, 0
    pending_task = None
    
    left_down = False
    right_down = False
    middle_down = False
    running = True

    MAX_COALESCE = 20  # Limit move processing to prevent button lag
    MIN_DWELL = 0.025 
    DELTA_DWELL = 0.015
    DOWN_TUPLE = (LEFT_BUTTON_DOWN, RIGHT_BUTTON_DOWN, MIDDLE_BUTTON_DOWN)

    while running:
        try:
            # 15.0 seconds timeout: If no heartbeat/input from Main, release everything
            if pending_task:
                task, data = pending_task
                pending_task = None
            else:
                task, data = m_queue.get(timeout=15.0)

            if task == "button":
                m_ctx.send(m_handle, MouseStroke(MOUSE_MOVE_RELATIVE, data, 0, 0, 0))
                
                if data == LEFT_BUTTON_DOWN: left_down = True
                elif data == LEFT_BUTTON_UP: left_down = False
                elif data == RIGHT_BUTTON_DOWN: right_down = True
                elif data == RIGHT_BUTTON_UP: right_down = False
                elif data == MIDDLE_BUTTON_DOWN: middle_down = True
                elif data == MIDDLE_BUTTON_UP: middle_down = False
                
                # Check for "DOWN" mouse button events
                if data in DOWN_TUPLE:
                     _sleep(MIN_DWELL + _random() * DELTA_DWELL)
                else:
                    _sleep(0.005) # Tiny release gap

            elif task == "move_rel":
                acc_dx += data[0]
                acc_dy += data[1]

                # Capped Coalescing
                # Only eat 20 moves max before checking for a click
                coalesce_count = 0
                while not m_queue.empty() and coalesce_count < MAX_COALESCE:
                    try:
                        next_task, next_data = m_queue.get_nowait()
                        if next_task == "move_rel":
                            acc_dx += next_data[0]
                            acc_dy += next_data[1]
                            coalesce_count += 1
                        else:
                            pending_task = (next_task, next_data)
                            break 
                    except: 
                        break

                if acc_dx != 0 or acc_dy != 0:
                    m_ctx.send(m_handle, MouseStroke(MOUSE_MOVE_RELATIVE, MOUSE_MOVE_RELATIVE, 0, acc_dx, acc_dy))
                    acc_dx, acc_dy = 0, 0
                
                _sleep(0.0005)

            elif task == "move_abs":
                x, y = data
                m_ctx.send(m_handle, MouseStroke(MOUSE_MOVE_ABSOLUTE | MOUSE_VIRTUAL_DESKTOP, MOUSE_MOVE_ABSOLUTE, 0, x, y))
                _sleep(0.001)

        except Exception: # Timeout
            print("[Watchdog] Mouse worker timeout. Releasing buttons.")
            if left_down:
                m_ctx.send(m_handle, MouseStroke(MOUSE_MOVE_RELATIVE, LEFT_BUTTON_UP, 0, 0, 0))
                left_down = False
            if right_down:
                m_ctx.send(m_handle, MouseStroke(MOUSE_MOVE_RELATIVE, RIGHT_BUTTON_UP, 0, 0, 0))
                right_down = False
            if middle_down:
                m_ctx.send(m_handle, MouseStroke(MOUSE_MOVE_RELATIVE, MIDDLE_BUTTON_UP, 0, 0, 0))
                middle_down = False
            running = False
            

def maintain_bridge_health(bridge: InterceptionBridge):
    # Check Keyboard Worker
    if not bridge.k_proc.is_alive():
        print(f"\n[CRITICAL] {_datetime.now().strftime('%H:%M:%S')} - Keyboard Worker Died!")
        bridge.k_proc = multiprocessing.Process(target=keyboard_worker, name="Keyboard Worker", args=(bridge.k_queue,), daemon=True)
        bridge.k_proc.start()
        # Re-apply High Priority to the new PID
        set_high_priority(bridge.k_proc.pid, "Revived Keyboard")
        # Safety: Clear the queue to prevent a backlog of old 'stuck' keys firing at once
        while not bridge.k_queue.empty():
            try:
                bridge.k_queue.get_nowait()
            except: 
                break

    # Check Mouse Worker
    if not bridge.m_proc.is_alive():
        print(f"\n[CRITICAL] {_datetime.now().strftime('%H:%M:%S')} - Mouse Worker Died!")
        bridge.m_proc = multiprocessing.Process(target=mouse_worker, name="Mouse Worker", args=(bridge.m_queue,), daemon=True)
        bridge.m_proc.start()
        set_high_priority(bridge.m_proc.pid, "Revived Mouse")
        # Safety: Clear the queue to prevent a backlog of old 'stuck' mouse movements firing at once
        while not bridge.m_queue.empty():
            try: 
                bridge.m_queue.get_nowait()
            except: 
                break


def stop_process(process:Process):
    if process.is_alive():
        print(f"Closing {process.name}...")
        process.terminate()
        time.sleep(1.0)
        if process.is_alive():
            process.kill()
            

def get_vibrant_random_color(alpha=1.0):
    # Random Hue, High Saturation (0.7-1.0), High Value (0.9)
    h = random.random()
    s = random.uniform(0.7, 1.0)
    v = 0.9
    r, g, b = colorsys.hsv_to_rgb(h, s, v)
    return (r, g, b, alpha)
