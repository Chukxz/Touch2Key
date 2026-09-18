from __future__ import annotations

import json
import logging
import threading
from typing import TYPE_CHECKING, Any

from modules.core.pipeline_factory import create_pipeline_from_zone
from modules.database import Layout, LayoutZone, store
from modules.utils import CIRCLE, RECTANGLE, MapperEvent

if TYPE_CHECKING:
    from modules.core.pipeline import Pipeline
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

        self.width: int = 360
        self.height: int = 800
        self.dpi: int = 160
        self.mouse_wheel_radius: float = 50.0
        self.sprint_distance: float = 10.0
        self.bezel_height: float = 14.0

        self.json_data: list[tuple[str, dict[str, Any]]] = []
        self.custom_pipelines: list[Pipeline] = []

        self._load_layout()

        if self.mapper_event_dispatcher is not None:
            self.mapper_event_dispatcher.register_callback(
                "ON_LAYOUT_RELOAD", self._on_dispatcher_reload
            )

    def get_mouse_wheel_info(self) -> tuple[float, float]:
        with self.layout_lock:
            return self.mouse_wheel_radius, self.sprint_distance

    def _load_layout(self) -> None:
        """Loads metadata, parses custom pipelines, and extracts bezel height."""
        layout = store.get_active_layout()
        if layout is None:
            logger.warning("No active layout found in SQLite database.")
            settings = store.settings.get()
            with self.layout_lock:
                self.width = settings.json_dev_width or 360
                self.height = settings.json_dev_height or 800
                self.dpi = settings.json_dev_dpi or 160
                self.custom_pipelines = []
                self.json_data = []
                self.bezel_height = 14.0
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

            compiled_pipelines: list[Pipeline] = []
            extracted_bezel_height = 14.0

            for z in zones:
                cfg_raw = getattr(z, "pipeline_config", "{}") or "{}"
                try:
                    cfg = json.loads(cfg_raw)
                    reg = cfg.get("region", {})
                    if reg.get("type") == "BEZEL" or z.zone_type == "BEZEL":
                        extracted_bezel_height = float(reg.get("bezel_height", 14.0))
                        continue
                except Exception:
                    pass

                pipeline = create_pipeline_from_zone(
                    zone=z,
                    screen_width=float(self.width),
                    screen_height=float(self.height),
                    toggle_mode_callback=self.toggle_mode_callback,
                )
                if pipeline is not None:
                    compiled_pipelines.append(pipeline)

            self.custom_pipelines = compiled_pipelines
            self.bezel_height = extracted_bezel_height

            normalized: list[tuple[str, dict[str, Any]]] = []
            for z in zones:
                if z.zone_type == "BEZEL":
                    continue

                z_dict: dict[str, Any] = {
                    "name": z.name,
                    "type": z.zone_type,
                    "move_camera": z.move_camera,
                    "priority": getattr(z, "priority", 0),
                    "pipeline_config": getattr(z, "pipeline_config", "{}") or "{}",
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

            logger.info(
                "Active layout '%s' loaded. (%dx%d, %d zones, %d pipelines, bezel: %.1fpx)",
                self.active_layout.name,
                self.width,
                self.height,
                len(self.zones),
                len(self.custom_pipelines),
                self.bezel_height,
            )

    def _on_dispatcher_reload(self) -> None:
        self._load_layout()

    def reload(self) -> None:
        self._load_layout()
        self.config.reload_config()
        if self.mapper_event_dispatcher is not None:
            self.mapper_event_dispatcher.dispatch(
                MapperEvent(action="ON_LAYOUT_RELOAD")
            )
        logger.info("Layout hot-reloaded and dispatched.")
