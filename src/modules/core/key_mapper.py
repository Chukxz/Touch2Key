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
        self.dispatcher = mapper.dispatcher

        self.lock = threading.Lock()
        self.pipelines: list[Any] = []
        self.ignored_scancodes = {MOUSE_WHEEL_SIMULATOR_CODE, SPRINT_DISTANCE_CODE}

        self._update_bridge_typematics()
        self.rebuild_pipelines()

        self.mapper.dispatcher.register_callback(
            "ON_RELOAD", self._update_bridge_typematics
        )
        self.dispatcher.register_callback("ON_RELOAD", self.rebuild_pipelines)
        self.dispatcher.register_callback(
            "ON_WORKER_RESPAWN", self._on_worker_respawn_key
        )

    def _resolve_scancode_set(self, raw_tokens: str | None) -> set[int]:
        resolved_codes = set()

        if raw_tokens is not None:
            tokens = {k.strip().lower() for k in raw_tokens.split(",") if k.strip()}
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
        layout_loader = self.mapper.engine_ref.layout_loader

        if layout_loader is None:
            logger.warning(
                "Layout Loader not initialized. KeyMapper pipelines will be empty."
            )
            self.release_all()
            with self.lock:
                self.pipelines = []
            return

        if layout is None:
            logger.warning(
                "No active layout found in SQLite database. KeyMapper pipelines will be empty."
            )
            self.release_all()
            with self.lock:
                self.pipelines = []
            return

        with layout_loader.layout_lock:
            key_raw_zones = layout_loader.keys_data.copy()

        w = float(layout.width)
        h = float(layout.height)

        new_pipelines = []

        for scancode, values in key_raw_zones:
            if scancode in self.ignored_scancodes:
                continue

            zone_id = int(values.get("id", 0))
            zone_type = str(values.get("type", ""))
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

            if zone_type == CIRCLE:
                region = CircularRegion(
                    center=Point(
                        scale_coord(w, values.get("cx")),
                        scale_coord(h, values.get("cy")),
                    ),
                    radius=scale_coord(w, values.get("r", values.get("val1", 50.0))),
                )
            elif zone_type == RECTANGLE:
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
                scancode=scancode,
                region=region,
                pointer=pointer,
                sensitivity_x=sens_x,
                sensitivity_y=sens_y,
                mouse_button=is_mouse_btn,
                priority=priority,
                creation_id=zone_id,
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
