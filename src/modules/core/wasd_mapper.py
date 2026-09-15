from __future__ import annotations

import logging
import threading
from typing import TYPE_CHECKING

from modules.core.pipeline import (
    CircularRegion,
    FixedJoystick,
    FloatingJoystick,
    AnchoredFloatingJoystick,
    Point,
    RectangularRegion,
)
from modules.core.pipeline_output import BridgeOutputSink
from modules.utils import CIRCLE, MOUSE_WHEEL_CODE, TouchEvent

if TYPE_CHECKING:
    from .mapper import Mapper

logger = logging.getLogger("modules.core.wasd_mapper")


class WASDMapper:
    """Manages directional joystick movement and sprint using Pipeline architecture."""

    def __init__(self, mapper: Mapper):
        self.mapper = mapper
        self.config = mapper.config
        self.bridge = mapper.bridge
        self.output_sink = BridgeOutputSink(self.bridge)
        self.mapper_event_dispatcher = mapper.mapper_event_dispatcher

        self.lock = threading.Lock()
        self.pipeline = None

        self._build_pipeline()

        self.mapper_event_dispatcher.register_callback(
            "ON_CONFIG_RELOAD", self._build_pipeline
        )
        self.mapper_event_dispatcher.register_callback(
            "ON_LAYOUT_RELOAD", self._build_pipeline
        )
        self.mapper_event_dispatcher.register_callback(
            "ON_WORKER_RESPAWN", self._on_worker_respawn
        )
        self.mapper_event_dispatcher.register_callback(
            "ON_WASD_BLOCK", self._on_wasd_block
        )

    def _build_pipeline(self) -> None:
        s = self.config.settings
        inner_r, outer_r = self.mapper.layout_loader.get_mouse_wheel_info()
        w = float(self.mapper.layout_loader.width)
        h = float(self.mapper.layout_loader.height)

        raw_zones = self.mapper.layout_loader.json_data.copy()

        # Check if the layout defines an explicit fixed HUD joystick zone
        fixed_zone = None
        for scancode, z_dict in raw_zones:
            if z_dict.get("name") == MOUSE_WHEEL_CODE and z_dict.get("type") == CIRCLE:
                fixed_zone = z_dict
                break

        # Determine movement half-screen partition based on handedness
        if s.left_handed:
            half_screen_region = RectangularRegion(Point(w / 2.0, 0.0), Point(w, h))
        else:
            half_screen_region = RectangularRegion(Point(0.0, 0.0), Point(w / 2.0, h))

        anchored_enabled = getattr(s, "anchored_floating_joystick", False)

        if fixed_zone is not None and anchored_enabled:
            # -------------------------------------------------------------
            # 1. Anchored Floating Joystick (Hybrid)
            # -------------------------------------------------------------
            self.mapper.is_floating_joystick = True
            anchor_pt = Point(fixed_zone["cx"] * w, fixed_zone["cy"] * h)
            snap_r = (
                fixed_zone["r"] * w
                if fixed_zone.get("r")
                else getattr(s, "joystick_snap_radius", 80.0)
            )

            pipeline = AnchoredFloatingJoystick(
                default_anchor=anchor_pt,
                region=half_screen_region,
                dead_zone=s.deadzone * inner_r,
                walk_radius=inner_r,
                sprint_radius=outer_r,
                leash_radius=outer_r,
                snap_radius=snap_r,
                hysteresis_deg=s.hysteresis,
                up="w",
                down="s",
                left="a",
                right="d",
                sprint_key=s.sprint_key or "shift",
            )
            logger.info(
                "Configured Anchored Floating Joystick at anchor=(%0.1f, %0.1f) snap_radius=%0.1f",
                anchor_pt.x,
                anchor_pt.y,
                snap_r,
            )

        elif fixed_zone is not None:
            # -------------------------------------------------------------
            # 2. Pure Fixed Joystick
            # -------------------------------------------------------------
            self.mapper.is_floating_joystick = False
            center = Point(fixed_zone["cx"] * w, fixed_zone["cy"] * h)
            touch_radius = fixed_zone["r"] * w

            pipeline = FixedJoystick(
                center=center,
                touch_radius=touch_radius,
                dead_zone=s.deadzone * inner_r,
                walk_radius=inner_r,
                sprint_radius=outer_r,
                hysteresis_deg=s.hysteresis,
                up="w",
                down="s",
                left="a",
                right="d",
                sprint_key=s.sprint_key or "shift",
            )
            logger.info(
                "Configured Fixed Joystick at (%0.1f, %0.1f) radius=%0.1f",
                center.x,
                center.y,
                touch_radius,
            )

        else:
            # -------------------------------------------------------------
            # 3. Pure Floating Joystick
            # -------------------------------------------------------------
            self.mapper.is_floating_joystick = True

            pipeline = FloatingJoystick(
                region=half_screen_region,
                dead_zone=s.deadzone * inner_r,
                walk_radius=inner_r,
                sprint_radius=outer_r,
                leash_radius=outer_r,
                hysteresis_deg=s.hysteresis,
                up="w",
                down="s",
                left="a",
                right="d",
                sprint_key=s.sprint_key or "shift",
            )
            logger.info(
                "Configured Floating Joystick (Handedness: %s)",
                "Left" if s.left_handed else "Right",
            )

        with self.lock:
            # Release any active keys held by the previous pipeline before swapping
            if self.pipeline:
                self.pipeline.reset(self.output_sink)
            self.pipeline = pipeline

    def process_touch(self, touch_event: TouchEvent, is_visible: bool) -> None:
        if is_visible or self.mapper.wasd_block > 0:
            self.touch_up()
            return

        with self.lock:
            if self.pipeline:
                self.pipeline.process(touch_event, self.output_sink)

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
