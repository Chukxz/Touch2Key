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
    PACK_REL_STRUCT_SIZE,
    clamp,
)

if TYPE_CHECKING:
    from modules.platforms.base import AbstractBridge

logger = logging.getLogger("modules.core.pipeline_output")


@dataclass(slots=True)
class BridgeOutputSink(OutputSink):
    """Bridges Semantic stage outputs to the hardware driver Bridge."""

    bridge: AbstractBridge
    
    # Callback into the Mapper to retrieve: (dev_w, dev_h, win_info, screen_w, screen_h)
    callback: Callable[[], tuple[float, float, dict | None, int, int]] | None = None 
    
    # Accumulators for fractional mouse movements to prevent slow-aim pixel loss
    _acc_x: float = field(init=False, default=0.0)
    _acc_y: float = field(init=False, default=0.0)
    _lock: threading.Lock = field(default_factory=threading.Lock)

    def set_viewport_callback(
        self, 
        callback: Callable[[], tuple[float, float, dict | None, int, int]] | None
    ) -> None:
        """Dynamically binds or unbinds the viewport info provider from the Mapper."""
        self.callback = callback

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

    def mouse_move_abs(self, dev_x: float, dev_y: float) -> None:
        """Converts oriented device pixels into PC target window physical pixels using the callback."""
        if self.callback is None:
            # Fallback if the engine hasn't wired the callback yet
            self.bridge.mouse_move_abs(int(round(dev_x)), int(round(dev_y)))
            return

        # Query the mapper for the current device dimensions and window offsets
        dev_w, dev_h, win, screen_w, screen_h = self.callback()
        
        dev_w = max(1.0, float(dev_w))
        dev_h = max(1.0, float(dev_h))

        norm_x = clamp(dev_x / dev_w, 0.0, 1.0)
        norm_y = clamp(dev_y / dev_h, 0.0, 1.0)

        # Apply offsets if the target window is valid and visible
        if win and win["width"] > 0 and win["height"] > 0:
            target_x = win["left"] + norm_x * win["width"]
            target_y = win["top"] + norm_y * win["height"]
        else:
            target_x = norm_x * screen_w
            target_y = norm_y * screen_h

        self.bridge.mouse_move_abs(int(round(target_x)), int(round(target_y)))

    def mouse_move(self, dx: float, dy: float) -> None:
        """Accumulates fractional deltas from ANY pipeline (WheelMapper, Pointer buttons, etc.)."""
        with self._lock:
            self._acc_x += dx
            self._acc_y += dy

    def flush_mouse_move(self) -> None:
        """Dispatches aggregated whole pixels to the OS and retains the fractional remainder."""
        with self._lock:
            idx = int(clamp(round(self._acc_x), -PACK_REL_STRUCT_SIZE, PACK_REL_STRUCT_SIZE))
            idy = int(clamp(round(self._acc_y), -PACK_REL_STRUCT_SIZE, PACK_REL_STRUCT_SIZE))

            if idx != 0 or idy != 0:
                self.bridge.mouse_move_rel(idx, idy)
                self._acc_x -= idx
                self._acc_y -= idy

    def reset_mouse_accumulators(self) -> None:
        """Called when no fingers are actively moving the cursor."""
        with self._lock:
            self._acc_x = 0.0
            self._acc_y = 0.0
