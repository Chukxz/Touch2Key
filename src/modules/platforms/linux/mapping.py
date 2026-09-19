from __future__ import annotations

from typing import ClassVar
from ..base import AbstractMapping
from .ecodes_map import LINUX_KEY_MAP, LINUX_KEY_MAP_INV
from modules.utils import SCANCODES, SCANCODES_INV, SPECIAL_MAP, SPECIAL_MAP_INV


class Mapping(AbstractMapping):
    """Linux keycode mapping implementation for Qt/Matplotlib native scancodes."""

    _MODIFIER_MAP: ClassVar[dict[int, str]] = {
        0: "",
        0x38: "lalt",
        0xE038: "ralt",
        0x1D: "lctrl",
        0xE01D: "rctrl",
        0x2A: "lshift",
        0x36: "rshift",
    }

    _MODIFIER_MAP_INV: ClassVar[dict[str, int]] = {
        v: k for k, v in _MODIFIER_MAP.items() if v
    }

    def get_key_name_from_code(self, key_code: int) -> str:
        """Translates a Linux native scancode (from Qt or Matplotlib) to a human-readable key token.

        Handles the standard Linux X11/Qt keycode offset (X11 scancode = evdev_code + 8).
        """
        if not key_code:
            return ""

        # Helper to lookup evdev scancode -> Windows equivalent -> canonical token string
        def _resolve_evdev(code: int) -> str:
            win_scancode = LINUX_KEY_MAP_INV.get(code)
            if win_scancode is None:
                return ""

            if win_scancode in self._MODIFIER_MAP:
                return self._MODIFIER_MAP[win_scancode]

            name = SCANCODES_INV.get(win_scancode)
            if name:
                return SPECIAL_MAP_INV.get(name, name).lower()
            return ""

        # 1. Try as a raw evdev code
        token = _resolve_evdev(key_code)
        if token:
            return token

        # 2. Try with X11 offset compensation (Qt/Matplotlib on X11 typically adds 8 to evdev code)
        if key_code > 8:
            token = _resolve_evdev(key_code - 8)
            if token:
                return token

        return ""

    def get_key_code_from_name(self, key_name: str) -> int:
        """Translates a key string token to an evdev Linux keycode."""
        clean = key_name.strip().lower()

        # Check modifier mapping
        win_scancode = self._MODIFIER_MAP_INV.get(clean)
        if win_scancode is None:
            # Check standard scancodes or canonical aliases
            win_scancode = SCANCODES.get(clean)
            if win_scancode is None:
                canonical = SPECIAL_MAP.get(clean)
                if canonical:
                    win_scancode = SCANCODES.get(canonical)

        if win_scancode is not None:
            return LINUX_KEY_MAP.get(win_scancode, 0)

        return 0