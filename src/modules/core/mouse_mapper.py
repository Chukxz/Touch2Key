from __future__ import annotations

import json
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
    TouchPhase,
    Vector,
)

from modules.core import BridgeOutputSink
from modules.utils import scale_coord, TouchEvent

if TYPE_CHECKING:
    from .mapper import Mapper

logger = logging.getLogger("modules.core.mouse_mapper")


class MouseMapper:
    """Manages camera movement and cursor tracking.

    When WASD is fixed, look controls default across the screen unless a custom
    POINTER zone is defined. Drops touch motion from TRACK_FIRE slots to prevent
    aim reticle dragging from fighting the camera.
    """

    def __init__(self, mapper: Mapper):
        self.mapper = mapper
        self.config = mapper.config
        self.bridge = mapper.bridge
        self.output_sink = BridgeOutputSink(self.bridge)
        self.mapper_event_dispatcher = mapper.mapper_event_dispatcher

        self.lock = threading.Lock()
        self.pipeline: Pipeline[Vector] | None = None
        self.final_sens_x = 1.0
        self.final_sens_y = 1.0

        self._build_pipeline()

        self.mapper_event_dispatcher.register_callback(
            "ON_CONFIG_RELOAD", self._build_pipeline
        )
        self.mapper_event_dispatcher.register_callback(
            "ON_LAYOUT_RELOAD", self._build_pipeline
        )
        self.mapper_event_dispatcher.register_callback(
            "ON_AGGREGATION", self._aggregate
        )

    def _build_pipeline(self) -> None:
        dev_w = float(self.mapper.layout_loader.width)
        dev_h = float(self.mapper.layout_loader.height)
        pc_w = float(self.mapper.screen_w)
        pc_h = float(self.mapper.screen_h)
        
        ratio_x = (pc_w / dev_w) if dev_w > 0 else 1.0
        ratio_y = (pc_h / dev_h) if dev_h > 0 else 1.0
        sens_x = self.config.settings.sensitivity_x
        sens_y = self.config.settings.sensitivity_y
        
        final_sens_x = sens_x * ratio_x
        final_sens_y = sens_y * ratio_y
        
        # 1. Check if the layout explicitly defined a custom POINTER / Look zone
        custom_look_zone = None
        
        for zone in self.mapper.layout_loader.zones:
            try:
                zone.set_parsed_config_from_json()
                sem_idx, _, _ = zone.CONFIG_HELPER.get_semantic_config()

                if sem_idx == 2: # POINTER
                    custom_look_zone = zone
                    break
            except Exception:
                pass

        if custom_look_zone is not None:
            zone = custom_look_zone
            reg_type = zone.zone_type.upper()
            
            # Inspect custom zone sensitivity overrides
            zone.set_parsed_config_from_json()
            _, _, trans_sens_x, trans_sens_y, _, _ = zone.CONFIG_HELPER.get_transform_config()
            
            sens_x = trans_sens_x if zone.ignore_app_settings else self.config.settings.sensitivity_x
            sens_y = trans_sens_y if zone.ignore_app_settings else self.config.settings.sensitivity_y
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
            wasd_is_floating = self.mapper.is_floating_joystick

            # If WASD is fixed, mouse mapper can claim touches across the full screen
            if not wasd_is_floating:
                look_region = AlwaysRegion()
                logger.info(
                    "MouseMapper assigned Full-Screen Region (Fixed Joystick active)."
                )
            else:
                # Floating joystick active: restrict look control to opposite half
                if self.config.settings.left_handed:
                    look_region = RectangularRegion(
                        Point(0.0, 0.0), Point(dev_w / 2.0, dev_h)
                    )
                else:
                    look_region = RectangularRegion(
                        Point(dev_w / 2.0, 0.0), Point(dev_w, dev_h)
                    )
                logger.info(
                    "MouseMapper restricted to %s half-screen (Floating Joystick active).",
                    "Left" if self.config.settings.left_handed else "Right",
                )
                
        logger.info(
            f"\n[MOUSEMAPPER] - Sync: PC width ({pc_w}px) / Phone width ({dev_w}px) = X Ratio ({ratio_x:.2f}).\
              \n[MOUSEMAPPER] - Final X Sensitivity: {final_sens_x:.4f} (User X Sensitivity: {sens_x}x).\
              \n\
              \n[MOUSEMAPPER] - Sync: PC height ({pc_h}px) / Phone height ({dev_h}px) = Y Ratio ({ratio_y:.2f}).\
              \n[MOUSEMAPPER] - Final Y Sensitivity: {final_sens_y:.4f} (User Y Sensitivity: {sens_y}x)."
        )
        
        self.final_sens_x = final_sens_x
        self.final_sens_y = final_sens_y

        pipeline = Pipeline(
            region=look_region,
            origin=DynamicOrigin(),
            constraint=NoConstraint(),
            transformation=DeltaTransform(sensitivity_x=final_sens_x, sensitivity_y=final_sens_y),
            semantics=[PointerSemantic()],
        )
        with self.lock:
            self.pipeline = pipeline

    def process_touch(self, touch_event: TouchEvent, is_visible: bool) -> None:
        if is_visible:
            # Menu mode: cursor visible, direct 1:1 absolute coordinate targeting
            gx, gy = self.mapper.device_to_game_abs(
                touch_event.position.x, touch_event.position.y
            )

            if touch_event.phase is TouchPhase.DOWN:
                self.bridge.left_click_down()
            elif touch_event.phase is TouchPhase.MOVE:
                self.bridge.mouse_move_abs(int(round(gx)), int(round(gy)))                
            elif touch_event.phase is TouchPhase.UP:
                self.bridge.left_click_up()
            return

        with self.lock:
            if self.pipeline:
                self.pipeline.process(touch_event, self.output_sink)

    def touch_up(self) -> None:
        with self.lock:
            if self.pipeline:
                self.pipeline.reset(self.output_sink)

    def _aggregate(
        self, sum_dx: float, sum_dy: float, acc_x: float, acc_y: float
    ) -> None:
        self.output_sink.mouse_move(sum_dx * self.final_sens_x, sum_dy * self.final_sens_y)