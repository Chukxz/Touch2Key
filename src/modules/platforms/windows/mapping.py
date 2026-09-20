from __future__ import annotations

from typing import ClassVar
from ..base import AbstractMapping
from modules.utils import SCANCODES, SCANCODES_INV, SPECIAL_MAP, SPECIAL_MAP_INV


class Mapping(AbstractMapping):
    """Windows-specific keycode mapping implementation for Qt/Matplotlib native scancodes."""

    _MODIFIER_MAP: ClassVar[dict[int, str]] = {
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

    def get_key_name_from_code(self, key_code: int) -> str | None:
        """Translates a Windows native scancode (from Qt or Matplotlib) to a canonical key token."""
        if not key_code:
            return ""

        # 1. Direct match in dedicated modifier map
        if key_code in self._MODIFIER_MAP:
            return self._MODIFIER_MAP[key_code]

        # 2. Match exact code in SCANCODES_INV
        name = SCANCODES_INV.get(key_code)
        if name:
            return SPECIAL_MAP_INV.get(name, name).lower()

        # 3. Match masked lower byte for standard 1-byte keys
        name_stripped = SCANCODES_INV.get(key_code & 0xFF)
        if name_stripped:
            return SPECIAL_MAP_INV.get(name_stripped, name_stripped).lower()

        # 4. Check if key_code is an extended prefix (0xE0XX)
        if (key_code & 0xFF00) == 0xE000:
            ext_name = SCANCODES_INV.get(key_code)
            if ext_name:
                return SPECIAL_MAP_INV.get(ext_name, ext_name).lower()

        return None

    def get_key_code_from_name(self, key_name: str) -> int | None:
        """Translates a standard key string token to a Windows native scancode."""
        clean = key_name.strip().lower()
        if clean in self._MODIFIER_MAP_INV:
            return self._MODIFIER_MAP_INV[clean]

        code = SCANCODES.get(clean)
        if code is not None:
            return code

        canonical = SPECIAL_MAP.get(clean)
        if canonical and canonical in SCANCODES:
            return SCANCODES[canonical]

        return None