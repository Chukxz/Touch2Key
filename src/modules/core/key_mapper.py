from __future__ import annotations

import logging
import threading
from typing import TYPE_CHECKING, Callable

from modules.core.pipeline import (
    Button,
    CircularRegion,
    Point,
    RectangularRegion,
    ModeAwareRegion,
    TrackFire,
)
from modules.core.pipeline_output import BridgeOutputSink
from modules.utils import (
    CIRCLE,
    RECTANGLE,
    M_LEFT,
    M_RIGHT,
    M_MIDDLE,
    MOUSE_WHEEL_CODE,
    SPRINT_DISTANCE_CODE,
    TouchEvent,
)

if TYPE_CHECKING:
    from .mapper import Mapper

logger = logging.getLogger("modules.core.key_mapper")


class KeyMapper:
    """Manages zone-mapped buttons and track-fire pipelines."""

    def __init__(self, mapper: Mapper, on_toggle_mode: Callable[[], None] | None = None):
        self.mapper = mapper
        self.config = mapper.config
        self.bridge = mapper.bridge
        self.output_sink = BridgeOutputSink(self.bridge, on_toggle_mode)
        self.mapper_event_dispatcher = mapper.mapper_event_dispatcher

        self.lock = threading.Lock()
        self.pipelines = []
        self.ignored_keys = {MOUSE_WHEEL_CODE, SPRINT_DISTANCE_CODE}

        self._build_pipelines()

        self.mapper_event_dispatcher.register_callback("ON_LAYOUT_RELOAD", self._build_pipelines)
        self.mapper_event_dispatcher.register_callback("ON_WORKER_RESPAWN", self._on_worker_respawn)

    def _build_pipelines(self) -> None:
        raw_zones = self.mapper.layout_loader.json_data.copy()
        w = float(self.mapper.layout_loader.width)
        h = float(self.mapper.layout_loader.height)
        toggle_scancode = self.mapper.toggle_key_scancode

        new_pipelines = []

        for scancode, value in raw_zones:
            name = value.get("name", "")
            if name in self.ignored_keys:
                continue

            z_type = value.get("type")
            move_camera = value.get("move_camera", False)
            priority = value.get("priority", 0)

            # 1. Base Geometry
            if z_type == CIRCLE:
                base_region = CircularRegion(
                    center=Point(value["cx"] * w, value["cy"] * h),
                    radius=value["r"] * w,
                )
            elif z_type == RECTANGLE:
                base_region = RectangularRegion(
                    top_left=Point(value["x1"] * w, value["y1"] * h),
                    bottom_right=Point(value["x2"] * w, value["y2"] * h),
                )
            else:
                continue

            # 2. Check if this is the explicit Toggle Zone
            is_toggle_zone = (
                toggle_scancode is not None
                and (
                    scancode == toggle_scancode
                    or str(scancode) == str(toggle_scancode)
                    or name == self.mapper.emulator.get("toggle_key")
                )
            )

            if is_toggle_zone:
                # Mode-Aware: Only intercepts touch when cursor is hidden
                region = ModeAwareRegion(base_region=base_region, engine_ref=self.mapper.engine_ref)
            else:
                region = base_region

            # 3. Construct Pipeline
            is_mouse_btn = scancode in (M_LEFT, M_RIGHT, M_MIDDLE)
            if move_camera:
                pipeline = TrackFire(
                    button=str(scancode),
                    region=region,
                    sensitivity_x=self.config.settings.sensitivity,
                    sensitivity_y=self.config.settings.sensitivity,
                    priority=priority,
                )
            else:
                pipeline = Button(
                    output=str(scancode),
                    region=region,
                    mouse_button=is_mouse_btn,
                    priority=priority,
                )

            new_pipelines.append(pipeline)

        with self.lock:
            self.pipelines = new_pipelines

    def process_touch(self, touch_event: TouchEvent, is_visible: bool) -> None:
        if is_visible:
            return

        with self.lock:
            for pipeline in self.pipelines:
                pipeline.process(touch_event, self.output_sink)

    def release_all(self) -> None:
        with self.lock:
            for pipeline in self.pipelines:
                pipeline.reset(self.output_sink)

    def _on_worker_respawn(self, worker_type: str) -> None:
        self.release_all()