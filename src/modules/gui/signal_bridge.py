"""
Bridges modules' threaded MapperEventDispatcher callbacks into
PySide6 Signals, so GUI widgets can react to engine state (window,
touch reader, mapper) without touching Qt objects from a non-GUI thread.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Callable
from PySide6.QtCore import QObject, Signal

if TYPE_CHECKING:
    from modules.utils import MapperEventDispatcher


class EngineSignalBridge(QObject):
    """Bridges threaded MapperEventDispatcher events to Qt main thread signals."""

    config_reloaded = Signal()
    layout_reloaded = Signal()
    menu_mode_toggled = Signal(bool)
    wasd_block_changed = Signal()
    worker_respawned = Signal(str)
    aggregation = Signal(float, float, float, float)
    generic_event = Signal(str, dict)

    def __init__(self, parent: QObject | None = None):
        super().__init__(parent)
        self.dispatcher: MapperEventDispatcher | None = None
        self._registered_callbacks: list[tuple[str, Callable]] = []

    def bind(self, dispatcher: MapperEventDispatcher | None) -> None:
        """Binds to a new engine dispatcher, unbinding any prior registration first."""
        self.unbind()

        if dispatcher is None:
            return

        self.dispatcher = dispatcher

        def _on_config(**kw):
            self.config_reloaded.emit()

        def _on_layout(**kw):
            self.layout_reloaded.emit()

        def _on_mode(is_visible=True, **kw):
            self.menu_mode_toggled.emit(bool(is_visible))

        def _on_wasd_block(**kw):
            self.wasd_block_changed.emit()

        def _on_respawn(worker_type="", **kw):
            self.worker_respawned.emit(worker_type)

        def _on_agg(sum_dx=0.0, sum_dy=0.0, acc_x=0.0, acc_y=0.0, **kw):
            self.aggregation.emit(sum_dx, sum_dy, acc_x, acc_y)

        callbacks = [
            ("ON_CONFIG_RELOAD", _on_config),
            ("ON_LAYOUT_RELOAD", _on_layout),
            ("ON_MENU_MODE_TOGGLE", _on_mode),
            ("ON_WASD_BLOCK", _on_wasd_block),
            ("ON_WORKER_RESPAWN", _on_respawn),
            ("ON_AGGREGATION", _on_agg),
        ]

        for action, cb in callbacks:
            self.dispatcher.register_callback(action, cb)
            self._registered_callbacks.append((action, cb))

    def unbind(self) -> None:
        """Unregisters all bound callbacks from the current dispatcher."""
        if self.dispatcher is not None and hasattr(self.dispatcher, "unregister_callback"):
            for action, cb in self._registered_callbacks:
                try:
                    self.dispatcher.unregister_callback(action, cb)
                except Exception:
                    pass

        self._registered_callbacks.clear()
        self.dispatcher = None

    def emit_generic(self, action: str, **kwargs: Any) -> None:
        self.generic_event.emit(action, kwargs)