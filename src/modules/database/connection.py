"""Thread-local sqlite3 connection management for the database layer.

Each thread gets its own connection. WAL mode allows concurrent readers
against the last-committed snapshot while writers execute updates.
"""

import logging
import sqlite3
import threading
from pathlib import Path

from modules.database.migrations import run_migrations, set_fresh_install_version
from modules.utils import DB_PATH

logger = logging.getLogger("modules.database.connection")

_SCHEMA = """
CREATE TABLE IF NOT EXISTS app_settings (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    left_handed INTEGER NOT NULL DEFAULT 0,
    floating_joystick INTEGER NOT NULL DEFAULT 0
    anchored_joystick INTEGER NOT NULL DEFAULT 0,
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
    typematic_enabled INTEGER NOT NULL DEFAULT 1,
    typematic_delay_ms REAL NOT NULL DEFAULT 250.0,
    typematic_rate_hz REAL NOT NULL DEFAULT 30.0,
    windows_keyboard_device INTEGER,
    windows_mouse_device INTEGER,
    typematic_exclude_keys TEXT,
    double_tap_enabled INTEGER NOT NULL DEFAULT 1,
    system_toggle_enabled INTEGER NOT NULL DEFAULT 1,
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);

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

CREATE TABLE IF NOT EXISTS layout_zones (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    layout_id INTEGER NOT NULL REFERENCES layouts(id) ON DELETE CASCADE,
    scancode TEXT NOT NULL,
    name TEXT NOT NULL DEFAULT '',
    zone_type TEXT NOT NULL CHECK (zone_type IN ('CIRCLE', 'RECTANGLE', 'BEZEL')),
    cx REAL, cy REAL, r REAL,
    x1 REAL, y1 REAL, x2 REAL, y2 REAL,
    pipeline_config TEXT NOT NULL DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS idx_layout_zones_layout_id ON layout_zones(layout_id);
"""

_SEED_DEFAULT_SETTINGS_ROW = "INSERT OR IGNORE INTO app_settings (id) VALUES (1);"


class ConnectionManager:
    """Owns one sqlite3.Connection per thread, pointed at the on-disk database file."""

    def __init__(self, db_path: Path | str = DB_PATH):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._local = threading.local()

        run_migrations(self.db_path)

    def get_connection(self) -> sqlite3.Connection:
        conn = getattr(self._local, "connection", None)
        if conn is not None:
            return conn

        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row

        actual_mode = conn.execute("PRAGMA journal_mode = WAL;").fetchone()[0]
        if actual_mode.lower() != "wal":
            logger.warning(
                "Requested WAL journal mode but got '%s' instead for %s.",
                actual_mode,
                self.db_path,
            )

        conn.execute("PRAGMA foreign_keys = ON;")
        conn.execute("PRAGMA synchronous = NORMAL;")
        conn.executescript(_SCHEMA)
        conn.execute(_SEED_DEFAULT_SETTINGS_ROW)

        # Migration safeguard: ensure pipeline_config column exists
        cursor = conn.cursor()
        cursor.execute("PRAGMA table_info(layout_zones);")
        columns = [row["name"] for row in cursor.fetchall()]
        if "pipeline_config" not in columns:
            cursor.execute(
                "ALTER TABLE layout_zones ADD COLUMN pipeline_config TEXT NOT NULL DEFAULT '{}';"
            )

        set_fresh_install_version(conn)

        conn.commit()
        self._local.connection = conn
        return conn

    def close_current_thread_connection(self) -> None:
        """Closes the current thread's connection promptly upon worker or engine shutdown."""
        conn = getattr(self._local, "connection", None)
        if conn is not None:
            conn.close()
            self._local.connection = None


connection_manager = ConnectionManager()
