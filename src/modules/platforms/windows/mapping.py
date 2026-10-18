from __future__ import annotations

import ctypes
from typing import ClassVar

from ..base import AbstractMapping
from modules.utils import SCANCODES, SCANCODES_INV, SPECIAL_MAP


class Mapping(AbstractMapping):
    """Windows-specific keycode mapping implementation with comprehensive OS and Qt scancode resolution."""

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

    def _normalize_scancode(self, key_code: int) -> int:
        """Normalizes Qt (0x100 bit flag) and raw Windows extended flags into canonical 0xE000 format."""
        # Qt extended key flag: 0x100 | make_code -> 0xE000 | make_code
        if (key_code & 0x100) and (key_code & 0xFF00) != 0xE000:
            return 0xE000 | (key_code & 0xFF)
        return key_code

    def get_key_name_from_code(self, key_code: int) -> str | None:
        """Translates any Windows scancode to a canonical key token, falling back to Win32 API."""
        if not key_code:
            return None

        norm_code = self._normalize_scancode(key_code)

        # 1. Direct match in dedicated modifier map
        if norm_code in self._MODIFIER_MAP:
            return self._MODIFIER_MAP[norm_code]

        # 2. Exact match in canonical inverted table
        name = SCANCODES_INV.get(norm_code)
        if name:
            return name.lower()

        # 3. Match raw un-normalized code if table stores un-prefixed values
        if key_code != norm_code:
            name = SCANCODES_INV.get(key_code)
            if name:
                return name.lower()

        # 4. Standard 1-byte keys (only if NOT an extended key)
        if (norm_code & 0xFF00) == 0:
            name_stripped = SCANCODES_INV.get(norm_code & 0xFF)
            if name_stripped:
                return name_stripped.lower()

        # 5. Fallback: Query Windows OS API directly (GetKeyNameTextW)
        try:
            # Construct lParam: bit 16-23 is scancode, bit 24 is extended key flag
            lparam = (norm_code & 0xFF) << 16
            if (norm_code & 0xFF00) == 0xE000:
                lparam |= 1 << 24

            buf = ctypes.create_unicode_buffer(64)
            length = ctypes.windll.user32.GetKeyNameTextW(lparam, buf, 64)
            if length > 0:
                raw_os_name = buf.value.strip().lower()
                clean = SPECIAL_MAP.get(raw_os_name, raw_os_name)
                if clean is not None:
                    return clean.lower()

        except Exception:
            pass

        # 6. Final guarantee: Return hexadecimal token so no scancode is ever lost
        return f"0x{norm_code:x}"

    def get_key_code_from_name(self, key_name: str) -> int | None:
        """Translates a key string token or hex string to a Windows native scancode."""
        clean = key_name.strip().lower()

        if clean in self._MODIFIER_MAP_INV:
            return self._MODIFIER_MAP_INV[clean]

        code = SCANCODES.get(clean)
        if code is not None:
            return code

        canonical = SPECIAL_MAP.get(clean)
        if canonical and canonical in SCANCODES:
            return SCANCODES[canonical]

        # Parse raw hex strings like '0x1e' or '0xe01d'
        if clean.startswith("0x"):
            try:
                return int(clean, 16)
            except ValueError:
                pass

        # Fallback: Query Windows OS API via MapVirtualKeyW
        try:
            # Map first character to virtual key, then virtual key to scan code
            if len(clean) == 1:
                vk = ctypes.windll.user32.VkKeyScanW(ord(clean)) & 0xFF
                if vk > 0:
                    vsc = ctypes.windll.user32.MapVirtualKeyW(vk, 0)  # MAPVK_VK_TO_VSC
                    if vsc > 0:
                        return vsc
        except Exception:
            pass

        return None
