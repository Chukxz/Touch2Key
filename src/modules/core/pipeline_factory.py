from __future__ import annotations

import sys
import math
from typing import Any, TYPE_CHECKING

from modules.core.pipeline import (
    Unit,
    Region,
    AlwaysRegion,
    CircularRegion,
    RectangularRegion,
    FixedOrigin,
    DynamicOrigin,
    AnchoredOrigin,
    NoConstraint,
    RadialConstraint,
    LeashConstraint,
    IdentityTransform,
    DeltaTransform,
    JoystickTransform,
    ButtonSemantic,
    ToggleSemantic,
    PointerSemantic,
    DirectionalSemantic,
    Pipeline,
)

from modules.utils import (
    ALLOWED_PIPELINE_FIELDS,
    M_LEFT,
    M_MIDDLE,
    M_RIGHT,
    BASELINE_DPI,
    TOP_BEZEL_ID,
    BOTTOM_BEZEL_ID,
    TOGGLE_MODE,
    TOGGLE_VKB,
    dp_to_px,
    InvalidFieldError,
    Point,
    Vector,
)

if TYPE_CHECKING:
    from modules.database import LayoutZone


# ---------------------------------------------------------------------------
# Factory Constructors
# ---------------------------------------------------------------------------


def Button(
    button: str,
    region: Region | None,
    pointer: bool = False,
    sensitivity_x: float = 1.0,
    sensitivity_y: float = 1.0,
    mouse_button: bool = False,
    priority: int = 0,
    creation_id: int = 0,
) -> Pipeline[Vector]:
    return Pipeline(
        region=region or AlwaysRegion(),
        origin=DynamicOrigin(),
        constraint=NoConstraint(),
        transformation=DeltaTransform(sensitivity_x, sensitivity_y),
        semantics=[
            ButtonSemantic(output=button, mouse_button=mouse_button),
            PointerSemantic(pointer=pointer),
        ],
        priority=priority,
        type_precedence=2,
        creation_id=creation_id,
        allow_multi_claim=True,
    )


def FixedJoystick(
    center: Point,
    radius: float,
    dead_zone: float,
    walk_radius: float,
    sprint_distance: float = 0.0,
    hysteresis_deg: float = 5.0,
    up: str = "w",
    down: str = "s",
    left: str = "a",
    right: str = "d",
    sprint_key: str = "shift",
    priority: int = 0,
    creation_id: int = 0,
) -> Pipeline[frozenset[str]]:
    return Pipeline(
        region=CircularRegion(center=center, radius=radius),
        origin=FixedOrigin(position=center),
        constraint=RadialConstraint(radius=radius),
        transformation=JoystickTransform(
            dead_zone=dead_zone,
            walk_radius=walk_radius,
            sprint_distance=sprint_distance,
            hysteresis_rad=math.radians(hysteresis_deg),
            up=up,
            down=down,
            left=left,
            right=right,
            sprint_key=sprint_key,
        ),
        semantics=[DirectionalSemantic()],
        priority=priority,
        type_precedence=1,
        creation_id=creation_id,
    )


def FloatingJoystick(
    region: Region,
    dead_zone: float,
    walk_radius: float,
    sprint_distance: float = 0.0,
    radius: float = 0.0,
    hysteresis_deg: float = 5.0,
    up: str = "w",
    down: str = "s",
    left: str = "a",
    right: str = "d",
    sprint_key: str = "shift",
    priority: int = 0,
    creation_id: int = 0,
) -> Pipeline[frozenset[str]]:
    constraint = LeashConstraint(
        radius
        if radius > 0
        else (
            sprint_distance
            if sprint_distance > 0
            else (float(dp_to_px(60.0, BASELINE_DPI)))  # 60 DP stick radius
        )
    )
    return Pipeline(
        region=region,
        origin=DynamicOrigin(),
        constraint=constraint,
        transformation=JoystickTransform(
            dead_zone=dead_zone,
            walk_radius=walk_radius,
            sprint_distance=sprint_distance,
            hysteresis_rad=math.radians(hysteresis_deg),
            up=up,
            down=down,
            left=left,
            right=right,
            sprint_key=sprint_key,
        ),
        semantics=[DirectionalSemantic()],
        priority=priority,
        type_precedence=1,
        creation_id=creation_id,
    )


def AnchoredJoystick(
    default_anchor: Point,
    region: Region,
    dead_zone: float,
    walk_radius: float,
    sprint_distance: float = 0.0,
    radius: float = 0.0,
    snap_radius: float = 80.0,
    hysteresis_deg: float = 5.0,
    up: str = "w",
    down: str = "s",
    left: str = "a",
    right: str = "d",
    sprint_key: str = "shift",
    priority: int = 0,
    creation_id: int = 0,
) -> Pipeline[frozenset[str]]:
    constraint = LeashConstraint(
        radius
        if radius > 0
        else (
            sprint_distance
            if sprint_distance > 0
            else (float(dp_to_px(60.0, BASELINE_DPI)))  # 60 DP stick radius
        )
    )
    return Pipeline(
        region=region,
        origin=AnchoredOrigin(default_anchor=default_anchor, snap_radius=snap_radius),
        constraint=constraint,
        transformation=JoystickTransform(
            dead_zone=dead_zone,
            walk_radius=walk_radius,
            sprint_distance=sprint_distance,
            hysteresis_rad=math.radians(hysteresis_deg),
            up=up,
            down=down,
            left=left,
            right=right,
            sprint_key=sprint_key,
        ),
        semantics=[DirectionalSemantic()],
        priority=priority,
        type_precedence=1,
        creation_id=creation_id,
    )


def MousePointer(
    region: Region | None,
    sensitivity_x: float = 1.0,
    sensitivity_y: float = 1.0,
    priority: int = -100,
    creation_id: int = sys.maxsize,
) -> Pipeline[Vector]:
    return Pipeline(
        region=region or AlwaysRegion(),
        origin=DynamicOrigin(),
        constraint=NoConstraint(),
        transformation=DeltaTransform(sensitivity_x, sensitivity_y),
        semantics=[PointerSemantic()],
        priority=priority,
        type_precedence=0,
        creation_id=creation_id,
    )


def SystemToggle(
    output: str,
    region: Region,
    priority: int = 100,
    creation_id: int = 0,
) -> Pipeline[Unit]:
    """Factory for standardizing Bezel/System boundary zones defined in the layout."""
    return Pipeline(
        region=region,
        origin=FixedOrigin(Point(0.0, 0.0)),
        constraint=NoConstraint(),
        transformation=IdentityTransform(),
        semantics=[ToggleSemantic(output=output)],
        priority=priority,
        type_precedence=2,
        creation_id=creation_id,
        is_system=True,
    )


def create_pipeline_from_zone(
    zone: LayoutZone,
    screen_width: float,
    screen_height: float,
    center=Point(0.0, 0.0),
    snap_radius = 80.0,
    radius = 150.0,
    walk_radius = 80.0,
    sprint_distance = 120.0,
    toggle_mode_callback: Any | None = None,
    **fields: Any,
) -> Pipeline[Any] | None:
    """Builds a typed 5-stage Pipeline instance from database zone metadata."""
    unknown = set(fields) - ALLOWED_PIPELINE_FIELDS
    if unknown:
        raise InvalidFieldError(f"Unknown layout_zones field(s): {sorted(unknown)}")
    
    zone.set_parsed_config_from_json()
    
    # Stage 1: Region Selection
    reg_idx, _, _, priority = zone.CONFIG_HELPER.get_region_config()

    if reg_idx == 0: # ALWAYS
        region = AlwaysRegion()
        
    elif reg_idx == 1:  # CIRCLULAR
        cx = float(zone.cx if zone.cx is not None else 0.0)
        cy = float(zone.cy if zone.cy is not None else 0.0)
        r = float(zone.r if zone.r is not None else 50.0)
        region = CircularRegion(center=Point(cx, cy), radius=r)
        
    elif reg_idx == 2: # RECTANGULAR
        x1 = float(zone.x1 if zone.x1 is not None else 0.0)
        y1 = float(zone.y1 if zone.y1 is not None else 0.0)
        x2 = float(zone.x2 if zone.x2 is not None else screen_width)
        y2 = float(zone.y2 if zone.y2 is not None else screen_height)
        region = RectangularRegion(top_left=Point(x1, y1), bottom_right=Point(x2, y2))
    
    else:
        return

    # Stage 2: Origin Selection
    orig_idx, _ = zone.CONFIG_HELPER.get_origin_config()
    
    if orig_idx == 0: # FIXED
        origin = FixedOrigin(position=center)
    elif orig_idx == 1: # DYNAMIC
        origin = DynamicOrigin()
    elif orig_idx == 2: # ANCHORED
        origin = AnchoredOrigin(default_anchor=center, snap_radius=snap_radius)
    else:
        return
    
    # Stage 3: Constraint Selection
    const_idx, _ = zone.CONFIG_HELPER.get_constraint_config()
    
    if const_idx == 0: # NONE
        constraint = NoConstraint()
    elif const_idx == 1: # RADIAL
        constraint = RadialConstraint(radius=radius)
    elif const_idx == 2: #LEASH
        constraint = LeashConstraint(leash_radius=radius)
    else:
        return

    # Stage 4: Transformation Selection
    trans_idx, _, sens_x, sens_y, dz, hys = zone.CONFIG_HELPER.get_transform_config()

    if trans_idx == 0: # Identity
        transformation = IdentityTransform()
    elif trans_idx == 1: # Delta
        transformation = DeltaTransform(sensitivity_x=sens_x, sensitivity_y=sens_y)
    elif trans_idx == 2: # Joystick
        transformation = JoystickTransform(
            dead_zone=dz,
            walk_radius=walk_radius,
            sprint_distance=sprint_distance,
            hysteresis_rad=hys,
        )
    else:
        return

    # Stage 5: Semantics Selection
    sem_idx, _, pointer = zone.CONFIG_HELPER.get_semantic_config()

    semantics: list[Any] = []
    allow_multi_claim = False
    type_precedence = 2
    is_system = False

    if sem_idx == 0:  # BUTTON
        is_mouse_button = int(zone.scancode) in (M_LEFT, M_RIGHT, M_MIDDLE)
        semantics.append(
            ButtonSemantic(output=zone.scancode, mouse_button=is_mouse_button)
        )
        semantics.append(PointerSemantic(pointer))
        allow_multi_claim = True
        
    elif sem_idx == 1: # Directional
        semantics.append(DirectionalSemantic())
        type_precedence = 1
        
    elif sem_idx == 2: # Pointer
        semantics.append(PointerSemantic())
        type_precedence = 0        
        
    elif sem_idx == 3: # Toggle 
        if zone.scancode == str(TOP_BEZEL_ID):
            semantics.append(ToggleSemantic(output=TOGGLE_MODE))
            is_system = True
            
        elif zone.scancode == str(BOTTOM_BEZEL_ID):
            semantics.append(ToggleSemantic(output=TOGGLE_VKB))
            is_system = True
        
        else:
            return
    
    else:
        return
    
    return Pipeline[Any](
        region=region,
        origin=origin,
        constraint=constraint,
        transformation=transformation,
        semantics=semantics,
        priority=priority,
        type_precedence=type_precedence,
        creation_id=zone.id,
        allow_multi_claim=allow_multi_claim,
        is_system=is_system
    )