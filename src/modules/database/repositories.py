"""Typed repository classes over the SQLite database schema.

Validates field names against an explicit ALLOWED_FIELDS set before executing SQL.
"""

from __future__ import annotations

import json
import logging
import math
import sqlite3
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
    MAX_BEZEL_DP,
    MAX_PRIORITY,
    MIN_BEZEL_DP,
    MIN_PRIORITY,
    RECTANGLE,
    TOP_BEZEL_ID,
    TOP_BEZEL_NAME,
    MOUSE_WHEEL_SIMULATOR_CODE,
    calculate_rect,
    clamp,
    dp_to_px,
)
from modules.core.pipeline import PipelineConfig
from .connection import connection_manager

if TYPE_CHECKING:
    from . import AppSettings, Layout, LayoutZone

logger = logging.getLogger("modules.database.repository")


class DuplicateNameError(ValueError):
    """Raised when a layout name collides with the UNIQUE constraint on layouts.name."""


def _translate_integrity_error(exc: sqlite3.IntegrityError) -> Exception:
    msg = str(exc)
    if "UNIQUE" in msg and "layouts.name" in msg:
        return DuplicateNameError("A layout with that name already exists.")
    return exc


def _close(a: Optional[float], b: Optional[float], tol: float = 1e-6) -> bool:
    if a is None or b is None:
        return a is None and b is None
    return math.isclose(float(a), float(b), abs_tol=tol)


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
    toggle_hotkeys: Optional[str]
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
        "toggle_hotkeys",
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
                conn.execute(
                    "INSERT OR IGNORE INTO app_settings (id, typematic_excluded_keys) VALUES (1, ?);",
                    (EXCLUDED_KEYS,),
                )
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

    def wipe_database(self) -> None:
        conn = connection_manager.get_connection()

        with conn:
            conn.execute("DELETE FROM layout_zones;")
            conn.execute("DELETE FROM layouts;")
            conn.execute("DELETE FROM app_settings WHERE id = 1;")

            # Match the existing reset_to_defaults() defaults,
            # but clear the active profile as part of this transaction.
            conn.execute(
                """
                INSERT INTO app_settings (
                    id,
                    active_layout_id,
                    typematic_excluded_keys,
                    profile_sort_order
                )
                VALUES (1, NULL, ?, 'Recently Modified');
                """,
                (EXCLUDED_KEYS,),
            )


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

    def name_exists(self, name: str, exclude_id: int | None = None) -> bool:
        """True if another layout (not `exclude_id`) already uses this name."""
        found = self.get_by_name(name)
        return found is not None and found.id != exclude_id

    # ------------------------------------------------------------------
    # Low-level helpers that run inside a caller-owned transaction
    # ------------------------------------------------------------------
    def _validate_create_fields(self, fields: dict[str, Any]) -> None:
        unknown = set(fields) - self.ALLOWED_FIELDS
        if unknown:
            raise InvalidFieldError(f"Unknown layouts field(s): {sorted(unknown)}")
        missing = self._REQUIRED_ON_CREATE - set(fields)
        if missing:
            raise ValueError(f"Missing required layout field(s): {sorted(missing)}")

    def _insert_layout(self, conn: sqlite3.Connection, fields: dict[str, Any]) -> int:
        self._validate_create_fields(fields)
        fields.setdefault("mouse_wheel_radius", 50.0)
        fields.setdefault("sprint_distance", 10.0)
        fields.setdefault("image_path", None)
        columns = ", ".join(fields)
        placeholders = ", ".join(f":{key}" for key in fields)
        cursor = conn.execute(
            f"INSERT INTO layouts ({columns}) VALUES ({placeholders});", fields
        )
        return int(cursor.lastrowid)  # type: ignore[arg-type]

    def _update_layout(
        self, conn: sqlite3.Connection, layout_id: int, fields: dict[str, Any]
    ) -> None:
        unknown = set(fields) - self.ALLOWED_FIELDS
        if unknown:
            raise InvalidFieldError(f"Unknown layouts field(s): {sorted(unknown)}")
        params = dict(fields)
        params["id"] = layout_id
        assignments = [f"{key} = :{key}" for key in fields]
        assignments.append("updated_at = datetime('now')")
        cursor = conn.execute(
            f"UPDATE layouts SET {', '.join(assignments)} WHERE id = :id;", params
        )
        if cursor.rowcount == 0:
            raise KeyError(f"No layout with id={layout_id}.")

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def create(self, auto_seed: bool = True, **fields: Any) -> Layout:
        conn = connection_manager.get_connection()
        try:
            with conn:
                new_id = self._insert_layout(conn, fields)
        except sqlite3.IntegrityError as exc:
            raise _translate_integrity_error(exc) from exc

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

        conn = connection_manager.get_connection()
        try:
            with conn:
                self._update_layout(conn, layout_id, fields)
        except sqlite3.IntegrityError as exc:
            raise _translate_integrity_error(exc) from exc

        layout = self.get(layout_id)
        if layout is None:
            raise KeyError(f"No layout with id={layout_id}.")
        return layout

    def apply_image_params(
        self,
        layout_id: int,
        width: int,
        height: int,
        dpi: int,
        image_path: Optional[str],
    ) -> Layout:
        """Atomically stores new canvas params. If the resolution changed, rescales
        every non-bezel zone plus mouse_wheel_radius/sprint_distance in the same
        transaction. Writes nothing (and leaves updated_at alone) if nothing changed."""
        conn = connection_manager.get_connection()
        with conn:
            row = conn.execute(
                "SELECT * FROM layouts WHERE id = ?;", (layout_id,)
            ).fetchone()
            if row is None:
                raise KeyError(f"No layout with id={layout_id}.")

            old_w, old_h = int(row["width"]), int(row["height"])
            unchanged = (
                old_w == width
                and old_h == height
                and int(row["dpi"]) == dpi
                and row["image_path"] == image_path
            )
            if unchanged:
                return Layout.from_row(row)

            radius = float(row["mouse_wheel_radius"])
            sprint = float(row["sprint_distance"])

            if old_w > 0 and old_h > 0 and (old_w != width or old_h != height):
                sx = width / old_w
                sy = height / old_h
                sr = min(sx, sy)
                conn.execute(
                    "UPDATE layout_zones SET "
                    "cx = ROUND(cx * :sx), cy = ROUND(cy * :sy), r = ROUND(r * :sr), "
                    "x1 = ROUND(x1 * :sx), y1 = ROUND(y1 * :sy), "
                    "x2 = ROUND(x2 * :sx), y2 = ROUND(y2 * :sy), "
                    "updated_at = datetime('now') "
                    "WHERE layout_id = :id AND zone_type != 'BEZEL';",
                    {"sx": sx, "sy": sy, "sr": sr, "id": layout_id},
                )
                radius = round(radius * sr)
                sprint = round(sprint * sr)

            self._update_layout(
                conn,
                layout_id,
                {
                    "width": width,
                    "height": height,
                    "dpi": dpi,
                    "image_path": image_path,
                    "mouse_wheel_radius": radius,
                    "sprint_distance": sprint,
                },
            )

            new_row = conn.execute(
                "SELECT * FROM layouts WHERE id = ?;", (layout_id,)
            ).fetchone()
            LayoutZonesRepository()._resync_bezels_in_txn(
                conn, Layout.from_row(new_row)
            )

        layout = self.get(layout_id)
        if layout is None:
            raise KeyError(f"No layout with id={layout_id}.")
        return layout

    def save_with_zones(
        self,
        layout_id: Optional[int],
        layout_fields: dict[str, Any],
        top_bezel_dp: int,
        bottom_bezel_dp: int,
        zones: list[dict[str, Any]],
    ) -> Layout:
        """Atomic save: create-or-update the layout row, then replace ALL of its zones
        (both bezels + `zones`) in ONE transaction. Any failure rolls everything back.

        layout_id=None creates a new layout (layout_fields must hold name/width/height/dpi).
        """
        zones_repo = LayoutZonesRepository()
        conn = connection_manager.get_connection()
        try:
            with conn:
                if layout_id is None:
                    target_id = self._insert_layout(conn, dict(layout_fields))
                else:
                    target_id = layout_id
                    self._update_layout(conn, target_id, dict(layout_fields))

                row = conn.execute(
                    "SELECT * FROM layouts WHERE id = ?;", (target_id,)
                ).fetchone()
                if row is None:
                    raise KeyError(f"No layout with id={target_id}.")
                layout = Layout.from_row(row)

                conn.execute(
                    "DELETE FROM layout_zones WHERE layout_id = ?;", (target_id,)
                )
                zones_repo._insert_bezels_and_zones(
                    conn, layout, top_bezel_dp, bottom_bezel_dp, zones
                )
        except sqlite3.IntegrityError as exc:
            raise _translate_integrity_error(exc) from exc
        return layout

    def delete(self, layout_id: int) -> None:
        conn = connection_manager.get_connection()
        with conn:
            conn.execute("DELETE FROM layouts WHERE id = ?;", (layout_id,))

    def delete_profile(self, layout_id: int) -> bool:
        conn = connection_manager.get_connection()

        with conn:
            exists = conn.execute(
                "SELECT 1 FROM layouts WHERE id = ?;",
                (layout_id,),
            ).fetchone()

            if exists is None:
                return False

            # Remove the active reference before deleting the layout.
            conn.execute(
                """
                UPDATE app_settings
                SET active_layout_id = NULL,
                    updated_at = datetime('now')
                WHERE id = 1 AND active_layout_id = ?;
                """,
                (layout_id,),
            )

            conn.execute(
                "DELETE FROM layout_zones WHERE layout_id = ?;",
                (layout_id,),
            )
            conn.execute(
                "DELETE FROM layouts WHERE id = ?;",
                (layout_id,),
            )

        return True

    def delete_all(self) -> None:
        conn = connection_manager.get_connection()
        with conn:
            conn.execute("DELETE FROM layouts;")

    def duplicate(self, layout_id: int, new_name: str) -> Layout:
        """Atomic: the new layout and all of its zones are created in one transaction."""
        conn = connection_manager.get_connection()
        try:
            with conn:
                row = conn.execute(
                    "SELECT * FROM layouts WHERE id = ?;", (layout_id,)
                ).fetchone()
                if row is None:
                    raise KeyError(f"No layout with id={layout_id}")

                new_id = self._insert_layout(
                    conn,
                    {
                        "name": new_name,
                        "width": row["width"],
                        "height": row["height"],
                        "dpi": row["dpi"],
                        "mouse_wheel_radius": row["mouse_wheel_radius"],
                        "sprint_distance": row["sprint_distance"],
                        "image_path": row["image_path"],
                    },
                )
                conn.execute(
                    "INSERT INTO layout_zones (layout_id, scancode, name, zone_type, "
                    "cx, cy, r, x1, y1, x2, y2, ignore_app_settings, pipeline_json) "
                    "SELECT ?, scancode, name, zone_type, cx, cy, r, x1, y1, x2, y2, "
                    "ignore_app_settings, pipeline_json "
                    "FROM layout_zones WHERE layout_id = ? ORDER BY id;",
                    (new_id, layout_id),
                )
        except sqlite3.IntegrityError as exc:
            raise _translate_integrity_error(exc) from exc

        new_layout = self.get(new_id)
        if new_layout is None:
            raise KeyError("Error duplicating layout.")
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

    def count_by_layout(self) -> dict[int, int]:
        """Non-bezel zone counts for every layout in ONE query (no per-layout N+1, no auto-heal)."""
        conn = connection_manager.get_connection()
        rows = conn.execute(
            "SELECT layout_id, COUNT(*) AS n FROM layout_zones "
            "WHERE zone_type != ? GROUP BY layout_id;",
            (BEZEL,),
        ).fetchall()
        return {int(r["layout_id"]): int(r["n"]) for r in rows}

    @staticmethod
    def _normalise_pipeline(pipeline_json: str) -> str:
        """Clamps region priority and bezel dp to the supported ranges.

        Returns the input untouched when it is unparseable, has no region, or is already
        in range, so well-formed JSON is never rewritten (and `{}` never gains idx -1).
        """
        p_cfg = PipelineConfig()
        p_cfg.set_pipeline_config_from_json(pipeline_json)
        region = p_cfg.pipeline_config.get("region")
        if not isinstance(region, dict):
            return pipeline_json

        try:
            dp = int(float(region.get("bezel_dp_thickness", BEZEL_DP_THICKNESS)))
            prio = int(region.get("priority", 0))
        except (TypeError, ValueError):
            return pipeline_json

        new_dp = clamp(dp, MIN_BEZEL_DP, MAX_BEZEL_DP)
        new_prio = clamp(prio, MIN_PRIORITY, MAX_PRIORITY)
        if new_dp == dp and new_prio == prio:
            return pipeline_json

        logger.warning(
            "Clamped pipeline values: bezel_dp %s -> %s, priority %s -> %s",
            dp,
            new_dp,
            prio,
            new_prio,
        )
        region["bezel_dp_thickness"] = new_dp
        region["priority"] = new_prio
        return p_cfg.get_pipeline_json_from_config()

    def _insert(self, conn: sqlite3.Connection, fields: dict[str, Any]) -> int:
        """Validated INSERT that runs inside the caller's transaction (no commit)."""
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
        fields["pipeline_json"] = self._normalise_pipeline(fields["pipeline_json"])

        columns = ", ".join(fields)
        placeholders = ", ".join(f":{key}" for key in fields)
        cursor = conn.execute(
            f"INSERT INTO layout_zones ({columns}) VALUES ({placeholders});", fields
        )
        return int(cursor.lastrowid)  # type: ignore[arg-type]

    def create(self, **fields: Any) -> LayoutZone:
        conn = connection_manager.get_connection()
        with conn:
            new_id = self._insert(conn, fields)

        zone = self.get(new_id)
        if zone is None:
            raise KeyError("Error creating zone.")
        return zone

    def _insert_bezels_and_zones(
        self,
        conn: sqlite3.Connection,
        layout: Layout,
        top_bezel_dp: int,
        bottom_bezel_dp: int,
        zones: list[dict[str, Any]],
    ) -> None:
        self._insert(
            conn,
            self._bezel_fields(
                layout, TOP_BEZEL_ID, TOP_BEZEL_NAME, True, int(top_bezel_dp)
            ),
        )
        self._insert(
            conn,
            self._bezel_fields(
                layout, BOTTOM_BEZEL_ID, BOTTOM_BEZEL_NAME, False, int(bottom_bezel_dp)
            ),
        )
        for zone_fields in zones:
            fields = dict(zone_fields)
            fields["layout_id"] = layout.id
            self._insert(conn, fields)

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

        if "pipeline_json" in fields:
            fields["pipeline_json"] = self._normalise_pipeline(fields["pipeline_json"])

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

    def clear_non_bezel_zones(self, layout_id: int) -> None:
        conn = connection_manager.get_connection()

        with conn:
            conn.execute(
                """
                DELETE FROM layout_zones
                WHERE layout_id = ?
                  AND zone_type != ?;
                """,
                (layout_id, BEZEL),
            )

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
        """Guarantees the existence of top and bottom bezels in the layout while removing all duplicates of each.

        Returns True only if rows were created or deleted. Re-syncing an existing bezel's
        geometry is a no-op write when nothing differs, so reads no longer bump updated_at.
        """
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

        # Clamp the dp value itself so the stored dp and the computed px always agree.
        dp_thickness = clamp(dp_thickness, MIN_BEZEL_DP, MAX_BEZEL_DP)

        thickness_px = float(dp_to_px(dp_thickness, layout.dpi))
        y1 = 0.0 if is_top else layout.height - thickness_px
        y2 = thickness_px if is_top else layout.height
        cx, cy, _x1, _y1, _x2, _y2 = calculate_rect(0.0, y1, layout.width, y2)

        return cx, cy, _x1, _y1, _x2, _y2, dp_thickness

    def _bezel_fields(
        self,
        layout: Layout,
        scancode: int,
        name: str,
        is_top: bool,
        thickness_dp: int | None = None,
    ) -> dict[str, Any]:
        cx, cy, _x1, _y1, _x2, _y2, dp_thickness = self._calculate_native_bezel(
            layout, is_top, thickness_dp
        )

        p_cfg = PipelineConfig()
        p_cfg.set_pipeline_config_from_json(_DEFAULT_BEZEL_PIPELINE_JSON)
        p_cfg.set_region_config(bezel_dp_thickness=dp_thickness)

        return {
            "layout_id": layout.id,
            "scancode": scancode,
            "name": name,
            "zone_type": BEZEL,
            "cx": cx,
            "cy": cy,
            "r": None,
            "x1": _x1,
            "y1": _y1,
            "x2": _x2,
            "y2": _y2,
            "pipeline_json": p_cfg.get_pipeline_json_from_config(),
        }

    def create_bezel(
        self,
        layout: Layout,
        scancode: int,
        name: str,
        is_top: bool,
        thickness_dp: int | None = None,
    ) -> int:
        """If thickness dp is None it uses the default BEZEL_DP_THICKNESS."""
        created_bezel_zone = self.create(
            **self._bezel_fields(layout, scancode, name, is_top, thickness_dp)
        )
        created_bezel_zone.set_parsed_config_from_json()
        return created_bezel_zone.id

    @staticmethod
    def _bezel_unchanged(
        zone: LayoutZone,
        cx: float,
        cy: float,
        x1: float,
        y1: float,
        x2: float,
        y2: float,
        new_json: str,
    ) -> bool:
        if zone.r is not None:
            return False
        if not (
            _close(zone.cx, cx)
            and _close(zone.cy, cy)
            and _close(zone.x1, x1)
            and _close(zone.y1, y1)
            and _close(zone.x2, x2)
            and _close(zone.y2, y2)
        ):
            return False
        try:
            return json.loads(zone.pipeline_json) == json.loads(new_json)
        except (TypeError, ValueError):
            return False

    def update_bezel(
        self,
        layout: Layout,
        zone: LayoutZone,
        is_top: bool,
        thickness_dp: int | None = None,
    ):
        """If thickness_dp is None, it uses the parsed dp thickness from its region config.

        Skips the write entirely when geometry and config already match.
        """
        zone.set_parsed_config_from_json()

        if thickness_dp is None:
            _, _, _dp_thickness, _ = zone.CONFIG_HELPER.get_region_config()
            thickness_dp = int(_dp_thickness)

        cx, cy, _x1, _y1, _x2, _y2, dp_thickness = self._calculate_native_bezel(
            layout, is_top, thickness_dp
        )

        zone.CONFIG_HELPER.set_region_config(bezel_dp_thickness=dp_thickness)
        new_json = zone.CONFIG_HELPER.get_pipeline_json_from_config()

        if self._bezel_unchanged(zone, cx, cy, _x1, _y1, _x2, _y2, new_json):
            return zone.id

        return self.update(
            zone_id=zone.id,
            cx=cx,
            cy=cy,
            r=None,
            x1=_x1,
            y1=_y1,
            x2=_x2,
            y2=_y2,
            pipeline_json=new_json,
        ).id

    def _resync_bezels_in_txn(self, conn: sqlite3.Connection, layout: Layout) -> None:
        """Recomputes bezel geometry from `layout` using the caller's transaction (no commit)."""
        rows = conn.execute(
            "SELECT * FROM layout_zones WHERE layout_id = ? AND zone_type = ?;",
            (layout.id, BEZEL),
        ).fetchall()
        for row in rows:
            zone = LayoutZone.from_row(row)
            if zone.scancode == TOP_BEZEL_ID:
                is_top = True
            elif zone.scancode == BOTTOM_BEZEL_ID:
                is_top = False
            else:
                continue

            zone.set_parsed_config_from_json()
            _, _, dp, _ = zone.CONFIG_HELPER.get_region_config()
            cx, cy, x1, y1, x2, y2, dp = self._calculate_native_bezel(
                layout, is_top, int(dp)
            )
            zone.CONFIG_HELPER.set_region_config(bezel_dp_thickness=dp)
            new_json = zone.CONFIG_HELPER.get_pipeline_json_from_config()

            if self._bezel_unchanged(zone, cx, cy, x1, y1, x2, y2, new_json):
                continue
            conn.execute(
                "UPDATE layout_zones SET cx = ?, cy = ?, r = NULL, x1 = ?, y1 = ?, "
                "x2 = ?, y2 = ?, pipeline_json = ?, updated_at = datetime('now') "
                "WHERE id = ?;",
                (cx, cy, x1, y1, x2, y2, new_json, zone.id),
            )

    def get_mouse_wheel_zone(self, layout: Layout) -> Optional[LayoutZone]:
        current_zones = self.list_for_layout(layout.id, False)
        mouse_wheel_zone: Optional[LayoutZone] = None

        for zone in current_zones:
            if zone.scancode == MOUSE_WHEEL_SIMULATOR_CODE:
                mouse_wheel_zone = zone
                break

        return mouse_wheel_zone

    def get_mouse_wheel_directional_scancodes(self, layout: Optional[Layout]):
        W = 0x11
        A = 0x1E
        S = 0x1F
        D = 0x20

        def_ret = int(W), int(A), int(S), int(D)

        if layout is None:
            return def_ret

        mouse_wheel_zone: Optional[LayoutZone] = self.get_mouse_wheel_zone(layout)

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

    def set_mouse_wheel_directional_scancodes(
        self, layout: Optional[Layout], direction_id: int, direction_value: int
    ) -> bool:
        """`direction_map` {0: 'up', 1: 'left', 2: 'down', 3: 'right'}"""
        if layout is None:
            return False

        mouse_wheel_zone: Optional[LayoutZone] = self.get_mouse_wheel_zone(layout)
        if mouse_wheel_zone is None:
            return False

        direction_map = {0: "up", 1: "left", 2: "down", 3: "right"}
        mouse_wheel_zone.set_parsed_config_from_json()
        zone_json = mouse_wheel_zone.CONFIG_HELPER.pipeline_config

        direction = direction_map.get(direction_id)
        if direction is None:
            return False

        zone_json.update({direction: direction_value})

        self.update(
            mouse_wheel_zone.id,
            pipeline_json=mouse_wheel_zone.CONFIG_HELPER.get_pipeline_json_from_config(),
        )
        return True
