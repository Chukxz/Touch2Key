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
from modules.utils import get_scancode_from_key

if TYPE_CHECKING:
    from modules.core.pipeline import Pipeline
    from modules.core.pipeline_output import BridgeOutputSink
    from .mapper import Mapper

logger = logging.getLogger("modules.core.wheel_mapper")


class WheelMapper:
    def __init__(self, mapper: Mapper, output_sink: BridgeOutputSink):
        self.mapper = mapper
        self.output_sink = output_sink
        self.dispatcher = mapper.dispatcher
        self.engine_ref = mapper.engine_ref
        self.pipeline: Pipeline | None = None
        self.rebuild_pipeline()

        self.dispatcher.register_callback(
            "ON_WORKER_RESPAWN", self._on_worker_respawn_wheel
        )

    def _clear(self, reason: str | None = None) -> None:
        if reason:
            logger.warning(reason)
        self.touch_up()
        with self.engine_ref.lock:
            self.pipeline = None

    def rebuild_pipeline(self) -> None:
        loader = self.engine_ref.layout_loader
        if loader is None:
            self._clear("Layout Loader not initialized. WheelMapper pipeline will be empty.")
            return

        snap = loader.snapshot
        layout = snap.layout
        if layout is None:
            self._clear(
                "No active layout found in SQLite database. WheelMapper pipeline will be empty."
            )
            return

        wheel = snap.wheel
        if wheel is None:
            self._clear()
            return

        settings = snap.settings
        inner_r = float(layout.mouse_wheel_radius)
        outer_r = float(layout.sprint_distance)
        w = float(layout.width)
        h = float(layout.height)

        if settings.left_handed:
            half_screen_region = RectangularRegion(Point(w / 2.0, 0.0), Point(w, h))
        else:
            half_screen_region = RectangularRegion(Point(0.0, 0.0), Point(w / 2.0, h))

        deadzone = wheel.deadzone if wheel.ignore_app_settings else float(settings.deadzone)
        hysteresis = (
            wheel.hysteresis if wheel.ignore_app_settings else float(settings.hysteresis)
        )
        sprint = (
            get_scancode_from_key(settings.sprint_key)
            if settings.sprint_key is not None
            else None
        )

        center = wheel.center
        up, left, down, right = snap.wheel_keys

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
                priority=wheel.priority,
                creation_id=wheel.id,
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
                priority=wheel.priority,
                creation_id=wheel.id,
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
                priority=wheel.priority,
                creation_id=wheel.id,
            )
            logger.info("Configured Fixed Joystick at (%.1f, %.1f)", center.x, center.y)

        with self.engine_ref.lock:
            if self.pipeline is not None:
                self.pipeline.reset(self.output_sink)
            self.pipeline = pipeline

    def touch_up(self) -> None:
        with self.engine_ref.lock:
            if self.pipeline is not None:
                self.pipeline.reset(self.output_sink)

    def _on_worker_respawn_wheel(self, worker_type: str) -> None:
        if worker_type == "keyboard":
            self.touch_up()