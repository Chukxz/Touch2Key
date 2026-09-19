"""Typed repository classes over the SQLite database schema.

Validates field names against an explicit ALLOWED_FIELDS set before executing SQL.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, fields as dataclass_fields
from typing import Any, Optional, TYPE_CHECKING

from .connection import connection_manager

if TYPE_CHECKING:
    from . import AppSettings, Layout, LayoutZone


class InvalidFieldError(ValueError):
    """Raised when update()/create() receives a field name outside ALLOWED_FIELDS."""


@dataclass(frozen=True, slots=True)
class AppSettings:
    id: int
    left_handed: bool
    anchored_floating_joystick: bool
    joystick_snap_radius: float
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
    typematic_enabled: bool
    typematic_delay_ms: float
    typematic_rate_hz: float
    typematic_exclude_keys: Optional[str]
    active_layout_id: Optional[int]
    updated_at: str

    @classmethod
    def from_row(cls, row) -> AppSettings:
        data = {f.name: row[f.name] for f in dataclass_fields(cls)}
        data["left_handed"] = bool(data["left_handed"])
        data["anchored_floating_joystick"] = bool(data["anchored_floating_joystick"])
        data["joystick_snap_radius"] = float(data.get("joystick_snap_radius", 80.0))
        
        # Typematic type coercions & safe null handling
        data["typematic_enabled"] = bool(data.get("typematic_enabled", 1))
        data["typematic_delay_ms"] = float(data.get("typematic_delay_ms", 250.0))
        data["typematic_rate_hz"] = float(data.get("typematic_rate_hz", 30.0))
        raw_excludes = data.get("typematic_exclude_keys")
        data["typematic_exclude_keys"] = str(raw_excludes) if raw_excludes is not None else None
        
        return cls(**data)


@dataclass(frozen=True, slots=True)
class Layout:
    id: int
    name: str
    width: int
    height: int
    dpi: int
    mouse_wheel_radius: float
    sprint_distance: float
    image_path: Optional[str]
    created_at: str
    updated_at: str

    @classmethod
    def from_row(cls, row) -> Layout:
        return cls(**{f.name: row[f.name] for f in dataclass_fields(cls)})


@dataclass(frozen=True, slots=True)
class LayoutZone:
    id: int
    layout_id: int
    scancode: str
    name: str
    zone_type: str  # 'CIRCLE' | 'RECTANGLE' | 'BEZEL'
    cx: Optional[float]
    cy: Optional[float]
    r: Optional[float]
    x1: Optional[float]
    y1: Optional[float]
    x2: Optional[float]
    y2: Optional[float]
    pipeline_config: str

    @property
    def priority(self) -> int:
        """Extracts runtime priority from the unified pipeline_config JSON."""
        try:
            cfg = json.loads(self.pipeline_config)
            return int(cfg.get("priority", 0))
        except Exception:
            return 0

    @property
    def move_camera(self) -> bool:
        """Determines if this zone is configured for camera look/track-fire."""
        try:
            cfg = json.loads(self.pipeline_config)
            return cfg.get("semantics", {}).get("mode") == "TRACK_FIRE"
        except Exception:
            return False

    @classmethod
    def from_row(cls, row) -> LayoutZone:
        data = {
            f.name: row[f.name] for f in dataclass_fields(cls) if f.name in row.keys()
        }
        data["pipeline_config"] = (
            str(row["pipeline_config"]) if "pipeline_config" in row.keys() else "{}"
        )
        return cls(**data)


class AppSettingsRepository:
    """Single-row settings table (id=1)."""

    ALLOWED_FIELDS = {
        "left_handed",
        "anchored_floating_joystick",
        "joystick_snap_radius",
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
        "typematic_enabled",
        "typematic_delay_ms",
        "typematic_rate_hz",
        "typematic_exclude_keys",
    }

    def get(self) -> AppSettings:
        conn = connection_manager.get_connection()
        row = conn.execute("SELECT * FROM app_settings WHERE id = 1;").fetchone()
        if row is None:
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
                f"UPDATE app_settings SET {set_clause}, updated_at = datetime('now') WHERE id = :id;",
                params,
            )
        return self.get()

    def reset_to_defaults(self) -> AppSettings:
        conn = connection_manager.get_connection()
        with conn:
            cursor = conn.execute(
                "SELECT active_layout_id FROM app_settings WHERE id = 1;"
            )
            row = cursor.fetchone()
            active_layout_id = row[0] if row else None

            conn.execute("DELETE FROM app_settings WHERE id = 1;")
            conn.execute(
                "INSERT INTO app_settings (id, active_layout_id, typematic_exclude_keys) "
                "VALUES (1, ?, 'w,a,s,d,shift,ctrl,alt');",
                (active_layout_id,),
            )
        return self.get()


class LayoutsRepository:
    ALLOWED_FIELDS = {
        "name",
        "width",
        "height",
        "dpi",
        "mouse_wheel_radius",
        "sprint_distance",
        "image_path",
    }
    _REQUIRED_ON_CREATE = {"name", "width", "height", "dpi"}

    def list_all(self) -> list[Layout]:
        conn = connection_manager.get_connection()
        rows = conn.execute("SELECT * FROM layouts ORDER BY name;").fetchall()
        return [Layout.from_row(row) for row in rows]

    def get(self, layout_id: int | None) -> Optional[Layout]:
        if layout_id is None:
            return None
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
                f"UPDATE layouts SET {set_clause}, updated_at = datetime('now') WHERE id = :id;",
                params,
            )

        layout = self.get(layout_id)
        if layout is None:
            raise KeyError(f"No layout with id={layout_id}")
        return layout

    def delete(self, layout_id: int) -> None:
        conn = connection_manager.get_connection()
        with conn:
            conn.execute("DELETE FROM layouts WHERE id = ?;", (layout_id,))

    def delete_all(self) -> None:
        conn = connection_manager.get_connection()
        with conn:
            conn.execute("DELETE FROM layouts;")

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
                pipeline_config=zone.pipeline_config,
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
        "pipeline_config",
    }

    VALID_ZONE_TYPES = {"CIRCLE", "RECTANGLE", "BEZEL"}
    _REQUIRED_ON_CREATE = {"layout_id", "scancode", "zone_type"}

    def list_for_layout(self, layout_id: int) -> list[LayoutZone]:
        conn = connection_manager.get_connection()
        rows = conn.execute(
            "SELECT * FROM layout_zones WHERE layout_id = ? ORDER BY id;", (layout_id,)
        ).fetchall()
        return [LayoutZone.from_row(row) for row in rows]

    def get(self, zone_id: int | None) -> Optional[LayoutZone]:
        if zone_id is None:
            return None
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
        fields.setdefault("pipeline_config", "{}")

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