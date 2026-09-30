from __future__ import annotations

import logging
import threading
from typing import TYPE_CHECKING, Any

from modules.core.pipeline import (
    CircularRegion,
    Point,
    RectangularRegion,
)
from modules.core.pipeline_output import BridgeOutputSink
from modules.core.pipeline_factory import Button

from modules.utils import (
    CIRCLE,
    M_LEFT,
    M_MIDDLE,
    M_RIGHT,
    MOUSE_WHEEL_SIMULATOR_CODE,
    RECTANGLE,
    SPRINT_DISTANCE_CODE,
    EXCLUDED_KEYS,
    get_scancode_from_key,
    scale_coord,
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
        output_sink: BridgeOutputSink,
        typematic_enabled: bool = True,
        typematic_delay_ms: float = 250.0,
        typematic_rate_hz: float = 30.0,
        typematic_excluded_keys: str | None = None,
    ):
        self.mapper = mapper
        self.config = mapper.config
        self.bridge = mapper.bridge
        self.output_sink = output_sink
        self.mapper_event_dispatcher = mapper.mapper_event_dispatcher

        self.typematic_enabled = typematic_enabled
        self.typematic_delay_ms = typematic_delay_ms
        self.typematic_rate_hz = typematic_rate_hz
        self.typematic_excluded_keys = typematic_excluded_keys

        # Tracks touch slot assignments for camera look suppression
        self.lock = threading.Lock()
        self.pipelines = []
        self.ignored_keys = {MOUSE_WHEEL_SIMULATOR_CODE, SPRINT_DISTANCE_CODE}

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
        fallback = set(EXCLUDED_KEYS)
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
        resolved = self._resolve_scancode_set(self.typematic_excluded_keys)
        self.bridge.update_typematic(
            enabled=self.typematic_enabled,
            delay_ms=self.typematic_delay_ms,
            rate_hz=self.typematic_rate_hz,
            exclude_scancodes=resolved,
        )

    def _on_config_reload(self) -> None:
        """Hot-reloads settings and updates the low-level bridge."""
        s = self.config.settings
        if s:
            self.typematic_enabled = bool(getattr(s, "typematic_enabled", True))
            self.typematic_delay_ms = float(getattr(s, "typematic_delay_ms", 250.0))
            self.typematic_rate_hz = float(getattr(s, "typematic_rate_hz", 30.0))
            self.typematic_excluded_keys = getattr(s, "typematic_excluded_keys", None)
            self._sync_typematic_to_bridge()
            logger.info("KeyMapper pushed updated typematic parameters to bridge.")

    def _build_pipelines(self) -> None:
        key_raw_zones = self.mapper.layout_loader.keys_json_data.copy()
        w = float(self.mapper.layout_loader.width)
        h = float(self.mapper.layout_loader.height)

        new_pipelines = []

        for scancode, values in key_raw_zones:
            name = values.get("name", "")
            if name in self.ignored_keys:
                continue

            z_id = int(values.get("id", 0))
            z_type = str(values.get("type", ""))
            pointer = bool(values.get("pointer", False))
            priority = int(values.get("priority", 0))
            ignore_app_settings = bool(values.get("ignore_app_settings", False))
            is_mouse_btn = scancode in (M_LEFT, M_RIGHT, M_MIDDLE)

            sens_x = (
                float(values.get("sensitivity_x", 1.0))
                if ignore_app_settings
                else self.config.settings.sensitivity_x
            )
            sens_y = float(
                (values.get("sensitivity_y", 1.0))
                if ignore_app_settings
                else self.config.settings.sensitivity_y
            )

            if z_type == CIRCLE:
                region = CircularRegion(
                    center=Point(
                        scale_coord(w, values.get("cx")),
                        scale_coord(h, values.get("cy")),
                    ),
                    radius=scale_coord(w, values.get("r", values.get("val1", 50.0))),
                )
            elif z_type == RECTANGLE:
                region = RectangularRegion(
                    top_left=Point(
                        scale_coord(w, values.get("x1")),
                        scale_coord(h, values.get("y1")),
                    ),
                    bottom_right=Point(
                        scale_coord(w, values.get("x2")),
                        scale_coord(h, values.get("y2")),
                    ),
                )
            else:
                continue

            pipeline = Button(
                button=str(scancode),
                region=region,
                pointer=pointer,
                sensitivity_x=sens_x,
                sensitivity_y=sens_y,
                mouse_button=is_mouse_btn,
                priority=priority,
                creation_id=z_id,
            )

            new_pipelines.append(pipeline)

        with self.lock:
            # Release any active keys held by the previous pipeline before swapping
            for pipeline in self.pipelines:
                pipeline.reset(self.output_sink)

            self.pipelines = new_pipelines

    def release_all(self) -> None:
        with self.lock:
            for pipeline in self.pipelines:
                pipeline.reset(self.output_sink)

    def _on_worker_respawn(self, worker_type: str) -> None:
        if worker_type == "keyboard":
            self.release_all()
            self._sync_typematic_to_bridge()
