from __future__ import annotations

import logging
import sys
from typing import TYPE_CHECKING

from modules.core.pipeline import (
    AlwaysRegion,
    Point,
    RectangularRegion,
)
from modules.core.pipeline_factory import MousePointer
from modules.utils import MIN_PRIORITY, look_counts_per_px

if TYPE_CHECKING:
    from modules.core.pipeline import Pipeline
    from modules.core.pipeline_output import BridgeOutputSink
    from .mapper import Mapper

logger = logging.getLogger("modules.core.mouse_mapper")


class MouseMapper:
    def __init__(self, mapper: Mapper, output_sink: BridgeOutputSink):
        self.mapper = mapper
        self.output_sink = output_sink
        self.dispatcher = mapper.dispatcher
        self.engine_ref = mapper.engine_ref
        self.pipeline: Pipeline | None = None
        self.rebuild_pipeline()

        self.dispatcher.register_callback(
            "ON_WORKER_RESPAWN", self._on_worker_respawn_mouse
        )

    def _clear(self, reason: str) -> None:
        logger.warning(reason)
        self.touch_up()
        with self.engine_ref.lock:
            self.pipeline = None

    def rebuild_pipeline(self) -> None:
        loader = self.engine_ref.layout_loader
        if loader is None:
            self._clear(
                "Layout Loader not initialized. MouseMapper pipeline will be empty."
            )
            return

        snap = loader.snapshot
        layout = snap.layout
        if layout is None:
            self._clear(
                "No active layout found in SQLite database. MouseMapper pipeline will be empty."
            )
            return

        settings = snap.settings
        dev_w = float(layout.width)
        dev_h = float(layout.height)

        sens_x = settings.sensitivity_x
        sens_y = settings.sensitivity_y

        zone = snap.look_zone
        zone_priority = MIN_PRIORITY
        zone_creation_id = sys.maxsize

        if zone is not None:
            zone_priority = zone.priority
            zone_creation_id = zone.id

            if zone.ignore_app_settings:
                sens_x = zone.sensitivity_x
                sens_y = zone.sensitivity_y

            look_region = zone.region()
            if look_region is None or look_region.area <= 0.0:
                look_region = AlwaysRegion()

            logger.info(
                "MouseMapper assigned custom layout Look Area: '%s' (%s)",
                zone.name,
                zone.zone_type,
            )

        elif not settings.floating_joystick and not settings.anchored_joystick:
            look_region = AlwaysRegion()
            logger.info(
                "MouseMapper assigned Full-Screen Region (Fixed Joystick active)."
            )

        else:
            if settings.left_handed:
                look_region = RectangularRegion(
                    Point(0.0, 0.0), Point(dev_w / 2.0, dev_h)
                )
            else:
                look_region = RectangularRegion(
                    Point(dev_w / 2.0, 0.0), Point(dev_w, dev_h)
                )
            logger.info(
                "MouseMapper restricted to %s half-screen.",
                "Left" if settings.left_handed else "Right",
            )

        # finger px -> dp (layout DPI) -> mouse counts; uniform on X and Y and
        # independent of both the phone and the PC resolution.
        pipeline = MousePointer(
            region=look_region,
            sensitivity_x=look_counts_per_px(sens_x, layout.dpi),
            sensitivity_y=look_counts_per_px(sens_y, layout.dpi),
            priority=zone_priority,
            creation_id=zone_creation_id,
        )

        with self.engine_ref.lock:
            if self.pipeline is not None:
                self.pipeline.reset(self.output_sink)
            self.pipeline = pipeline

    def touch_up(self) -> None:
        with self.engine_ref.lock:
            if self.pipeline is not None:
                self.pipeline.reset(self.output_sink)

    def _on_worker_respawn_mouse(self, worker_type: str) -> None:
        if worker_type == "mouse":
            self.touch_up()
