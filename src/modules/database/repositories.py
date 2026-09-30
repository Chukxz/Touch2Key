"""Typed repository classes over the SQLite database schema.

Validates field names against an explicit ALLOWED_FIELDS set before executing SQL.
"""

from __future__ import annotations

from dataclasses import dataclass, field, fields as dataclass_fields
from typing import Any, Optional, TYPE_CHECKING

from modules.utils import (
    EXCLUDED_KEYS,
    BEZEL,
    BEZEL_DP_THICKNESS,
    CIRCLE,
    RECTANGLE,
    InvalidFieldError,
)

from modules.core.pipeline import PipelineConfig
from .connection import connection_manager

if TYPE_CHECKING:
    from . import AppSettings, Layout, LayoutZone

from modules.core.bezel_validator import (
    bezels_exist_ids,
    get_bezel_thicknesses,
    ensure_top_bezel,
    ensure_bottom_bezel,
)


@dataclass(frozen=True, slots=True)
class AppSettings:
    id: int
    left_handed: bool
    floating_joystick: bool
    anchored_joystick: bool
    json_dev_width: int
    json_dev_height: int
    json_dev_dpi: int
    deadzone: float
    hysteresis: float
    sensitivity_x: float
    sensitivity_y: float
    toggle_key: Optional[str]
    sprint_key: Optional[str]
    adb_rate_cap: float
    pps_alert_threshold: float
    active_layout_id: Optional[int]
    typematic_enabled: bool
    typematic_delay_ms: float
    typematic_rate_hz: float
    typematic_excluded_keys: Optional[str]
    double_tap_enabled: bool
    bezel_toggle_enabled: bool
    created_at: str | None = None
    updated_at: str | None = None

    @classmethod
    def from_row(cls, row) -> AppSettings:
        # Convert sqlite3.Row directly to kwargs
        d = dict(row)
        # Coerce booleans in a single generic pass
        d["left_handed"] = bool(d["left_handed"])
        d["floating_joystick"] = bool(d["floating_joystick"])
        d["anchored_joystick"] = bool(d["anchored_joystick"])
        d["typematic_enabled"] = bool(d["typematic_enabled"])
        d["double_tap_enabled"] = bool(d["double_tap_enabled"])
        d["bezel_toggle_enabled"] = bool(d["bezel_toggle_enabled"])
        return cls(**d)


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
    zone_type: str  # BEZEL | CIRCLE | RECTANGLE
    cx: Optional[float]
    cy: Optional[float]
    r: Optional[float]
    x1: Optional[float]
    y1: Optional[float]
    x2: Optional[float]
    y2: Optional[float]
    ignore_app_settings: bool
    pipeline_json: str
    created_at: str
    updated_at: str

    # Give each instance its own helper object without requiring it in __init__
    CONFIG_HELPER: PipelineConfig = field(
        default_factory=PipelineConfig, init=False, repr=False
    )

    def set_parsed_config_from_json(self):
        if self.CONFIG_HELPER.should_get_config:
            self.CONFIG_HELPER.set_pipeline_config_from_json(self.pipeline_json)

    @property
    def priority(self) -> int:
        """Extracts runtime priority from the unified pipeline_json JSON."""
        self.set_parsed_config_from_json()
        _, _, _, priority = self.CONFIG_HELPER.get_region_config()
        return priority

    @property
    def pointer(self) -> bool:
        """Determines if this zone is configured for camera look around."""
        self.set_parsed_config_from_json()
        _, _, pointer = self.CONFIG_HELPER.get_semantic_config()
        return pointer

    @classmethod
    def from_row(cls, row) -> LayoutZone:
        data = {
            f.name: row[f.name] for f in dataclass_fields(cls) if f.name in row.keys()
        }
        data["ignore_app_settings"] = bool(data["ignore_app_settings"])
        data["pipeline_json"] = (
            str(row["pipeline_json"]) if "pipeline_json" in row.keys() else "{}"
        )
        return cls(**data)


class AppSettingsRepository:
    """Single-row settings table (id=1)."""

    ALLOWED_FIELDS = {
        "left_handed",
        "floating_joystick",
        "anchored_joystick",
        "json_dev_width",
        "json_dev_height",
        "json_dev_dpi",
        "deadzone",
        "hysteresis",
        "sensitivity_x",
        "sensitivity_y",
        "toggle_key",
        "sprint_key",
        "adb_rate_cap",
        "pps_alert_threshold",
        "active_layout_id",
        "typematic_enabled",
        "typematic_delay_ms",
        "typematic_rate_hz",
        "typematic_excluded_keys",
        "double_tap_enabled",
        "bezel_toggle_enabled",
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
                "INSERT INTO app_settings (id, active_layout_id, typematic_excluded_keys) "
                f"VALUES (1, ?, {EXCLUDED_KEYS});",
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

    def create(self, auto_seed_bezels: bool = True, **fields: Any) -> Layout:
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

        # --- Auto-Seed System Bezels for fresh layouts ---
        if auto_seed_bezels:
            self._auto_seed_bezels(layout)
        return layout

    @staticmethod
    def _auto_seed_bezels(
        layout: Layout,
        top_dp_thickness: float | None = None,
        bottom_dp_thickness: float | None = None,
    ):
        zones_repo = LayoutZonesRepository()
        ensure_top_bezel(layout, zones_repo, top_dp_thickness)
        ensure_bottom_bezel(layout, zones_repo, bottom_dp_thickness)

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
            auto_seed_bezels=False,  # Prevent double-seeding, we will copy them below
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
                pipeline_json=zone.pipeline_json,
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
        "ignore_app_settings",
        "pipeline_json",
    }

    VALID_ZONE_TYPES = {BEZEL, CIRCLE, RECTANGLE}
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
        fields.setdefault("ignore_app_settings", False)
        fields.setdefault("pipeline_json", "{}")

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

    def delete(self, zone_id: int, delete_bezel=False) -> None:
        delete_zone = True

        if not delete_bezel:
            zone = self.get(zone_id)
            if zone is not None and zone.zone_type == BEZEL:
                delete_zone = False

        if delete_zone:
            conn = connection_manager.get_connection()
            with conn:
                conn.execute("DELETE FROM layout_zones WHERE id = ?;", (zone_id,))

        else:
            print(
                f"[!] Could not delete zone because deletion of 'zone type: {BEZEL}' is forbidden by the caller."
            )

    def delete_all_for_layout(self, layout_id: int, auto_seed_bezels=True) -> None:
        layouts_repo = LayoutsRepository()
        layout = layouts_repo.get(layout_id)

        top_bezel_dp_thickness = float(BEZEL_DP_THICKNESS)
        bottom_bezel_dp_thickness = float(BEZEL_DP_THICKNESS)

        if auto_seed_bezels:
            zones = self.list_for_layout(layout_id)
            top_id, bottom_id = bezels_exist_ids(zones)

            top_zone = self.get(top_id)
            if top_zone is not None and layout is not None:
                top_bezel_dp_thickness, _ = get_bezel_thicknesses(top_zone, layout)

            bottom_zone = self.get(bottom_id)
            if bottom_zone is not None and layout is not None:
                bottom_bezel_dp_thickness, _ = get_bezel_thicknesses(
                    bottom_zone, layout
                )

        conn = connection_manager.get_connection()
        with conn:
            conn.execute("DELETE FROM layout_zones WHERE layout_id = ?;", (layout_id,))

        if auto_seed_bezels:
            if layout is not None:
                layouts_repo._auto_seed_bezels(
                    layout, top_bezel_dp_thickness, bottom_bezel_dp_thickness
                )
