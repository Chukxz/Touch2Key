from __future__ import annotations

from typing import TYPE_CHECKING
import threading

from modules.utils import BEZEL, scale_coord
from modules.core.pipeline import RectangularRegion, Point
from modules.core.pipeline_factory import SystemToggle

if TYPE_CHECKING:
    from modules.core.mapper import Mapper
    from modules.core.pipeline_output import BridgeOutputSink


class BezelMapper:
    def __init__(self, mapper: Mapper, output_sink: BridgeOutputSink):
        self.mapper = mapper
        self.output_sink = output_sink
        self.mapper_event_dispatcher = mapper.mapper_event_dispatcher

        self.lock = threading.Lock()
        self.pipelines = []

        self._build_pipelines()

        self.mapper_event_dispatcher.register_callback("ON_LAYOUT_RELOAD", self._build_pipelines)
        self.mapper_event_dispatcher.register_callback("ON_WORKER_RESPAWN", self._on_worker_respawn)

    def _build_pipelines(self):
        bezels_raw_zones = self.mapper.layout_loader.bezels_json_data.copy()
        w = float(self.mapper.layout_loader.width)
        h = float(self.mapper.layout_loader.height)

        new_pipelines = []

        for scancode, values in bezels_raw_zones:
            z_type = str(values.get("type", ""))
            priority = int(values.get("priority", 0))

            if z_type == BEZEL:
                region = RectangularRegion(
                    top_left=Point(scale_coord(w, values.get("x1")), scale_coord(h, values.get("y1"))),
                    bottom_right=Point(scale_coord(w, values.get("x2")), scale_coord(h, values.get("y2"))),
                )
                pipeline = SystemToggle(output=(str(scancode)), region=region, priority=priority)
                new_pipelines.append(pipeline)

        with self.lock:
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
