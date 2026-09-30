from __future__ import annotations

import logging
import threading
from typing import TYPE_CHECKING

from modules.core.pipeline_factory import FixedJoystick, FloatingJoystick, AnchoredJoystick
from modules.core.pipeline import Point, RectangularRegion
from modules.utils import scale_coord, CIRCLE, MOUSE_WHEEL_SIMULATOR_CODE

if TYPE_CHECKING:
    from .mapper import Mapper
    from modules.core.pipeline_output import BridgeOutputSink

logger = logging.getLogger("modules.core.wasd_mapper")


class WASDMapper:
    def __init__(self, mapper: Mapper, output_sink: BridgeOutputSink):
        self.mapper = mapper
        self.config = mapper.config
        self.output_sink = output_sink
        self.mapper_event_dispatcher = mapper.mapper_event_dispatcher

        self.lock = threading.Lock()
        self.pipeline = None

        self._build_pipeline()

        self.mapper_event_dispatcher.register_callback("ON_CONFIG_RELOAD", self._build_pipeline)
        self.mapper_event_dispatcher.register_callback("ON_LAYOUT_RELOAD", self._build_pipeline)
        self.mapper_event_dispatcher.register_callback("ON_WORKER_RESPAWN", self._on_worker_respawn)
        self.mapper_event_dispatcher.register_callback("ON_WASD_BLOCK", self._on_wasd_block)

    def _build_pipeline(self) -> None:
        inner_r, outer_r = self.mapper.layout_loader.get_mouse_wheel_info()
        w = float(self.mapper.layout_loader.width)
        h = float(self.mapper.layout_loader.height)

        key_raw_zones = self.mapper.layout_loader.keys_json_data.copy()
        wasd_zone_values = None
        for _, values in key_raw_zones:
            if values.get("name") == MOUSE_WHEEL_SIMULATOR_CODE and values.get("type") == CIRCLE:
                wasd_zone_values = values
                break

        if self.config.settings.left_handed:
            half_screen_region = RectangularRegion(Point(w / 2.0, 0.0), Point(w, h))
        else:
            half_screen_region = RectangularRegion(Point(0.0, 0.0), Point(w / 2.0, h))

        if wasd_zone_values is not None:
            z_id = int(wasd_zone_values.get("id", 0))
            priority = int(wasd_zone_values.get("priority", 0))
            ignore_app_settings = bool(wasd_zone_values.get("ignore_app_settings", False))

            deadzone = float(wasd_zone_values.get("deadzone", 0.1)) if ignore_app_settings else self.config.settings.deadzone
            hysteresis = float(wasd_zone_values.get("hysteresis", 4.0)) if ignore_app_settings else self.config.settings.hysteresis
            sprint_key = self.config.settings.sprint_key or "lshift"

            center = Point(
                scale_coord(wasd_zone_values["cx"], w),
                scale_coord(wasd_zone_values["cy"], h)
            )

            if self.config.settings.anchored_joystick:
                self.mapper.is_floating_joystick = True
                self.mapper.is_anchored_joystick = True
                pipeline = AnchoredJoystick(
                    default_anchor=center, region=half_screen_region, dead_zone=deadzone * inner_r,
                    walk_radius=inner_r, sprint_distance=outer_r, radius=outer_r, snap_radius=inner_r,
                    hysteresis_deg=hysteresis, up="w", down="s", left="a", right="d",
                    sprint_key=sprint_key, priority=priority, creation_id=z_id,
                )
                logger.info("Configured Anchored Floating Joystick at (%0.1f, %0.1f)", center.x, center.y)

            elif self.config.settings.floating_joystick:
                self.mapper.is_floating_joystick = True
                self.mapper.is_anchored_joystick = False
                pipeline = FloatingJoystick(
                    region=half_screen_region, dead_zone=deadzone * inner_r, walk_radius=inner_r,
                    sprint_distance=outer_r, radius=outer_r, hysteresis_deg=hysteresis,
                    up="w", down="s", left="a", right="d", sprint_key=sprint_key,
                )
                logger.info("Configured Floating Joystick.")

            else:
                self.mapper.is_floating_joystick = False
                self.mapper.is_anchored_joystick = False
                pipeline = FixedJoystick(
                    center=center, radius=inner_r, dead_zone=deadzone * inner_r, walk_radius=inner_r,
                    sprint_distance=outer_r, hysteresis_deg=hysteresis, up="w", down="s",
                    left="a", right="d", sprint_key=sprint_key,
                )
                logger.info("Configured Fixed Joystick at (%0.1f, %0.1f)", center.x, center.y)

        with self.lock:
            if self.pipeline:
                self.pipeline.reset(self.output_sink)
            self.pipeline = pipeline

    def touch_up(self) -> None:
        with self.lock:
            if self.pipeline:
                self.pipeline.reset(self.output_sink)

    def _on_wasd_block(self) -> None:
        if self.mapper.wasd_block > 0:
            self.touch_up()

    def _on_worker_respawn(self, worker_type: str) -> None:
        if worker_type == "keyboard":
            self.touch_up()
