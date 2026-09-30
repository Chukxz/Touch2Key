from __future__ import annotations

import colorsys
import sys
import random
import re
import struct
import subprocess
import time
import threading
import math
from dataclasses import dataclass
from enum import Enum, auto
from pathlib import Path
from typing import TYPE_CHECKING, Callable, Literal, Any

from PySide6.QtCore import QObject, Signal

APP_NAME = "Touch2Key"

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

BASELINE_DPI = 160
BASELINE_WIDTH = 800
BASELINE_HEIGHT = 360
DOWN = "DOWN"
UP = "UP"
PRESSED = "PRESSED"
IDLE = "IDLE"

CIRCLE = "CIRCLE"
RECTANGLE = "RECTANGLE"
BEZEL = "BEZEL"

TOGGLE_VKB = "TOGGLE_VKB"
TOGGLE_MODE = "TOGGLE_MODE"

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

TOP_BEZEL_NAME = "Top Bezel"
BOTTOM_BEZEL_NAME = "Bottom Bezel"
BEZEL_DP_THICKNESS = 25  # ~3.97mm
SPRINT_DISTANCE_CODE = "LEFT_BRACKET"
MOUSE_WHEEL_SIMULATOR_CODE = "RIGHT_BRACKET"

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
DEFAULT_ADB_RATE_CAP = 250
DEFAULT_PPS = 60

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
    "ON_CONFIG_RELOAD",
    "ON_LAYOUT_RELOAD",
    "ON_WASD_BLOCK",
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

COPY_RE = re.compile(r"- Copy(?:\((\d+)\)|(?=\s|$))")

_ROUTE_SRC_RE = re.compile(
    r"\bdev\s+(?:wlan\d+|s?wlan\d+|ap\d+)\b.*?\bsrc\s+(\d+\.\d+\.\d+\.\d+)"
)

_PHYSICAL_SIZE_RE = re.compile(r"Physical size:\s*(\d+)x(\d+)")


class InvalidFieldError(ValueError):
    """Raised when update()/create()/create_pipeline_from_zone()

    receives a field name outside ALLOWED_FIELDS."""


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
            "ON_DEVICES_CHANGE": [],
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
            callbacks = self.callback_registry.get(event.action, []).copy()

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


# ---------------------------------------------------------------------------
# Engine <-> GUI process IPC protocol
# ---------------------------------------------------------------------------
# Every message sent over the engine<->GUI multiprocessing.Pipe is one
# `send_bytes`/`recv_bytes` frame: 1 opcode byte, then a fixed-width struct
# payload (if the opcode has one), then a trailing UTF-8 string (if the
# opcode carries one). Pipe framing gives each call its own boundary, so a
# trailing string needs no length prefix of its own -- it's just "whatever's
# left after the fixed part".
#
# GUI -> engine process (commands)
IPC_CMD_START = 0x01
IPC_CMD_STOP = 0x02
IPC_CMD_CONFIG_RELOAD = 0x03
IPC_CMD_LAYOUT_RELOAD = 0x04
IPC_CMD_DEVICES_CHANGE = 0x05
IPC_CMD_TARGET_WINDOW_CHANGE = 0x86

# Engine process -> GUI (lifecycle + forwarded dispatcher events)
IPC_EVT_STARTED = 0x80
IPC_EVT_STOPPED = 0x81
IPC_EVT_ERROR = 0x82

# All little-endian, no implicit padding ("<" prefix). Optional ints use -1
# as the "None" sentinel; optional strings use "" as the "None" sentinel.
PACK_IPC_START_STRUCT = struct.Struct("<Biff?ff")
PACK_IPC_DEVICES_CHANGE_STRUCT = struct.Struct("<Bii")
PACK_IPC_MENU_MODE_TOGGLE_STRUCT = struct.Struct("<B?")
PACK_IPC_TARGET_WINDOW_CHANGE_STRUCT = struct.Struct("<Bi")

_IPC_NONE_INT = -1
_IPC_STR_SEP = "\x1f"  # unit separator


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
    rate_cap: float,
    pps: float,
    toggle_key: str | None,
    sprint_key: str | None,
    typematic_enabled: bool,
    typematic_delay_ms: float,
    typematic_rate_hz: float,
    typematic_excluded_keys: str | None,
) -> bytes:
    header = PACK_IPC_START_STRUCT.pack(
        IPC_CMD_START,
        _pack_opt_int(window_id),
        rate_cap,
        pps,
        typematic_enabled,
        typematic_delay_ms,
        typematic_rate_hz,
    )
    return header + _pack_trailing_strings(
        toggle_key, sprint_key, typematic_excluded_keys
    )


def unpack_ipc_start_cmd(payload: bytes) -> dict[str, Any]:
    fixed_size = PACK_IPC_START_STRUCT.size
    (
        _,
        window_id,
        rate_cap,
        pps,
        typematic_enabled,
        typematic_delay_ms,
        typematic_rate_hz,
    ) = PACK_IPC_START_STRUCT.unpack_from(payload, 0)
    toggle_key, sprint_key, typematic_excluded_keys = _unpack_trailing_strings(
        payload[fixed_size:], 3
    )
    return {
        "window_id": _unpack_opt_int(window_id),
        "rate_cap": rate_cap,
        "pps": pps,
        "typematic_enabled": typematic_enabled,
        "typematic_delay_ms": typematic_delay_ms,
        "typematic_rate_hz": typematic_rate_hz,
        "toggle_key": toggle_key,
        "sprint_key": sprint_key,
        "typematic_excluded_keys": typematic_excluded_keys,
    }


def pack_ipc_stop_cmd() -> bytes:
    return bytes([IPC_CMD_STOP])


def pack_ipc_config_reload_cmd() -> bytes:
    return bytes([IPC_CMD_CONFIG_RELOAD])


def pack_ipc_layout_reload_cmd() -> bytes:
    return bytes([IPC_CMD_LAYOUT_RELOAD])


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
    """Engine-process-side dispatcher.

    Drop-in replacement for MapperEventDispatcher: everything registered
    in-process (AppConfig/LayoutLoader/Mapper callbacks) still fires exactly
    as before. Incoming command bytes from the GUI are turned into local
    dispatches so existing in-process callbacks (e.g. Engine._on_devices_change)
    fire unchanged regardless of whether the event originated locally or over IPC.
    """

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
        """Decodes one incoming GUI->engine command and dispatches it locally.

        Returns False for IPC_CMD_STOP (caller should stop the engine and its
        reader loop), True for everything else handled.
        """
        opcode = payload[0]
        if opcode == IPC_CMD_STOP:
            return False
        if opcode == IPC_CMD_CONFIG_RELOAD:
            self.dispatch(MapperEvent(action="ON_CONFIG_RELOAD"))
        elif opcode == IPC_CMD_LAYOUT_RELOAD:
            self.dispatch(MapperEvent(action="ON_LAYOUT_RELOAD"))
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
            print(f"[!] Unknown IPC command opcode: {opcode}")
        return True

    def run_command_loop(self) -> None:
        """Blocks, servicing GUI->engine commands until IPC_CMD_STOP or the pipe closes."""
        while True:
            try:
                payload = self.conn.recv_bytes()
            except (EOFError, OSError):
                return
            if not payload or not self.handle_command(payload):
                return


class QtIpcMapperEventDispatcher(QObject):
    """GUI-process-side counterpart to IpcMapperEventDispatcher.

    Wraps the GUI's end of the engine<->GUI Pipe. A background thread reads
    incoming lifecycle/forwarded-dispatcher bytes and re-emits them as Qt
    signals (safe to connect to cross-thread; Qt queues the delivery onto
    whatever thread the receiver lives in). Plain methods send commands
    (start/stop/config reload/layout reload/devices change/windows change) to the engine.
    """

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
                print(f"[!] Unknown IPC event opcode: {opcode}")
        except Exception as exc:
            print(f"[!] Failed to handle IPC event (opcode={opcode}): {exc}")

    def _send(self, payload: bytes) -> None:
        with self._send_lock:
            try:
                self.conn.send_bytes(payload)
            except (BrokenPipeError, OSError) as exc:
                print(f"[!] Failed to send IPC command: {exc}")

    def send_start(
        self,
        window_id: int | None,
        rate_cap: float,
        pps: float,
        toggle_key: str | None,
        sprint_key: str | None,
        typematic_enabled: bool = True,
        typematic_delay_ms: float = 250.0,
        typematic_rate_hz: float = 30.0,
        typematic_excluded_keys: str | None = None,
    ) -> None:
        self._send(
            pack_ipc_start_cmd(
                window_id,
                rate_cap,
                pps,
                toggle_key,
                sprint_key,
                typematic_enabled,
                typematic_delay_ms,
                typematic_rate_hz,
                typematic_excluded_keys,
            )
        )

    def send_stop(self) -> None:
        self._send(pack_ipc_stop_cmd())

    def send_config_reload(self) -> None:
        self._send(pack_ipc_config_reload_cmd())

    def send_layout_reload(self) -> None:
        self._send(pack_ipc_layout_reload_cmd())

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
    out = subprocess.check_output([ADB, "devices"], timeout=10).decode().splitlines()
    real = [
        d.split()[0] for d in out[1:] if "device" in d and not d.startswith("emulator-")
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
        )
        return "device" in res.stdout
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
                [ADB, "-s", device, "shell", "ip", "route"], text=True, timeout=10
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


def make_copy_name(name: str) -> str:
    matches = list(COPY_RE.finditer(name))

    if not matches:
        return f"{name} - Copy"

    match = matches[-1]
    number = int(match.group(1) or 1) + 1

    return name[: match.start()] + f"- Copy({number})" + name[match.end() :]
