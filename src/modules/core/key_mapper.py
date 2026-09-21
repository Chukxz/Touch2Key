from __future__ import annotations

import logging
import threading
from typing import TYPE_CHECKING, Any

from modules.core.pipeline import (
    Button,
    CircularRegion,
    Point,
    RectangularRegion,
    TrackFire,
)
from modules.core import BridgeOutputSink
from modules.utils import (
    CIRCLE,
    M_LEFT,
    M_MIDDLE,
    M_RIGHT,
    MOUSE_WHEEL_CODE,
    RECTANGLE,
    SPRINT_DISTANCE_CODE,
    EXCLUDE_KEYS,
    TouchEvent,
    TouchPhase,
    get_scancode_from_key,
)

if TYPE_CHECKING:
    from .mapper import Mapper

logger = logging.getLogger("modules.core.key_mapper")


class KeyMapper:
    """Manages zone-mapped buttons, track-fire pipelines, and coordinates

    typematic configurations directly with the low-level hardware bridge.
    """

    def __init__(
        self,
        mapper: Mapper,
        typematic_enabled: bool = True,
        typematic_delay_ms: float = 250.0,
        typematic_rate_hz: float = 30.0,
        typematic_exclude_keys: str | None = None,
    ):
        self.mapper = mapper
        self.config = mapper.config
        self.bridge = mapper.bridge
        self.output_sink = BridgeOutputSink(self.bridge)
        self.mapper_event_dispatcher = mapper.mapper_event_dispatcher

        self.typematic_enabled = typematic_enabled
        self.typematic_delay_ms = typematic_delay_ms
        self.typematic_rate_hz = typematic_rate_hz
        self.typematic_exclude_keys = typematic_exclude_keys

        # Tracks touch slot assignments for camera look suppression
        self.slot_zone_map: dict[int, Any] = {}
        self.lock = threading.Lock()
        self.pipelines = []
        self.ignored_keys = {MOUSE_WHEEL_CODE, SPRINT_DISTANCE_CODE}

        self._build_pipelines()
        self._sync_typematic_to_bridge()

        self.mapper_event_dispatcher.register_callback(
            "ON_LAYOUT_RELOAD", self._build_pipelines
        )
        self.mapper_event_dispatcher.register_callback(
            "ON_WORKER_RESPAWN", self._on_worker_respawn
        )
        self.mapper_event_dispatcher.register_callback(
            "ON_CONFIG_RELOAD", self._on_config_reload
        )

    def _resolve_scancode_set(self, raw_tokens: str | None) -> set[int]:
        """Maps comma-separated string tokens into numerical hardware scancodes."""
        fallback = set(EXCLUDE_KEYS)
        tokens = (
            {k.strip().lower() for k in raw_tokens.split(",") if k.strip()}
            if raw_tokens
            else fallback
        )

        resolved_codes = set()
        for token in tokens:
            code = get_scancode_from_key(token)
            if code is not None:
                resolved_codes.add(code)
        return resolved_codes

    def _sync_typematic_to_bridge(self) -> None:
        """Dispatches current typematic parameters to the driver worker process."""
        resolved = self._resolve_scancode_set(self.typematic_exclude_keys)
        if hasattr(self.bridge, "update_typematic"):
            self.bridge.update_typematic(
                enabled=self.typematic_enabled,
                delay_ms=self.typematic_delay_ms,
                rate_hz=self.typematic_rate_hz,
                exclude_scancodes=resolved,
            )

    def _on_config_reload(self) -> None:
        """Hot-reloads settings and updates the low-level bridge."""
        s = getattr(self.config, "settings", None)
        if s:
            self.typematic_enabled = bool(getattr(s, "typematic_enabled", True))
            self.typematic_delay_ms = float(getattr(s, "typematic_delay_ms", 250.0))
            self.typematic_rate_hz = float(getattr(s, "typematic_rate_hz", 30.0))
            self.typematic_exclude_keys = getattr(s, "typematic_exclude_keys", None)
            self._sync_typematic_to_bridge()
            logger.info("KeyMapper pushed updated typematic parameters to bridge.")

    def get_active_zone_for_slot(self, slot_id: int | None):
        """Allows MouseMapper to inspect if a touch slot belongs to TRACK_FIRE."""
        if slot_id is None:
            return None
        with self.lock:
            return self.slot_zone_map.get(slot_id)

    def _build_pipelines(self) -> None:
        raw_zones = self.mapper.layout_loader.keys_json_data.copy()
        w = float(self.mapper.layout_loader.width)
        h = float(self.mapper.layout_loader.height)

        def _scale_x(val: float | None) -> float:
            if val is None:
                return 0.0
            return val * w if val <= 1.0 else val

        def _scale_y(val: float | None) -> float:
            if val is None:
                return 0.0
            return val * h if val <= 1.0 else val

        new_pipelines = []

        for scancode, value in raw_zones:
            name = value.get("name", "")
            if name in self.ignored_keys:
                continue

            z_type = value.get("type")
            move_camera = value.get("move_camera", False)
            priority = value.get("priority", 0)

            if z_type == CIRCLE:
                base_region = CircularRegion(
                    center=Point(_scale_x(value.get("cx")), _scale_y(value.get("cy"))),
                    radius=_scale_x(value.get("r", value.get("val1", 50.0))),
                )
            elif z_type == RECTANGLE:
                base_region = RectangularRegion(
                    top_left=Point(_scale_x(value.get("x1")), _scale_y(value.get("y1"))),
                    bottom_right=Point(_scale_x(value.get("x2")), _scale_y(value.get("y2"))),
                )
            else:
                continue

            region = base_region

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

        slot_id = getattr(touch_event, "slot", None) or getattr(
            touch_event, "tracking_id", None
        )

        with self.lock:
            for pipeline in self.pipelines:
                claimed = pipeline.process(touch_event, self.output_sink)
                if claimed and slot_id is not None:
                    if touch_event.phase is TouchPhase.DOWN:
                        self.slot_zone_map[slot_id] = pipeline
                    elif touch_event.phase is TouchPhase.UP:
                        self.slot_zone_map.pop(slot_id, None)

    def release_all(self) -> None:
        with self.lock:
            self.slot_zone_map.clear()
            for pipeline in self.pipelines:
                pipeline.reset(self.output_sink)

    def _on_worker_respawn(self, worker_type: str) -> None:
        self.release_all()
        if worker_type == "keyboard":
            self._sync_typematic_to_bridge()

    def stop(self) -> None:
        self.release_all()