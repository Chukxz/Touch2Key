from __future__ import annotations

import logging
import threading
from typing import TYPE_CHECKING, Any

from modules.database import store
from modules.utils import (
    BEZEL,
    CIRCLE,
    RECTANGLE,
)

# REMOVED: from modules.core.bezel_validator import ensure_system_bezels

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
        toggle_mode_callback: Any | None = None,
    ):
        self.mapper_event_dispatcher = dispatcher
        self.foreground_window = foreground_window
        self.toggle_mode_callback = toggle_mode_callback
        self.layout_lock = threading.Lock()

        self.keys_json_data: list[tuple[str, dict[str, Any]]] = []
        self.bezels_json_data: list[tuple[str, dict[str, Any]]] = []

        self.load_layout()
        self.mapper_event_dispatcher.register_callback("ON_LAYOUT_RELOAD", self.load_layout)

    def load_layout(self) -> None:
        """Loads metadata and parses bezel and keys pipelines."""
        layout = store.get_active_layout()
        if layout is None:
            logger.warning("No active layout found in SQLite database.")
            with self.layout_lock:
                self.keys_json_data = []
                self.bezels_json_data = []
            return

        # Native repository auto-heals bezels, so we just fetch the zones
        zones = store.get_active_layout_zones()

        # Guard against zero or negative dimensions
        layout_w = max(int(layout.width or 0), 1)
        layout_h = max(int(layout.height or 0), 1)

        # Temporary lists to prevent duplicate appending on reload
        new_keys_json_data: list[tuple[str, dict[str, Any]]] = []
        new_bezels_json_data: list[tuple[str, dict[str, Any]]] = []

        for z in zones:
            z.set_parsed_config_from_json()
            _, _, sens_x, sens_y, dz, hys = z.CONFIG_HELPER.get_transform_config()

            z_dict: dict[str, Any] = {
                "id": z.id,
                "name": z.name,
                "type": z.zone_type,
                "pointer": z.pointer,
                "priority": z.priority,
                "sensitivity_x": sens_x,
                "sensitivity_y": sens_y,
                "deadzone": dz,
                "hysteresis": hys,
                "ignore_app_settings": z.ignore_app_settings,
            }

            if z.zone_type == CIRCLE:
                z_dict["cx"] = (z.cx or 0.0) / layout_w
                z_dict["cy"] = (z.cy or 0.0) / layout_h
                z_dict["r"] = (z.r or 0.0) / layout_w

            elif z.zone_type in (BEZEL, RECTANGLE):
                z_dict["x1"] = (z.x1 or 0.0) / layout_w
                z_dict["y1"] = (z.y1 or 0.0) / layout_h
                z_dict["x2"] = (z.x2 or 0.0) / layout_w
                z_dict["y2"] = (z.y2 or 0.0) / layout_h

            if z.zone_type == BEZEL:
                new_bezels_json_data.append((z.scancode, z_dict))
            else:
                new_keys_json_data.append((z.scancode, z_dict))

        # Safely swap the active lists under lock
        with self.layout_lock:
            self.keys_json_data = new_keys_json_data
            self.bezels_json_data = new_bezels_json_data

        logger.info(
            "Active layout '%s' loaded. (%dx%d, %d zones)",
            layout.name,
            layout_w,
            layout_h,
            len(zones),
        )
