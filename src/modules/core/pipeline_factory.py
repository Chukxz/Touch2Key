from __future__ import annotations

import math
import sys
from typing import Any, TYPE_CHECKING

from modules.core.pipeline import (
    AlwaysRegion,
    AnchoredOrigin,
    ButtonSemantic,
    CircularRegion,
    DeltaTransform,
    DirectionalSemantic,
    DynamicOrigin,
    FixedOrigin,
    IdentityTransform,
    JoystickTransform,
    LeashConstraint,
    NoConstraint,
    Pipeline,
    PointerSemantic,
    RadialConstraint,
    RectangularRegion,
    Region,
    ToggleSemantic,
    Unit,
    Vector,
)
from modules.utils import (
    ALLOWED_PIPELINE_FIELDS,
    BASELINE_DPI,
    BOTTOM_BEZEL_ID,
    InvalidFieldError,
    MOUSE_SCANCODES,
    Point,
    TOP_BEZEL_ID,
    dp_to_px,
)

if TYPE_CHECKING:
    from modules.database import LayoutZone


# ---------------------------------------------------------------------------
# Factory Constructors
# ---------------------------------------------------------------------------


def Button(
    button: int,
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
    dead_zone: float,
    up: int,
    down: int,
    left: int,
    right: int,
    inner_radius: float = 80.0,
    outer_radius: float = 120.0,
    sprint: int | None = None,
    hysteresis_deg: float = 5.0,
    priority: int = 0,
    creation_id: int = 0,
) -> Pipeline[frozenset[int]]:
    return Pipeline(
        region=CircularRegion(center=center, radius=inner_radius),
        origin=FixedOrigin(position=center),
        constraint=RadialConstraint(radius=outer_radius),
        transformation=JoystickTransform(
            dead_zone=dead_zone,
            radius=inner_radius,
            hysteresis_rad=math.radians(hysteresis_deg),
            up=up,
            down=down,
            left=left,
            right=right,
            sprint=sprint,
        ),
        semantics=[DirectionalSemantic()],
        priority=priority,
        type_precedence=1,
        creation_id=creation_id,
    )


def FloatingJoystick(
    region: Region,
    dead_zone: float,
    up: int,
    down: int,
    left: int,
    right: int,
    inner_radius: float = 80.0,
    outer_radius: float = 120.0,
    sprint: int | None = None,
    hysteresis_deg: float = 5.0,
    priority: int = 0,
    creation_id: int = 0,
) -> Pipeline[frozenset[int]]:
    effective_leash = (
        outer_radius
        if outer_radius > 0.0
        else (
            inner_radius if inner_radius > 0.0 else float(dp_to_px(60.0, BASELINE_DPI))
        )
    )
    return Pipeline(
        region=region,
        origin=DynamicOrigin(),
        constraint=LeashConstraint(leash_radius=effective_leash),
        transformation=JoystickTransform(
            dead_zone=dead_zone,
            radius=inner_radius,
            hysteresis_rad=math.radians(hysteresis_deg),
            up=up,
            down=down,
            left=left,
            right=right,
            sprint=sprint,
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
    up: int,
    down: int,
    left: int,
    right: int,
    inner_radius: float = 80.0,
    outer_radius: float = 120.0,
    sprint: int | None = None,
    hysteresis_deg: float = 5.0,
    priority: int = 0,
    creation_id: int = 0,
) -> Pipeline[frozenset[int]]:
    effective_leash = (
        outer_radius
        if outer_radius > 0.0
        else (
            inner_radius if inner_radius > 0.0 else float(dp_to_px(60.0, BASELINE_DPI))
        )
    )
    return Pipeline(
        region=region,
        origin=AnchoredOrigin(default_anchor=default_anchor, snap_radius=inner_radius),
        constraint=LeashConstraint(leash_radius=effective_leash),
        transformation=JoystickTransform(
            dead_zone=dead_zone,
            radius=inner_radius,
            hysteresis_rad=math.radians(hysteresis_deg),
            up=up,
            down=down,
            left=left,
            right=right,
            sprint=sprint,
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
    output: int,
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


# ---------------------------------------------------------------------------
# Database Metadata Pipeline Builder
# ---------------------------------------------------------------------------


def create_pipeline_from_zone(
    zone: LayoutZone,
    screen_width: float,
    screen_height: float,
    center: Point | None = None,
    inner_radius: float = 80.0,
    outer_radius: float = 120.0,
    sprint: int | None = None,
    **fields: Any,
) -> Pipeline[Any] | None:
    """Builds a typed 5-stage Pipeline instance from database zone metadata."""
    unknown = set(fields) - ALLOWED_PIPELINE_FIELDS
    if unknown:
        raise InvalidFieldError(f"Unknown layout_zones field(s): {sorted(unknown)}")

    zone.set_parsed_config_from_json()

    # --- Stage 1: Region Selection & Spatial Geometry Inference ---
    reg_idx, _, _, priority = zone.CONFIG_HELPER.get_region_config()
    detected_center = Point(0.0, 0.0)
    detected_radius = 50.0

    if reg_idx == 0:  # ALWAYS
        region: Region = AlwaysRegion()
        detected_center = Point(screen_width / 2.0, screen_height / 2.0)
        detected_radius = min(screen_width, screen_height) / 2.0

    elif reg_idx == 1:  # CIRCULAR
        cx = float(zone.cx if zone.cx is not None else 0.0)
        cy = float(zone.cy if zone.cy is not None else 0.0)
        r = float(zone.r if zone.r is not None else 50.0)
        detected_center = Point(cx, cy)
        detected_radius = r
        region = CircularRegion(center=detected_center, radius=detected_radius)

    elif reg_idx == 2:  # RECTANGULAR
        x1 = float(zone.x1 if zone.x1 is not None else 0.0)
        y1 = float(zone.y1 if zone.y1 is not None else 0.0)
        x2 = float(zone.x2 if zone.x2 is not None else screen_width)
        y2 = float(zone.y2 if zone.y2 is not None else screen_height)
        detected_center = Point((x1 + x2) / 2.0, (y1 + y2) / 2.0)
        detected_radius = min(abs(x2 - x1), abs(y2 - y1)) / 2.0
        region = RectangularRegion(top_left=Point(x1, y1), bottom_right=Point(x2, y2))

    else:
        return None

    resolved_center = center if center is not None else detected_center
    resolved_radius = outer_radius if outer_radius is not None else detected_radius

    # --- Stage 2: Origin Selection ---
    orig_idx, _ = zone.CONFIG_HELPER.get_origin_config()

    if orig_idx == 0:  # FIXED
        origin = FixedOrigin(position=resolved_center)
    elif orig_idx == 1:  # DYNAMIC
        origin = DynamicOrigin()
    elif orig_idx == 2:  # ANCHORED
        origin = AnchoredOrigin(
            default_anchor=resolved_center, snap_radius=inner_radius
        )
    else:
        return None

    # --- Stage 3: Constraint Selection ---
    const_idx, _ = zone.CONFIG_HELPER.get_constraint_config()

    if const_idx == 0:  # NONE
        constraint = NoConstraint()
    elif const_idx == 1:  # RADIAL
        constraint = RadialConstraint(radius=resolved_radius)
    elif const_idx == 2:  # LEASH
        constraint = LeashConstraint(leash_radius=resolved_radius)
    else:
        return None

    # --- Stage 4: Transformation Selection ---
    trans_idx, _, sens_x, sens_y, dz, hys_deg = (
        zone.CONFIG_HELPER.get_transform_config()
    )

    cfg = zone.CONFIG_HELPER.pipeline_config
    W = 0x11
    A = 0x1E
    S = 0x1F
    D = 0x20

    if trans_idx == 0:  # IDENTITY
        transformation = IdentityTransform()
    elif trans_idx == 1:  # DELTA
        transformation = DeltaTransform(sensitivity_x=sens_x, sensitivity_y=sens_y)
    elif trans_idx == 2:  # JOYSTICK
        transformation = JoystickTransform(
            dead_zone=dz,
            radius=inner_radius,
            hysteresis_rad=math.radians(hys_deg),
            up=cfg.get("up", W),
            left=cfg.get("left", A),
            down=cfg.get("down", S),
            right=cfg.get("right", D),
            sprint=sprint,
        )
    else:
        return None

    # --- Stage 5: Semantics Selection ---
    sem_idx, _, pointer = zone.CONFIG_HELPER.get_semantic_config()

    semantics: list[Any] = []
    allow_multi_claim = False
    type_precedence = 2
    is_system = False
    scancode = zone.scancode

    if sem_idx == 0:  # BUTTON
        is_mouse_button = scancode in MOUSE_SCANCODES

        semantics.append(
            ButtonSemantic(output=zone.scancode, mouse_button=is_mouse_button)
        )
        if pointer:
            semantics.append(PointerSemantic(pointer=True))
        allow_multi_claim = True

    elif sem_idx == 1:  # DIRECTIONAL
        semantics.append(DirectionalSemantic())
        type_precedence = 1

    elif sem_idx == 2:  # POINTER
        semantics.append(PointerSemantic(pointer=True))
        type_precedence = 0

    elif sem_idx == 3:  # SYSTEM TOGGLE
        if scancode == TOP_BEZEL_ID:
            semantics.append(ToggleSemantic(output=scancode))
            is_system = True
        elif scancode == BOTTOM_BEZEL_ID:
            semantics.append(ToggleSemantic(output=scancode))
            is_system = True
        else:
            return None

    else:
        return None

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
        is_system=is_system,
    )
