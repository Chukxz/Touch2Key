# REPOSITORIES.PY

"""
Typed repository classes over the sqlite schema. Each repository is
deliberately narrow (one table's worth of reads/writes) rather than one
big DAO, so core/ modules that only ever need settings don't have to
import layout/zone concerns to get them.

Every write method validates its own field names against an explicit
allow-list before building SQL, since these use dict-driven partial
updates (**fields) -- without the allow-list check, an unrecognized
kwarg would either raise a confusing sqlite OperationalError deep in a
string-built query or, worse, if ever refactored to string-format
column names instead of using bound parameters, become a SQL injection
surface. Keying off an explicit set closes that off structurally.
"""

from __future__ import annotations
from dataclasses import dataclass
from typing import Optional

from .connection import Database

# ---------------------------------------------------------------- settings --


@dataclass
class AppSettings:
    left_handed: bool = False
    json_dev_width: int = 360
    json_dev_height: int = 800
    json_dev_dpi: int = 160
    deadzone: float = 0.1
    hysteresis: float = 5.0
    sensitivity: float = 1.0
    toggle_key: Optional[str] = None
    sprint_key: Optional[str] = None
    adb_rate_cap: float = 125.0
    pps_alert_threshold: float = 60.0
    active_layout_id: Optional[int] = None

    # Compatibility helpers shaped like the old TOML sections, so
    # something like AppConfig.get("system") can wrap an AppSettings
    # instance and hand back the same dict shape core/ modules already
    # expect, without every consumer changing.
    def as_system_dict(self) -> dict:
        return {
            "left_handed": self.left_handed,
            "json_dev_res": [self.json_dev_width, self.json_dev_height],
            "json_dev_dpi": self.json_dev_dpi,
        }

    def as_joystick_dict(self) -> dict:
        return {"deadzone": self.deadzone, "hysteresis": self.hysteresis}

    def as_mouse_dict(self) -> dict:
        return {"sensitivity": self.sensitivity}


class AppSettingsRepository:
    _ALLOWED_FIELDS = {
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

    def __init__(self, db: Database):
        self.db = db

    def get(self) -> AppSettings:
        conn = self.db.connection
        conn.execute("INSERT OR IGNORE INTO app_settings (id) VALUES (1)")
        conn.commit()
        row = conn.execute("SELECT * FROM app_settings WHERE id = 1").fetchone()
        return AppSettings(
            left_handed=bool(row["left_handed"]),
            json_dev_width=row["json_dev_width"],
            json_dev_height=row["json_dev_height"],
            json_dev_dpi=row["json_dev_dpi"],
            deadzone=row["deadzone"],
            hysteresis=row["hysteresis"],
            sensitivity=row["sensitivity"],
            toggle_key=row["toggle_key"],
            sprint_key=row["sprint_key"],
            adb_rate_cap=row["adb_rate_cap"],
            pps_alert_threshold=row["pps_alert_threshold"],
            active_layout_id=row["active_layout_id"],
        )

    def update(self, **fields) -> None:
        """Partial update, e.g. repo.update(left_handed=True, sensitivity=1.5)."""
        unknown = set(fields) - self._ALLOWED_FIELDS
        if unknown:
            raise ValueError(f"Unknown app_settings field(s): {sorted(unknown)}")
        if not fields:
            return

        conn = self.db.connection
        conn.execute("INSERT OR IGNORE INTO app_settings (id) VALUES (1)")
        set_clause = ", ".join(f"{key} = :{key}" for key in fields)
        params = dict(fields)
        params["id"] = 1
        conn.execute(f"UPDATE app_settings SET {set_clause} WHERE id = :id", params)
        conn.commit()

    def reset_to_defaults(self) -> AppSettings:
        conn = self.db.connection
        conn.execute("DELETE FROM app_settings WHERE id = 1")
        conn.execute("INSERT INTO app_settings (id) VALUES (1)")
        conn.commit()
        return self.get()


# ----------------------------------------------------------------- layouts --


@dataclass
class Layout:
    id: int
    name: str
    width: int
    height: int
    dpi: int
    mouse_wheel_radius: float
    sprint_distance: float


_LAYOUT_COLUMNS = "id, name, width, height, dpi, mouse_wheel_radius, sprint_distance"


class LayoutRepository:
    def __init__(self, db: Database):
        self.db = db

    def list_all(self) -> list[Layout]:
        rows = self.db.connection.execute(
            f"SELECT {_LAYOUT_COLUMNS} FROM layouts ORDER BY name COLLATE NOCASE"
        ).fetchall()
        return [self._row_to_layout(r) for r in rows]

    def get(self, layout_id: int) -> Optional[Layout]:
        row = self.db.connection.execute(
            f"SELECT {_LAYOUT_COLUMNS} FROM layouts WHERE id = ?", (layout_id,)
        ).fetchone()
        return self._row_to_layout(row) if row else None

    def get_active(self) -> Optional[Layout]:
        row = self.db.connection.execute(f"""
            SELECT l.id, l.name, l.width, l.height, l.dpi,
                   l.mouse_wheel_radius, l.sprint_distance
            FROM layouts l
            JOIN app_settings s ON s.active_layout_id = l.id
            WHERE s.id = 1
            """).fetchone()
        return self._row_to_layout(row) if row else None

    def create(
        self,
        name: str,
        width: int,
        height: int,
        dpi: int,
        mouse_wheel_radius: float = 50.0,
        sprint_distance: float = 10.0,
    ) -> Layout:
        with self.db.transaction() as conn:
            cursor = conn.execute(
                "INSERT INTO layouts (name, width, height, dpi, mouse_wheel_radius, sprint_distance) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (name, width, height, dpi, mouse_wheel_radius, sprint_distance),
            )
            layout_id = cursor.lastrowid
        layout = self.get(layout_id)
        assert layout is not None  # just inserted; row must exist
        return layout

    def rename(self, layout_id: int, new_name: str) -> None:
        conn = self.db.connection
        conn.execute("UPDATE layouts SET name = ? WHERE id = ?", (new_name, layout_id))
        conn.commit()

    def delete(self, layout_id: int) -> None:
        """layout_zones cascade-deletes via ON DELETE CASCADE. If this
        was the active layout, app_settings.active_layout_id falls back
        to NULL via ON DELETE SET NULL rather than raising -- callers
        (GUI/CLI) should check get_active() after a delete and prompt
        the user to pick a replacement, since Mapper/JSONLoader assume
        a layout is always configured and will need that guarded."""
        conn = self.db.connection
        conn.execute("DELETE FROM layouts WHERE id = ?", (layout_id,))
        conn.commit()

    def duplicate(self, layout_id: int, new_name: str) -> Layout:
        source = self.get(layout_id)
        if source is None:
            raise ValueError(f"Layout {layout_id} not found")

        with self.db.transaction() as conn:
            cursor = conn.execute(
                "INSERT INTO layouts (name, width, height, dpi, mouse_wheel_radius, sprint_distance) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (
                    new_name,
                    source.width,
                    source.height,
                    source.dpi,
                    source.mouse_wheel_radius,
                    source.sprint_distance,
                ),
            )
            new_id = cursor.lastrowid
            conn.execute(
                """
                INSERT INTO layout_zones
                    (layout_id, scancode, name, zone_type, cx, cy, r, x1, y1, x2, y2, move_camera)
                SELECT ?, scancode, name, zone_type, cx, cy, r, x1, y1, x2, y2, move_camera
                FROM layout_zones WHERE layout_id = ?
                """,
                (new_id, layout_id),
            )
        layout = self.get(new_id)
        assert layout is not None
        return layout

    def set_active(self, layout_id: int) -> None:
        if self.get(layout_id) is None:
            raise ValueError(f"Layout {layout_id} not found")
        conn = self.db.connection
        conn.execute("INSERT OR IGNORE INTO app_settings (id) VALUES (1)")
        conn.execute(
            "UPDATE app_settings SET active_layout_id = ? WHERE id = 1", (layout_id,)
        )
        conn.commit()

    @staticmethod
    def _row_to_layout(row) -> Layout:
        return Layout(
            id=row["id"],
            name=row["name"],
            width=row["width"],
            height=row["height"],
            dpi=row["dpi"],
            mouse_wheel_radius=row["mouse_wheel_radius"],
            sprint_distance=row["sprint_distance"],
        )


# ------------------------------------------------------------------- zones --


@dataclass
class Zone:
    id: int
    layout_id: int
    scancode: str
    name: str
    zone_type: str  # 'circle' or 'rect'
    cx: Optional[float] = None
    cy: Optional[float] = None
    r: Optional[float] = None
    x1: Optional[float] = None
    y1: Optional[float] = None
    x2: Optional[float] = None
    y2: Optional[float] = None
    move_camera: bool = False


class ZoneRepository:
    _UPDATE_ALLOWED_FIELDS = {
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

    def __init__(self, db: Database):
        self.db = db

    def list_for_layout(self, layout_id: int) -> list[Zone]:
        rows = self.db.connection.execute(
            "SELECT * FROM layout_zones WHERE layout_id = ? ORDER BY id", (layout_id,)
        ).fetchall()
        return [self._row_to_zone(r) for r in rows]

    def get(self, zone_id: int) -> Optional[Zone]:
        row = self.db.connection.execute(
            "SELECT * FROM layout_zones WHERE id = ?", (zone_id,)
        ).fetchone()
        return self._row_to_zone(row) if row else None

    def add(
        self,
        layout_id: int,
        scancode: str,
        name: str,
        zone_type: str,
        move_camera: bool = False,
        **coords,
    ) -> Zone:
        self._validate_zone_type_and_coords(zone_type, coords)
        with self.db.transaction() as conn:
            cursor = conn.execute(
                """
                INSERT INTO layout_zones
                    (layout_id, scancode, name, zone_type, cx, cy, r, x1, y1, x2, y2, move_camera)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    layout_id,
                    scancode,
                    name,
                    zone_type,
                    coords.get("cx"),
                    coords.get("cy"),
                    coords.get("r"),
                    coords.get("x1"),
                    coords.get("y1"),
                    coords.get("x2"),
                    coords.get("y2"),
                    int(bool(move_camera)),
                ),
            )
            zone_id = cursor.lastrowid
        zone = self.get(zone_id)
        assert zone is not None
        return zone

    def update(self, zone_id: int, **fields) -> None:
        unknown = set(fields) - self._UPDATE_ALLOWED_FIELDS
        if unknown:
            raise ValueError(f"Unknown zone field(s): {sorted(unknown)}")
        if not fields:
            return
        if "move_camera" in fields:
            fields["move_camera"] = int(bool(fields["move_camera"]))

        conn = self.db.connection
        set_clause = ", ".join(f"{key} = :{key}" for key in fields)
        params = dict(fields)
        params["id"] = zone_id
        conn.execute(f"UPDATE layout_zones SET {set_clause} WHERE id = :id", params)
        conn.commit()

    def delete(self, zone_id: int) -> None:
        conn = self.db.connection
        conn.execute("DELETE FROM layout_zones WHERE id = ?", (zone_id,))
        conn.commit()

    def replace_all_for_layout(self, layout_id: int, zones: list[dict]) -> None:
        """Bulk replace, used by the legacy JSON importer and any future
        'reset this layout's zones' action. Wrapped in one transaction
        so a mid-import failure (a malformed zone raising partway
        through) can't leave a layout with its old zones deleted and
        only some new ones inserted."""
        with self.db.transaction() as conn:
            conn.execute("DELETE FROM layout_zones WHERE layout_id = ?", (layout_id,))
            for zone in zones:
                self._validate_zone_type_and_coords(zone["zone_type"], zone)
                conn.execute(
                    """
                    INSERT INTO layout_zones
                        (layout_id, scancode, name, zone_type, cx, cy, r, x1, y1, x2, y2, move_camera)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        layout_id,
                        zone["scancode"],
                        zone.get("name", ""),
                        zone["zone_type"],
                        zone.get("cx"),
                        zone.get("cy"),
                        zone.get("r"),
                        zone.get("x1"),
                        zone.get("y1"),
                        zone.get("x2"),
                        zone.get("y2"),
                        int(bool(zone.get("move_camera", False))),
                    ),
                )

    @staticmethod
    def _validate_zone_type_and_coords(zone_type: str, coords: dict) -> None:
        if zone_type == "circle":
            required = {"cx", "cy", "r"}
        elif zone_type == "rect":
            required = {"x1", "y1", "x2", "y2"}
        else:
            raise ValueError(
                f"Unknown zone_type: {zone_type!r} (expected 'circle' or 'rect')"
            )
        present = {k for k, v in coords.items() if v is not None}
        missing = required - present
        if missing:
            raise ValueError(
                f"{zone_type} zone missing required field(s): {sorted(missing)}"
            )

    @staticmethod
    def _row_to_zone(row) -> Zone:
        return Zone(
            id=row["id"],
            layout_id=row["layout_id"],
            scancode=row["scancode"],
            name=row["name"],
            zone_type=row["zone_type"],
            cx=row["cx"],
            cy=row["cy"],
            r=row["r"],
            x1=row["x1"],
            y1=row["y1"],
            x2=row["x2"],
            y2=row["y2"],
            move_camera=bool(row["move_camera"]),
        )
