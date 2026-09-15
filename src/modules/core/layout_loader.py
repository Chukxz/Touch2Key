from __future__ import annotations

import logging
import threading
from typing import TYPE_CHECKING, Any

from modules.database import store, Layout, LayoutZone
from modules.utils import MapperEvent, CIRCLE, RECTANGLE

if TYPE_CHECKING:
    from .config import AppConfig

logger = logging.getLogger("modules.core.layout_loader")


class LayoutLoader:
    """Database-backed layout loader. Maintains the LayoutLoader interface
    expected by downstream mappers while querying SQLite tables directly.
    """

    def __init__(self, config: AppConfig, foreground_window: Any = None):
        self.config = config
        self.mapper_event_dispatcher = config.mapper_event_dispatcher
        self.foreground_window = foreground_window

        self.layout_lock = threading.Lock()
        self.active_layout: Layout | None = None
        self.zones: list[LayoutZone] = []

        self.width = 360
        self.height = 800
        self.dpi = 160
        self.mouse_wheel_radius = 50.0
        self.sprint_distance = 10.0

        self.json_data: list[tuple[str, dict]] = []
        self._load_layout()

    def get_mouse_wheel_info(self) -> tuple[float, float]:
        with self.layout_lock:
            return self.mouse_wheel_radius, self.sprint_distance

    def _load_layout(self) -> None:
        """Fetches active layout metadata and normalized touch zones from SQLite."""
        layout = store.get_active_layout()
        if layout is None:
            logger.warning("No active layout found in SQLite database.")
            return

        zones = store.get_active_layout_zones()

        with self.layout_lock:
            self.active_layout = layout
            self.zones = zones
            self.width = layout.width
            self.height = layout.height
            self.dpi = layout.dpi
            self.mouse_wheel_radius = layout.mouse_wheel_radius
            self.sprint_distance = layout.sprint_distance

            # Build normalized zones list for legacy components and pipeline builders
            normalized: list[tuple[str, dict]] = []
            for z in zones:
                z_dict = {
                    "name": z.name,
                    "type": z.zone_type,
                    "move_camera": z.move_camera,
                }
                if z.zone_type == CIRCLE:
                    z_dict["cx"] = (z.cx or 0.0) / self.width
                    z_dict["cy"] = (z.cy or 0.0) / self.height
                    z_dict["r"] = (z.r or 0.0) / self.width
                elif z.zone_type == RECTANGLE:
                    z_dict["x1"] = (z.x1 or 0.0) / self.width
                    z_dict["y1"] = (z.y1 or 0.0) / self.height
                    z_dict["x2"] = (z.x2 or 0.0) / self.width
                    z_dict["y2"] = (z.y2 or 0.0) / self.height

                normalized.append((z.scancode, z_dict))

            self.json_data = normalized

    def reload(self) -> None:
        """Hot-reloads active layout and notifies engine workers."""
        self._load_layout()
        self.config.reload_config()
        self.mapper_event_dispatcher.dispatch(MapperEvent(action="ON_JSON_RELOAD"))
        logger.info("Layout hot-reloaded from database.")