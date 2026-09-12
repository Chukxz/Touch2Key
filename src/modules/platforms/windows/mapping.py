from typing import ClassVar
from ..base import AbstractMapping


class Mapping(AbstractMapping):
    """Windows-specific scancode mapping implementation."""

    _MODIFIER_MAP: ClassVar[dict[int, str]] = {
        56: "lalt",
        312: "ralt",
        29: "lctrl",
        285: "rctrl",
        42: "lshift",
        54: "rshift",
    }

    # Generate reverse map once at class load for O(1) lookups
    _REVERSE_MAP: ClassVar[dict[str, int]] = {v: k for k, v in _MODIFIER_MAP.items()}

    def get_key_from_scancode(self, scancode: int) -> str:
        """Translates a Windows native scancode to a standard key string."""
        return self._MODIFIER_MAP.get(scancode, "")

    def get_scancode_from_key(self, key_name: str) -> int:
        """Translates a standard key string to a Windows native scancode."""
        return self._REVERSE_MAP.get(key_name, 0)
