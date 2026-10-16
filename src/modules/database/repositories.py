"""Typed repository classes over the SQLite database schema.

Validates field names against an explicit ALLOWED_FIELDS set before executing SQL.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field, fields as dataclass_fields
from typing import Any, Optional, TYPE_CHECKING

from modules.utils import (
    BEZEL,
    BEZEL_DP_THICKNESS,
    BOTTOM_BEZEL_ID,
    BOTTOM_BEZEL_NAME,
    CIRCLE,
    EXCLUDED_KEYS,
    InvalidFieldError,
    RECTANGLE,
    TOP_BEZEL_ID,
    TOP_BEZEL_NAME,
    MOUSE_WHEEL_SIMULATOR_CODE,
    calculate_rect,
    dp_to_px,
)
from modules.core.pipeline import PipelineConfig
from .connection import connection_manager

if TYPE_CHECKING:
    from . import AppSettings, Layout, LayoutZone

logger = logging.getLogger("modules.database.repository")

# NATIVE Repository DEFAULT TEMPLATE
_DEFAULT_BEZEL_PIPELINE_JSON = json.dumps(
    {
        "region": {
            "idx": 2,
            "mode": "RECTANGULAR",
            "bezel_dp_thickness": BEZEL_DP_THICKNESS,
            "priority": 100,
        },
        "origin": {"idx": 0, "mode": "FIXED"},
        "constraint": {"idx": 0, "mode": "NONE"},
        "transform": {
            "idx": 0,
            "mode": "IDENTITY",
            "sensitivity_x": 1.0,
            "sensitivity_y": 1.0,
            "deadzone": 0.1,
            "hysteresis": 5.0,
        },
        "semantic": {"idx": 3, "mode": "TOGGLE", "pointer": False},
    }
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
    two_finger_tap_enabled: bool
    bezel_toggle_enabled: bool
    profile_sort_order: str = "Recently Modified"
    created_at: str | None = None
    updated_at: str | None = None

    @classmethod
    def from_row(cls, row) -> AppSettings:
        d = dict(row)
        d["left_handed"] = bool(d["left_handed"])
        d["floating_joystick"] = bool(d["floating_joystick"])
        d["anchored_joystick"] = bool(d["anchored_joystick"])
        d["typematic_enabled"] = bool(d["typematic_enabled"])
        d["two_finger_tap_enabled"] = bool(d["two_finger_tap_enabled"])
        d["bezel_toggle_enabled"] = bool(d["bezel_toggle_enabled"])
        d["profile_sort_order"] = str(d.get("profile_sort_order", "Recently Modified"))
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
    scancode: int
    name: str
    zone_type: str
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

    CONFIG_HELPER: PipelineConfig = field(
        default_factory=PipelineConfig, init=False, repr=False
    )

    def set_parsed_config_from_json(self) -> None:
        if self.CONFIG_HELPER.should_get_config:
            self.CONFIG_HELPER.set_pipeline_config_from_json(self.pipeline_json)

    @property
    def priority(self) -> int:
        self.set_parsed_config_from_json()
        _, _, _, priority = self.CONFIG_HELPER.get_region_config()
        return priority

    @property
    def pointer(self) -> bool:
        self.set_parsed_config_from_json()
        _, _, pointer = self.CONFIG_HELPER.get_semantic_config()
        return pointer

    def get_bezel_thickness_px(self, dpi: int) -> float:
        """Returns the pixel thickness of the bezel directly from the parsed JSON data."""
        self.set_parsed_config_from_json()
        _, _, dp_thickness, _ = self.CONFIG_HELPER.get_region_config()
        return float(dp_to_px(dp_thickness, dpi))

    @classmethod
    def from_row(cls, row) -> LayoutZone:
        data = {
            f.name: row[f.name]
            for f in dataclass_fields(cls)
            if f.init and f.name in row.keys()
        }
        data["ignore_app_settings"] = bool(data.get("ignore_app_settings", False))
        data["pipeline_json"] = (
            str(row["pipeline_json"]) if "pipeline_json" in row.keys() else "{}"
        )
        return cls(**data)


class AppSettingsRepository:
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
        "two_finger_tap_enabled",
        "bezel_toggle_enabled",
        "profile_sort_order",
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
                "INSERT INTO app_settings (id, active_layout_id, typematic_excluded_keys, profile_sort_order) "
                "VALUES (1, ?, ?, 'Recently Modified');",
                (active_layout_id, EXCLUDED_KEYS),
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

    def create(self, auto_seed: bool = True, **fields: Any) -> Layout:
        unknown = set(fields) - self.ALLOWED_FIELDS
        if unknown:
            raise InvalidFieldError(f"Unknown layouts field(s): {sorted(unknown)}")
        missing = self._REQUIRED_ON_CREATE - set(fields)
        if missing:
            raise ValueError(f"Missing required layout field(s): {sorted(missing)}")

        fields.setdefault("mouse_wheel_radius", 50.0)
        fields.setdefault("sprint_distance", 10.0)
        fields.setdefault("image_path", None)
        columns = ", ".join(fields)
        placeholders = ", ".join(f":{key}" for key in fields)

        conn = connection_manager.get_connection()
        with conn:
            cursor = conn.execute(
                f"INSERT INTO layouts ({columns}) VALUES ({placeholders});", fields
            )
            new_id = cursor.lastrowid

        layout = self.get(new_id)
        if layout is None:
            raise KeyError("Error creating layout.")

        if auto_seed:
            zones_repo = LayoutZonesRepository()
            zones_repo.ensure_bezels(layout)
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
            raise KeyError(f"No layout with id={layout_id}.")
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
            auto_seed=False,
            name=new_name,
            width=source.width,
            height=source.height,
            dpi=source.dpi,
            mouse_wheel_radius=source.mouse_wheel_radius,
            sprint_distance=source.sprint_distance,
            image_path=source.image_path,
        )

        zones_repo = LayoutZonesRepository()
        for zone in zones_repo.list_for_layout(layout_id, auto_heal=False):
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
                ignore_app_settings=zone.ignore_app_settings,
                pipeline_json=zone.pipeline_json,
            )
        return new_layout


class LayoutZonesRepository:
    ALLOWED_CREATE_FIELDS = {
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

    ALLOWED_UPDATE_FIELDS = set(ALLOWED_CREATE_FIELDS) - set({"layout_id", "scancode"})

    VALID_ZONE_TYPES = {BEZEL, CIRCLE, RECTANGLE}
    _REQUIRED_ON_CREATE = {"layout_id", "scancode", "zone_type"}

    def get(self, zone_id: int | None) -> Optional[LayoutZone]:
        if zone_id is None:
            return None
        conn = connection_manager.get_connection()
        row = conn.execute(
            "SELECT * FROM layout_zones WHERE id = ?;", (zone_id,)
        ).fetchone()
        return LayoutZone.from_row(row) if row is not None else None

    def create(self, **fields: Any) -> LayoutZone:
        unknown = set(fields) - self.ALLOWED_CREATE_FIELDS
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
                f"INSERT INTO layout_zones ({columns}) VALUES ({placeholders});",
                fields,
            )
            new_id = cursor.lastrowid

        zone = self.get(new_id)
        if zone is None:
            raise KeyError("Error creating zone.")
        return zone

    def update(self, zone_id: int, **fields: Any) -> LayoutZone:
        unknown = set(fields) - self.ALLOWED_UPDATE_FIELDS
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
                f"UPDATE layout_zones SET {set_clause}, updated_at = datetime('now') WHERE id = :id;",
                params,
            )

        zone = self.get(zone_id)
        if zone is None:
            raise KeyError(f"No zone with id={zone_id}.")
        return zone

    def delete(self, zone_id: int, delete_bezel: bool = False) -> None:
        if not delete_bezel:
            zone = self.get(zone_id)
            if zone is not None and zone.zone_type == BEZEL:
                logger.warning(
                    "Could not delete zone %s because deletion of 'zone type: %s' is forbidden by caller.",
                    zone_id,
                    BEZEL,
                )
                return

        self._force_delete(zone_id)

    def _force_delete(self, zone_id: int) -> None:
        conn = connection_manager.get_connection()
        with conn:
            conn.execute("DELETE FROM layout_zones WHERE id = ?;", (zone_id,))

    def delete_all_for_layout(self, layout_id: int) -> None:
        conn = connection_manager.get_connection()
        with conn:
            conn.execute("DELETE FROM layout_zones WHERE layout_id = ?;", (layout_id,))

    def list_for_layout(
        self, layout_id: int, auto_heal: bool = True
    ) -> list[LayoutZone]:
        conn = connection_manager.get_connection()
        rows = conn.execute(
            "SELECT * FROM layout_zones WHERE layout_id = ? ORDER BY id;", (layout_id,)
        ).fetchall()
        zones = [LayoutZone.from_row(row) for row in rows]

        if auto_heal:
            layouts_repo = LayoutsRepository()
            layout = layouts_repo.get(layout_id)
            if layout and self.ensure_bezels(layout, zones):
                rows = conn.execute(
                    "SELECT * FROM layout_zones WHERE layout_id = ? ORDER BY id;",
                    (layout_id,),
                ).fetchall()
                zones = [LayoutZone.from_row(row) for row in rows]

        return zones

    def ensure_bezels(
        self, layout: Layout, current_zones: list[LayoutZone] | None = None
    ) -> bool:
        """Guarantees the existence of top and bottom bezels in the layout while removing all duplicates of each."""
        if current_zones is None:
            conn = connection_manager.get_connection()
            rows = conn.execute(
                "SELECT * FROM layout_zones WHERE layout_id = ? ORDER BY id;",
                (layout.id,),
            ).fetchall()
            current_zones = [LayoutZone.from_row(row) for row in rows]

        healed = False
        top_bezels = [
            z
            for z in current_zones
            if z.scancode == TOP_BEZEL_ID and z.zone_type == BEZEL
        ]
        bottom_bezels = [
            z
            for z in current_zones
            if z.scancode == BOTTOM_BEZEL_ID and z.zone_type == BEZEL
        ]

        if top_bezels:
            top_bezel = top_bezels[0]
            self.update_bezel(layout, top_bezel, True)

            for dup in top_bezels[1:]:
                self._force_delete(dup.id)
                healed = True
        else:
            self.create_bezel(layout, TOP_BEZEL_ID, TOP_BEZEL_NAME, True)
            healed = True

        if bottom_bezels:
            bottom_bezel = bottom_bezels[0]
            self.update_bezel(layout, bottom_bezel, False)

            for dup in bottom_bezels[1:]:
                self._force_delete(dup.id)
                healed = True
        else:
            self.create_bezel(layout, BOTTOM_BEZEL_ID, BOTTOM_BEZEL_NAME, False)
            healed = True

        return healed

    def _calculate_native_bezel(
        self, layout: Layout, is_top: bool, thickness_dp: int | None = None
    ):
        if thickness_dp is not None:
            dp_thickness = thickness_dp
        else:
            dp_thickness = BEZEL_DP_THICKNESS

        thickness_px = float(dp_to_px(max(1, min(100, dp_thickness)), layout.dpi))
        y1 = 0.0 if is_top else layout.height - thickness_px
        y2 = thickness_px if is_top else layout.height
        cx, cy, _x1, _y1, _x2, _y2 = calculate_rect(0.0, y1, layout.width, y2)

        return cx, cy, _x1, _y1, _x2, _y2, dp_thickness

    def create_bezel(
        self,
        layout: Layout,
        scancode: int,
        name: str,
        is_top: bool,
        thickness_dp: int | None = None,
    ) -> int:
        """If thickness dp is None it uses the default BEZEL_DP_THICKNESS."""
        cx, cy, _x1, _y1, _x2, _y2, dp_thickness = self._calculate_native_bezel(
            layout, is_top, thickness_dp
        )

        p_cfg = PipelineConfig()
        p_cfg.set_pipeline_config_from_json(_DEFAULT_BEZEL_PIPELINE_JSON)
        p_cfg.set_region_config(bezel_dp_thickness=dp_thickness)

        created_bezel_zone = self.create(
            layout_id=layout.id,
            scancode=scancode,
            name=name,
            zone_type=BEZEL,
            cx=cx,
            cy=cy,
            r=None,
            x1=_x1,
            y1=_y1,
            x2=_x2,
            y2=_y2,
            pipeline_json=p_cfg.get_pipeline_json_from_config(),
        )

        created_bezel_zone.set_parsed_config_from_json()
        return created_bezel_zone.id

    def update_bezel(
        self,
        layout: Layout,
        zone: LayoutZone,
        is_top: bool,
        thickness_dp: int | None = None,
    ):
        """If thickness_dp is None, it uses the parsed dp thickness from its region config."""
        zone.set_parsed_config_from_json()

        if thickness_dp is None:
            _, _, _dp_thickness, _ = zone.CONFIG_HELPER.get_region_config()
            thickness_dp = int(_dp_thickness)

        cx, cy, _x1, _y1, _x2, _y2, dp_thickness = self._calculate_native_bezel(
            layout, is_top, thickness_dp
        )

        zone.CONFIG_HELPER.set_region_config(bezel_dp_thickness=dp_thickness)

        return self.update(
            zone_id=zone.id,
            cx=cx,
            cy=cy,
            r=None,
            x1=_x1,
            y1=_y1,
            x2=_x2,
            y2=_y2,
            pipeline_json=zone.CONFIG_HELPER.get_pipeline_json_from_config(),
        ).id

    def get_mouse_wheel_directional_scancodes(self, layout: Optional[Layout]):
        W = 0x11
        A = 0x1E
        S = 0x1F
        D = 0x20

        def_ret = int(W), int(A), int(S), int(D)

        if layout is None:
            return def_ret

        current_zones = self.list_for_layout(layout.id, False)
        mouse_wheel_zone: Optional[LayoutZone] = None

        for zone in current_zones:
            if zone.scancode == MOUSE_WHEEL_SIMULATOR_CODE:
                mouse_wheel_zone = zone
                break

        if mouse_wheel_zone is None:
            return def_ret

        else:
            mouse_wheel_zone.set_parsed_config_from_json()
            zone_json = mouse_wheel_zone.CONFIG_HELPER.pipeline_config

            up = int(zone_json.get("up", W))
            left = int(zone_json.get("left", A))
            down = int(zone_json.get("down", S))
            right = int(zone_json.get("right", D))

            return up, left, down, right
