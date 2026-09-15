from __future__ import annotations

import logging
import threading
from typing import TYPE_CHECKING

from modules.core.pipeline import (
    AlwaysRegion,
    DeltaTransform,
    DynamicOrigin,
    NoConstraint,
    Pipeline,
    PointerMoveSemantic,
    Point,
    RectangularRegion,
    TouchPhase,
    Vector,
)
from modules.core.pipeline_output import BridgeOutputSink
from modules.utils import TouchEvent

if TYPE_CHECKING:
    from .mapper import Mapper

logger = logging.getLogger("modules.core.mouse_mapper")


class MouseMapper:
    """Manages camera movement. When WASD is fixed, look controls span the entire screen."""

    def __init__(self, mapper: Mapper):
        self.mapper = mapper
        self.config = mapper.config
        self.bridge = mapper.bridge
        self.output_sink = BridgeOutputSink(self.bridge)
        self.mapper_event_dispatcher = mapper.mapper_event_dispatcher

        self.lock = threading.Lock()
        self.pipeline: Pipeline[Vector] | None = None
        self._build_pipeline()

        self.mapper_event_dispatcher.register_callback("ON_CONFIG_RELOAD", self._build_pipeline)
        self.mapper_event_dispatcher.register_callback("ON_JSON_RELOAD", self._build_pipeline)
        self.mapper_event_dispatcher.register_callback("ON_AGGREGATION", self._aggregate)

    def _build_pipeline(self) -> None:
        s = self.config.settings
        sens = s.sensitivity
        dev_w = float(self.mapper.layout_loader.width)
        dev_h = float(self.mapper.layout_loader.height)
        pc_w = float(self.mapper.screen_w)
        ratio = (pc_w / dev_w) if dev_w > 0 else 1.0
        final_sens = sens * ratio

        # Determine if WASD is floating or fixed
        wasd_is_floating = self.mapper.is_floating_joystick

        # If WASD is fixed, the mouse mapper can claim touches anywhere across the full screen
        if not wasd_is_floating:
            look_region = AlwaysRegion()
            logger.info("MouseMapper assigned Full-Screen Region (Fixed Joystick active).")
        else:
            # Floating joystick active: restrict look control to opposite half
            if s.left_handed:
                look_region = RectangularRegion(Point(0.0, 0.0), Point(dev_w / 2.0, dev_h))
            else:
                look_region = RectangularRegion(Point(dev_w / 2.0, 0.0), Point(dev_w, dev_h))
            logger.info("MouseMapper restricted to %s half-screen (Floating Joystick active).", "Left" if s.left_handed else "Right")

        pipeline = Pipeline(
            region=look_region,
            origin=DynamicOrigin(),
            constraint=NoConstraint(),
            transformation=DeltaTransform(sensitivity_x=final_sens, sensitivity_y=final_sens),
            semantics=[PointerMoveSemantic()],
        )
        with self.lock:
            self.pipeline = pipeline

    def process_touch(self, touch_event: TouchEvent, is_visible: bool) -> None:
        if is_visible:
            if touch_event.phase is TouchPhase.DOWN:
                gx, gy = self.mapper.device_to_game_abs(touch_event.position.x, touch_event.position.y)
                self.bridge.mouse_move_abs(int(gx), int(gy))
                self.bridge.left_click_down()
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

    def _aggregate(self, sum_dx: float, sum_dy: float, acc_x: float, acc_y: float) -> None:
        sens = self.config.settings.sensitivity
        self.output_sink.mouse_move(sum_dx * sens, sum_dy * sens)