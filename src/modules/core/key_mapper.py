from __future__ import annotations

import logging
import threading
from typing import TYPE_CHECKING, Any

from modules.core.pipeline import CircularRegion, Point, RectangularRegion
from modules.core.pipeline_factory import Button
from modules.core.pipeline_output import BridgeOutputSink
from modules.database import store
from modules.utils import (
    CIRCLE,
    EXCLUDED_KEYS,
    MOUSE_SCANCODES,
    MOUSE_WHEEL_SIMULATOR_CODE,
    RECTANGLE,
    SPRINT_DISTANCE_CODE,
    get_scancode_from_key,
    scale_coord,
)

if TYPE_CHECKING:
    from .mapper import Mapper

logger = logging.getLogger("modules.core.key_mapper")


class KeyMapper:
    def __init__(
        self,
        mapper: Mapper,
        output_sink: BridgeOutputSink,
    ):
        self.mapper = mapper
        self.bridge = mapper.bridge
        self.output_sink = output_sink
        self.mapper_event_dispatcher = mapper.mapper_event_dispatcher

        self.lock = threading.Lock()
        self.pipelines: list[Any] = []
        self.ignored_keys = {MOUSE_WHEEL_SIMULATOR_CODE, SPRINT_DISTANCE_CODE}

        self._update_bridge_typematics()
        self.rebuild_pipelines()

        self.mapper.mapper_event_dispatcher.register_callback(
            "ON_RELOAD", self._update_bridge_typematics
        )
        self.mapper_event_dispatcher.register_callback(
            "ON_RELOAD", self.rebuild_pipelines
        )
        self.mapper_event_dispatcher.register_callback(
            "ON_WORKER_RESPAWN", self._on_worker_respawn_key
        )

    def _resolve_scancode_set(self, raw_tokens: str | None) -> set[int]:
        source = raw_tokens if raw_tokens else EXCLUDED_KEYS
        tokens = {k.strip().lower() for k in source.split(",") if k.strip()}
        resolved_codes = set()
        for token in tokens:
            code = get_scancode_from_key(token)
            if code is not None:
                resolved_codes.add(code)
        return resolved_codes

    def _update_bridge_typematics(self) -> None:
        settings = store.settings.get()
        resolved = self._resolve_scancode_set(settings.typematic_excluded_keys)
        self.bridge.update_typematic(
            enabled=settings.typematic_enabled,
            delay_ms=settings.typematic_delay_ms,
            rate_hz=settings.typematic_rate_hz,
            exclude_scancodes=resolved,
        )
        logger.info("KeyMapper updated typematic parameters to bridge.")

    def rebuild_pipelines(self) -> None:
        settings = store.settings.get()
        layout = store.get_active_layout()
        if layout is None:
            logger.warning(
                "No active layout found in SQLite database. KeyMapper pipelines will be empty."
            )
            self.release_all()
            with self.lock:
                self.pipelines = []
            return

        key_raw_zones = self.mapper.layout_loader.keys_json_data.copy()
        w = float(layout.width)
        h = float(layout.height)

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
            is_mouse_btn = scancode in MOUSE_SCANCODES

            sens_x = (
                float(values.get("sensitivity_x", 1.0))
                if ignore_app_settings
                else settings.sensitivity_x
            )
            sens_y = (
                float(values.get("sensitivity_y", 1.0))
                if ignore_app_settings
                else settings.sensitivity_y
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
                button=scancode,
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
            for pipeline in self.pipelines:
                pipeline.reset(self.output_sink)
            self.pipelines = new_pipelines

    def release_all(self) -> None:
        with self.lock:
            for pipeline in self.pipelines:
                pipeline.reset(self.output_sink)

    def _on_worker_respawn_key(self, worker_type: str) -> None:
        if worker_type == "keyboard":
            self.release_all()
            self._update_bridge_typematics()
