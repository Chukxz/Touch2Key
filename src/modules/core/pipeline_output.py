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
    """Bridges Semantic stage outputs to the hardware driver Bridge.

    Keys and mouse buttons are reference-counted per scancode. Several
    pipelines can hold the same scancode at once (two zones mapped to the same
    key, a joystick direction plus a button, sprint plus a sprint button). The
    bridge sees a DOWN only when the first holder arrives and an UP only when
    the last holder lets go, so one holder releasing never drops another's key.

    Only sink callers are counted (pipelines and the menu-mode cursor click).
    The virtual keyboard and the toggle-hotkey macro talk to the bridge
    directly and are intentionally outside this accounting.
    """

    bridge: AbstractBridge

    # Callback into the Mapper to retrieve: (dev_w, dev_h, win_info, screen_x, screen_y, screen_w, screen_h)
    callback: (
        Callable[[], tuple[float, float, dict[str, int] | None, int, int, int, int]]
        | None
    ) = None

    # Accumulators for fractional mouse movements to prevent slow-aim pixel loss
    _acc_x: float = field(init=False, default=0.0)
    _acc_y: float = field(init=False, default=0.0)
    _lock: threading.Lock = field(default_factory=threading.Lock)

    # Active holds per scancode. A scancode is present only while count >= 1.
    _key_refs: dict[int, int] = field(init=False, default_factory=dict)
    _mouse_refs: dict[int, int] = field(init=False, default_factory=dict)
    _refs_lock: threading.Lock = field(default_factory=threading.Lock)

    def set_viewport_callback(
        self,
        callback: (
            Callable[[], tuple[float, float, dict[str, int] | None, int, int, int, int]]
            | None
        ),
    ) -> None:
        """Dynamically binds or unbinds the viewport info provider from the Mapper."""
        self.callback = callback

    # ------------------------------------------------------------------
    # Keys (reference counted)
    # ------------------------------------------------------------------
    def key_down(self, scancode: int) -> None:
        with self._refs_lock:
            count = self._key_refs.get(scancode, 0)

            # Send first, count after: if the bridge raises, no hold is
            # recorded for a key that never went down.
            if count == 0:
                self.bridge.key_down(scancode)

            self._key_refs[scancode] = count + 1

    def key_up(self, scancode: int) -> None:
        with self._refs_lock:
            count = self._key_refs.get(scancode, 0)

            if count <= 0:
                # Nothing routed through the sink is holding this key.
                return

            if count > 1:
                self._key_refs[scancode] = count - 1
                return

            # Last holder: forget the hold first so a bridge error cannot
            # leave a permanent count behind.
            del self._key_refs[scancode]
            self.bridge.key_up(scancode)

    # ------------------------------------------------------------------
    # Mouse buttons (reference counted)
    # ------------------------------------------------------------------
    def _mouse_action(self, scancode: int, down: bool) -> Callable[[], None] | None:
        bridge = self.bridge

        if scancode == M_LEFT:
            return bridge.left_click_down if down else bridge.left_click_up
        if scancode == M_RIGHT:
            return bridge.right_click_down if down else bridge.right_click_up
        if scancode == M_MIDDLE:
            return bridge.middle_click_down if down else bridge.middle_click_up
        if scancode == M_BACK:
            return bridge.button4_down if down else bridge.button4_up
        if scancode == M_FORWARD:
            return bridge.button5_down if down else bridge.button5_up

        return None

    def mouse_down(self, scancode: int) -> None:
        action = self._mouse_action(scancode, True)
        if action is None:
            return

        with self._refs_lock:
            count = self._mouse_refs.get(scancode, 0)

            if count == 0:
                action()

            self._mouse_refs[scancode] = count + 1

    def mouse_up(self, scancode: int) -> None:
        action = self._mouse_action(scancode, False)
        if action is None:
            return

        with self._refs_lock:
            count = self._mouse_refs.get(scancode, 0)

            if count <= 0:
                return

            if count > 1:
                self._mouse_refs[scancode] = count - 1
                return

            del self._mouse_refs[scancode]
            action()

    def release_all_held(self) -> int:
        """Release every key and button the sink still counts as held.

        A safety net for state boundaries. After every pipeline has reset, all
        counts are normally zero and this does nothing. A non-zero result means
        some holder never sent its release (for example a lost touch UP), and
        the leaked hold is dropped here so it cannot outlive the boundary.
        Returns the number of scancodes released.
        """
        released = 0

        with self._refs_lock:
            keys = list(self._key_refs)
            buttons = list(self._mouse_refs)
            self._key_refs.clear()
            self._mouse_refs.clear()

            for scancode in keys:
                try:
                    self.bridge.key_up(scancode)
                    released += 1
                except Exception:
                    logger.exception("Failed to release leaked key %#x", scancode)

            for scancode in buttons:
                action = self._mouse_action(scancode, False)
                if action is None:
                    continue
                try:
                    action()
                    released += 1
                except Exception:
                    logger.exception("Failed to release leaked button %#x", scancode)

        return released

    # ------------------------------------------------------------------
    # Pointer movement
    # ------------------------------------------------------------------
    def mouse_move_abs(self, dev_x: float, dev_y: float) -> None:
        """Converts oriented device pixels into PC target window physical pixels using the callback."""
        if self.callback is None:
            # Fallback if the engine hasn't wired the callback yet
            self.bridge.mouse_move_abs(int(round(dev_x)), int(round(dev_y)))
            return

        # Query the mapper for the current device dimensions and window offsets
        dev_w, dev_h, win, screen_x, screen_y, screen_w, screen_h = self.callback()

        dev_w = max(1.0, float(dev_w))
        dev_h = max(1.0, float(dev_h))

        norm_x = clamp(dev_x / dev_w, 0.0, 1.0)
        norm_y = clamp(dev_y / dev_h, 0.0, 1.0)

        # Apply offsets if the target window is valid and visible
        if win and win["width"] > 0 and win["height"] > 0:
            target_x = win["left"] + norm_x * (win["width"] - 1)
            target_y = win["top"] + norm_y * (win["height"] - 1)
        else:
            target_x = screen_x + norm_x * (screen_w - 1)
            target_y = screen_y + norm_y * (screen_h - 1)

        self.bridge.mouse_move_abs(int(round(target_x)), int(round(target_y)))

    def mouse_move(self, dx: float, dy: float) -> None:
        """Accumulates fractional deltas from ANY pipeline (WheelMapper, Pointer buttons, etc.)."""
        with self._lock:
            self._acc_x += dx
            self._acc_y += dy

    def flush_mouse_move(self) -> None:
        """Dispatches aggregated whole pixels to the OS and retains the fractional remainder."""
        with self._lock:
            idx = int(
                clamp(round(self._acc_x), -PACK_REL_STRUCT_SIZE, PACK_REL_STRUCT_SIZE)
            )
            idy = int(
                clamp(round(self._acc_y), -PACK_REL_STRUCT_SIZE, PACK_REL_STRUCT_SIZE)
            )

            if idx != 0 or idy != 0:
                self.bridge.mouse_move_rel(idx, idy)
                self._acc_x -= idx
                self._acc_y -= idy

    def reset_mouse_accumulators(self) -> None:
        """Called when no fingers are actively moving the cursor."""
        with self._lock:
            self._acc_x = 0.0
            self._acc_y = 0.0
