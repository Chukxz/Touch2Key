from __future__ import annotations

from typing import TYPE_CHECKING
import threading

from modules.utils import BEZEL

if TYPE_CHECKING:
    from modules.core import Mapper, BridgeOutputSink

class BezelMapper():
    """Manages bezels using pipeline architecture"""
    def __init__(self, mapper: Mapper):
        self.mapper = mapper
        self.config = mapper.config
        self.bridge = mapper.bridge
        self.output_sink = BridgeOutputSink(self.bridge)
        self.mapper_event_dispatcher = mapper.mapper_event_dispatcher

        self.lock = threading.Lock()
        self.pipeline = None

        self._build_pipelines()
        
            
    def _build_pipelines(self):
        bezel_zones = [z for z in zones if z.zone_type == "BEZEL"]

        for z in bezel_zones:
            bezel_pipeline = create_pipeline_from_zone(
                zone=z,
                screen_width=float(self.width),
                screen_height=float(self.height),
                toggle_mode_callback=self.toggle_mode_callback,
            )
            if bezel_pipeline is not None:
                compiled_pipelines.append(bezel_pipeline)