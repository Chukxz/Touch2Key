from __future__ import annotations
from typing import TYPE_CHECKING

import threading
from pathlib import Path
import tomlkit
from tomlkit.exceptions import ParseError
import keyboard
from mapper_module.utils import MapperEvent, TOML_PATH, create_default_toml

if TYPE_CHECKING:
    from mapper_module.utils import MapperEventDispatcher


class AppConfig:
    def __init__(self, mapper_event_dispatcher: MapperEventDispatcher):
        self.mapper_event_dispatcher = mapper_event_dispatcher

        # Initialize the lock to protect config_data
        self.config_lock = threading.Lock()

        self.config_data = {}

        # Load immediately
        self._load_config()
        print(f"\n[CONFIG] - Configuration loaded from {TOML_PATH}.")
        print(
            f"\n[CONFIG] - Current Handedness: {self._display_handedness(self.get('system').get('left_handed', False))}"
        )

        # REGISTER HOTKEY
        print("\n[CONFIG] - Press F7 to switch handedness or F9 to only reload config.")
        keyboard.add_hotkey("f7", self._switch_handedness)
        keyboard.add_hotkey("f9", self.reload_config)

    def _load_config(self):
        """Loads TOML data safely. Creates default if missing or unreadable."""
        toml_path = Path(TOML_PATH)
        try:
            if not toml_path.exists():
                print(
                    f"\n[CONFIG] - Config file {TOML_PATH} not found! Creating default..."
                )
                create_default_toml()

            with toml_path.open("rb") as f:
                new_data = tomlkit.load(f)

            with self.config_lock:
                self.config_data = new_data
            return

        except ParseError as e:
            print(f"\n[CONFIG] - Failed to parse TOML: {e}")
            if self._attempt_line_ending_repair(toml_path):
                return
            if self.config_data:
                print("[CONFIG] - Keeping previous in-memory config.")
                return
            print("[CONFIG] - No usable previous config. Resetting to defaults.")
            self._backup_and_reset(toml_path)

        except Exception as e:
            print(f"[CONFIG] - Error loading config: {e}")
            if not self.config_data:
                self._backup_and_reset(toml_path)

    def _attempt_line_ending_repair(self, toml_path: Path) -> bool:
        """Most 'control characters in comments' errors come from stray \\r
        bytes (CRLF resave, or a partial write). Normalize to LF and retry
        once before giving up on the file."""
        try:
            raw = toml_path.read_bytes()
            normalized = raw.replace(b"\r\n", b"\n").replace(b"\r", b"\n")
            if normalized == raw:
                return False  # nothing to fix — different root cause

            new_data = tomlkit.loads(normalized.decode("utf-8"))
            with self.config_lock:
                self.config_data = new_data
            toml_path.write_bytes(normalized)  # persist the fix
            print("[CONFIG] - Repaired stray line-ending characters and reloaded.")
            return True
        except Exception as e:
            print(f"[CONFIG] - Auto-repair failed: {e}")
            return False

    def _backup_and_reset(self, toml_path: Path):
        try:
            if toml_path.exists():
                backup_path = toml_path.with_suffix(toml_path.suffix + ".bak")
                toml_path.replace(backup_path)
                print(f"[CONFIG] - Corrupt config backed up to {backup_path}.")
        except Exception as e:
            print(f"[CONFIG] - Could not back up corrupt config: {e}")

        create_default_toml()
        try:
            with toml_path.open("rb") as f:
                new_data = tomlkit.load(f)
            with self.config_lock:
                self.config_data = new_data
        except Exception as e:
            print(f"[CONFIG] - Failed to load freshly created default config: {e}")

    def reload_config(self):
        """Reloads from disk and notifies listeners."""
        print(f"\n[CONFIG] - Reloading TOML configuration from {TOML_PATH}...")
        self._load_config()

        # Dispatch event so other modules know config changed
        self.mapper_event_dispatcher.dispatch(MapperEvent(action="ON_CONFIG_RELOAD"))

    def _display_handedness(self, handedness):
        return "Left-Handed" if handedness else "Right-Handed"

    def _switch_handedness(self):
        """Toggles left-handed mode in config and saves."""

        with self.config_lock:
            config_system = self.get("system")
            current_value = config_system.get("left_handed", False)
            new_value = not current_value
            config_system["left_handed"] = new_value

            self.config_data["system"] = config_system

        # Save back to disk
        try:
            with open(TOML_PATH, "w", encoding="utf-8", newline="") as f:
                tomlkit.dump(self.config_data, f)
            print(
                f"\n[CONFIG] - Handedness switched to {self._display_handedness(new_value)}. Config saved."
            )
        except Exception as e:
            print(f"\n[CONFIG] - Failed to save config: {e}")

        # Notify listeners of config change
        self.mapper_event_dispatcher.dispatch(MapperEvent(action="ON_CONFIG_RELOAD"))

    def get(self, key, default=None):
        return self.config_data.get(key, default if default is not None else {})
