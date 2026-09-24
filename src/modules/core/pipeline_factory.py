from __future__ import annotations

import sys
import json
import math
from typing import Any, cast

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
    Transformation,
)

from modules.utils import (
    BASELINE_DPI,
    TOGGLE_MODE,
    TOGGLE_VKB,
    dp_to_px,
    Point,
    Vector,
)


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
    touch_radius: float,
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
        region=CircularRegion(center=center, radius=touch_radius),
        origin=FixedOrigin(position=center),
        constraint=RadialConstraint(radius=touch_radius),
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
    leash_radius: float = 0.0,
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
        leash_radius
        if leash_radius > 0
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
    leash_radius: float = 0.0,
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
        leash_radius
        if leash_radius > 0
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
        allow_multi_claim=False,
    )


def RelativePointer(
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
        allow_multi_claim=False,
        is_system=True,
    )


def create_pipeline_from_zone(
    zone: Any,
    screen_width: float,
    screen_height: float,
    toggle_mode_callback: Any | None = None,
) -> Pipeline[Any] | None:
    """Builds a typed 5-stage Pipeline instance from database zone metadata."""
    cfg_raw = getattr(zone, "pipeline_config", "{}") or "{}"
    try:
        cfg = json.loads(cfg_raw)
    except Exception:
        cfg = {}

    reg_cfg = cfg.get("region", {})
    reg_type = reg_cfg.get("type", zone.zone_type)
    
    # Flag to allow this pipeline to intercept touches even in Menu Mode
    is_system = (reg_type == "BEZEL" or zone.zone_type == "BEZEL")

    # Stage 1: Region Selection
    if reg_type == "ALWAYS":
        region = AlwaysRegion()
    elif reg_type == "RECTANGLE" or reg_type == "BEZEL":
        x1 = float(zone.x1 if zone.x1 is not None else 0.0)
        y1 = float(zone.y1 if zone.y1 is not None else 0.0)
        x2 = float(zone.x2 if zone.x2 is not None else screen_width)
        y2 = float(zone.y2 if zone.y2 is not None else screen_height)
        region = RectangularRegion(top_left=Point(x1, y1), bottom_right=Point(x2, y2))
    else:  # CIRCLE default
        cx = float(zone.cx if zone.cx is not None else 0.0)
        cy = float(zone.cy if zone.cy is not None else 0.0)
        r = float(zone.r if zone.r is not None else 50.0)
        region = CircularRegion(center=Point(cx, cy), radius=r)

    # Stage 2: Origin Selection
    orig_cfg = cfg.get("origin", {})
    orig_type = orig_cfg.get("type", "FIXED")
    if orig_type == "DYNAMIC":
        origin = DynamicOrigin()
    elif orig_type == "ANCHORED":
        anchor = Point(
            float(orig_cfg.get("anchor_x", zone.cx or 0.0)),
            float(orig_cfg.get("anchor_y", zone.cy or 0.0)),
        )
        snap_r = float(orig_cfg.get("snap_radius", 80.0))
        origin = AnchoredOrigin(default_anchor=anchor, snap_radius=snap_r)
    else:
        fixed_pt = Point(float(zone.cx or 0.0), float(zone.cy or 0.0))
        origin = FixedOrigin(position=fixed_pt)

    # Stage 3: Constraint Selection
    const_cfg = cfg.get("constraint", {})
    const_type = const_cfg.get("type", "NONE")
    if const_type == "RADIAL":
        radius = float(const_cfg.get("radius", zone.r or 100.0))
        constraint = RadialConstraint(radius=radius)
    elif const_type == "LEASH":
        leash_r = float(const_cfg.get("leash_radius", 150.0))
        constraint = LeashConstraint(leash_radius=leash_r)
    else:
        constraint = NoConstraint()

    # Stage 4: Transformation Selection
    trans_cfg = cfg.get("transform", {})
    trans_type = trans_cfg.get("type", "IDENTITY")

    transformation: Transformation[Any]
    if trans_type == "DELTA":
        sx = float(trans_cfg.get("sens_x", 1.0))
        sy = float(trans_cfg.get("sens_y", 1.0))
        transformation = DeltaTransform(sensitivity_x=sx, sensitivity_y=sy)
    elif trans_type == "JOYSTICK":
        transformation = JoystickTransform(
            dead_zone=float(trans_cfg.get("joy_dz", 10.0)),
            walk_radius=float(trans_cfg.get("joy_walk", 80.0)),
            sprint_radius=float(trans_cfg.get("joy_sprint", 120.0)),
            hysteresis_rad=math.radians(float(trans_cfg.get("joy_hysteresis", 5.0))),
        )
    else:
        # Cast to Transformation[Any] to prevent invariance conflict with Transformation[Unit]
        transformation = cast(Transformation[Any], IdentityTransform())

    # Stage 5: Semantics Selection
    sem_cfg = cfg.get("semantics", {})
    sem_mode = sem_cfg.get("mode", "BUTTON")
    action = sem_cfg.get("action")
    is_mouse_button = bool(sem_cfg.get("is_mouse_button", False))
    target_key = str(zone.scancode or "space")

    semantics: list[Any] = []
    allow_multi_claim = False
    type_precedence = 2

    if action == "TOGGLE_MODE" or sem_mode == "TOGGLE_MODE":
        semantics.append(ToggleSemantic(output="TOGGLE_MODE"))
    elif action == "TOGGLE_VKB" or sem_mode == "TOGGLE_VKB":
        semantics.append(ToggleSemantic(output="TOGGLE_VKB"))
    elif sem_mode == "WASD":
        semantics.append(DirectionalSemantic())
        type_precedence = 1
    elif sem_mode == "POINTER":
        semantics.append(PointerSemantic())
        type_precedence = 0
    elif sem_mode == "TRACK_FIRE":
        semantics.append(
            ButtonSemantic(output=target_key, mouse_button=is_mouse_button)
        )
        semantics.append(PointerSemantic())
        allow_multi_claim = True
    else:  # BUTTON
        semantics.append(
            ButtonSemantic(output=target_key, mouse_button=is_mouse_button)
        )
        allow_multi_claim = True

    priority = int(zone.priority if zone.priority is not None else 0)

    return Pipeline[Any](
        region=region,
        origin=origin,
        constraint=constraint,
        transformation=transformation,
        semantics=semantics,
        priority=priority,
        type_precedence=type_precedence,
        creation_id=int(zone.id or 0),
        allow_multi_claim=allow_multi_claim,
        is_system=is_system,  # Passes the system flag
    )