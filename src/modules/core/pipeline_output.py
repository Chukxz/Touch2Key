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
)

if TYPE_CHECKING:
    from modules.platforms.base import AbstractBridge

logger = logging.getLogger("modules.core.pipeline_output")


@dataclass(slots=True)
class BridgeOutputSink(OutputSink):
    """Bridges Semantic stage outputs to the hardware driver Bridge."""

    bridge: AbstractBridge
    # Accumulators for fractional mouse movements to prevent slow-aim pixel loss
    _acc_x: float = field(init=False, default=0.0)
    _acc_y: float = field(init=False, default=0.0)
    _lock: threading.Lock = field(default_factory=threading.Lock)

    def key_down(self, scancode: int) -> None:
        self.bridge.key_down(scancode)

    def key_up(self, scancode: int) -> None:
        self.bridge.key_up(scancode)

    def mouse_down(self, scancode: int) -> None:
        if scancode == M_LEFT:
            self.bridge.left_click_down()
        elif scancode == M_RIGHT:
            self.bridge.right_click_down()
        elif scancode == M_MIDDLE:
            self.bridge.middle_click_down()
        elif scancode == M_BACK:
            self.bridge.button4_down()
        elif scancode == M_FORWARD:
            self.bridge.button5_down()

    def mouse_up(self, scancode: int) -> None:
        if scancode == M_LEFT:
            self.bridge.left_click_up()
        elif scancode == M_RIGHT:
            self.bridge.right_click_up()
        elif scancode == M_MIDDLE:
            self.bridge.middle_click_up()
        elif scancode == M_BACK:
            self.bridge.button4_up()
        elif scancode == M_FORWARD:
            self.bridge.button5_up()

    def mouse_move(self, dx: float, dy: float) -> None:
        """Accumulates fractional deltas from ANY pipeline (WheelMapper, Pointer buttons, etc.)."""
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
