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
from modules.utils import TouchEvent

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
        s = self.config.settings
        sens = s.sensitivity
        dev_w = float(self.mapper.layout_loader.width)
        dev_h = float(self.mapper.layout_loader.height)
        pc_w = float(self.mapper.screen_w)
        ratio = (pc_w / dev_w) if dev_w > 0 else 1.0
        final_sens = sens * ratio

        # 1. Check if the layout explicitly defined a custom POINTER / Look zone
        custom_look_zone = None
        for zone in self.mapper.layout_loader.zones:
            try:
                cfg = json.loads(zone.pipeline_config or "{}")
                if cfg.get("semantics", {}).get("mode") == "POINTER":
                    custom_look_zone = (zone, cfg)
                    break
            except Exception:
                pass
            if (
                zone.name in ("LOOK_AREA", "Relative Pointer")
                or zone.scancode == "MOUSE_LOOK"
            ):
                custom_look_zone = (zone, {})
                break

        if custom_look_zone:
            zone, cfg = custom_look_zone
            reg_type = zone.zone_type.upper()

            # Helper to safely scale normalized (0-1) coordinates up to device dimensions
            def _scale_x(val: float | None) -> float:
                if val is None:
                    return 0.0
                return val * dev_w if val <= 1.0 else val

            def _scale_y(val: float | None) -> float:
                if val is None:
                    return 0.0
                return val * dev_h if val <= 1.0 else val

            if (
                reg_type == "CIRCLE"
                and zone.cx is not None
                and zone.cy is not None
                and zone.r
            ):
                look_region = CircularRegion(
                    Point(_scale_x(zone.cx), _scale_y(zone.cy)),
                    _scale_x(zone.r),
                )
            elif (
                reg_type == "RECTANGLE"
                and zone.x1 is not None
                and zone.y1 is not None
                and zone.x2 is not None
                and zone.y2 is not None
            ):
                look_region = RectangularRegion(
                    Point(_scale_x(zone.x1), _scale_y(zone.y1)),
                    Point(_scale_x(zone.x2), _scale_y(zone.y2)),
                )
            else:
                look_region = AlwaysRegion()

            # Inspect custom zone sensitivity overrides if provided
            trans_cfg = cfg.get("transform", {})
            sens_x = trans_cfg.get("sens_x", final_sens)
            sens_y = trans_cfg.get("sens_y", final_sens)

            logger.info(
                "MouseMapper assigned custom layout Look Area: '%s' (%s)",
                zone.name,
                reg_type,
            )
        else:
            sens_x = final_sens
            sens_y = final_sens
            wasd_is_floating = self.mapper.is_floating_joystick

            # If WASD is fixed, mouse mapper can claim touches across the full screen
            if not wasd_is_floating:
                look_region = AlwaysRegion()
                logger.info(
                    "MouseMapper assigned Full-Screen Region (Fixed Joystick active)."
                )
            else:
                # Floating joystick active: restrict look control to opposite half
                if s.left_handed:
                    look_region = RectangularRegion(
                        Point(0.0, 0.0), Point(dev_w / 2.0, dev_h)
                    )
                else:
                    look_region = RectangularRegion(
                        Point(dev_w / 2.0, 0.0), Point(dev_w, dev_h)
                    )
                logger.info(
                    "MouseMapper restricted to %s half-screen (Floating Joystick active).",
                    "Left" if s.left_handed else "Right",
                )

        pipeline = Pipeline(
            region=look_region,
            origin=DynamicOrigin(),
            constraint=NoConstraint(),
            transformation=DeltaTransform(sensitivity_x=sens_x, sensitivity_y=sens_y),
            semantics=[PointerSemantic()],
        )
        with self.lock:
            self.pipeline = pipeline

    def _should_suppress_touch(self, touch_event: TouchEvent) -> bool:
        """Determines if a touch slot is claimed by a TRACK_FIRE or button zone

        that forbids camera/mouse look tracking.
        """
        key_mapper = getattr(self.mapper, "key_mapper", None)
        if not key_mapper:
            return False

        slot_id = getattr(touch_event, "slot", None) or getattr(
            touch_event, "tracking_id", None
        )
        active_zone = (
            key_mapper.get_active_zone_for_slot(slot_id)
            if hasattr(key_mapper, "get_active_zone_for_slot")
            else None
        )

        if active_zone is not None:
            # Standard buttons only pass motion to camera if move_camera is True
            if not getattr(active_zone, "move_camera", False):
                return True

        return False

    def process_touch(self, touch_event: TouchEvent, is_visible: bool) -> None:
        if is_visible:
            # Menu mode: cursor visible, direct 1:1 absolute coordinate targeting
            gx, gy = self.mapper.device_to_game_abs(
                touch_event.position.x, touch_event.position.y
            )
            self.bridge.mouse_move_abs(int(round(gx)), int(round(gy)))

            if touch_event.phase is TouchPhase.DOWN:
                self.bridge.left_click_down()
            elif touch_event.phase is TouchPhase.UP:
                self.bridge.left_click_up()
            return

        # Suppress motion if this touch contact belongs to a TRACK_FIRE reticle drag
        if self._should_suppress_touch(touch_event):
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
        sens = self.config.settings.sensitivity
        self.output_sink.mouse_move(sum_dx * sens, sum_dy * sens)