from __future__ import annotations

import json
from typing import Any

from modules.core.pipeline import (
    AlwaysRegion,
    CircleRegion,
    Pipeline,
    RectRegion,
)
from modules.utils import Point


def create_pipeline_from_zone(
    zone: Any,
    screen_width: float,
    screen_height: float,
    toggle_mode_callback: Any | None = None,
) -> Pipeline | None:
    cfg_raw = getattr(zone, "pipeline_config", "{}") or "{}"
    try:
        cfg = json.loads(cfg_raw)
    except Exception:
        cfg = {}

    reg = cfg.get("region", {})
    reg_type = reg.get("type")

    # Bezel notch is managed at Engine level as the Master Bezel Return Toggle
    if reg_type == "BEZEL" or zone.zone_type == "BEZEL":
        return None

    # Stage 1: Region Selection
    if reg_type == "ALWAYS":
        region = AlwaysRegion()
    elif reg_type == "RECTANGLE" or (not reg_type and zone.zone_type == "RECTANGLE"):
        region = RectRegion(
            left=float(zone.x1 or 0.0),
            top=float(zone.y1 or 0.0),
            right=float(zone.x2 or screen_width),
            bottom=float(zone.y2 or screen_height),
        )
    else:
        region = CircleRegion(
            center=Point(float(zone.cx or 0.0), float(zone.cy or 0.0)),
            radius=float(zone.r or 50.0),
        )

    priority = int(zone.priority if zone.priority is not None else 0)
    sem = cfg.get("semantics", {})
    sem_mode = sem.get("mode", "BUTTON")

    # Stage 5: Semantic Mapping Handlers
    pipeline = Pipeline(
        region=region,
        priority=priority,
        key=zone.scancode,
        config=cfg,
        is_toggle=(sem_mode == "TOGGLE_KEY"),
        is_mode_switch=(sem_mode == "TOGGLE_MODE"),
        on_mode_toggle=toggle_mode_callback,
    )

    return pipeline
