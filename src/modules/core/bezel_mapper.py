from __future__ import annotations

from typing import TYPE_CHECKING, Callable
import threading

from modules.utils import BEZEL, scale_coord

from modules.core.pipeline import RectangularRegion, Point, SystemToggle

from modules.core import BridgeOutputSink

if TYPE_CHECKING:
    from modules.core import Mapper, BridgeOutputSink


class BezelMapper:
    """Manages bezels using pipeline architecture"""

    def __init__(
        self,
        mapper: Mapper,
        toggle_mode: Callable[[], None] | None = None,
        toggle_vkb: Callable[[], None] | None = None,
    ):
        self.mapper = mapper
        self.config = mapper.config
        self.bridge = mapper.bridge
        self.output_sink = BridgeOutputSink(self.bridge, toggle_mode, toggle_vkb)
        self.mapper_event_dispatcher = mapper.mapper_event_dispatcher

        self.lock = threading.Lock()
        self.pipelines = []

        self._build_pipelines()

    def _build_pipelines(self):
        bezels_raw_zones = self.mapper.layout_loader.bezels_json_data.copy()
        w = float(self.mapper.layout_loader.width)
        h = float(self.mapper.layout_loader.height)
        
        new_pipelines = []

        for scancode, value in bezels_raw_zones:
            z_type = value.get("type")
            priority = value.get("priority", 0)
            
            if z_type == BEZEL:
                region = RectangularRegion(
                    top_left=Point(scale_coord(w, value.get("x1")), scale_coord(h, value.get("y1"))),
                    bottom_right=Point(scale_coord(w, value.get("x2")), scale_coord(h, value.get("y2")))
                )
                
                pipeline = SystemToggle(
                    output=(str(scancode)),
                    region = region,
                    priority=priority
                )
                
                new_pipelines.append(pipeline)
        
        with self.lock:
            self.pipelines = new_pipelines