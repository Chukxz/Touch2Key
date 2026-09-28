from __future__ import annotations

import logging
import threading
from typing import TYPE_CHECKING, Any

from modules.database import Layout, LayoutZone, store
from modules.utils import (
    BEZEL,
    CIRCLE,
    RECTANGLE,
    BASELINE_DPI,
    BASELINE_HEIGHT,
    BASELINE_WIDTH,
    MapperEvent,
)

from modules.core.bezel_validator import ensure_system_bezels

if TYPE_CHECKING:
    from .config import AppConfig

logger = logging.getLogger("modules.core.layout_loader")


class LayoutLoader:
    """Database-backed layout loader. Maintains normalized touch zone data
    for legacy consumers while compiling dynamic 5-stage touch pipelines.
    """

    def __init__(
        self,
        config: AppConfig,
        foreground_window: Any = None,
        toggle_mode_callback: Any | None = None,
    ):
        self.config = config
        self.mapper_event_dispatcher = config.mapper_event_dispatcher
        self.foreground_window = foreground_window
        self.toggle_mode_callback = toggle_mode_callback

        self.layout_lock = threading.Lock()
        self.active_layout: Layout | None = None
        self.zones: list[LayoutZone] = []

        self.width: int = BASELINE_WIDTH
        self.height: int = BASELINE_HEIGHT
        self.dpi: int = BASELINE_DPI
        self.mouse_wheel_radius: float = 50.0
        self.sprint_distance: float = 10.0
        self.bezel_height: float = (
            14.0  # Kept strictly for backward compatibility if plugins expect it
        )

        self.keys_json_data: list[tuple[str, dict[str, Any]]] = []
        self.bezels_json_data: list[tuple[str, dict[str, Any]]] = []

        self._load_layout()

        if self.mapper_event_dispatcher is not None:
            self.mapper_event_dispatcher.register_callback(
                "ON_LAYOUT_RELOAD", self._load_layout
            )

    def get_mouse_wheel_info(self) -> tuple[float, float]:
        with self.layout_lock:
            return self.mouse_wheel_radius, self.sprint_distance

    def _load_layout(self) -> None:
        """Loads metadata and parses bezel pipelines."""
        layout = store.get_active_layout()
        if layout is None:
            logger.warning("No active layout found in SQLite database.")
            settings = store.settings.get()
            with self.layout_lock:
                self.width = settings.json_dev_width
                self.height = settings.json_dev_height
                self.dpi = settings.json_dev_dpi
                self.custom_pipelines = []
                self.keys_json_data = []
            return

        # --- Self-Heal ---
        # Ensures existing SQLite databases automatically get the Virtual Keyboard
        # and Mode Switch bezels injected before we compile pipelines.
        ensure_system_bezels(layout.id, store.layouts, store.zones)

        # Fetch zones AFTER auto-healing ensures bezels exist
        zones = store.get_active_layout_zones()

        with self.layout_lock:
            self.active_layout = layout
            self.zones = zones
            self.width = layout.width
            self.height = layout.height
            self.dpi = layout.dpi
            self.mouse_wheel_radius = layout.mouse_wheel_radius
            self.sprint_distance = layout.sprint_distance

            # Normalize touch and bezel coordinates for the Android/Mobile payload..
            normalized_keys: list[tuple[str, dict[str, Any]]] = []
            normalized_bezels: list[tuple[str, dict[str, Any]]] = []

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
                    z_dict["cx"] = (z.cx or 0.0) / self.width
                    z_dict["cy"] = (z.cy or 0.0) / self.height
                    z_dict["r"] = (z.r or 0.0) / self.width

                elif z.zone_type == BEZEL or z.zone_type == RECTANGLE:
                    z_dict["x1"] = (z.x1 or 0.0) / self.width
                    z_dict["y1"] = (z.y1 or 0.0) / self.height
                    z_dict["x2"] = (z.x2 or 0.0) / self.width
                    z_dict["y2"] = (z.y2 or 0.0) / self.height

                if z.zone_type == "BEZEL":
                    normalized_bezels.append((z.scancode, z_dict))
                else:
                    normalized_keys.append((z.scancode, z_dict))

            self.bezels_json_data = normalized_bezels
            self.keys_json_data = normalized_keys

            logger.info(
                "Active layout '%s' loaded. (%dx%d, %d zones, %d compiled pipelines)",
                self.active_layout.name,
                self.width,
                self.height,
                len(self.zones),
            )

    def reload(self) -> None:
        self._load_layout()
        self.config.reload_config()
        if self.mapper_event_dispatcher is not None:
            self.mapper_event_dispatcher.dispatch(
                MapperEvent(action="ON_LAYOUT_RELOAD")
            )
        logger.info("Layout hot-reloaded and dispatched.")
