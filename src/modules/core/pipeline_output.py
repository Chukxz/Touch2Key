from __future__ import annotations

import logging
import threading
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Callable

from modules.core.pipeline import OutputSink
from modules.utils import (
    M_BACK,
    M_FORWARD,
    M_LEFT,
    M_MIDDLE,
    M_RIGHT,
    SCANCODES,
    get_scancode_from_key,
)

if TYPE_CHECKING:
    from modules.platforms.base import AbstractBridge

logger = logging.getLogger("modules.core.pipeline_output")


@dataclass(slots=True)
class BridgeOutputSink(OutputSink):
    """Bridges Semantic stage outputs to the hardware driver Bridge."""

    bridge: AbstractBridge
    toggle_mode: Callable[[], None] | None = None
    toggle_vkb: Callable[[], None] | None = None

    # Accumulators for fractional mouse movements to prevent slow-aim pixel loss
    _acc_x: float = field(init=False, default=0.0)
    _acc_y: float = field(init=False, default=0.0)
    _lock: threading.Lock = field(default_factory=threading.Lock)

    def toggle_menu_mode(self) -> None:
        """Invokes Engine.toggle_mode directly."""
        if self.toggle_mode is not None:
            self.toggle_mode()

    def toggle_virtual_keyboard(self) -> None:
        """Invokes Engine.toggle_virtual_keyboard directly."""
        if self.toggle_vkb is not None:
            self.toggle_vkb()

    def key_down(self, key: str | int) -> None:
        scancode = self._resolve_scancode(key)
        if scancode is not None:
            self.bridge.key_down(scancode)
        else:
            logger.warning("Failed to resolve scancode for key_down: '%s'", key)

    def key_up(self, key: str | int) -> None:
        scancode = self._resolve_scancode(key)
        if scancode is not None:
            self.bridge.key_up(scancode)
        else:
            logger.warning("Failed to resolve scancode for key_up: '%s'", key)

    def mouse_down(self, button: str | int) -> None:
        scancode = self._resolve_scancode(button)
        b = str(button).lower().strip()

        if scancode == M_LEFT or b in ("mouse_left", "mouse1", "left", "m1", "left_click"):
            self.bridge.left_click_down()
        elif scancode == M_RIGHT or b in ("mouse_right", "mouse2", "right", "m2", "right_click"):
            self.bridge.right_click_down()
        elif scancode == M_MIDDLE or b in ("mouse_middle", "mouse3", "middle", "m3", "middle_click"):
            self.bridge.middle_click_down()
        elif scancode == M_BACK or b in (
            "mouse_back",
            "mouse4",
            "m4",
            "back",
            "m_back",
            "back_click",
            "button4",
            "button_4",
        ):
            self.bridge.button4_down()
        elif scancode == M_FORWARD or b in (
            "mouse_forward",
            "mouse5",
            "m5",
            "forward",
            "m_forward",
            "forward_click",
            "button5",
            "button_5",
        ):
            self.bridge.button5_down()
        else:
            logger.warning("Unrecognized mouse button in mouse_down: '%s'", button)

    def mouse_up(self, button: str | int) -> None:
        scancode = self._resolve_scancode(button)
        b = str(button).lower().strip()

        if scancode == M_LEFT or b in ("mouse_left", "mouse1", "left", "m1", "left_click"):
            self.bridge.left_click_up()
        elif scancode == M_RIGHT or b in ("mouse_right", "mouse2", "right", "m2", "right_click"):
            self.bridge.right_click_up()
        elif scancode == M_MIDDLE or b in ("mouse_middle", "mouse3", "middle", "m3", "middle_click"):
            self.bridge.middle_click_up()
        elif scancode == M_BACK or b in (
            "mouse_back",
            "mouse4",
            "m4",
            "back",
            "m_back",
            "back_click",
            "button4",
            "button_4",
        ):
            self.bridge.button4_up()
        elif scancode == M_FORWARD or b in (
            "mouse_forward",
            "mouse5",
            "m5",
            "forward",
            "m_forward",
            "forward_click",
            "button5",
            "button_5",
        ):
            self.bridge.button5_up()
        else:
            logger.warning("Unrecognized mouse button in mouse_up: '%s'", button)

    def mouse_move(self, dx: float, dy: float) -> None:
        """Accumulates fractional deltas from ANY pipeline (MouseMapper, Pointer buttons, etc.)."""
        with self._lock:
            self._acc_x += dx
            self._acc_y += dy

    def flush_mouse_move(self) -> None:
        """Dispatches aggregated whole pixels to the OS and retains the fractional remainder."""
        with self._lock:
            idx = int(round(self._acc_x))
            idy = int(round(self._acc_y))

            if idx != 0 or idy != 0:
                self.bridge.mouse_move_rel(idx, idy)
                self._acc_x -= idx
                self._acc_y -= idy

    def reset_mouse_accumulators(self) -> None:
        """Called when no fingers are actively moving the cursor."""
        with self._lock:
            self._acc_x = 0.0
            self._acc_y = 0.0

    @staticmethod
    def _resolve_scancode(key: str | int) -> int | None:
        if isinstance(key, int):
            return key
        if not key:
            return None

        key_str = str(key).strip()

        # 1. Explicit hex prefix (e.g., "0x1E", "0x9900")
        if key_str.startswith(("0x", "0X")):
            try:
                return int(key_str, 16)
            except ValueError:
                return None

        # 2. Canonical token and named key resolution via utility helper
        code = get_scancode_from_key(key_str)
        if code is not None:
            return code

        # 3. Direct dictionary match with casing fallbacks
        if key_str in SCANCODES:
            return SCANCODES[key_str]
        if key_str.upper() in SCANCODES:
            return SCANCODES[key_str.upper()]
        if key_str.lower() in SCANCODES:
            return SCANCODES[key_str.lower()]

        # 4. Pure decimal integer string (e.g., "30")
        if key_str.isdigit():
            try:
                return int(key_str)
            except ValueError:
                pass

        # 5. Bare multi-character hex string without prefix (e.g., "9904")
        if len(key_str) > 1:
            try:
                return int(key_str, 16)
            except ValueError:
                pass

        return None
