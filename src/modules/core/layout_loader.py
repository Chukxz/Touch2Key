from __future__ import annotations

import logging
import threading
from typing import TYPE_CHECKING, Any

from modules.database import store
from modules.utils import (
    BEZEL,
    CIRCLE,
    RECTANGLE,
    SPRINT_DISTANCE_CODE,
)

if TYPE_CHECKING:
    from modules.utils import MapperEventDispatcher

logger = logging.getLogger("modules.core.layout_loader")


class LayoutLoader:
    """Database-backed layout loader. Maintains normalized touch zone data
    for legacy consumers while compiling dynamic 5-stage touch pipelines.
    """

    def __init__(
        self,
        dispatcher: MapperEventDispatcher,
        foreground_window: Any = None,
    ):
        self.dispatcher = dispatcher
        self.foreground_window = foreground_window
        self.layout_lock = threading.Lock()

        self.keys_data: list[tuple[int, dict[str, Any]]] = []
        self.bezels_data: list[tuple[int, dict[str, Any]]] = []

        self.load_layout()
        self.dispatcher.register_callback(
            "ON_RELOAD", self.load_layout
        )

    def load_layout(self) -> None:
        """Loads metadata and parses bezel and keys pipelines."""
        layout = store.get_active_layout()
        if layout is None:
            logger.warning("No active layout found in SQLite database.")
            with self.layout_lock:
                self.keys_data = []
                self.bezels_data = []
            return

        # Native repository auto-heals bezels, so we just fetch the zones
        zones = store.get_active_layout_zones()

        # Guard against zero or negative dimensions
        layout_w = max(int(layout.width or 0), 1)
        layout_h = max(int(layout.height or 0), 1)

        # Temporary lists to prevent duplicate appending on reload
        new_keys_data: list[tuple[int, dict[str, Any]]] = []
        new_bezels_data: list[tuple[int, dict[str, Any]]] = []

        for zone in zones:
            if zone.scancode == SPRINT_DISTANCE_CODE:
                continue

            zone.set_parsed_config_from_json()
            _, _, sens_x, sens_y, dz, hys = zone.CONFIG_HELPER.get_transform_config()

            z_dict: dict[str, Any] = {
                "id": zone.id,
                "name": zone.name,
                "type": zone.zone_type,
                "pointer": zone.pointer,
                "priority": zone.priority,
                "sensitivity_x": sens_x,
                "sensitivity_y": sens_y,
                "deadzone": dz,
                "hysteresis": hys,
                "ignore_app_settings": zone.ignore_app_settings,
            }

            if zone.zone_type == CIRCLE:
                z_dict["cx"] = (zone.cx or 0.0) / layout_w
                z_dict["cy"] = (zone.cy or 0.0) / layout_h
                z_dict["r"] = (zone.r or 0.0) / layout_w

            elif zone.zone_type in (BEZEL, RECTANGLE):
                z_dict["x1"] = (zone.x1 or 0.0) / layout_w
                z_dict["y1"] = (zone.y1 or 0.0) / layout_h
                z_dict["x2"] = (zone.x2 or 0.0) / layout_w
                z_dict["y2"] = (zone.y2 or 0.0) / layout_h

            if zone.zone_type == BEZEL:
                new_bezels_data.append((zone.scancode, z_dict))
            else:
                new_keys_data.append((zone.scancode, z_dict))

        # Safely swap the active lists under lock
        with self.layout_lock:
            self.keys_data = new_keys_data
            self.bezels_data = new_bezels_data

        logger.info(
            "Active layout '%s' loaded. (%dx%d, %d zones)",
            layout.name,
            layout_w,
            layout_h,
            len(zones),
        )
