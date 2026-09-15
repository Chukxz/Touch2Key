"""
Bridges modules' threaded MapperEventDispatcher callbacks into
PySide6 Signals, so GUI widgets can react to engine state (window,
touch reader, mapper) without touching Qt objects from a non-GUI thread.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any
from PySide6.QtCore import QObject, Signal

if TYPE_CHECKING:
    from modules.utils import MapperEventDispatcher


class EngineSignalBridge(QObject):
    """Bridges threaded MapperEventDispatcher events to Qt main thread signals."""

    config_reloaded = Signal()
    layout_reloaded = Signal()
    menu_mode_toggled = Signal(bool)  # is_visible
    wasd_block_changed = Signal()
    worker_respawned = Signal(str)  # worker_type
    aggregation = Signal(float, float, float, float)  # sum_dx, sum_dy, acc_x, acc_y
    generic_event = Signal(str, dict)

    def __init__(self, parent: QObject | None = None):
        super().__init__(parent)
        self.dispatcher: MapperEventDispatcher | None = None

    def bind(self, dispatcher: MapperEventDispatcher | None) -> None:
        self.dispatcher = dispatcher
        if dispatcher is None:
            return

        dispatcher.register_callback(
            "ON_CONFIG_RELOAD", lambda **kw: self.config_reloaded.emit()
        )
        dispatcher.register_callback(
            "ON_LAYOUT_RELOAD", lambda **kw: self.layout_reloaded.emit()
        )
        dispatcher.register_callback(
            "ON_MENU_MODE_TOGGLE",
            lambda is_visible=True, **kw: self.menu_mode_toggled.emit(bool(is_visible)),
        )
        dispatcher.register_callback(
            "ON_WASD_BLOCK", lambda **kw: self.wasd_block_changed.emit()
        )
        dispatcher.register_callback(
            "ON_WORKER_RESPAWN",
            lambda worker_type="", **kw: self.worker_respawned.emit(worker_type),
        )
        dispatcher.register_callback(
            "ON_AGGREGATION",
            lambda sum_dx=0.0, sum_dy=0.0, acc_x=0.0, acc_y=0.0, **kw: (
                self.aggregation.emit(sum_dx, sum_dy, acc_x, acc_y)
            ),
        )

    def emit_generic(self, action: str, **kwargs: Any) -> None:
        self.generic_event.emit(action, kwargs)