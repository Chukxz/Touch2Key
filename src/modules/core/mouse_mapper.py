from __future__ import annotations

import logging
import threading
from typing import TYPE_CHECKING

from modules.core.pipeline import (
    AlwaysRegion,
    CircularRegion,
    DeltaTransform,
    DynamicOrigin,
    NoConstraint,
    Pipeline,
    Point,
    PointerSemantic,
    RectangularRegion,
)

from modules.utils import scale_coord
from modules.database import store

if TYPE_CHECKING:
    from .mapper import Mapper
    from modules.core.pipeline_output import BridgeOutputSink

logger = logging.getLogger("modules.core.mouse_mapper")


class MouseMapper:
    def __init__(self, mapper: Mapper, output_sink: BridgeOutputSink):
        self.mapper = mapper
        self.output_sink = output_sink
        self.mapper_event_dispatcher = mapper.mapper_event_dispatcher

        self.lock = threading.Lock()
        self.pipeline: Pipeline | None = None

        self._build_pipeline_mouse()

        self.mapper_event_dispatcher.register_callback(
            "ON_CONFIG_RELOAD", self._build_pipeline_mouse
        )
        self.mapper_event_dispatcher.register_callback(
            "ON_LAYOUT_RELOAD", self._build_pipeline_mouse
        )
        self.mapper_event_dispatcher.register_callback(
            "ON_WORKER_RESPAWN", self._on_worker_respawn_mouse
        )

    def _build_pipeline_mouse(self) -> None:
        settings = store.settings.get()
        layout = store.get_active_layout()
        if layout is None:
            logger.warning(
                "No active layout found in SQLite database. MouseMapper pipeline will be empty."
            )
            self.touch_up()
            self.pipeline = None
            return

        dev_w = float(layout.width)
        dev_h = float(layout.height)
        pc_w = float(self.mapper.screen_w)
        pc_h = float(self.mapper.screen_h)

        ratio_x = (pc_w / dev_w) if dev_w > 0 else 1.0
        ratio_y = (pc_h / dev_h) if dev_h > 0 else 1.0
        sens_x = settings.sensitivity_x
        sens_y = settings.sensitivity_y

        final_sens_x = sens_x * ratio_x
        final_sens_y = sens_y * ratio_y

        custom_look_zone = None

        for zone in store.zones.list_for_layout(layout.id):
            try:
                zone.set_parsed_config_from_json()
                sem_idx, _, _ = zone.CONFIG_HELPER.get_semantic_config()
                if sem_idx == 2:  # POINTER
                    custom_look_zone = zone
                    break
            except Exception:
                pass

        if custom_look_zone is not None:
            zone = custom_look_zone
            reg_type = zone.zone_type.upper()

            zone.set_parsed_config_from_json()
            _, _, trans_sens_x, trans_sens_y, _, _ = (
                zone.CONFIG_HELPER.get_transform_config()
            )

            sens_x = trans_sens_x if zone.ignore_app_settings else sens_x
            sens_y = trans_sens_y if zone.ignore_app_settings else sens_y
            final_sens_x = sens_x * ratio_x
            final_sens_y = sens_y * ratio_y

            if (
                reg_type == "CIRCLE"
                and zone.cx is not None
                and zone.cy is not None
                and zone.r
            ):
                look_region = CircularRegion(
                    Point(scale_coord(zone.cx), scale_coord(zone.cy)),
                    scale_coord(zone.r),
                )
            elif (
                reg_type == "RECTANGLE"
                and zone.x1 is not None
                and zone.y1 is not None
                and zone.x2 is not None
                and zone.y2 is not None
            ):
                look_region = RectangularRegion(
                    Point(scale_coord(zone.x1), scale_coord(zone.y1)),
                    Point(scale_coord(zone.x2), scale_coord(zone.y2)),
                )
            else:
                look_region = AlwaysRegion()
            logger.info(
                "MouseMapper assigned custom layout Look Area: '%s' (%s)",
                zone.name,
                reg_type,
            )

        else:
            if not settings.floating_joystick and not settings.anchored_joystick:
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

        logger.info(
            f"[MOUSEMAPPER] - Final X Sensitivity: {final_sens_x:.4f} (Ratio: {ratio_x:.2f}, User: {sens_x})"
        )
        logger.info(
            f"[MOUSEMAPPER] - Final Y Sensitivity: {final_sens_y:.4f} (Ratio: {ratio_y:.2f}, User: {sens_y})"
        )

        pipeline = Pipeline(
            region=look_region,
            origin=DynamicOrigin(),
            constraint=NoConstraint(),
            transformation=DeltaTransform(
                sensitivity_x=final_sens_x, sensitivity_y=final_sens_y
            ),
            semantics=[PointerSemantic()],
        )

        with self.lock:
            if self.pipeline is not None:
                self.pipeline.reset(self.output_sink)
            self.pipeline = pipeline

    def touch_up(self) -> None:
        with self.lock:
            if self.pipeline is not None:
                self.pipeline.reset(self.output_sink)

    def _on_worker_respawn_mouse(self, worker_type: str) -> None:
        if worker_type == "mouse":
            self.touch_up()
