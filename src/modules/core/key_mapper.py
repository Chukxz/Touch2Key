from __future__ import annotations

import logging
import threading
from typing import TYPE_CHECKING, Any

from modules.core.pipeline_factory import Button
from modules.core.pipeline_output import BridgeOutputSink
from modules.database import store
from modules.utils import (
    MOUSE_SCANCODES,
    get_scancode_from_key,
    look_counts_per_px,
)

if TYPE_CHECKING:
    from .layout_loader import LayoutSnapshot
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

        self._update_bridge_typematics()
        self.rebuild_pipelines()

        self.dispatcher.register_callback("ON_RELOAD", self._update_bridge_typematics)
        self.dispatcher.register_callback("ON_RELOAD", self.rebuild_pipelines)
        self.dispatcher.register_callback(
            "ON_WORKER_RESPAWN", self._on_worker_respawn_key
        )

    def _snapshot(self) -> LayoutSnapshot | None:
        loader = self.mapper.engine_ref.layout_loader
        return loader.snapshot if loader is not None else None

    def _resolve_scancode_set(self, raw_tokens: str | None) -> set[int]:
        resolved_codes: set[int] = set()

        if raw_tokens is not None:
            tokens = {k.strip().lower() for k in raw_tokens.split(",") if k.strip()}
            for token in tokens:
                code = get_scancode_from_key(token)
                if code is not None:
                    resolved_codes.add(code)

        return resolved_codes

    def _update_bridge_typematics(self) -> None:
        snap = self._snapshot()
        settings = snap.settings if snap is not None else store.settings.get()
        resolved = self._resolve_scancode_set(settings.typematic_excluded_keys)
        self.bridge.update_typematic(
            enabled=settings.typematic_enabled,
            delay_ms=settings.typematic_delay_ms,
            rate_hz=settings.typematic_rate_hz,
            exclude_scancodes=resolved,
        )
        logger.info("KeyMapper updated typematic parameters to bridge.")

    def _clear(self, reason: str) -> None:
        logger.warning(reason)
        self.release_all()
        with self.lock:
            self.pipelines = []

    def rebuild_pipelines(self) -> None:
        snap = self._snapshot()
        if snap is None:
            self._clear(
                "Layout Loader not initialized. KeyMapper pipelines will be empty."
            )
            return
        layout = snap.layout
        if layout is None:
            self._clear(
                "No active layout found in SQLite database. KeyMapper pipelines will be empty."
            )
            return

        settings = snap.settings
        new_pipelines = []

        for zone in snap.keys:
            region = zone.region()
            if region is None:
                continue

            sens_x = (
                zone.sensitivity_x
                if zone.ignore_app_settings
                else settings.sensitivity_x
            )
            sens_y = (
                zone.sensitivity_y
                if zone.ignore_app_settings
                else settings.sensitivity_y
            )

            new_pipelines.append(
                Button(
                    scancode=zone.scancode,
                    region=region,
                    pointer=zone.pointer,
                    # finger px -> dp -> mouse counts, same scale as the look area
                    sensitivity_x=look_counts_per_px(sens_x, layout.dpi),
                    sensitivity_y=look_counts_per_px(sens_y, layout.dpi),
                    mouse_button=zone.scancode in MOUSE_SCANCODES,
                    priority=zone.priority,
                    creation_id=zone.id,
                )
            )

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
