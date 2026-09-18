from typing import ClassVar
from ..base import AbstractMapping

from .ecodes_map import LINUX_KEY_MAP, LINUX_KEY_MAP_INV


class Mapping(AbstractMapping):
    """Linux (evdev/uinput) specific keycode mapping implementation."""

    _MODIFIER_MAP: ClassVar[dict[int, str]] = {
        0: "",
        56: "lalt",
        100: "ralt",
        29: "lctrl",
        97: "rctrl",
        42: "lshift",
        54: "rshift",
    }

    # Generate inverse map once at class load for O(1) lookups
    _MODIFIER_MAP_INV: ClassVar[dict[str, int]] = {
        v: k for k, v in _MODIFIER_MAP.items()
    }

    def get_key_name_from_code(self, key_code: int) -> str:
        """Translates a Linux native keycode to a standard key string."""
        return self._MODIFIER_MAP.get(LINUX_KEY_MAP_INV.get(key_code, 0), "")

    def get_key_code_from_name(self, key_name: str) -> int:
        """Translates a standard key string to a Linux native keycode."""
        return LINUX_KEY_MAP.get(self._MODIFIER_MAP_INV.get(key_name, 0), 0)
