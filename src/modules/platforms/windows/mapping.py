from typing import ClassVar
from ..base import AbstractMapping


class Mapping(AbstractMapping):
    """Windows-specific scancode mapping implementation."""

    _MODIFIER_MAP: ClassVar[dict[int, str]] = {
        0: "",
        56: "lalt",
        312: "ralt",
        29: "lctrl",
        285: "rctrl",
        42: "lshift",
        54: "rshift",
    }

    # Generate inverse map once at class load for O(1) lookups
    _MODIFIER_MAP_INV: ClassVar[dict[str, int]] = {
        v: k for k, v in _MODIFIER_MAP.items()
    }

    def get_key_name_from_code(self, key_code: int) -> str:
        """Translates a Windows native scancode to a standard key string."""
        return self._MODIFIER_MAP.get(key_code, "")

    def get_key_code_from_name(self, key_name: str) -> int:
        """Translates a standard key string to a Windows native scancode."""
        return self._MODIFIER_MAP_INV.get(key_name, 0)
