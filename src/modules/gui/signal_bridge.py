"""
Bridges modules' threaded MapperEventDispatcher callbacks into
PySide6 Signals, so GUI widgets can react to engine state (window,
touch reader, mapper) without touching Qt objects from a non-GUI thread.

MapperEventDispatcher.dispatch() invokes registered callbacks directly,
on whatever thread called dispatch() (main-loop thread, touch-reader
thread, aggregation thread, etc.). Qt widgets are NOT thread-safe, so
callbacks must never touch a QWidget directly.

Signal.emit() is safe to call from any thread: PySide6 automatically
queues the delivery to the receiving QObject's own thread affinity
(Qt.AutoConnection resolves to a queued connection cross-thread), as
long as this bridge object is constructed on the GUI thread and never
moved with moveToThread(). That is the only property this class relies
on for safety -- it does no locking of its own.
"""

from __future__ import annotations
from typing import TYPE_CHECKING, Any

from PySide6.QtCore import QObject, Signal

if TYPE_CHECKING:
    from modules.tils import MapperEventDispatcher


class EngineSignalBridge(QObject):
    """One instance lives on the MainWindow for the lifetime of the app.
    Call bind() each time a new Engine (and therefore a new dispatcher)
    is created in _start_engine(); there is currently no unbind(), so
    _stop_engine() must drop the Engine reference rather than reuse it,
    or callbacks will accumulate across start/stop cycles."""

    config_reloaded = Signal()
    json_reloaded = Signal()
    menu_mode_toggled = Signal(bool)  # is_visible
    wasd_block_changed = Signal()
    worker_respawned = Signal(str)  # worker_type
    aggregation = Signal(float, float, float, float)  # sum_dx, sum_dy, acc_x, acc_y

    # Catch-all for any action not worth a dedicated typed signal yet.
    generic_event = Signal(str, dict)

    def bind(self, dispatcher: "MapperEventDispatcher | None") -> None:
        if dispatcher is None:
            return

        dispatcher.register_callback(
            "ON_CONFIG_RELOAD", lambda **kw: self.config_reloaded.emit()
        )
        dispatcher.register_callback(
            "ON_JSON_RELOAD", lambda **kw: self.json_reloaded.emit()
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
