# STORE.PY

"""
Single entry point the rest of the app should import:

    from mapper_module.db import Store, default_db_path

    store = Store(default_db_path())
    settings = store.settings.get()
    active = store.layouts.get_active()
    zones = store.zones.list_for_layout(active.id) if active else []

Wraps one Database connection-manager plus its three repositories, so
callers do store.settings / store.layouts / store.zones instead of
constructing a Database and three repository classes by hand and
wiring them together every time a new module needs the store.
"""

from __future__ import annotations
from pathlib import Path

from .connection import Database
from .repositories import (
    AppSettings,
    AppSettingsRepository,
    Layout,
    LayoutRepository,
    Zone,
    ZoneRepository,
)


class Store:
    def __init__(self, db_path: str | Path):
        self.db = Database(db_path)
        self.settings = AppSettingsRepository(self.db)
        self.layouts = LayoutRepository(self.db)
        self.zones = ZoneRepository(self.db)

    def close(self) -> None:
        self.db.close()


def default_db_path() -> Path:
    """Mirrors mapper_module.utils.TOML_PATH's convention: keep the
    sqlite file alongside where the TOML config used to live, so
    existing install/uninstall scripts need only a filename change
    rather than a new directory-resolution rule. Adjust the filename
    here if PROJECT_ROOT already has a config subfolder convention
    your utils module follows that this doesn't yet know about."""
    from mapper_module.utils import PROJECT_ROOT

    return Path(PROJECT_ROOT) / "touch2key.db"


__all__ = [
    "Store",
    "Database",
    "AppSettings",
    "AppSettingsRepository",
    "Layout",
    "LayoutRepository",
    "Zone",
    "ZoneRepository",
    "default_db_path",
]
