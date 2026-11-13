from __future__ import annotations

import logging
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

        # Read pre-scaled device pixel boundaries directly from the snapshot
        inner_r = snap.wheel_radius
        w = float(snap.width)
        h = float(snap.height)

        # The stored sprint_distance is only meaningful when the layout has a sprint
        # zone. Otherwise it is the DB default (10 px), which would clamp the stick
        # to 10 px and make sprint fire almost immediately. With outer_r = 0 the
        # factories fall back to inner_radius for the clamp/leash, and
        # JoystickTransform disables sprint (radius <= 0).
        has_sprint = snap.has_sprint
        outer_r = snap.sprint_distance if has_sprint else 0.0

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
            if has_sprint and settings.sprint_key is not None
            else None
        )
        if settings.sprint_key is not None and not has_sprint:
            logger.info("Layout has no sprint zone; sprint is disabled.")

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
            self.pipeline = pipeline

    def touch_up(self) -> None:
        with self.engine_ref.lock:
            if self.pipeline is not None:
                self.pipeline.reset(self.output_sink)

    def _on_worker_respawn_wheel(self, worker_type: str) -> None:
        if worker_type == "keyboard":
            self.touch_up()
