from __future__ import annotations

import logging
import threading
from typing import TYPE_CHECKING, Any

from modules.core.pipeline import Point, RectangularRegion
from modules.core.pipeline_factory import SystemToggle
from modules.database import store
from modules.utils import (
    BEZEL,
    scale_coord,
)

if TYPE_CHECKING:
    from modules.core.mapper import Mapper
    from modules.core.pipeline_output import BridgeOutputSink

logger = logging.getLogger("modules.core.bezel_mapper")


class BezelMapper:
    def __init__(self, mapper: Mapper, output_sink: BridgeOutputSink):
        self.mapper = mapper
        self.output_sink = output_sink
        self.mapper_event_dispatcher = mapper.mapper_event_dispatcher

        self.lock = threading.Lock()
        self.pipelines: list[Any] = []

        self.rebuild_pipelines()

        self.mapper_event_dispatcher.register_callback(
            "ON_LAYOUT_RELOAD", self.rebuild_pipelines
        )
        self.mapper_event_dispatcher.register_callback(
            "ON_WORKER_RESPAWN", self._on_worker_respawn_bezel
        )

    def rebuild_pipelines(self) -> None:
        layout = store.get_active_layout()
        if layout is None:
            logger.warning(
                "No active layout found in SQLite database. BezelMapper pipelines will be empty."
            )
            self.release_all()
            with self.lock:
                self.pipelines = []
            return

        bezels_raw_zones = self.mapper.layout_loader.bezels_json_data.copy()
        w = float(layout.width)
        h = float(layout.height)

        new_pipelines = []

        for scancode, values in bezels_raw_zones:
            z_type = str(values.get("type", ""))
            priority = int(values.get("priority", 0))
            zone_id = int(values.get("id", 0))

            if z_type != BEZEL:
                continue

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

            pipeline = SystemToggle(
                output=scancode,
                region=region,
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

    def _on_worker_respawn_bezel(self, worker_type: str) -> None:
        if worker_type == "keyboard":
            self.release_all()
