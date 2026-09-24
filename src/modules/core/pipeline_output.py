from __future__ import annotations

from typing import TYPE_CHECKING, Callable
from modules.core.pipeline import OutputSink
from modules.utils import SCANCODES

if TYPE_CHECKING:
    from modules.platforms.base import AbstractBridge


class BridgeOutputSink(OutputSink):
    """Bridges Semantic stage outputs to the hardware driver Bridge."""

    def __init__(
        self,
        bridge: AbstractBridge,
        toggle_mode: Callable[[], None] | None = None,
        toggle_vkb: Callable[[], None] | None = None,
    ) -> None:
        self.bridge = bridge
        self._toggle_mode = toggle_mode
        self._toggle_vkb = toggle_vkb

    def toggle_menu_mode(self) -> None:
        """Invokes Engine.toggle_mode directly."""
        if self._toggle_mode is not None:
            self._toggle_mode()

    def toggle_virtual_keyboard(self) -> None:
        """Invokes Engine.toggle_virtual_keyboard directly."""
        if self._toggle_vkb is not None:
            self._toggle_vkb()

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
        idx = int(round(dx))
        idy = int(round(dy))
        if idx != 0 or idy != 0:
            self.bridge.mouse_move_rel(idx, idy)

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
