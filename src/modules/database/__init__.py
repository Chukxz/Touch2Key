"""Unified facade over the database layer.

Most callers should import `store` from here rather than reaching into connection.py or
repositories.py directly -- it's the seam that keeps AppConfig's and JSONLoader's eventual
sqlite-backed rewrite thin, and it's what legacy_migration.py writes into.
"""

from __future__ import annotations

import logging
from typing import Optional

from modules.utils import (
    BEZEL,
    BEZEL_DP_THICKNESS,
    BOTTOM_BEZEL_ID,
    TOP_BEZEL_ID,
    calculate_rect,
    dp_to_px,
)
from .connection import ConnectionManager, connection_manager

from .repositories import (
    AppSettings,
    AppSettingsRepository,
    InvalidFieldError,
    Layout,
    LayoutsRepository,
    LayoutZone,
    LayoutZonesRepository,
    _scancode_matches,
)

__all__ = [
    "Store",
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
]

logger = logging.getLogger("modules.database")


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

    l_w = layout.width
    l_h = layout.height
    thickness = float(dp_to_px(BEZEL_DP_THICKNESS, layout.dpi))
    zones = store.zones.list_for_layout(layout_id)
    updated_count = 0

    for zone in zones:
        if zone.zone_type == BEZEL:
            if _scancode_matches(zone.scancode, TOP_BEZEL_ID):
                cx, cy, x1, y1, x2, y2 = calculate_rect(0.0, 0.0, l_w, thickness)
                store.zones.update(
                    zone.id, cx=cx, cy=cy, r=None, x1=x1, y1=y1, x2=x2, y2=y2
                )
            elif _scancode_matches(zone.scancode, BOTTOM_BEZEL_ID):
                cx, cy, x1, y1, x2, y2 = calculate_rect(0.0, l_h - thickness, l_w, l_h)
                store.zones.update(
                    zone.id, cx=cx, cy=cy, r=None, x1=x1, y1=y1, x2=x2, y2=y2
                )

        zone.set_parsed_config_from_json()

        _, sem_mode, _ = zone.CONFIG_HELPER.get_semantic_config()

        # 1. Bezels
        if sem_mode == "TOGGLE":
            zone.CONFIG_HELPER.set_region_config(bezel_dp_thickness=BEZEL_DP_THICKNESS)

        # 2. Standard Buttons
        elif sem_mode == "BUTTON":
            zone.CONFIG_HELPER.set_transform_config(
                sensitivity_x=settings.sensitivity_x,
                sensitivity_y=settings.sensitivity_y,
            )

        # 3. Directional Movement Joystick Zone
        elif sem_mode == "DIRECTIONAL":
            origin_idx = 0
            if settings.anchored_joystick:
                origin_idx = 2
            elif settings.floating_joystick:
                origin_idx = 1

            zone.CONFIG_HELPER.set_origin_config(origin_idx)

        # 4. Camera Look Area
        elif sem_mode == "POINTER":
            zone.CONFIG_HELPER.set_transform_config(
                sensitivity_x=settings.sensitivity_x,
                sensitivity_y=settings.sensitivity_y,
                deadzone=settings.deadzone,
                hysteresis=settings.hysteresis,
            )

        store.zones.update(
            zone.id,
            ignore_app_settings=False,
            pipeline_json=zone.CONFIG_HELPER.get_pipeline_json_from_config(),
        )
        updated_count += 1

    logger.info(
        "Reset %d zones in layout ID %d to AppSettings.", updated_count, layout_id
    )
    return updated_count
