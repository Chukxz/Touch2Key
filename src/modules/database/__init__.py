"""
Unified facade over the database layer. Most callers should import
`store` from here rather than reaching into connection.py or
repositories.py directly -- it's the seam that keeps AppConfig's and
JSONLoader's eventual sqlite-backed rewrite thin (same compatibility-
shim approach already used for AppConfig.get()), and it's what
legacy_migration.py writes into.
"""
from __future__ import annotations

from typing import Optional

from .connection import connection_manager, ConnectionManager
from .repositories import (
    AppSettingsRepository,
    LayoutsRepository,
    LayoutZonesRepository,
    AppSettings,
    Layout,
    LayoutZone,
    InvalidFieldError,
)

__all__ = [
    "Store",
    "store",
    "AppSettings",
    "Layout",
    "LayoutZone",
    "InvalidFieldError",
]


class Store:
    """One instance is enough for the whole process -- repositories
    are stateless aside from the shared, thread-local connection
    manager, so construction is cheap and there's no reason to pass
    this around as anything but the module-level singleton below."""

    def __init__(self, manager: Optional[ConnectionManager] = None):
        self._manager = manager or connection_manager
        self.settings = AppSettingsRepository()
        self.layouts = LayoutsRepository()
        self.zones = LayoutZonesRepository()

    # Convenience methods mirroring the old AppConfig/JSONLoader surface,
    # so core/ consumers (Mapper, KeyMapper, WASDMapper, ...) need
    # minimal changes when their config source moves off TOML/JSON.

    def get_active_layout(self) -> Optional[Layout]:
        settings = self.settings.get()
        if settings.active_layout_id is None:
            return None
        return self.layouts.get(settings.active_layout_id)

    def get_active_layout_zones(self) -> list[LayoutZone]:
        layout = self.get_active_layout()
        if layout is None:
            return []
        return self.zones.list_for_layout(layout.id)

    def set_active_layout(self, layout_id: int) -> AppSettings:
        if self.layouts.get(layout_id) is None:
            raise KeyError(f"No layout with id={layout_id}")
        return self.settings.update(active_layout_id=layout_id)

    def close(self) -> None:
        """Call from a thread that's shutting down (mirrors
        TouchReader.stop()) to release that thread's connection."""
        self._manager.close_current_thread_connection()


# Process-wide singleton. `from modules.database import store`
# is the expected import at nearly every call site.
store = Store()
