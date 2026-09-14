from __future__ import annotations
from typing import TYPE_CHECKING

import subprocess
import os
import tomlkit
import re
import time
import platform
from typing import Literal
import random
from pathlib import Path
import colorsys
import struct

# Task IDs
TASK_BUTTON = 0
TASK_REL = 1
TASK_ABS = 2

# Pre-compiled C-struct formats for maximum speed
# <  = Little-endian
# B  = Unsigned char (1 byte) for the Task ID
# i  = Signed int (4 bytes)
# h  = Signed short (2 bytes)
PACK_BUTTON = struct.Struct("<Bi")  # 5 bytes total
PACK_REL = struct.Struct("<Bhh")  # 5 bytes total
PACK_ABS = struct.Struct("<Bii")  # 9 bytes total

# Keyboard Struct: < H (Unsigned Short for KeyCode), B (Unsigned Char for State 0/1)
PACK_KEY = struct.Struct("<HB")  # 3 bytes total

# Sentinel values meaning "keepalive only, do not press/release anything"
KEY_PING = 2
BUTTON_PING = 0x0000  # doesn't collide with any *_DOWN/*_UP flag
KEEPALIVE_INTERVAL = 5.0  # seconds; must stay well under the 15s worker poll timeout


if TYPE_CHECKING:
    from multiprocessing import Process

# Get location of this file: .../Touch2Key/src/modules
CURRENT_DIR = Path(__file__).resolve().parent

# Go up one level to 'src'
SRC_DIR = CURRENT_DIR.parent

# Go up another level to 'Touch2Key' (Root)
PROJECT_ROOT = SRC_DIR.parent

# OS environment
SYSTEM = platform.system()

# Path Assignments
ADB_NAME = "adb.exe" if SYSTEM == "Windows" else "adb"
ADB = PROJECT_ROOT / "bin" / "platform-tools" / ADB_NAME
UDEV_RULE_PATH = Path("/etc/udev/rules.d/99-touch2key.rules")

TOML_PATH = PROJECT_ROOT / "settings.toml"
IMAGES_FOLDER = SRC_DIR / "resources" / "images"
JSONS_FOLDER = SRC_DIR / "resources" / "jsons"

# Constants
DEF_DPI = 160

DOWN = "DOWN"
UP = "UP"
PRESSED = "PRESSED"
IDLE = "IDLE"

CIRCLE = "CIRCLE"
RECTANGLE = "RECTANGLE"
M_LEFT = 0x9901
M_RIGHT = 0x9902
M_MIDDLE = 0x9903
SPRINT_DISTANCE_CODE = "LEFT_BRACKET"
MOUSE_WHEEL_CODE = "RIGHT_BRACKET"

# Delays (in seconds)
RELOAD_DELAY = 0.5
SHORT_DELAY = 1.0
LONG_DELAY = 2.0
WINDOW_UPDATE_INTERVAL = 0.05
ROTATION_POLL_INTERVAL = 0.5

# Delay (in nanoseconds)
CURSOR_CHECK_DELAY_NS = 100_000_000

# Windows specific constants
# 0.5ms (5,000 units of 100ns)
NT_TIMER_RES = 5000
MAX_CLASS_NAME = 256

# Fallback Performance Constants
DEFAULT_ADB_RATE_CAP = 250
DEFAULT_PPS = 60

# Bridge Constants
MOUSE_MOVE_RELATIVE = 0x00
MOUSE_MOVE_ABSOLUTE = 0x01
MOUSE_VIRTUAL_DESKTOP = 0x02

LEFT_BUTTON_DOWN, LEFT_BUTTON_UP = 0x0001, 0x0002
RIGHT_BUTTON_DOWN, RIGHT_BUTTON_UP = 0x0004, 0x0008
MIDDLE_BUTTON_DOWN, MIDDLE_BUTTON_UP = 0x0010, 0x0020

# Window Selection
WINDOWS_HEADERS = ["Window ID", "Title", "Class Name", "Left", "Top", "Width", "Height"]

PORT = "5555"

EVENT_TYPE = Literal[
    "ON_CONFIG_RELOAD",
    "ON_JSON_RELOAD",
    "ON_WASD_BLOCK",
    "ON_MENU_MODE_TOGGLE",
    "ON_AGGREGATION",
    "ON_WORKER_RESPAWN",
]

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
SCANCODES.update(
    {
        "MOUSE_LEFT": M_LEFT,
        "MOUSE_RIGHT": M_RIGHT,
        "MOUSE_MIDDLE": M_MIDDLE,
    }
)

SCANCODES_INV = {v: k for k, v in SCANCODES.items()}

SCANCODES.update(
    {
        transformed: v
        for k, v in list(SCANCODES.items())
        for transformed in (
            [k.upper()]
            if k.islower()
            else [k.lower()] if k.startswith("F") and k[1:].isdigit() else []
        )
    }
)

SPECIAL_MAP = {
    "escape": "ESC",
    "enter": "ENTER",
    "backspace": "BACKSPACE",
    "tab": "TAB",
    "=": "EQUAL",
    "-": "MINUS",
    "[": "LEFT_BRACKET",
    "]": "RIGHT_BRACKET",
    ";": "SEMICOLON",
    "'": "APOSTROPHE",
    "`": "GRAVE",
    "\\": "BACKSLASH",
    ",": "COMMA",
    ".": "DOT",
    "/": "SLASH",
    "lshift": "LSHIFT",
    "rshift": "RSHIFT",
    "lalt": "LALT",
    "ralt": "RALT",
    "lctrl": "LCTRL",
    "rctrl": "RCTRL",
    "shift": "RSHIFT",
    "alt": "RALT",
    "ctrl": "RCTRL",
    "control": "RCTRL",
    " ": "SPACE",
    "*": "NUM_MULTIPLY",
    "caps_lock": "CAPSLOCK",
    "num_lock": "NUMLOCK",
    "scroll_lock": "SCROLLLOCK",
    "up": "E0_UP",
    "left": "E0_LEFT",
    "right": "E0_RIGHT",
    "down": "E0_DOWN",
    "insert": "E0_INSERT",
    "delete": "E0_DELETE",
}

SPECIAL_MAP_INV = {v: k for k, v in SPECIAL_MAP.items()}

# Low-level worker constants (dwell times in seconds)
MAX_COALESCE = 20
DOWN_TUPLE = (LEFT_BUTTON_DOWN, RIGHT_BUTTON_DOWN, MIDDLE_BUTTON_DOWN)
CONSTANT_DWELL = 0.001
MIN_BUTTON_DWELL = 0.025
MAX_BUTTON_DWELL = 0.04
MIN_MOUSE_DWELL = 0.0008
MAX_MOUSE_DWELL = 0.0012
MIN_KEY_DWELL = 0.040
MAX_KEY_DWELL = 0.070

# Standard Hardware Keyboard Repeat Specifications
INITIAL_DELAY_NS = 500_000_000  # 500ms pause before spamming starts
REPEAT_RATE = 0.0333  # ~30 spam events per second
# Base scancodes that DO NOT spam and DO NOT steal focus
# LCtrl(0x1D), RCtrl(0xE01D), LShift(0x2A), RShift(0x36), LAlt(0x38), RAlt(0xE038)
# CapsLock(0x3A), NumLock(0x45), ScrollLock(0x46)
NON_SPAMMING_KEYS = {0x2A, 0x36, 0x1D, 0xE01D, 0x38, 0xE038, 0x3A, 0x45, 0x46}


class TouchEvent:
    def __init__(
        self,
        slot: int,
        id: int,
        x: float,
        y: float,
        sx: float,
        sy: float,
        timestamp: float,
        is_mouse: bool,
        is_wasd: bool,
    ):
        self.slot = slot
        self.id = id
        self.x = x
        self.y = y
        self.sx = sx
        self.sy = sy
        self.timestamp = timestamp
        self.is_mouse = is_mouse
        self.is_wasd = is_wasd

    def show(self):
        return f"Slot: {self.slot}, ID: {self.id}, X: {self.x}, Y: {self.y}, SX: {self.sx}, SY: {self.sy}, Timestamp: {self.timestamp}, Mouse: {self.is_mouse}, WASD: {self.is_wasd}"


class MapperEvent:
    def __init__(
        self,
        action: EVENT_TYPE,
        is_visible=True,
        sum_dx: float | None = None,
        sum_dy: float | None = None,
        acc_x: float | None = None,
        acc_y: float | None = None,
        worker_type: str | None = None,
    ):
        self.action: EVENT_TYPE = action
        self.is_visible = is_visible
        self.sum_dx = sum_dx
        self.sum_dy = sum_dy
        self.acc_x = acc_x
        self.acc_y = acc_y
        self.worker_type = worker_type

    def show(self):
        _str = ""
        if self.sum_dx:
            _str += f", Sum DX: {self.sum_dx}"

        if self.acc_x:
            _str += f", Acc X: {self.acc_x}"

        if self.sum_dy:
            _str += f", Sum DY: {self.sum_dy}"

        if self.acc_y:
            _str += f", Acc Y: {self.acc_y}"

        if self.worker_type:
            _str += f", Worker Type: {self.worker_type}"

        return f"Action: {self.action}, Cursor Visible: {self.is_visible}" + _str


class MapperEventDispatcher:
    def __init__(self):
        # The Registry
        self.callback_registry = {
            "ON_CONFIG_RELOAD": [],
            "ON_JSON_RELOAD": [],
            "ON_WASD_BLOCK": [],
            "ON_MENU_MODE_TOGGLE": [],
            "ON_AGGREGATION": [],
            "ON_WORKER_RESPAWN": [],
        }

    def register_callback(self, event_type: EVENT_TYPE, func):
        if event_type in self.callback_registry:
            self.callback_registry[event_type].append(func)
        else:
            print(
                f"\n[UTILITY] - Attempted to register unknown event {event_type} for function {func.__name__}."
            )

    def unregister_callback(self, event_type: EVENT_TYPE, func):
        if event_type in self.callback_registry:
            if func in self.callback_registry[event_type]:
                self.callback_registry[event_type].remove(func)
            else:
                print(
                    f"\n[UTILITY] - Function {func.__name__} was not registered for {event_type}."
                )
        else:
            print(
                f"\n[UTILITY] - Attempted to unregister unknown event {event_type} for function {func.__name__}."
            )

    def dispatch(self, event_object: MapperEvent):
        registry_key = event_object.action

        if registry_key in self.callback_registry:
            for func in self.callback_registry.get(registry_key, []):
                if event_object.action in [
                    "ON_CONFIG_RELOAD",
                    "ON_JSON_RELOAD",
                    "ON_WASD_BLOCK",
                ]:
                    func()
                elif event_object.action in ["ON_MENU_MODE_TOGGLE"]:
                    func(event_object.is_visible)
                elif event_object.action in ["ON_AGGREGATION"]:
                    func(
                        event_object.sum_dx,
                        event_object.sum_dy,
                        event_object.acc_x,
                        event_object.acc_y,
                    )
                elif event_object.action in ["ON_WORKER_RESPAWN"]:
                    func(event_object.worker_type)

        else:
            print(f"\n[UTILITY] - Attempted to dispatch unknown event {registry_key}.")


def get_adb_device():
    out = subprocess.check_output([ADB, "devices"], timeout=10).decode().splitlines()
    real = [
        d.split()[0] for d in out[1:] if "device" in d and not d.startswith("emulator-")
    ]

    if not real:
        raise RuntimeError("\n[UTILITY] - No real device detected.")
    else:
        return real[0]


def get_screen_size(device):
    """Detect screen resolution (portrait natural)."""
    result = subprocess.run(
        [ADB, "-s", device, "shell", "wm", "size"],
        capture_output=True,
        text=True,
        timeout=10,
    )
    output = result.stdout.strip()
    if "Physical size" in output:
        w, h = map(int, output.split(":")[-1].strip().split("x"))
        return w, h

    return None


def get_dpi(device: str):
    """Detect screen DPI, fallback to 160."""
    try:
        result = subprocess.run(
            [ADB, "-s", device, "shell", "getprop", "ro.sf.lcd_density"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        val = result.stdout.strip()
        return int(val) if val else DEF_DPI
    except Exception:
        return DEF_DPI


def is_device_online(device: str):
    try:
        res = subprocess.run(
            [ADB, "-s", device, "get-state"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        return "device" in res.stdout
    except Exception:
        return False


def wireless_connect(device: str | None = None, continuous=True):
    running = True
    error_1 = False
    error_2 = False

    while running:
        if not device:
            try:
                device = get_adb_device()

            except RuntimeError:
                if continuous:
                    if not error_1:
                        print("\n[UTILITY] - No adb devices detected. Retrying...")
                        error_1 = True
                    time.sleep(SHORT_DELAY)
                    continue
                else:
                    return False, ""

            error_1 = False

        try:
            routes = (
                subprocess.check_output(
                    [ADB, "-s", device, "shell", "ip", "route"], timeout=10
                )
                .decode()
                .splitlines()
            )
            socket = [
                s.split()[-1] for s in routes if "dev ap0" in s or "dev wlan0" in s
            ]

            if not socket:
                raise RuntimeError(
                    f"\n[UTILITY] - No sockets found for device: {device}."
                )
            socket_path = socket[0] + ":" + PORT

            if device == socket_path:
                print(f"\n[UTILITY] - Connected successfully to device: {socket_path}.")
            else:
                subprocess.run([ADB, "-s", device, "tcpip", PORT], timeout=10)
                final = (
                    subprocess.check_output(
                        [ADB, "-s", device, "connect", socket_path], timeout=10
                    )
                    .decode()
                    .splitlines()[0]
                )  # If there's an error its supposed to be raised here.

                if (
                    "(10065)" in final
                ):  # Default fallback if no errors were raised in previous line
                    raise RuntimeError(
                        f"\n[UTILITY] - Cannot connect to {socket_path}: A socket operation was attempted to an unreachable host (10065)."
                    )

                print(
                    f"\n[UTILITY] - Connected successfully to device: {device} on socket: {socket_path}, device now set to: {socket_path}."
                )

            if continuous:
                running = False
            else:
                return True, socket_path

        except Exception as e:
            if continuous:
                if not error_2:
                    print(f"\n[UTILITY] - Error connecting, retrying...")
                    error_2 = True
                time.sleep(SHORT_DELAY)
                continue
            else:
                return False, ""

        error_2 = False


def is_in_circle(px: float, py: float, cx: float, cy: float, r: float):
    return (px - cx) ** 2 + (py - cy) ** 2 <= r * r


def is_in_rectangle(
    px: float, py: float, left: float, right: float, top: float, bottom: float
):
    return (left <= px <= right) and (top <= py <= bottom)


def create_default_toml():
    print(f"\n[UTILITY] - Resetting '{TOML_PATH}' to default.")
    doc = tomlkit.document()

    system = tomlkit.table()
    system.add("left_handed", False)
    system.add("hud_image_path", "")
    system.add("json_path", "")
    system.add("json_dev_res", [360, 800])
    system.add("json_dev_dpi", 160)
    doc.add("system", system)

    mouse = tomlkit.table()
    mouse.add("sensitivity", 1.0)
    doc.add("mouse", mouse)

    joystick = tomlkit.table()
    joystick.add("deadzone", 0.1)
    joystick.add("hysteresis", 5.0)
    joystick.add("mouse_wheel_radius", 50.0)
    joystick.add("sprint_distance", 10.0)
    doc.add("joystick", joystick)

    keys = tomlkit.table()
    keys.add("toggle_key", "")
    keys.add("sprint_key", "")
    doc.add("keys", keys)

    try:
        with open(TOML_PATH, "w", encoding="utf-8", newline="") as f:
            tomlkit.dump(doc, f)
        print(f"\n[UTILITY] - Successfully created settings.toml at '{TOML_PATH}'.")
    except Exception as e:
        print(f"\n[UTILITY] - Failed to create settings.toml: {e}.")


def get_keys_from_toml() -> tuple[str | None, str | None]:
    try:
        if not TOML_PATH.exists():
            return None, None
        with open(TOML_PATH, "r", encoding="utf-8", newline="") as f:
            doc = tomlkit.load(f)
        keys = doc.get("keys", {})
        toggle = keys.get("toggle_key") or None
        sprint = keys.get("sprint_key") or None
        return toggle, sprint
    except Exception:
        return None, None


def update_toml_keys(toggle_key: str | None, sprint_key: str | None):
    try:
        if not TOML_PATH.exists():
            create_default_toml()
        with open(TOML_PATH, "r", encoding="utf-8", newline="") as f:
            doc = tomlkit.load(f)
        if "keys" not in doc:
            doc.append("keys", tomlkit.table())
        doc["keys"]["toggle_key"] = toggle_key or ""
        doc["keys"]["sprint_key"] = sprint_key or ""
        with open(TOML_PATH, "w", encoding="utf-8", newline="") as f:
            tomlkit.dump(doc, f)
    except Exception as e:
        print(f"\n[UTILITY] - Could not save key config: {e}.")


def update_toml(
    w=None,
    h=None,
    dpi=None,
    image_path=None,
    json_path=None,
    mouse_wheel_radius=None,
    sprint_distance=None,
    strict=False,
):
    try:
        if not os.path.exists(TOML_PATH):
            create_default_toml()

        with open(TOML_PATH, "r", encoding="utf-8", newline="") as f:
            doc = tomlkit.load(f)

        table_keys = doc.keys()

        if "joystick" not in doc:
            doc.append("joystick", tomlkit.table())
        joystick = doc["joystick"]

        if "system" not in table_keys:
            doc.append("system", tomlkit.table())
        system = doc["system"]

        if mouse_wheel_radius is not None:
            joystick.update({"mouse_wheel_radius": mouse_wheel_radius})
        if sprint_distance is not None:
            joystick.update({"sprint_distance": sprint_distance})

        if w and h:
            system.update({"json_dev_res": [w, h]})
        if dpi:
            system.update({"json_dev_dpi": dpi})

        i_path = Path(image_path).as_posix() if image_path else ""
        if image_path is not None:
            system.update({"hud_image_path": i_path})

        j_path = Path(json_path).as_posix() if json_path else ""
        if json_path is not None:
            system.update({"json_path": j_path})

        with open(TOML_PATH, "w", encoding="utf-8", newline="") as f:
            tomlkit.dump(doc, f)

    except Exception as e:
        if os.path.exists(TOML_PATH):
            os.replace(TOML_PATH, str(TOML_PATH) + ".bak")
            print("\n[UTILITY] - Settings were corrupted and reset. Backup created.")
        create_default_toml()
        if strict:
            raise e
        else:
            print(f"\n[UTILITY] - Could not update Toml: {e}.")


def get_rotation(device):
    rotation = 0
    patterns = [
        r"mCurrentRotation=(\d+)",
        r"rotation=(\d+)",
        r"mCurrentOrientation=(\d+)",
        r"mUserRotation=(\d+)",
    ]
    try:
        result = subprocess.run(
            [ADB, "-s", device, "shell", "dumpsys", "display"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        for pat in patterns:
            m = re.search(pat, result.stdout)
            if m:
                rotation = int(m.group(1)) % 4
                break
    except Exception:
        pass
    return rotation


def rotate_resolution(x, y, rotation):
    if x is None or y is None:
        return x, y
    res_x, res_y = x, y
    if rotation == 1 or rotation == 3:
        return res_y, res_x
    return res_x, res_y


def stop_process(process: Process):
    if process.is_alive():
        print(f"[UTILITY] - Closing {process.name}...")
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


def get_dulled_hue_color(hue, alpha=1.0):
    # Given a hue (0-1), return a color with that hue but medium saturation and high value
    s = 0.4
    v = 0.9
    r, g, b = colorsys.hsv_to_rgb(hue, s, v)
    return (r, g, b, alpha)


def get_hue_modified_alpha_from_hsv(color):
    """
    Returns a heavily modified alpha of the form 1.0 - alpha**2
    """

    r, g, b, a = color
    h, _, _ = colorsys.rgb_to_hsv(r, g, b)
    return h, 1.0 - a**2


def get_scancode_and_bridge_key_from_key(key):
    mapped_key = key
    val = SCANCODES.get(mapped_key)
    if val is None:
        mapped_key = SPECIAL_MAP.get(key)
        if mapped_key:
            val = SCANCODES.get(mapped_key)
    return hex(val) if val is not None else None, (
        mapped_key if val is not None else None
    )


def get_key_from_scancode(scancode):
    try:
        code_int = int(scancode, 16) if isinstance(scancode, str) else int(scancode)
    except (TypeError, ValueError):
        return ""
    key = SCANCODES_INV.get(code_int)
    if key is None:
        return ""
    return SPECIAL_MAP_INV.get(key, key)
