from __future__ import annotations

import colorsys
import sys
import random
import re
import struct
import subprocess
import time
import threading
from dataclasses import dataclass
from enum import Enum, auto
from pathlib import Path
from typing import TYPE_CHECKING, Callable, Literal, Any

# Task IDs
TASK_BUTTON = 0
TASK_REL = 1
TASK_ABS = 2

# Pre-compiled C-struct formats for maximum speed
PACK_BUTTON = struct.Struct("<Bi")
PACK_REL = struct.Struct("<Bhh")
PACK_ABS = struct.Struct("<Bii")
PACK_KEY = struct.Struct("<HB")

# Sentinel values for IPC Key and Mouse streams
KEY_PING = 2
KEY_CONFIG = 3  # Configuration payload for typematic timing & exclusions

# Structure: <B (Task ID = 3) ? (enabled) I (initial_delay_ns) f (repeat_rate_sec) H (excluded_count)
# Followed by array of H (unsigned short scancodes)
PACK_TYPEMATIC_HEADER = struct.Struct("<B?IfH")

BUTTON_PING = 0x0000
KEEPALIVE_INTERVAL = 5.0

if TYPE_CHECKING:
    from multiprocessing import Process

# ---------------------------------------------------------------------------
# Project & Data Paths
# ---------------------------------------------------------------------------
CURRENT_DIR = Path(__file__).resolve().parent
SRC_DIR = CURRENT_DIR.parent
PROJECT_ROOT = SRC_DIR.parent

# Binaries & Driver Rules
BIN_FOLDER = PROJECT_ROOT / "bin"
ADB_NAME = "adb.exe" if sys.platform == "win32" else "adb"
ADB = BIN_FOLDER / "platform-tools" / ADB_NAME
UDEV_RULE_PATH = Path("/etc/udev/rules.d/99-touch2key.rules")

# Centralized Data Directory
DATA_FOLDER = PROJECT_ROOT / "data"
DB_FOLDER = DATA_FOLDER / "db"
IMAGES_FOLDER = DATA_FOLDER / "images"
JSONS_FOLDER = DATA_FOLDER / "jsons"
PROFILES_FOLDER = DATA_FOLDER / "profiles"
TOML_PATH = DATA_FOLDER / "settings.toml"
DB_PATH = DB_FOLDER / "touch2key.db"
DIAGNOSTICS_FOLDER = PROJECT_ROOT / "diagnostics"
LOGS_FOLDER = PROJECT_ROOT / "logs"

# Auto-create runtime directories on module import
BIN_FOLDER.mkdir(parents=True, exist_ok=True)
DATA_FOLDER.mkdir(parents=True, exist_ok=True)
DB_FOLDER.mkdir(parents=True, exist_ok=True)
DIAGNOSTICS_FOLDER.mkdir(parents=True, exist_ok=True)
IMAGES_FOLDER.mkdir(parents=True, exist_ok=True)
JSONS_FOLDER.mkdir(parents=True, exist_ok=True)
LOGS_FOLDER.mkdir(parents=True, exist_ok=True)
PROFILES_FOLDER.mkdir(parents=True, exist_ok=True)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

DEF_DPI = 160
DOWN = "DOWN"
UP = "UP"
PRESSED = "PRESSED"
IDLE = "IDLE"

CIRCLE = "CIRCLE"
RECTANGLE = "RECTANGLE"
BEZEL = BEZEL

# VIRTUAL KEYBOARD CONSTANTS
MODIFIER_KEYS = "lshift,rshift,lctrl,rctrl,lalt,ralt"
LOCK_KEYS = "caps_lock,num_lock,scroll_lock"
TOGGLE_KEY_ID = 0x9900

M_LEFT = 0x9901
M_RIGHT = 0x9902
M_MIDDLE = 0x9903
TOP_BEZEL_ID = 0x9905
BOTTOM_BEZEL_ID = 0x9906
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

WINDOWS_HEADERS = ["Window ID", "Title", "Class Name", "Left", "Top", "Width", "Height"]
PORT = "5555"

Callback = Callable[..., None]

EVENT_TYPE = Literal[
    "ON_CONFIG_RELOAD",
    "ON_LAYOUT_RELOAD",
    "ON_WASD_BLOCK",
    "ON_MENU_MODE_TOGGLE",
    "ON_AGGREGATION",
    "ON_WORKER_RESPAWN",
    "ON_TARGET_WINDOW_CHANGE",
    "ON_DEVICES_CHANGED",
]

# Low-level worker constants
MAX_COALESCE = 20
DOWN_TUPLE = (LEFT_BUTTON_DOWN, RIGHT_BUTTON_DOWN, MIDDLE_BUTTON_DOWN)
CONSTANT_DWELL = 0.001
MIN_BUTTON_DWELL = 0.025
MAX_BUTTON_DWELL = 0.04
MIN_MOUSE_DWELL = 0.0008
MAX_MOUSE_DWELL = 0.0012
MIN_KEY_DWELL = 0.040
MAX_KEY_DWELL = 0.070

# TYPEMATIC DEFAULTS
INITIAL_DELAY_NS = 500_000_000
REPEAT_RATE = 0.0333
EXCLUDE_KEYS = "esc,tab,lshift,rshift,lctrl,rctrl,lalt,ralt,caps_lock,num_lock,scroll_lock,f1,f2,f3,f4,f5,f6,f7,f8,f9,f10,f11,f12"

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
    # Extended keys (0xE0XX series)
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
    "E0_NUM_ENTER": 0xE01C,
    "E0_SLASH": 0xE035,
    # Internal Mouse Codes
    "MOUSE_LEFT": M_LEFT,
    "MOUSE_RIGHT": M_RIGHT,
    "MOUSE_MIDDLE": M_MIDDLE,
}

SCANCODES_INV = {v: k for k, v in SCANCODES.items()}

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


# ---------------------------------------------------------------------------
# Fundamental Pipeline Data Types
# ---------------------------------------------------------------------------


class TouchPhase(Enum):
    DOWN = auto()
    MOVE = auto()
    UP = auto()


@dataclass(slots=True, frozen=True)
class Point:
    x: float
    y: float

    def __sub__(self, other: Point) -> Vector:
        return Vector(self.x - other.x, self.y - other.y)

    def __add__(self, vector: Vector) -> Point:
        return Point(self.x + vector.x, self.y + vector.y)


@dataclass(slots=True, frozen=True)
class Vector:
    x: float
    y: float

    @property
    def magnitude(self) -> float:
        import math

        return math.hypot(self.x, self.y)

    @property
    def magnitude_squared(self) -> float:
        return self.x * self.x + self.y * self.y

    def scaled(self, factor: float) -> Vector:
        return Vector(self.x * factor, self.y * factor)


@dataclass(slots=True, frozen=True)
class TouchEvent:
    contact_id: int
    phase: TouchPhase
    position: Point
    timestamp: float


@dataclass(slots=True)
class MapperEvent:
    action: EVENT_TYPE
    is_visible: bool = True
    sum_dx: float | None = None
    sum_dy: float | None = None
    acc_x: float | None = None
    acc_y: float | None = None
    worker_type: str | None = None
    target_window_id: int | None = None
    payload: dict | None = None


class MapperEventDispatcher:
    """Thread-safe event dispatcher for cross-thread engine, worker, and GUI notifications."""

    _NO_ARGS: frozenset[EVENT_TYPE] = frozenset(
        {
            "ON_CONFIG_RELOAD",
            "ON_LAYOUT_RELOAD",
            "ON_WASD_BLOCK",
        }
    )

    def __init__(self) -> None:
        self._lock = threading.Lock()

        self.callback_registry: dict[EVENT_TYPE, list[Callback]] = {
            "ON_CONFIG_RELOAD": [],
            "ON_LAYOUT_RELOAD": [],
            "ON_WASD_BLOCK": [],
            "ON_MENU_MODE_TOGGLE": [],
            "ON_AGGREGATION": [],
            "ON_WORKER_RESPAWN": [],
            "ON_TARGET_WINDOW_CHANGE": [],
            "ON_DEVICES_CHANGED": [],
        }

    def register_callback(
        self,
        event_type: EVENT_TYPE,
        func: Callback,
    ) -> None:
        try:
            with self._lock:
                if event_type not in self.callback_registry:
                    print(
                        f"[!] Unknown event type '{event_type}' during callback registration."
                    )
                    return

                callbacks = self.callback_registry[event_type]
                if func not in callbacks:
                    callbacks.append(func)
        except Exception as exc:
            func_name = getattr(func, "__name__", repr(func))
            print(
                f"[!] Error registering callback {func_name} for event {event_type}: {exc}"
            )

    def unregister_callback(
        self,
        event_type: EVENT_TYPE,
        func: Callback,
    ) -> None:
        try:
            with self._lock:
                if event_type not in self.callback_registry:
                    print(
                        f"[!] Unknown event type '{event_type}' during callback unregistration."
                    )
                    return

                callbacks = self.callback_registry[event_type]
                if func in callbacks:
                    callbacks.remove(func)
        except Exception as exc:
            func_name = getattr(func, "__name__", repr(func))
            print(
                f"[!] Error unregistering callback {func_name} for event {event_type}: {exc}"
            )

    def unregister_by_owner(self, owner: Any) -> None:
        """Removes all callbacks bound to a specific instance by checking func.__self__."""
        try:
            with self._lock:
                for event_type, callbacks in self.callback_registry.items():
                    self.callback_registry[event_type] = [
                        cb
                        for cb in callbacks
                        if getattr(cb, "__self__", None) is not owner
                    ]
        except Exception as exc:
            print(f"[!] Error unregistering callbacks for owner {owner}: {exc}")

    def unregister_all(self) -> None:
        """Flushes every registered callback across all event categories in a single call."""
        with self._lock:
            for event_type in self.callback_registry:
                self.callback_registry[event_type].clear()

    def dispatch(self, event: MapperEvent) -> None:
        with self._lock:
            callbacks = tuple(self.callback_registry.get(event.action, ()))

        args = self._get_callback_args(event)

        for callback in callbacks:
            try:
                callback(*args)
            except Exception as exc:
                func_name = getattr(callback, "__name__", repr(callback))
                print(
                    f"[!] Error in callback {func_name} for event {event.action}: {exc}"
                )

    @staticmethod
    def _get_callback_args(event: MapperEvent) -> tuple:
        action = event.action

        if action in MapperEventDispatcher._NO_ARGS:
            return ()

        if action == "ON_MENU_MODE_TOGGLE":
            return (event.is_visible,)

        if action == "ON_AGGREGATION":
            return (
                event.sum_dx,
                event.sum_dy,
                event.acc_x,
                event.acc_y,
            )

        if action == "ON_WORKER_RESPAWN":
            return (event.worker_type,)

        if action == "ON_TARGET_WINDOW_CHANGE":
            return (event.target_window_id,)

        if action == "ON_DEVICES_CHANGED":
            return (event,)

        return ()


def get_adb_device():
    out = subprocess.check_output([ADB, "devices"], timeout=10).decode().splitlines()
    real = [
        d.split()[0] for d in out[1:] if "device" in d and not d.startswith("emulator-")
    ]
    if not real:
        raise RuntimeError("No real device detected.")
    return real[0]


def get_screen_size(device):
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
    while True:
        if not device:
            try:
                device = get_adb_device()
            except RuntimeError:
                if continuous:
                    time.sleep(SHORT_DELAY)
                    continue
                return False, ""
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
                raise RuntimeError(f"No sockets found for device: {device}.")
            socket_path = f"{socket[0]}:{PORT}"

            if device != socket_path:
                subprocess.run([ADB, "-s", device, "tcpip", PORT], timeout=10)
                subprocess.check_output(
                    [ADB, "-s", device, "connect", socket_path], timeout=10
                )
            return True, socket_path
        except Exception:
            if continuous:
                time.sleep(SHORT_DELAY)
                continue
            return False, ""


def is_in_circle(px: float, py: float, cx: float, cy: float, r: float):
    return (px - cx) ** 2 + (py - cy) ** 2 <= r * r


def is_in_rectangle(
    px: float, py: float, left: float, right: float, top: float, bottom: float
):
    return (left <= px <= right) and (top <= py <= bottom)


def get_rotation(device):
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
                return int(m.group(1)) % 4
    except Exception:
        pass
    return 0


def rotate_resolution(x, y, rotation):
    if x is None or y is None:
        return x, y
    if rotation in (1, 3):
        return y, x
    return x, y


def stop_process(process: Process):
    if process.is_alive():
        print(f"[UTILITY] - Closing {process.name}...")
        process.terminate()
        time.sleep(1.0)
        if process.is_alive():
            process.kill()


def get_vibrant_random_color(alpha=1.0):
    h = random.random()
    s = random.uniform(0.7, 1.0)
    v = 0.9
    r, g, b = colorsys.hsv_to_rgb(h, s, v)
    return (r, g, b, alpha)


def get_dulled_hue_color(hue, alpha=1.0):
    s = 0.4
    v = 0.9
    r, g, b = colorsys.hsv_to_rgb(hue, s, v)
    return (r, g, b, alpha)


def get_hue_modified_alpha_from_hsv(color):
    r, g, b, a = color
    h, _, _ = colorsys.rgb_to_hsv(r, g, b)
    return h, 1.0 - a**2


def get_scancode_and_bridge_key_from_key(key: str):
    mapped_key = key
    val = SCANCODES.get(mapped_key)
    if val is None:
        mapped_key = SPECIAL_MAP.get(key)
        if mapped_key:
            val = SCANCODES.get(mapped_key)
    return hex(val) if val is not None else None, (
        mapped_key if val is not None else None
    )


def get_scancode_from_key(key: str):
    code = SCANCODES.get(key)
    if code is None:
        canonical = SPECIAL_MAP.get(key)
        if canonical:
            code = SCANCODES.get(canonical)

    return code


def get_key_from_scancode(scancode: str | int):
    try:
        code_int = int(scancode, 16) if isinstance(scancode, str) else int(scancode)
    except (TypeError, ValueError):
        return None
    key = SCANCODES_INV.get(code_int)
    return SPECIAL_MAP_INV.get(key, key) if key else None
