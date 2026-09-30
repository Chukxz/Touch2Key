from __future__ import annotations

import threading
from typing import TYPE_CHECKING, Callable
from dataclasses import dataclass, field
from modules.core.pipeline import OutputSink
from modules.utils import SCANCODES

if TYPE_CHECKING:
    from modules.platforms.base import AbstractBridge


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

    def key_down(self, key: str) -> None:
        scancode = self._resolve_scancode(key)
        if scancode is not None:
            self.bridge.key_down(scancode)

    def key_up(self, key: str) -> None:
        scancode = self._resolve_scancode(key)
        if scancode is not None:
            self.bridge.key_up(scancode)

    def mouse_down(self, button: str) -> None:
        b = button.lower()
        if b in ("mouse_left", "mouse1", "left"):
            self.bridge.left_click_down()
        elif b in ("mouse_right", "mouse2", "right"):
            self.bridge.right_click_down()
        elif b in ("mouse_middle", "mouse3", "middle"):
            self.bridge.middle_click_down()

    def mouse_up(self, button: str) -> None:
        b = button.lower()
        if b in ("mouse_left", "mouse1", "left"):
            self.bridge.left_click_up()
        elif b in ("mouse_right", "mouse2", "right"):
            self.bridge.right_click_up()
        elif b in ("mouse_middle", "mouse3", "middle"):
            self.bridge.middle_click_up()

    def mouse_move(self, dx: float, dy: float) -> None:
        """Accumulates fractional deltas from ANY pipeline (MouseMapper, Pointer buttons, etc.)"""
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
                # Subtract the dispatched whole pixels, keeping the remainder
                self._acc_x -= idx
                self._acc_y -= idy
                
    def reset_mouse_accumulators(self) -> None:
        """Called when no fingers are actively moving the cursor."""
        with self._lock:
            self._acc_x = 0.0
            self._acc_y = 0.0

    @staticmethod
    def _resolve_scancode(key: str) -> int | None:
        if isinstance(key, int):
            return key
        if key in SCANCODES:
            return SCANCODES[key]
        try:
            return int(key, 16) if str(key).startswith("0x") else int(key)
        except (ValueError, TypeError):
            return None
