from __future__ import annotations
from typing import TYPE_CHECKING

from modules.core.pipeline import PipelineConfig

from modules.utils import (
    BEZEL,
    BEZEL_DP_THICKNESS,
    TOP_BEZEL_ID,
    BOTTOM_BEZEL_ID,
    TOP_BEZEL_NAME,
    BOTTOM_BEZEL_NAME,
    dp_to_px,
    calculate_rect,
)

if TYPE_CHECKING:
    from modules.database.repositories import (
        Layout,
        LayoutZone,
        LayoutsRepository,
        LayoutZonesRepository,
    )


def bezels_exist_ids(zones: list[LayoutZone]) -> tuple[int, int]:
    top_id = -1
    bottom_id = -1

    for z in zones:
        if z.zone_type != BEZEL:
            continue

        if top_id < 0 and str(z.scancode) == str(TOP_BEZEL_ID):
            top_id = z.id

        if bottom_id < 0 and str(z.scancode) == str(BOTTOM_BEZEL_ID):
            bottom_id = z.id

        if top_id >= 0 and bottom_id >= 0:
            break

    return top_id, bottom_id


def get_bezel_thicknesses(zone: LayoutZone, layout: Layout):
    zone.set_parsed_config_from_json()
    _, _, bezel_dp_thickness, _ = zone.CONFIG_HELPER.get_region_config()
    return bezel_dp_thickness, float(dp_to_px(bezel_dp_thickness, layout.dpi))


def ensure_top_bezel(
    layout: Layout,
    zones_repo: LayoutZonesRepository,
    dp_thickness: float | None = None,
):
    if dp_thickness is None:
        dp_thickness = float(BEZEL_DP_THICKNESS)

    w = layout.width
    h = layout.height
    _thickness = float(dp_to_px(dp_thickness, layout.dpi))
    cx, cy, x1, y1, x2, y2 = calculate_rect(0.0, h - _thickness, w, _thickness)

    Pipeline_Config = PipelineConfig()
    Pipeline_Config.set_region_config(2, dp_thickness, 100)
    Pipeline_Config.set_origin_config(0)
    Pipeline_Config.set_constraint_config(0)
    Pipeline_Config.set_transform_config(0)
    Pipeline_Config.set_semantic_config(3)

    return zones_repo.create(
        layout_id=layout.id,
        scancode=TOP_BEZEL_ID,
        name=TOP_BEZEL_NAME,
        zone_type=BEZEL,
        cx=cx,
        cy=cy,
        r=None,
        x1=x1,
        y1=y1,
        x2=x2,
        y2=y2,
        pipeline_json=Pipeline_Config.get_pipeline_json_from_config(),
    ).id


def ensure_bottom_bezel(
    layout: Layout,
    zones_repo: LayoutZonesRepository,
    dp_thickness: float | None = None,
):
    if dp_thickness is None:
        dp_thickness = float(BEZEL_DP_THICKNESS)

    w = layout.width
    _thickness = float(dp_to_px(dp_thickness, layout.dpi))
    cx, cy, x1, y1, x2, y2 = calculate_rect(0.0, 0.0, w, _thickness)

    Pipeline_Config = PipelineConfig()
    Pipeline_Config.set_region_config(2, dp_thickness, 100)
    Pipeline_Config.set_origin_config(0)
    Pipeline_Config.set_constraint_config(0)
    Pipeline_Config.set_transform_config(0)
    Pipeline_Config.set_semantic_config(3)

    return zones_repo.create(
        layout_id=layout.id,
        scancode=BOTTOM_BEZEL_ID,
        name=BOTTOM_BEZEL_NAME,
        zone_type=BEZEL,
        cx=cx,
        cy=cy,
        r=None,
        x1=x1,
        y1=y1,
        x2=x2,
        y2=y2,
        pipeline_json=Pipeline_Config.get_pipeline_json_from_config(),
    ).id


def ensure_system_bezels(
    layout_id: int, layouts_repo: LayoutsRepository, zones_repo: LayoutZonesRepository
):
    """Verifies a layout has both system bezels (Top/Mode, Bottom/VKB) and creates them if missing."""
    layout = layouts_repo.get(layout_id)
    if not layout:
        return -1, -1

    zones = zones_repo.list_for_layout(layout_id)
    top_id, bottom_id = bezels_exist_ids(zones)

    if top_id < 0:
        top_id = ensure_top_bezel(layout, zones_repo)
        print("Auto-healed missing Top Bezel for layout ID %d", layout.id)

    if bottom_id < 0:
        bottom_id = ensure_bottom_bezel(layout, zones_repo)
        print("Auto-healed missing Bottom Bezel for layout ID %d", layout.id)

    return top_id, bottom_id
