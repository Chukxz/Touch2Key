from __future__ import annotations

import logging
import threading
from typing import TYPE_CHECKING

from modules.core.pipeline import Point, RectangularRegion
from modules.core.pipeline_factory import (
    AnchoredJoystick,
    FixedJoystick,
    FloatingJoystick,
)
from modules.database import store
from modules.utils import (
    CIRCLE,
    MOUSE_WHEEL_SIMULATOR_CODE,
    get_scancode_from_key,
    scale_coord,
)

if TYPE_CHECKING:
    from modules.core.pipeline import Pipeline
    from modules.core.pipeline_output import BridgeOutputSink
    from .mapper import Mapper

logger = logging.getLogger("modules.core.wheel_mapper")


class WheelMapper:
    def __init__(self, mapper: Mapper, output_sink: BridgeOutputSink):
        self.mapper = mapper
        self.output_sink = output_sink
        self.mapper_event_dispatcher = mapper.mapper_event_dispatcher

        self.lock = threading.Lock()
        self.pipeline: Pipeline | None = None

        self.rebuild_pipeline()

        self.mapper_event_dispatcher.register_callback(
            "ON_CONFIG_RELOAD", self.rebuild_pipeline
        )
        self.mapper_event_dispatcher.register_callback(
            "ON_LAYOUT_RELOAD", self.rebuild_pipeline
        )
        self.mapper_event_dispatcher.register_callback(
            "ON_WORKER_RESPAWN", self._on_respawn_wheel
        )

    def rebuild_pipeline(self) -> None:
        settings = store.settings.get()
        layout = store.get_active_layout()
        if layout is None:
            logger.warning(
                "No active layout found in SQLite database. WheelMapper pipeline will be empty."
            )
            self.touch_up()
            with self.lock:
                self.pipeline = None
            return

        inner_r = float(layout.mouse_wheel_radius)
        outer_r = float(layout.sprint_distance)
        w = float(layout.width)
        h = float(layout.height)

        key_raw_zones = self.mapper.layout_loader.keys_json_data.copy()
        wheel_zone_values = None
        for _, values in key_raw_zones:
            if (
                values.get("name") == MOUSE_WHEEL_SIMULATOR_CODE
                and values.get("type") == CIRCLE
            ):
                wheel_zone_values = values
                break

        if settings.left_handed:
            half_screen_region = RectangularRegion(Point(w / 2.0, 0.0), Point(w, h))
        else:
            half_screen_region = RectangularRegion(Point(0.0, 0.0), Point(w / 2.0, h))

        if wheel_zone_values is None:
            self.touch_up()
            with self.lock:
                self.pipeline = None
            return

        z_id = int(wheel_zone_values.get("id", 0))
        priority = int(wheel_zone_values.get("priority", 0))
        ignore_app_settings = bool(wheel_zone_values.get("ignore_app_settings", False))

        deadzone = (
            float(wheel_zone_values.get("deadzone", 0.1))
            if ignore_app_settings
            else float(settings.deadzone)
        )
        hysteresis = (
            float(wheel_zone_values.get("hysteresis", 4.0))
            if ignore_app_settings
            else float(settings.hysteresis)
        )
        sprint = get_scancode_from_key(settings.sprint_key) if settings.sprint_key is not None else None

        center = Point(
            scale_coord(w, wheel_zone_values.get("cx")),
            scale_coord(h, wheel_zone_values.get("cy")),
        )

        up, left, down, right = store.zones.get_mouse_wheel_directional_scancodes(layout)

        if settings.anchored_joystick:
            pipeline = AnchoredJoystick(
                default_anchor=center,
                region=half_screen_region,
                dead_zone=deadzone * inner_r,
                up=up,
                left=left,
                down=down,
                right=right,
                inner_radius=inner_r,
                outer_radius=outer_r,
                sprint=sprint,
                hysteresis_deg=hysteresis,
                priority=priority,
                creation_id=z_id,
            )
            logger.info(
                "Configured Anchored Floating Joystick at (%.1f, %.1f)",
                center.x,
                center.y,
            )

        elif settings.floating_joystick:
            pipeline = FloatingJoystick(
                region=half_screen_region,
                dead_zone=deadzone * inner_r,
                up=up,
                left=left,
                down=down,
                right=right,
                inner_radius=inner_r,
                outer_radius=outer_r,
                sprint=sprint,
                hysteresis_deg=hysteresis,
                priority=priority,
                creation_id=z_id,
            )
            logger.info("Configured Floating Joystick.")

        else:
            pipeline = FixedJoystick(
                center=center,
                dead_zone=deadzone * inner_r,
                up=up,
                left=left,
                down=down,
                right=right,
                inner_radius=inner_r,
                outer_radius=outer_r,
                sprint=sprint,
                hysteresis_deg=hysteresis,
                priority=priority,
                creation_id=z_id,
            )
            logger.info("Configured Fixed Joystick at (%.1f, %.1f)", center.x, center.y)

        with self.lock:
            if self.pipeline is not None:
                self.pipeline.reset(self.output_sink)
            self.pipeline = pipeline

    def touch_up(self) -> None:
        with self.lock:
            if self.pipeline is not None:
                self.pipeline.reset(self.output_sink)

    release_all = touch_up

    def _on_respawn_wheel(self, worker_type: str) -> None:
        if worker_type == "keyboard":
            self.touch_up()
