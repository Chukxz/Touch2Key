from __future__ import annotations

import colorsys
import sys
import logging
import random
import re
import struct
import subprocess
import time
import threading
import math
from enum import Enum, auto
from dataclasses import dataclass
from enum import Enum, auto
from pathlib import Path
from typing import TYPE_CHECKING, Callable, Literal, Any

from PySide6.QtCore import QObject, Signal

logger = logging.getLogger("modules.utils")

APP_NAME = "Touch2Key"

# ---------------------------------------------------------------------------
# OS SUBPROCESS FLAGS (PREVENTS FLICKERING CONSOLE WINDOWS)
# ---------------------------------------------------------------------------
if sys.platform == "win32":
    CREATE_NO_WINDOW = subprocess.CREATE_NO_WINDOW
else:
    CREATE_NO_WINDOW = 0

# Task IDs
TASK_BUTTON = 0
TASK_REL = 1
TASK_ABS = 2
TASK_WHEEL = 3

# Packing: 1 byte task ID, 2 bytes signed short delta (h-delta, v-delta)
# Example: delta_y > 0 is scroll up, delta_y < 0 is scroll down

# Pre-compiled C-struct formats
PACK_BUTTON_STRUCT = struct.Struct("<Bi")  # task_id, button
PACK_REL_STRUCT = struct.Struct("<Bhh")  # task_id, delta_x, delta_y
PACK_ABS_STRUCT = struct.Struct("<Bii")  # task_id, x, y
PACK_KEY_STRUCT = struct.Struct("<HB")  # key_code, key_state
PACK_WHEEL_STRUCT = struct.Struct("<Bhh")  # task_id, delta_x, delta_y

# Sentinel values for IPC Key and Mouse streams
KEY_PING = 2
KEY_CONFIG = 3  # Configuration payload for typematic timing & exclusions

# Structure: <B (Task ID = 3) ? (enabled) I (initial_delay_ns) f (repeat_rate_sec) H (excluded_count)
# Followed by a dynamically populated array of H (unsigned short scancodes)
PACK_TYPEMATIC_STRUCT = struct.Struct("<B?IfH")

BUTTON_PING = 0x0000
KEEPALIVE_INTERVAL = 5.0

# IPC Struct: 1 byte for state (1=Down, 0=Up), 2 bytes for Scancode
VKB_STRUCT = struct.Struct("<BH")


if TYPE_CHECKING:
    from multiprocessing import Process
    from multiprocessing.connection import Connection

# ---------------------------------------------------------------------------
# Project & Data Paths
# ---------------------------------------------------------------------------
CURRENT_DIR = Path(__file__).resolve().parent
SRC_DIR = CURRENT_DIR.parent
PROJECT_ROOT = SRC_DIR.parent

# Centralized Data Directory
ASSETS_FOLDER = PROJECT_ROOT / "assets"
BIN_FOLDER = PROJECT_ROOT / "bin"
DATA_FOLDER = PROJECT_ROOT / "data"
DB_FOLDER = DATA_FOLDER / "db"
DIAGNOSTICS_FOLDER = PROJECT_ROOT / "diagnostics"
ICONS_FOLDER = ASSETS_FOLDER / "icons"
IMAGES_FOLDER = DATA_FOLDER / "images"
JSONS_FOLDER = DATA_FOLDER / "jsons"
LOGS_FOLDER = PROJECT_ROOT / "logs"
PROFILES_FOLDER = DATA_FOLDER / "profiles"
TOML_PATH = DATA_FOLDER / "settings.toml"
DB_PATH = DB_FOLDER / "touch2key.db"

# Auto-create runtime directories on module import
ASSETS_FOLDER.mkdir(parents=True, exist_ok=True)
BIN_FOLDER.mkdir(parents=True, exist_ok=True)
DATA_FOLDER.mkdir(parents=True, exist_ok=True)
DB_FOLDER.mkdir(parents=True, exist_ok=True)
DIAGNOSTICS_FOLDER.mkdir(parents=True, exist_ok=True)
ICONS_FOLDER.mkdir(parents=True, exist_ok=True)
IMAGES_FOLDER.mkdir(parents=True, exist_ok=True)
JSONS_FOLDER.mkdir(parents=True, exist_ok=True)
LOGS_FOLDER.mkdir(parents=True, exist_ok=True)
PROFILES_FOLDER.mkdir(parents=True, exist_ok=True)

# Binaries & Driver Rules
ADB_NAME = "adb.exe" if sys.platform == "win32" else "adb"
ADB = BIN_FOLDER / "platform-tools" / ADB_NAME
UDEV_RULE_PATH = Path("/etc/udev/rules.d/99-touch2key.rules")


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

VISUALIZER_RUNTIME_FILE = DATA_FOLDER / "visualizer_runtime.json"
RUNTIME_FILE = DATA_FOLDER / "engine_runtime.json"
READ_ATTEMPTS = 3

ABS_CONST = 0xFFFF

BASELINE_DPI = 160
BASELINE_WIDTH = 800
BASELINE_HEIGHT = 360
DOWN = "DOWN"
UP = "UP"
PRESSED = "PRESSED"

CIRCLE = "CIRCLE"
RECTANGLE = "RECTANGLE"
BEZEL = "BEZEL"

# VIRTUAL KEYBOARD CONSTANTS
MODIFIER_KEYS = "lshift,rshift,lctrl,rctrl,lalt,ralt"
LOCK_KEYS = "caps_lock,num_lock,scroll_lock"

M_LEFT = 0x9900
M_RIGHT = 0x9901
M_MIDDLE = 0x9902
M_FORWARD = 0x9903
M_BACK = 0x9904
TOP_BEZEL_ID = 0x9905
BOTTOM_BEZEL_ID = 0x9906

# Unified tuple for mouse scancode checks across pipeline & key mappers
MOUSE_SCANCODES: tuple[int, ...] = (
    M_LEFT,
    M_RIGHT,
    M_MIDDLE,
    M_FORWARD,
    M_BACK,
)

TOP_BEZEL_NAME = "Top Bezel"
BOTTOM_BEZEL_NAME = "Bottom Bezel"
BEZEL_DP_THICKNESS = 25  # ~3.97mm
SPRINT_DISTANCE_CODE = 0x1A  # "left_bracket"
MOUSE_WHEEL_SIMULATOR_CODE = 0x1B  # "right_bracket"

# Delays (in seconds)
RELOAD_DELAY = 0.5
SHORT_DELAY = 1.0
LONG_DELAY = 2.0
WINDOW_UPDATE_INTERVAL = 0.05
ROTATION_POLL_INTERVAL = 0.5
DEF_MOVE_INTERVAL = 0.001
VKB_SLEEP_TIME = 0.1

# Delay (in nanoseconds)
CURSOR_CHECK_DELAY_NS = 100_000_000

# Windows specific constants
NT_TIMER_RES = 5000
MAX_CLASS_NAME = 256

# Fallback Performance Constants
DEFAULT_ADB_RATE_CAP = 250.0
DEFAULT_PPS = 60.0

# Mouse / joystick
SENSITIVITY_MIN, SENSITIVITY_MAX = 0.1, 10.0
DEADZONE_MIN, DEADZONE_MAX = 0.0, 1.0
HYSTERESIS_MIN, HYSTERESIS_MAX = 0.0, 45.0  # degrees

# Performance
ADB_RATE_CAP_MIN, ADB_RATE_CAP_MAX = 30.0, 1000.0  # Hz
PPS_ALERT_MIN, PPS_ALERT_MAX = 10.0, 500.0

# Typematic
TYPEMATIC_DELAY_MIN_MS, TYPEMATIC_DELAY_MAX_MS = 100.0, 1000.0
TYPEMATIC_RATE_MIN_HZ, TYPEMATIC_RATE_MAX_HZ = 1.0, 100.0

# Zones
MIN_PRIORITY, MAX_PRIORITY = -100, 200
MIN_BEZEL_DP, MAX_BEZEL_DP = 1, 100

# Bridge Constants
MOUSE_MOVE_RELATIVE = 0x00
MOUSE_MOVE_ABSOLUTE = 0x01
MOUSE_VIRTUAL_DESKTOP = 0x02
MOUSE_WHEEL = 0x0400
MOUSE_HWHEEL = 0x0800
WHEEL_DELTA = 120  # Windows standard step value

LEFT_BUTTON_DOWN, LEFT_BUTTON_UP = 0x0001, 0x0002
RIGHT_BUTTON_DOWN, RIGHT_BUTTON_UP = 0x0004, 0x0008
MIDDLE_BUTTON_DOWN, MIDDLE_BUTTON_UP = 0x0010, 0x0020
BUTTON_4_DOWN = 0x0040  # Back
BUTTON_4_UP = 0x0080
BUTTON_5_DOWN = 0x0100  # Forward
BUTTON_5_UP = 0x0200

WINDOWS_HEADERS = ["Window ID", "Title", "Class Name", "Left", "Top", "Width", "Height"]
PORT = "5555"

Callback = Callable[..., None]

EVENT_TYPE = Literal[
    "ON_RELOAD",
    "ON_MENU_MODE_TOGGLE",
    "ON_AGGREGATION",
    "ON_WORKER_RESPAWN",
    "ON_TARGET_WINDOW_CHANGE",
    "ON_DEVICES_CHANGE",
]

# Pipeline: Region ⟶ Origin ⟶ Constraint ⟶ Transformation ⟶ Semantic

REGION_MODES = ["ALWAYS", "CIRCULAR", "RECTANGULAR"]
ORIGIN_MODES = ["FIXED", "DYNAMIC", "ANCHORED"]
CONSTRAINT_MODES = ["NONE", "RADIAL", "LEASH"]
TRANSFORM_MODES = ["IDENTITY", "DELTA", "JOYSTICK"]
SEMANTIC_MODES = ["BUTTON", "DIRECTIONAL", "POINTER", "TOGGLE"]
ALLOWED_PIPELINE_FIELDS = {
    "center",
    "snap_radius",
    "radius",
}

# Low-level worker constants
MAX_COALESCE = 20
DOWN_TUPLE = (
    LEFT_BUTTON_DOWN,
    RIGHT_BUTTON_DOWN,
    MIDDLE_BUTTON_DOWN,
    BUTTON_4_DOWN,
    BUTTON_5_DOWN,
)
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
EXCLUDED_KEYS = "esc,tab,lshift,rshift,lctrl,rctrl,lalt,ralt,caps_lock,num_lock,scroll_lock,f1,f2,f3,f4,f5,f6,f7,f8,f9,f10,f11,f12"

SCANCODES = {
    "esc": 0x01,
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
    "minus": 0x0C,
    "equal": 0x0D,
    "backspace": 0x0E,
    "tab": 0x0F,
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
    "left_bracket": 0x1A,
    "right_bracket": 0x1B,
    "enter": 0x1C,
    "lctrl": 0x1D,
    "a": 0x1E,
    "s": 0x1F,
    "d": 0x20,
    "f": 0x21,
    "g": 0x22,
    "h": 0x23,
    "j": 0x24,
    "k": 0x25,
    "l": 0x26,
    "semicolon": 0x27,
    "apostrophe": 0x28,
    "grave": 0x29,
    "lshift": 0x2A,
    "backslash": 0x2B,
    "z": 0x2C,
    "x": 0x2D,
    "c": 0x2E,
    "v": 0x2F,
    "b": 0x30,
    "n": 0x31,
    "m": 0x32,
    "comma": 0x33,
    "dot": 0x34,
    "slash": 0x35,
    "rshift": 0x36,
    "num_multiply": 0x37,
    "lalt": 0x38,
    "space": 0x39,
    "capslock": 0x3A,
    "f1": 0x3B,
    "f2": 0x3C,
    "f3": 0x3D,
    "f4": 0x3E,
    "f5": 0x3F,
    "f6": 0x40,
    "f7": 0x41,
    "f8": 0x42,
    "f9": 0x43,
    "f10": 0x44,
    "numlock": 0x45,
    "scrolllock": 0x46,
    "num_7": 0x47,
    "num_8": 0x48,
    "num_9": 0x49,
    "num_minus": 0x4A,
    "num_4": 0x4B,
    "num_5": 0x4C,
    "num_6": 0x4D,
    "num_plus": 0x4E,
    "num_1": 0x4F,
    "num_2": 0x50,
    "num_3": 0x51,
    "num_0": 0x52,
    "num_dot": 0x53,
    "f11": 0x57,
    "f12": 0x58,
    # Extended keys (0xE0XX series)
    "e0_home": 0xE047,
    "e0_up": 0xE048,
    "e0_pageup": 0xE049,
    "e0_pagedown": 0xE051,
    "e0_left": 0xE04B,
    "e0_right": 0xE04D,
    "e0_end": 0xE04F,
    "e0_down": 0xE050,
    "e0_insert": 0xE052,
    "e0_delete": 0xE053,
    "rctrl": 0xE01D,
    "ralt": 0xE038,
    "e0_num_enter": 0xE01C,
    "e0_slash": 0xE035,
    # Internal Mouse Codes
    "mouse_left": M_LEFT,
    "mouse_right": M_RIGHT,
    "mouse_middle": M_MIDDLE,
    "mouse_forward": M_FORWARD,
    "mouse_back": M_BACK,
}

SCANCODES_INV = {v: k for k, v in SCANCODES.items()}

SPECIAL_MAP = {
    "escape": "esc",
    "=": "equal",
    "-": "minus",
    "[": "left_bracket",
    "]": "right_bracket",
    ";": "semicolon",
    "'": "apostrophe",
    "`": "grave",
    "\\": "backslash",
    ",": "comma",
    ".": "dot",
    "/": "slash",
    "shift": "rshift",
    "alt": "ralt",
    "ctrl": "rctrl",
    "control": "rctrl",
    "space": "space",
    " ": "space",
    "*": "num_multiply",
    "caps_lock": "capslock",
    "caps lock": "capslock",
    "num_lock": "numlock",
    "num lock": "numlock",
    "scroll_lock": "scrolllock",
    "scroll lock": "scrolllock",
    "up": "e0_up",
    "left": "e0_left",
    "right": "e0_right",
    "down": "e0_down",
    "insert": "e0_insert",
    "delete": "e0_delete",
    # Extended Mouse button aliases
    "left_click": "mouse_left",
    "m1": "mouse_left",
    "mouse1": "mouse_left",
    "right_click": "mouse_right",
    "m2": "mouse_right",
    "mouse2": "mouse_right",
    "middle_click": "mouse_middle",
    "m3": "mouse_middle",
    "mouse3": "mouse_middle",
    "back_click": "mouse_back",
    "m4": "mouse_back",
    "mouse4": "mouse_back",
    "m_back": "mouse_back",
    "forward_click": "mouse_forward",
    "m5": "mouse_forward",
    "mouse5": "mouse_forward",
    "m_forward": "mouse_forward",
}

COPY_RE = re.compile(r"- Copy(?:\s*\((\d+)\)|(?=\s|$))")

_ROUTE_SRC_RE = re.compile(
    r"\bdev\s+(?:wlan\d+|s?wlan\d+|ap\d+)\b.*?\bsrc\s+(\d+\.\d+\.\d+\.\d+)"
)

_PHYSICAL_SIZE_RE = re.compile(r"Physical size:\s*(\d+)x(\d+)")


class InvalidFieldError(ValueError):
    """Raised when update()/create()/create_pipeline_from_zone() receives a field name outside ALLOWED_FIELDS."""


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
    target_window_title: str = ""
    keyboard_device_id: int | None = None
    mouse_device_id: int | None = None
    cooldown: float = 0.0
    dispatch_msg: str | None = None

    def __post_init__(self) -> None:
        self.cooldown = max(0.0, self.cooldown)


class MapperEventDispatcher:
    """Thread-safe event dispatcher with per-action trailing-edge debouncing.

    Eligible pending events are delivered by deadline, preserving collection
    order when deadlines are equal. Callbacks are executed outside locks.
    """

    _NO_ARGS: frozenset[EVENT_TYPE] = frozenset({"ON_RELOAD"})

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._debounce_lock = threading.Lock()

        self._last_debounce_times: dict[EVENT_TYPE, float] = {}

        # action -> (deadline, collection_sequence, event)
        self._debounce_cache: dict[
            EVENT_TYPE, tuple[float, int, MapperEvent]
        ] = {}

        self._next_sequence = 0

        self.callback_registry: dict[EVENT_TYPE, list[Callback]] = {
            "ON_RELOAD": [],
            "ON_MENU_MODE_TOGGLE": [],
            "ON_AGGREGATION": [],
            "ON_WORKER_RESPAWN": [],
            "ON_TARGET_WINDOW_CHANGE": [],
            "ON_DEVICES_CHANGE": [],
        }

        self._debounce_thread = threading.Thread(
            target=self._debounce_loop,
            daemon=True,
            name="MapperEventDebouncer",
        )
        self._debounce_thread.start()

    def _debounce_loop(self) -> None:
        while True:
            now = time.perf_counter()
            ready: list[tuple[float, int, MapperEvent]] = []

            with self._debounce_lock:
                for action, (deadline, sequence, event) in list(
                    self._debounce_cache.items()
                ):
                    if deadline <= now:
                        del self._debounce_cache[action]
                        self._last_debounce_times[action] = now
                        ready.append((deadline, sequence, event))

            # Deadline order, then collection order for equal deadlines.
            ready.sort(key=lambda item: (item[0], item[1]))

            for _, _, event in ready:
                self._deliver(event)

            time.sleep(0.01)

    def _check_debounce(self, event: MapperEvent) -> bool:
        """Return True when the event should be delivered immediately."""
        action = event.action
        now = time.perf_counter()

        with self._debounce_lock:
            if event.cooldown == 0:
                self._debounce_cache.pop(action, None)
                return True

            last = self._last_debounce_times.get(action)

            if last is None or now - last >= event.cooldown:
                self._debounce_cache.pop(action, None)
                self._last_debounce_times[action] = now
                return True

            self._next_sequence += 1
            self._debounce_cache[action] = (
                last + event.cooldown,
                self._next_sequence,
                event,
            )
            return False

    def register_callback(
        self,
        event_type: EVENT_TYPE,
        callback: Callback,
    ) -> None:
        with self._lock:
            callbacks = self.callback_registry.get(event_type)

            if callbacks is None:
                logger.warning(
                    "Unknown event type %r during callback registration.",
                    event_type,
                )
                return

            if callback not in callbacks:
                callbacks.append(callback)
                logger.debug(
                    "Registered callback %s for event %s",
                    getattr(callback, "__name__", repr(callback)),
                    event_type,
                )
            else:
                logger.debug(
                    "Callback %s already registered for event %s",
                    getattr(callback, "__name__", repr(callback)),
                    event_type,
                )

    def unregister_callback(
        self,
        event_type: EVENT_TYPE,
        callback: Callback,
    ) -> None:
        with self._lock:
            callbacks = self.callback_registry.get(event_type)

            if callbacks is None:
                logger.warning(
                    "Unknown event type %r during callback unregistration.",
                    event_type,
                )
                return

            try:
                callbacks.remove(callback)
            except ValueError:
                logger.debug(
                    "Callback %s not found for event %s",
                    getattr(callback, "__name__", repr(callback)),
                    event_type,
                )

    def unregister_by_owner(self, owner: Any) -> None:
        """Remove callbacks bound to a specific instance."""
        with self._lock:
            for event_type, callbacks in self.callback_registry.items():
                self.callback_registry[event_type] = [
                    callback
                    for callback in callbacks
                    if getattr(callback, "__self__", None) is not owner
                ]

    def unregister_all(self) -> None:
        """Remove all registered callbacks."""
        with self._lock:
            for callbacks in self.callback_registry.values():
                callbacks.clear()

    def dispatch(
        self,
        event: MapperEvent,
    ) -> None:
        if not self._check_debounce(event):
            return

        # Immediate dispatch supersedes a pending event of this action.
        with self._debounce_lock:
            self._debounce_cache.pop(event.action, None)

        self._deliver(event)

    def _deliver(self, event: MapperEvent) -> None:
        """Invoke a snapshot of callbacks without holding registry locks."""
        if event.dispatch_msg is not None:
            print(event.dispatch_msg)

        with self._lock:
            callbacks = self.callback_registry.get(
                event.action, []
            ).copy()

        args = self._get_callback_args(event)

        for callback in callbacks:
            callback_name = getattr(
                callback, "__name__", repr(callback)
            )

            try:
                callback(*args)
                logger.debug(
                    "Dispatched event %s to callback %s",
                    event.action,
                    callback_name,
                )
            except Exception:
                logger.exception(
                    "Error in callback %s for event %s",
                    callback_name,
                    event.action,
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
            return (
                event.target_window_id,
                event.target_window_title,
            )

        if action == "ON_DEVICES_CHANGE":
            return (
                event.keyboard_device_id,
                event.mouse_device_id,
            )

        return ()


class TouchEventCount():
    def __init__(self):
        self.event_count_down = 0
        self.event_count_move = 0
        self.event_count_up = 0
        self.event_count = 0
        
    def record(self, touch_event: TouchEvent):
        if touch_event.phase is TouchPhase.MOVE:
            self.event_count_move += 1
        elif touch_event.phase is TouchPhase.DOWN:
            self.event_count_down += 1
        elif touch_event.phase is TouchPhase.UP:
            self.event_count_up += 1
        
        self.event_count += 1

    def reset(self):
        self.event_count_down = 0
        self.event_count_move = 0
        self.event_count_up = 0
        self.event_count = 0


class CurveType(Enum):
    LINEAR = auto()
    CUBIC = auto()
    EXPONENTIAL = auto()

class InputCurve:
    def __init__(self, curve_type=CurveType.CUBIC):
        # Configuration
        self.curve_type = curve_type
        self.initial_delay = 0.400  # 400ms wait before auto-repeat begins
        self.start_delay = 0.200    # 5 Hz starting speed (1 / 5)
        self.min_delay = 0.033      # 30 Hz maximum speed (1 / 30)
        
        # Adjust ramp duration based on curve steepness
        if self.curve_type == CurveType.EXPONENTIAL:
            self.ramp_duration = 1.0  # Shorter ramp for true exponential
        else:
            self.ramp_duration = 1.5  # Standard ramp for linear/cubic
            
        # State tracking
        self.is_held = False
        self.hold_start_time = 0.0
        self.last_fire_time = 0.0

    def check_input(self, current_time_sec, is_key_down):
        # Reset state if the key is released
        if not is_key_down:
            self.is_held = False
            return False

        # Phase 1: Initial Press
        if not self.is_held:
            self.is_held = True
            self.hold_start_time = current_time_sec
            self.last_fire_time = current_time_sec
            return True  # Trigger the very first increment
            
        time_held = current_time_sec - self.hold_start_time
        
        # Wait for the initial delay to pass
        if time_held < self.initial_delay:
            return False
            
        # Phase 2: Calculate progress (0.0 to 1.0)
        ramp_active_time = time_held - self.initial_delay
        progress = min(ramp_active_time / self.ramp_duration, 1.0)
        
        # Phase 3: Apply the selected easing function
        if self.curve_type == CurveType.LINEAR:
            eased_progress = progress
            
        elif self.curve_type == CurveType.CUBIC:
            eased_progress = progress ** 3
            
        elif self.curve_type == CurveType.EXPONENTIAL:
            # Standard Expo Ease-In: stays flat then spikes aggressively
            eased_progress = 0.0 if progress == 0.0 else math.pow(2, 10 * (progress - 1))
            
        # Phase 4: Interpolate the delay and check if it's time to fire
        current_delay = self.start_delay - (eased_progress * (self.start_delay - self.min_delay))
        
        if (current_time_sec - self.last_fire_time) >= current_delay:
            self.last_fire_time = current_time_sec
            return True
            
        return False  
        

# ---------------------------------------------------------------------------
# Engine <-> GUI process IPC protocol
# ---------------------------------------------------------------------------
IPC_CMD_START = 0x01
IPC_CMD_STOP = 0x02
IPC_CMD_RELOAD = 0x03
IPC_CMD_DEVICES_CHANGE = 0x04
IPC_CMD_TARGET_WINDOW_CHANGE = 0x05

IPC_EVT_STARTED = 0x80
IPC_EVT_STOPPED = 0x81
IPC_EVT_ERROR = 0x82

# Using signed 64-bit integers ("q") for window IDs to prevent 32-bit overflow
PACK_IPC_START_STRUCT = struct.Struct("<Bq")
PACK_IPC_DEVICES_CHANGE_STRUCT = struct.Struct("<Bii")
PACK_IPC_TARGET_WINDOW_CHANGE_STRUCT = struct.Struct("<Bq")

_IPC_NONE_INT = -1
_IPC_STR_SEP = "\x1f"


def _pack_opt_int(value: int | None) -> int:
    return _IPC_NONE_INT if value is None else value


def _unpack_opt_int(value: int) -> int | None:
    return None if value == _IPC_NONE_INT else value


def _pack_trailing_strings(*values: str | None) -> bytes:
    return _IPC_STR_SEP.join(v or "" for v in values).encode("utf-8")


def _unpack_trailing_strings(data: bytes, count: int) -> list[str | None]:
    parts = data.decode("utf-8").split(_IPC_STR_SEP) if data else [""] * count
    parts = (parts + [""] * count)[:count]
    return [p or None for p in parts]


def pack_ipc_start_cmd(
    window_id: int | None,
) -> bytes:
    header = PACK_IPC_START_STRUCT.pack(
        IPC_CMD_START,
        _pack_opt_int(window_id),
    )
    return header


def unpack_ipc_start_cmd(payload: bytes) -> dict[str, Any]:
    (
        _,
        window_id,
    ) = PACK_IPC_START_STRUCT.unpack(payload)

    return {"window_id": _unpack_opt_int(window_id)}


def pack_ipc_stop_cmd() -> bytes:
    return bytes([IPC_CMD_STOP])


def pack_ipc_reload_cmd() -> bytes:
    return bytes([IPC_CMD_RELOAD])


def pack_ipc_devices_change_cmd(k_id: int | None, m_id: int | None) -> bytes:
    return PACK_IPC_DEVICES_CHANGE_STRUCT.pack(
        IPC_CMD_DEVICES_CHANGE, _pack_opt_int(k_id), _pack_opt_int(m_id)
    )


def unpack_ipc_devices_change_cmd(payload: bytes) -> tuple[int | None, int | None]:
    _, k_id, m_id = PACK_IPC_DEVICES_CHANGE_STRUCT.unpack(payload)
    return _unpack_opt_int(k_id), _unpack_opt_int(m_id)


def pack_ipc_target_window_change_cmd(
    target_window_id: int | None, target_window_title: str
) -> bytes:
    header = PACK_IPC_TARGET_WINDOW_CHANGE_STRUCT.pack(
        IPC_CMD_TARGET_WINDOW_CHANGE, _pack_opt_int(target_window_id)
    )
    return header + target_window_title.encode("utf-8")


def unpack_ipc_target_window_change_cmd(payload: bytes) -> tuple[int | None, str]:
    fixed_size = PACK_IPC_TARGET_WINDOW_CHANGE_STRUCT.size
    _, target_window_id = PACK_IPC_TARGET_WINDOW_CHANGE_STRUCT.unpack_from(payload, 0)
    title = payload[fixed_size:].decode("utf-8")
    return _unpack_opt_int(target_window_id), title


def pack_ipc_started_evt() -> bytes:
    return bytes([IPC_EVT_STARTED])


def pack_ipc_stopped_evt() -> bytes:
    return bytes([IPC_EVT_STOPPED])


def pack_ipc_error_evt(message: str) -> bytes:
    return bytes([IPC_EVT_ERROR]) + message.encode("utf-8")


def unpack_ipc_error_evt(payload: bytes) -> str:
    return payload[1:].decode("utf-8")


class IpcMapperEventDispatcher(MapperEventDispatcher):
    """Engine-process-side dispatcher."""

    def __init__(self, conn: Connection) -> None:
        super().__init__()
        self.conn = conn
        self._send_lock = threading.Lock()

    def dispatch(self, event: MapperEvent) -> None:
        super().dispatch(event)

    def send_ipc(self, payload: bytes) -> None:
        with self._send_lock:
            self.conn.send_bytes(payload)

    def send_started(self) -> None:
        self.send_ipc(pack_ipc_started_evt())

    def send_stopped(self) -> None:
        self.send_ipc(pack_ipc_stopped_evt())

    def send_error(self, message: str) -> None:
        self.send_ipc(pack_ipc_error_evt(message))

    def handle_command(self, payload: bytes) -> bool:
        opcode = payload[0]
        if opcode == IPC_CMD_STOP:
            return False
        if opcode == IPC_CMD_RELOAD:
            self.dispatch(MapperEvent(action="ON_RELOAD"))
        elif opcode == IPC_CMD_DEVICES_CHANGE:
            k_id, m_id = unpack_ipc_devices_change_cmd(payload)
            self.dispatch(
                MapperEvent(
                    action="ON_DEVICES_CHANGE",
                    keyboard_device_id=k_id,
                    mouse_device_id=m_id,
                )
            )
        elif opcode == IPC_CMD_TARGET_WINDOW_CHANGE:
            window_id, window_title = unpack_ipc_target_window_change_cmd(payload)
            self.dispatch(
                MapperEvent(
                    action="ON_TARGET_WINDOW_CHANGE",
                    target_window_id=window_id,
                    target_window_title=window_title,
                )
            )
        else:
            logger.warning(f"[!] Unknown IPC command opcode: {opcode}")
        return True

    def run_command_loop(self) -> None:
        while True:
            try:
                payload = self.conn.recv_bytes()
            except (EOFError, OSError):
                return
            if not payload or not self.handle_command(payload):
                return


class QtIpcMapperEventDispatcher(QObject):
    """GUI-process-side counterpart to IpcMapperEventDispatcher."""

    engine_started = Signal()
    engine_stopped = Signal()
    engine_error = Signal(str)

    def __init__(self, conn: Any, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.conn = conn
        self._send_lock = threading.Lock()
        self._running = True
        self._reader_thread = threading.Thread(target=self._read_loop, daemon=True)
        self._reader_thread.start()

    def _read_loop(self) -> None:
        while self._running:
            try:
                payload = self.conn.recv_bytes()
            except (EOFError, OSError):
                return
            if payload:
                self._handle_event(payload)

    def _handle_event(self, payload: bytes) -> None:
        opcode = payload[0]
        try:
            if opcode == IPC_EVT_STARTED:
                self.engine_started.emit()
            elif opcode == IPC_EVT_STOPPED:
                self.engine_stopped.emit()
            elif opcode == IPC_EVT_ERROR:
                self.engine_error.emit(unpack_ipc_error_evt(payload))
            else:
                logger.warning(f"[!] Unknown IPC event opcode: {opcode}")
        except Exception as exc:
            logger.debug(
                f"[!] Failed to handle IPC event (opcode={opcode}): {exc}",
                exc_info=True,
            )

    def _send(self, payload: bytes) -> None:
        with self._send_lock:
            try:
                self.conn.send_bytes(payload)
            except (BrokenPipeError, OSError) as exc:
                logger.error(f"[!] Failed to send IPC command: {exc}", exc_info=True)

    def send_start(
        self,
        window_id: int | None,
    ) -> None:
        self._send(
            pack_ipc_start_cmd(
                window_id,
            )
        )

    def send_stop(self) -> None:
        self._send(pack_ipc_stop_cmd())

    def send_reload(self) -> None:
        self._send(pack_ipc_reload_cmd())

    def send_devices_change(self, k_id: int | None, m_id: int | None) -> None:
        self._send(pack_ipc_devices_change_cmd(k_id, m_id))

    def send_target_window_change(
        self, target_window_id: int | None, target_window_title: str
    ):
        self._send(
            pack_ipc_target_window_change_cmd(target_window_id, target_window_title)
        )

    def close(self) -> None:
        self._running = False
        try:
            self.conn.close()
        except OSError:
            pass


def get_adb_device():
    out = (
        subprocess.check_output(
            [ADB, "devices"], timeout=10, creationflags=CREATE_NO_WINDOW
        )
        .decode()
        .splitlines()
    )
    real = [
        p[0]
        for line in out[1:]
        if len(p := line.split()) >= 2
        and p[1] == "device"
        and not p[0].startswith("emulator-")
    ]
    if not real:
        raise RuntimeError("No real device detected.")
    return real[0]


def get_screen_size(device: str) -> tuple[int, int] | None:
    result = subprocess.run(
        [ADB, "-s", device, "shell", "wm", "size"],
        capture_output=True,
        text=True,
        timeout=10,
        creationflags=CREATE_NO_WINDOW,
    )
    match = _PHYSICAL_SIZE_RE.search(result.stdout)
    if match:
        return int(match.group(1)), int(match.group(2))
    return None


def get_dpi(device: str):
    try:
        result = subprocess.run(
            [ADB, "-s", device, "shell", "getprop", "ro.sf.lcd_density"],
            capture_output=True,
            text=True,
            timeout=10,
            creationflags=CREATE_NO_WINDOW,
        )
        val = result.stdout.strip()
        return int(val) if val else BASELINE_DPI
    except Exception:
        return BASELINE_DPI


def is_device_online(device: str):
    try:
        res = subprocess.run(
            [ADB, "-s", device, "get-state"],
            capture_output=True,
            text=True,
            timeout=10,
            creationflags=CREATE_NO_WINDOW,
        )
        return res.stdout.strip() == "device"
    except Exception:
        return False


def wireless_connect(device: str | None = None, continuous: bool = True):
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
            routes = subprocess.check_output(
                [ADB, "-s", device, "shell", "ip", "route"],
                text=True,
                timeout=10,
                creationflags=CREATE_NO_WINDOW,
            ).splitlines()
            ip_addr = None
            for line in routes:
                m = _ROUTE_SRC_RE.search(line)
                if m:
                    ip_addr = m.group(1)
                    break
            if not ip_addr:
                raise RuntimeError(f"No sockets found for device: {device}.")
            socket_path = f"{ip_addr}:{PORT}"

            if device != socket_path:
                # 1. Restart adbd daemon on device in TCP mode
                subprocess.run(
                    [ADB, "-s", device, "tcpip", PORT],
                    timeout=5,
                    creationflags=CREATE_NO_WINDOW,
                    check=True,
                )
                # 2. Allow adbd 1.5 seconds to restart and bind to port 5555
                time.sleep(1.5)

                # 3. Connect to the IP address WITHOUT '-s <device>'
                subprocess.run(
                    [ADB, "connect", socket_path],
                    timeout=5,
                    creationflags=CREATE_NO_WINDOW,
                    check=True,
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
            creationflags=CREATE_NO_WINDOW,
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


def get_scancode_from_key(key: str):
    key_lower = key.lower()
    code = SCANCODES.get(key_lower)
    if code is None:
        canonical = SPECIAL_MAP.get(key_lower)
        if canonical:
            code = SCANCODES.get(canonical)
    return code


def get_key_from_scancode(scancode: int):
    return SCANCODES_INV.get(scancode)


def dp_to_px(dp: float, dpi: int = BASELINE_DPI) -> int:
    """Converts density-independent pixels (DP) to device pixels (PX)."""
    return round(dp * (dpi / BASELINE_DPI))


def px_to_dp(px: float, dpi: int = BASELINE_DPI) -> float:
    """Converts device pixels (PX) to density-independent pixels (DP)."""
    return px / (dpi / BASELINE_DPI)


def calculate_rect(
    x1: float, y1: float, x2: float, y2: float
) -> tuple[float, float, float, float, float, float]:
    xs = [x1, x2]
    ys = [y1, y2]
    cx = float(round(sum(xs) / 2))
    cy = float(round(sum(ys) / 2))

    return (cx, cy, min(xs), min(ys), max(xs), max(ys))


def scale_coord(base: float, val: float | None = None) -> float:
    if val is None:
        return 0.0
    return val * base if val <= 1.0 else val


def clamp(value, lo, hi):
    return max(lo, min(hi, value))


def make_copy_name(name: str) -> str:
    matches = list(COPY_RE.finditer(name))

    if not matches:
        return f"{name} - Copy"

    match = matches[-1]
    number = int(match.group(1) or 1) + 1

    return name[: match.start()] + f"- Copy ({number})" + name[match.end() :]


def prune_directory(
    target_dir: Path, max_age_days: int = 60, max_count: int = 100
) -> None:
    """
    Prunes files in a specific directory based on age and maximum file count.
    Default: A maximum age of 60 days (2 months) and a maximum count of 100.
    """
    if not target_dir.exists():
        return

    current_time = time.time()
    max_age_seconds = max_age_days * 86400

    # 1. Prune by age (older than max_age_days)
    for file_path in target_dir.glob("*"):
        if file_path.is_file():
            try:
                file_age = current_time - file_path.stat().st_mtime
                if file_age > max_age_seconds:
                    file_path.unlink(missing_ok=True)
            except Exception:
                pass  # Skip locked or inaccessible files

    # 2. Prune by count (keep only the newest max_count files)
    files: list[tuple[float, Path]] = []
    for f in target_dir.glob("*"):
        try:
            if f.is_file():
                files.append((f.stat().st_mtime, f))
        except OSError:
            continue  # deleted or locked by another process
    files.sort(key=lambda item: item[0])

    while len(files) > max_count:
        _, oldest_file = files.pop(0)
        try:
            oldest_file.unlink(missing_ok=True)
        except Exception:
            pass


def bresenham(
    x0: int,
    y0: int,
    x1: int,
    y1: int,
    width0: int = 1,
    height0: int = 1,
    width1: int | None = None,
    height1: int | None = None,
):
    if width1 is None:
        width1 = width0
    if height1 is None:
        height1 = height0

    dx = abs(x1 - x0)
    dy = abs(y1 - y0)

    sx = 1 if x0 < x1 else -1
    sy = 1 if y0 < y1 else -1

    error = dx - dy
    steps = max(dx, dy)
    k = 0

    while True:
        if steps:
            w = width0 + (width1 - width0) * k // steps
            h = height0 + (height1 - height0) * k // steps
        else:
            w, h = width0, height0

        yield x0 - w // 2, y0 - h // 2, w, h

        if x0 == x1 and y0 == y1:
            break

        e2 = 2 * error

        if e2 > -dy:
            error -= dy
            x0 += sx

        if e2 < dx:
            error += dx
            y0 += sy

        k += 1
