from __future__ import annotations

from typing import ClassVar
from ..base import AbstractMapping
from .ecodes_map import LINUX_KEY_MAP, LINUX_KEY_MAP_INV
from modules.utils import SCANCODES, SCANCODES_INV, SPECIAL_MAP


class Mapping(AbstractMapping):
    """Linux keycode mapping implementation for Qt and Matplotlib native scancodes."""

    _MODIFIER_MAP: ClassVar[dict[int, str]] = {
        0x2A: "lshift",
        0x36: "rshift",
        0x1D: "lctrl",
        0xE01D: "rctrl",
        0x38: "lalt",
        0xE038: "ralt",
        0xE05B: "lwin",
        0xE05C: "rwin",
    }

    _MODIFIER_MAP_INV: ClassVar[dict[str, int]] = {
        v: k for k, v in _MODIFIER_MAP.items()
    }
    # Common desktop environment aliases for the Super/Meta key
    _MODIFIER_MAP_INV.update(
        {
            "win": 0xE05B,
            "super": 0xE05B,
            "meta": 0xE05B,
        }
    )

    def get_key_name_from_code(self, key_code: int) -> str | None:
        """Translates a Linux native scancode (from Qt or Matplotlib) to a canonical key token.

        Handles the standard Linux X11/XKB offset (X11 scancode = evdev_code + 8).
        """
        if not key_code:
            return None

        def _resolve_evdev(code: int) -> str | None:
            win_scancode = LINUX_KEY_MAP_INV.get(code)
            if win_scancode is None:
                return None

            if win_scancode in self._MODIFIER_MAP:
                return self._MODIFIER_MAP[win_scancode]

            name = SCANCODES_INV.get(win_scancode)
            if name:
                return name.lower()
            return None

        # 1. On X11 and Wayland (xkbcommon), Qt nativeScanCode is ALWAYS evdev + 8.
        # This MUST be evaluated first to avoid matching shifted evdev codes.
        if key_code > 8:
            token = _resolve_evdev(key_code - 8)
            if token:
                return token

        # 2. Fallback: try raw evdev code (console / uinput without XKB offset)
        token = _resolve_evdev(key_code)
        if token:
            return token

        # 3. Retain raw hex representation so unknown scancodes are never silently lost
        return f"0x{key_code:x}"

    def get_key_code_from_name(self, key_name: str) -> int | None:
        """Translates a key string token, alias, or hex string to an evdev Linux keycode."""
        clean = key_name.strip().lower()

        # Parse raw hex strings like '0x1e' or '0x2a'
        if clean.startswith("0x"):
            try:
                win_scancode = int(clean, 16)
                code = LINUX_KEY_MAP.get(win_scancode)
                if code and code > 0:
                    return code
            except ValueError:
                pass

        # Check dedicated modifier map and Super/Meta aliases
        win_scancode = self._MODIFIER_MAP_INV.get(clean)
        if win_scancode is None:
            win_scancode = SCANCODES.get(clean)
            if win_scancode is None:
                canonical = SPECIAL_MAP.get(clean)
                if canonical:
                    win_scancode = SCANCODES.get(canonical)

        if win_scancode is not None:
            code = LINUX_KEY_MAP.get(win_scancode)
            if code and code > 0:
                return code

        return None
