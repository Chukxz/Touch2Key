from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from modules.core.pipeline_factory import Bezel
from modules.utils import BOTTOM_BEZEL_ID, TOP_BEZEL_ID

if TYPE_CHECKING:
    from modules.core.mapper import Mapper
    from modules.core.pipeline_output import BridgeOutputSink

logger = logging.getLogger("modules.core.bezel_mapper")


class BezelMapper:
    def __init__(self, mapper: Mapper, output_sink: BridgeOutputSink):
        self.mapper = mapper
        self.output_sink = output_sink
        self.dispatcher = mapper.dispatcher
        self.engine_ref = mapper.engine_ref
        self.pipelines: list[Any] = []
        self.rebuild_pipelines()

        self.dispatcher.register_callback(
            "ON_WORKER_RESPAWN", self._on_worker_respawn_bezel
        )

    def _clear(self, reason: str) -> None:
        logger.warning(reason)
        self.release_all()
        with self.engine_ref.lock:
            self.pipelines = []

    def rebuild_pipelines(self) -> None:
        loader = self.engine_ref.layout_loader
        if loader is None:
            self._clear("Layout Loader not initialized. BezelMapper pipelines will be empty.")
            return

        snap = loader.snapshot
        if snap.layout is None:
            self._clear(
                "No active layout found in SQLite database. BezelMapper pipelines will be empty."
            )
            return

        new_pipelines = []

        for zone in snap.bezels:
            region = zone.region()
            if region is None:
                continue

            passed_callback = None

            if zone.scancode == TOP_BEZEL_ID:
                passed_callback = self.mapper.execute_toggle_hotkeys

            elif zone.scancode == BOTTOM_BEZEL_ID:
                passed_callback = self.engine_ref.toggle_virtual_keyboard

            new_pipelines.append(
                Bezel(
                    scancode=zone.scancode,
                    region=region,
                    priority=zone.priority,
                    callback=passed_callback,
                    creation_id=zone.id,
                )
            )

        with self.engine_ref.lock:
            for pipeline in self.pipelines:
                pipeline.reset(self.output_sink)
            self.pipelines = new_pipelines

    def release_all(self) -> None:
        with self.engine_ref.lock:
            for pipeline in self.pipelines:
                pipeline.reset(self.output_sink)

    def _on_worker_respawn_bezel(self, worker_type: str) -> None:
        if worker_type == "keyboard":
            self.release_all()
