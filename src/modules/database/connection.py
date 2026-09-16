"""
Thread-local sqlite3 connection management for Touch2Key's database
layer. Each thread that touches the database gets its own connection
(sqlite3.Connection objects are not safe to share across threads, and
WAL mode makes per-thread connections the simpler and faster choice
here since Mapper/TouchReader/GUI threads all read config concurrently
while writes -- a settings save, a layout edit -- are comparatively
rare).

WAL mode lets one writer proceed while readers keep reading against
the last-committed snapshot, matching this app's actual traffic
pattern: frequent reads in or near the hot touch loop, against
occasional writes from the GUI or a hotkey handler.
"""

from __future__ import annotations

import logging
import sqlite3
import threading
from pathlib import Path

from modules.utils import DB_PATH
from modules.database.migrations import run_migrations, set_fresh_install_version

logger = logging.getLogger("modules.database.connection")


# layouts before app_settings/layout_zones so both FOREIGN KEY targets
# already exist textually in the script, even though sqlite doesn't
# strictly require creation order for this -- it reads more clearly.
_SCHEMA = """
CREATE TABLE IF NOT EXISTS layouts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    width INTEGER NOT NULL,
    height INTEGER NOT NULL,
    dpi INTEGER NOT NULL,
    mouse_wheel_radius REAL NOT NULL DEFAULT 50.0,
    sprint_distance REAL NOT NULL DEFAULT 10.0,
    image_path TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS app_settings (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    left_handed INTEGER NOT NULL DEFAULT 0,
    anchored_floating_joystick INTEGER NOT NULL DEFAULT 0,
    joystick_snap_radius REAL NOT NULL DEFAULT 80.0,
    json_dev_width INTEGER NOT NULL DEFAULT 360,
    json_dev_height INTEGER NOT NULL DEFAULT 800,
    json_dev_dpi INTEGER NOT NULL DEFAULT 160,
    deadzone REAL NOT NULL DEFAULT 0.1,
    hysteresis REAL NOT NULL DEFAULT 5.0,
    sensitivity REAL NOT NULL DEFAULT 1.0,
    toggle_key TEXT,
    sprint_key TEXT,
    adb_rate_cap REAL NOT NULL DEFAULT 250.0,
    pps_alert_threshold REAL NOT NULL DEFAULT 60.0,
    active_layout_id INTEGER REFERENCES layouts(id) ON DELETE SET NULL,
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS layout_zones (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    layout_id INTEGER NOT NULL REFERENCES layouts(id) ON DELETE CASCADE,
    scancode TEXT NOT NULL,
    name TEXT NOT NULL DEFAULT '',
    zone_type TEXT NOT NULL CHECK (zone_type IN ('CIRCLE', 'RECTANGLE')),
    cx REAL, cy REAL, r REAL,
    x1 REAL, y1 REAL, x2 REAL, y2 REAL,
    move_camera INTEGER NOT NULL DEFAULT 0,
    priority INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_layout_zones_layout_id ON layout_zones(layout_id);
"""

_SEED_DEFAULT_SETTINGS_ROW = "INSERT OR IGNORE INTO app_settings (id) VALUES (1);"


class ConnectionManager:
    """Owns one sqlite3.Connection per thread, all pointed at the same
    on-disk database file. Call get_connection() from any thread;
    schema creation runs once per new connection (CREATE TABLE IF NOT
    EXISTS is cheap and idempotent, so no separate "have we migrated"
    flag is needed for schema itself -- see legacy_migration.py for
    one-time *data* import from TOML/JSON, which does need one)."""

    def __init__(self, db_path: Path | str = DB_PATH):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._local = threading.local()

        run_migrations(self.db_path)

    def get_connection(self) -> sqlite3.Connection:
        conn = getattr(self._local, "connection", None)
        if conn is not None:
            return conn

        # Run migrations ONLY ONCE globally before threads start connecting
        conn = sqlite3.connect(self.db_path)
        # Default isolation_level ("" = deferred) is kept deliberately --
        # NOT set to None. Repositories rely on `with conn:` to wrap
        # multi-statement writes (e.g. delete-then-insert in
        # reset_to_defaults, or duplicate()'s layout-plus-zones copy)
        # in a real transaction with commit/rollback. isolation_level=
        # None puts sqlite3 in autocommit mode, where `with conn:`
        # silently does nothing and a failure mid-sequence leaves
        # partial writes -- easy trap, worth calling out explicitly.
        conn.row_factory = sqlite3.Row

        # Some filesystems (network mounts, certain overlay/container
        # filesystems) don't support the shared-memory locking WAL
        # needs; sqlite then silently stays on the prior journal mode
        # instead of raising. Check the actual result rather than
        # assuming the request succeeded -- WAL not sticking isn't
        # fatal (the app still works, just without WAL's concurrent
        # reader/writer benefit), but it's worth knowing about instead
        # of debugging phantom "why isn't this reader seeing my write"
        # issues later.
        actual_mode = conn.execute("PRAGMA journal_mode = WAL;").fetchone()[0]
        if actual_mode.lower() != "wal":
            logger.warning(
                "Requested WAL journal mode but got '%s' instead -- the "
                "filesystem at %s may not support it. Falling back to "
                "this mode; reads/writes still work, just without WAL's "
                "concurrent access benefit.",
                actual_mode,
                self.db_path,
            )

        conn.execute("PRAGMA foreign_keys = ON;")
        conn.execute("PRAGMA synchronous = NORMAL;")  # safe with WAL, faster than FULL
        conn.executescript(_SCHEMA)
        conn.execute(_SEED_DEFAULT_SETTINGS_ROW)

        # If this was a completely fresh database, stamp it with the latest version
        # so it doesn't try to run migrations from version 0 on the next launch.
        set_fresh_install_version(conn)

        conn.commit()
        self._local.connection = conn
        return conn

    def close_current_thread_connection(self) -> None:
        """Call when a worker thread is shutting down (e.g. from
        TouchReader.stop() or Engine._shutdown()) to release that
        thread's connection promptly instead of waiting on GC."""
        conn = getattr(self._local, "connection", None)
        if conn is not None:
            conn.close()
            self._local.connection = None


# Module-level singleton: one ConnectionManager per process, shared by
# every repository and by the Store facade in __init__.py.
connection_manager = ConnectionManager()
