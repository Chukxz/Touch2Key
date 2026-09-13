"""
Typed repository classes over the sqlite schema in connection.py.

Every update()/create() validates field names against an explicit
allow-list before building SQL. Values are always bound as query
parameters (safe from injection by construction), but *column names*
cannot be parameterized in sqlite3 -- an allow-list is what stands
between a typo, a stale field name after a schema change, or a future
GUI wiring bug (e.g. passing a raw dict keyed by Qt widget object
names) and either a SQL error or a silently-wrong UPDATE against a
similarly-named column.
"""

from __future__ import annotations

from dataclasses import dataclass, fields as dataclass_fields
from typing import Any, Optional

from .connection import connection_manager


class InvalidFieldError(ValueError):
    """Raised when update()/create() receives a field name outside a
    repository's ALLOWED_FIELDS."""


@dataclass
class AppSettings:
    id: int
    left_handed: bool
    json_dev_width: int
    json_dev_height: int
    json_dev_dpi: int
    deadzone: float
    hysteresis: float
    sensitivity: float
    toggle_key: Optional[str]
    sprint_key: Optional[str]
    adb_rate_cap: float
    pps_alert_threshold: float
    active_layout_id: Optional[int]
    updated_at: str

    @classmethod
    def from_row(cls, row) -> "AppSettings":
        data = {f.name: row[f.name] for f in dataclass_fields(cls)}
        data["left_handed"] = bool(data["left_handed"])
        return cls(**data)


@dataclass
class Layout:
    id: int
    name: str
    width: int
    height: int
    dpi: int
    mouse_wheel_radius: float
    sprint_distance: float
    created_at: str
    updated_at: str

    @classmethod
    def from_row(cls, row) -> "Layout":
        return cls(**{f.name: row[f.name] for f in dataclass_fields(cls)})


@dataclass
class LayoutZone:
    id: int
    layout_id: int
    scancode: str
    name: str
    zone_type: str  # 'CIRCLE' | 'RECT'
    cx: Optional[float]
    cy: Optional[float]
    r: Optional[float]
    x1: Optional[float]
    y1: Optional[float]
    x2: Optional[float]
    y2: Optional[float]
    move_camera: bool

    @classmethod
    def from_row(cls, row) -> "LayoutZone":
        data = {
            f.name: row[f.name]
            for f in dataclass_fields(cls)
            if f.name != "move_camera"
        }
        data["move_camera"] = bool(row["move_camera"])
        return cls(**data)


class AppSettingsRepository:
    """Single-row settings table (id=1). Mirrors the old TOML
    [system]/[joystick]/[mouse] sections flattened into one row, since
    there's only ever one active configuration at a time."""

    ALLOWED_FIELDS = {
        "left_handed",
        "json_dev_width",
        "json_dev_height",
        "json_dev_dpi",
        "deadzone",
        "hysteresis",
        "sensitivity",
        "toggle_key",
        "sprint_key",
        "adb_rate_cap",
        "pps_alert_threshold",
        "active_layout_id",
    }

    def get(self) -> AppSettings:
        conn = connection_manager.get_connection()
        row = conn.execute("SELECT * FROM app_settings WHERE id = 1;").fetchone()
        if row is None:
            # Defensive: connection.py seeds this row on schema
            # creation, so reaching here means it was deleted out from
            # under us (e.g. a manual DB edit). Re-seed rather than crash.
            with conn:
                conn.execute("INSERT OR IGNORE INTO app_settings (id) VALUES (1);")
            row = conn.execute("SELECT * FROM app_settings WHERE id = 1;").fetchone()
        return AppSettings.from_row(row)

    def update(self, **fields: Any) -> AppSettings:
        unknown = set(fields) - self.ALLOWED_FIELDS
        if unknown:
            raise InvalidFieldError(f"Unknown app_settings field(s): {sorted(unknown)}")
        if not fields:
            return self.get()

        set_clause = ", ".join(f"{key} = :{key}" for key in fields)
        params = dict(fields)
        params["id"] = 1

        conn = connection_manager.get_connection()
        with conn:
            conn.execute(
                f"UPDATE app_settings SET {set_clause}, updated_at = datetime('now') "
                f"WHERE id = :id;",
                params,
            )
        return self.get()

    def reset_to_defaults(self) -> AppSettings:
        conn = connection_manager.get_connection()
        with conn:
            conn.execute("DELETE FROM app_settings WHERE id = 1;")
            conn.execute("INSERT INTO app_settings (id) VALUES (1);")
        return self.get()


class LayoutsRepository:
    ALLOWED_FIELDS = {
        "name",
        "width",
        "height",
        "dpi",
        "mouse_wheel_radius",
        "sprint_distance",
    }
    _REQUIRED_ON_CREATE = {"name", "width", "height", "dpi"}

    def list_all(self) -> list[Layout]:
        conn = connection_manager.get_connection()
        rows = conn.execute("SELECT * FROM layouts ORDER BY name;").fetchall()
        return [Layout.from_row(row) for row in rows]

    def get(self, layout_id: int) -> Optional[Layout]:
        conn = connection_manager.get_connection()
        row = conn.execute(
            "SELECT * FROM layouts WHERE id = ?;", (layout_id,)
        ).fetchone()
        return Layout.from_row(row) if row is not None else None

    def get_by_name(self, name: str) -> Optional[Layout]:
        conn = connection_manager.get_connection()
        row = conn.execute("SELECT * FROM layouts WHERE name = ?;", (name,)).fetchone()
        return Layout.from_row(row) if row is not None else None

    def create(self, **fields: Any) -> Layout:
        unknown = set(fields) - self.ALLOWED_FIELDS
        if unknown:
            raise InvalidFieldError(f"Unknown layouts field(s): {sorted(unknown)}")
        missing = self._REQUIRED_ON_CREATE - set(fields)
        if missing:
            raise ValueError(f"Missing required layout field(s): {sorted(missing)}")

        fields.setdefault("mouse_wheel_radius", 50.0)
        fields.setdefault("sprint_distance", 10.0)

        columns = ", ".join(fields)
        placeholders = ", ".join(f":{key}" for key in fields)

        conn = connection_manager.get_connection()
        with conn:
            cursor = conn.execute(
                f"INSERT INTO layouts ({columns}) VALUES ({placeholders});", fields
            )
            new_id = cursor.lastrowid

        layout = self.get(new_id)
        assert layout is not None
        return layout

    def update(self, layout_id: int, **fields: Any) -> Layout:
        unknown = set(fields) - self.ALLOWED_FIELDS
        if unknown:
            raise InvalidFieldError(f"Unknown layouts field(s): {sorted(unknown)}")
        if not fields:
            existing = self.get(layout_id)
            if existing is None:
                raise KeyError(f"No layout with id={layout_id}")
            return existing

        set_clause = ", ".join(f"{key} = :{key}" for key in fields)
        params = dict(fields)
        params["id"] = layout_id

        conn = connection_manager.get_connection()
        with conn:
            conn.execute(
                f"UPDATE layouts SET {set_clause}, updated_at = datetime('now') "
                f"WHERE id = :id;",
                params,
            )

        layout = self.get(layout_id)
        if layout is None:
            raise KeyError(f"No layout with id={layout_id}")
        return layout

    def delete(self, layout_id: int) -> None:
        """Cascades to layout_zones via ON DELETE CASCADE. If this
        layout was app_settings.active_layout_id, that column is set
        to NULL by its own foreign key clause -- callers should pick a
        new active layout afterward if one is needed."""
        conn = connection_manager.get_connection()
        with conn:
            conn.execute("DELETE FROM layouts WHERE id = ?;", (layout_id,))

    def duplicate(self, layout_id: int, new_name: str) -> Layout:
        source = self.get(layout_id)
        if source is None:
            raise KeyError(f"No layout with id={layout_id}")

        new_layout = self.create(
            name=new_name,
            width=source.width,
            height=source.height,
            dpi=source.dpi,
            mouse_wheel_radius=source.mouse_wheel_radius,
            sprint_distance=source.sprint_distance,
        )

        zones_repo = LayoutZonesRepository()
        for zone in zones_repo.list_for_layout(layout_id):
            zones_repo.create(
                layout_id=new_layout.id,
                scancode=zone.scancode,
                name=zone.name,
                zone_type=zone.zone_type,
                cx=zone.cx,
                cy=zone.cy,
                r=zone.r,
                x1=zone.x1,
                y1=zone.y1,
                x2=zone.x2,
                y2=zone.y2,
                move_camera=zone.move_camera,
            )
        return new_layout


class LayoutZonesRepository:
    ALLOWED_FIELDS = {
        "layout_id",
        "scancode",
        "name",
        "zone_type",
        "cx",
        "cy",
        "r",
        "x1",
        "y1",
        "x2",
        "y2",
        "move_camera",
    }
    VALID_ZONE_TYPES = {"circle", "rect"}
    _REQUIRED_ON_CREATE = {"layout_id", "scancode", "zone_type"}

    def list_for_layout(self, layout_id: int) -> list[LayoutZone]:
        conn = connection_manager.get_connection()
        rows = conn.execute(
            "SELECT * FROM layout_zones WHERE layout_id = ? ORDER BY id;", (layout_id,)
        ).fetchall()
        return [LayoutZone.from_row(row) for row in rows]

    def get(self, zone_id: int) -> Optional[LayoutZone]:
        conn = connection_manager.get_connection()
        row = conn.execute(
            "SELECT * FROM layout_zones WHERE id = ?;", (zone_id,)
        ).fetchone()
        return LayoutZone.from_row(row) if row is not None else None

    def create(self, **fields: Any) -> LayoutZone:
        unknown = set(fields) - self.ALLOWED_FIELDS
        if unknown:
            raise InvalidFieldError(f"Unknown layout_zones field(s): {sorted(unknown)}")
        missing = self._REQUIRED_ON_CREATE - set(fields)
        if missing:
            raise ValueError(f"Missing required zone field(s): {sorted(missing)}")
        if fields["zone_type"] not in self.VALID_ZONE_TYPES:
            raise ValueError(f"zone_type must be one of {self.VALID_ZONE_TYPES}")

        fields.setdefault("name", "")
        fields.setdefault("move_camera", False)
        fields["move_camera"] = int(bool(fields["move_camera"]))

        columns = ", ".join(fields)
        placeholders = ", ".join(f":{key}" for key in fields)

        conn = connection_manager.get_connection()
        with conn:
            cursor = conn.execute(
                f"INSERT INTO layout_zones ({columns}) VALUES ({placeholders});", fields
            )
            new_id = cursor.lastrowid

        zone = self.get(new_id)
        assert zone is not None
        return zone

    def update(self, zone_id: int, **fields: Any) -> LayoutZone:
        unknown = set(fields) - self.ALLOWED_FIELDS
        if unknown:
            raise InvalidFieldError(f"Unknown layout_zones field(s): {sorted(unknown)}")
        if "zone_type" in fields and fields["zone_type"] not in self.VALID_ZONE_TYPES:
            raise ValueError(f"zone_type must be one of {self.VALID_ZONE_TYPES}")
        if "move_camera" in fields:
            fields["move_camera"] = int(bool(fields["move_camera"]))
        if not fields:
            existing = self.get(zone_id)
            if existing is None:
                raise KeyError(f"No zone with id={zone_id}")
            return existing

        set_clause = ", ".join(f"{key} = :{key}" for key in fields)
        params = dict(fields)
        params["id"] = zone_id

        conn = connection_manager.get_connection()
        with conn:
            conn.execute(
                f"UPDATE layout_zones SET {set_clause} WHERE id = :id;", params
            )

        zone = self.get(zone_id)
        if zone is None:
            raise KeyError(f"No zone with id={zone_id}")
        return zone

    def delete(self, zone_id: int) -> None:
        conn = connection_manager.get_connection()
        with conn:
            conn.execute("DELETE FROM layout_zones WHERE id = ?;", (zone_id,))

    def delete_all_for_layout(self, layout_id: int) -> None:
        conn = connection_manager.get_connection()
        with conn:
            conn.execute("DELETE FROM layout_zones WHERE layout_id = ?;", (layout_id,))
