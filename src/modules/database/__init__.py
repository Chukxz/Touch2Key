"""Unified facade over the database layer.

Most callers should import `store` from here rather than reaching into connection.py or
repositories.py directly -- it's the seam that keeps AppConfig's and JSONLoader's eventual
sqlite-backed rewrite thin, and it's what legacy_migration.py writes into.
"""

from __future__ import annotations

import json
import logging
from typing import Optional, TYPE_CHECKING

from .connection import ConnectionManager, connection_manager
from .repositories import (
    AppSettings,
    AppSettingsRepository,
    InvalidFieldError,
    Layout,
    LayoutsRepository,
    LayoutZone,
    LayoutZonesRepository,
)

__all__ = [
    "Store",
    "store",
    "connection_manager",
    "ConnectionManager",
    "AppSettings",
    "Layout",
    "LayoutZone",
    "AppSettingsRepository",
    "LayoutsRepository",
    "LayoutZonesRepository",
    "InvalidFieldError",
    "reset_layout_zones_to_app_settings",
    "ensure_system_bezels",
]

logger = logging.getLogger("modules.database")

from modules.utils import (
    BEZEL,
    BEZEL_DP_THICKNESS,
    TOP_BEZEL_ID,
    BOTTOM_BEZEL_ID,
    dp_to_px,
    calculate_rect,
    bezels_exist_ids,
    ensure_top_bezel,
    ensure_bottom_bezel,
)

if TYPE_CHECKING:
    from modules.database.connection import ConnectionManager
    from modules.database.repositories import (
        AppSettings,
        AppSettingsRepository,
        LayoutsRepository,
        LayoutZonesRepository,
    )


class Store:
    """One instance is enough for the whole process -- repositories

    are stateless aside from the shared, thread-local connection
    manager, so construction is cheap and there's no reason to pass
    this around as anything but the module-level singleton below.
    """

    def __init__(self, manager: Optional[ConnectionManager] = None):
        self._manager = manager or connection_manager
        self.settings = AppSettingsRepository()
        self.layouts = LayoutsRepository()
        self.zones = LayoutZonesRepository()

    def get_active_layout(self) -> Optional[Layout]:
        settings = self.settings.get()
        if settings.active_layout_id is None:
            return None
        return self.layouts.get(settings.active_layout_id)

    def get_active_layout_zones(self) -> list[LayoutZone]:
        layout = self.get_active_layout()
        if layout is None:
            return []
        return self.zones.list_for_layout(layout.id)

    def set_active_layout(self, layout_id: Optional[int]) -> AppSettings:
        if layout_id is not None and self.layouts.get(layout_id) is None:
            raise KeyError(f"No layout with id={layout_id}")
        return self.settings.update(active_layout_id=layout_id)

    def close(self) -> None:
        """Call from a thread that's shutting down to release that thread's connection."""
        self._manager.close_current_thread_connection()


# Process-wide singleton
store = Store()


def reset_layout_zones_to_app_settings(layout_id: int) -> int:
    """Updates all zones in a layout to synchronize parameters with global AppSettings.

    Returns the count of successfully updated zones.
    """
    settings = store.settings.get()
    layout = store.layouts.get(layout_id)
    if not layout:
        return 0

    inner_r = layout.mouse_wheel_radius
    outer_r = layout.sprint_distance
    l_w = layout.width
    l_h = layout.height
    thickness = float(dp_to_px(BEZEL_DP_THICKNESS, layout.dpi))
    zones = store.zones.list_for_layout(layout_id)
    updated_count = 0

    for zone in zones:
        if zone.zone_type == BEZEL:

            if zone.scancode == str(TOP_BEZEL_ID):
                cx, cy, x1, y1, x2, y2 = calculate_rect(0.0, 0.0, l_w, thickness)
                store.zones.update(
                    zone.id, cx=cx, cy=cy, r=None, x1=x1, y1=y1, x2=x2, y2=y2
                )

            elif zone.scancode == str(BOTTOM_BEZEL_ID):
                cx, cy, x1, y1, x2, y2 = calculate_rect(0.0, l_h - thickness, l_w, l_h)
                store.zones.update(
                    zone.id, cx=cx, cy=cy, r=None, x1=x1, y1=y1, x2=x2, y2=y2
                )

        try:
            cfg = json.loads(zone.pipeline_config or "{}")
        except Exception:
            cfg = {}

        sem_mode = cfg.get("semantics", {}).get("mode", "BUTTON")
        trans_type = cfg.get("transform", {}).get("type", "IDENTITY")

        # 1. Directional Movement Joystick Zone
        if sem_mode == "WASD" or trans_type == "JOYSTICK" or zone.name == "MOUSE_WHEEL":
            origin_type = "ANCHORED" if settings.anchored_floating_joystick else "FIXED"
            cfg["origin"] = {
                "type_idx": 2 if settings.anchored_floating_joystick else 1,
                "type": origin_type,
                "anchor_x": float(zone.cx or 0.0),
                "anchor_y": float(zone.cy or 0.0),
                "snap_radius": float(settings.joystick_snap_radius),
            }
            cfg["transform"] = {
                "type_idx": 3,
                "type": "JOYSTICK",
                "joy_dz": float(settings.deadzone * inner_r),
                "joy_walk": float(inner_r),
                "joy_sprint": float(outer_r),
                "joy_hysteresis": float(settings.hysteresis),
            }
            cfg["semantics"] = {"type_idx": 3, "mode": "WASD", "is_mouse_button": False}
            cfg["priority"] = 0

        # 2. Camera Look Area
        elif sem_mode == "POINTER" or trans_type == "DELTA":
            cfg["transform"] = {
                "type_idx": 1,
                "type": "DELTA",
                "sens_x": float(settings.sensitivity),
                "sens_y": float(settings.sensitivity),
            }
            cfg["semantics"] = {
                "type_idx": 4,
                "mode": "POINTER",
                "is_mouse_button": False,
            }
            cfg["priority"] = -100

        # 3. Standard Buttons & Track-Fire
        else:
            if sem_mode == "TRACK_FIRE":
                cfg["transform"] = {
                    "type_idx": 1,
                    "type": "DELTA",
                    "sens_x": float(settings.sensitivity),
                    "sens_y": float(settings.sensitivity),
                }
            cfg["priority"] = 0

        store.zones.update(zone.id, pipeline_config=json.dumps(cfg))
        updated_count += 1

    logger.info(
        "Reset %d zones in layout ID %d to AppSettings.", updated_count, layout_id
    )
    return updated_count


def ensure_system_bezels(layout_id: int) -> None:
    """Verifies a layout has both system bezels (Top/Mode, Bottom/VKB) and creates them if missing."""
    layout = store.layouts.get(layout_id)
    if not layout:
        return

    zones = store.zones.list_for_layout(layout_id)
    top_id, bottom_id = bezels_exist_ids(zones)

    if top_id < 0:
        ensure_top_bezel(layout, store.zones)
        logger.info("Auto-healed missing Top Bezel for layout ID %d", layout.id)

    if bottom_id < 0:
        ensure_bottom_bezel(layout, store.zones)
        logger.info("Auto-healed missing Bottom Bezel for layout ID %d", layout.id)
