# SCHEMA.PY

"""
Schema DDL, kept as one executable script rather than per-statement
strings so Database.__init__ can run it in a single executescript()
call. Ordered layouts -> layout_zones -> app_settings so the foreign
keys read naturally top-to-bottom, though SQLite doesn't actually
require referenced tables to exist before the referencing CREATE TABLE
statement -- only by the time a DML statement enforces the constraint.
"""

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS layouts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    width INTEGER NOT NULL,
    height INTEGER NOT NULL,
    dpi INTEGER NOT NULL,
    mouse_wheel_radius REAL NOT NULL DEFAULT 50.0,
    sprint_distance REAL NOT NULL DEFAULT 10.0,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS layout_zones (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    layout_id INTEGER NOT NULL REFERENCES layouts(id) ON DELETE CASCADE,
    scancode TEXT NOT NULL,
    name TEXT NOT NULL DEFAULT '',
    zone_type TEXT NOT NULL CHECK (zone_type IN ('circle', 'rect')),
    cx REAL,
    cy REAL,
    r REAL,
    x1 REAL,
    y1 REAL,
    x2 REAL,
    y2 REAL,
    move_camera INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_layout_zones_layout_id ON layout_zones(layout_id);

CREATE TABLE IF NOT EXISTS app_settings (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    left_handed INTEGER NOT NULL DEFAULT 0,
    json_dev_width INTEGER NOT NULL DEFAULT 360,
    json_dev_height INTEGER NOT NULL DEFAULT 800,
    json_dev_dpi INTEGER NOT NULL DEFAULT 160,
    deadzone REAL NOT NULL DEFAULT 0.1,
    hysteresis REAL NOT NULL DEFAULT 5.0,
    sensitivity REAL NOT NULL DEFAULT 1.0,
    toggle_key TEXT,
    sprint_key TEXT,
    adb_rate_cap REAL NOT NULL DEFAULT 125.0,
    pps_alert_threshold REAL NOT NULL DEFAULT 60.0,
    active_layout_id INTEGER REFERENCES layouts(id) ON DELETE SET NULL,
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);

-- Guarded with `WHEN NEW.updated_at = OLD.updated_at` so the trigger's
-- own UPDATE doesn't re-fire itself (an unguarded AFTER UPDATE trigger
-- that runs UPDATE on the same table recurses infinitely).
CREATE TRIGGER IF NOT EXISTS trg_layouts_updated_at
AFTER UPDATE ON layouts
WHEN NEW.updated_at = OLD.updated_at
BEGIN
    UPDATE layouts SET updated_at = datetime('now') WHERE id = NEW.id;
END;

CREATE TRIGGER IF NOT EXISTS trg_app_settings_updated_at
AFTER UPDATE ON app_settings
WHEN NEW.updated_at = OLD.updated_at
BEGIN
    UPDATE app_settings SET updated_at = datetime('now') WHERE id = NEW.id;
END;
"""
