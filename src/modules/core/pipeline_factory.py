from __future__ import annotations

import math
import sys
from typing import Any, Callable, TYPE_CHECKING

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
    MIN_PRIORITY,
    MOUSE_SCANCODES,
    clamp,
    dp_to_px,
    InvalidFieldError,
    Point,
)

if TYPE_CHECKING:
    from modules.database import LayoutZone


# ---------------------------------------------------------------------------
# Factory Constructors
# ---------------------------------------------------------------------------


def Button(
    scancode: int,
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
            ButtonSemantic(scancode, mouse_button),
            PointerSemantic(pointer),
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
            radius=outer_radius,
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
            radius=outer_radius,
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
        origin=AnchoredOrigin(default_anchor, snap_radius=inner_radius),
        constraint=LeashConstraint(leash_radius=effective_leash),
        transformation=JoystickTransform(
            dead_zone=dead_zone,
            radius=outer_radius,
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
    priority: int = MIN_PRIORITY,
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


def Bezel(
    scancode: int,
    region: Region,
    priority: int = 100,
    callback: Callable[..., None] | None = None,
    creation_id: int = 0,
) -> Pipeline[Unit]:
    """Factory for standardizing Bezel/System boundary zones defined in the layout."""
    return Pipeline(
        region=region,
        origin=FixedOrigin(Point(0.0, 0.0)),
        constraint=NoConstraint(),
        transformation=IdentityTransform(),
        semantics=[
            (
                ToggleSemantic(callback)
                if callback is not None
                else ButtonSemantic(scancode)
            )
        ],
        priority=priority,
        type_precedence=4,
        creation_id=creation_id,
        is_bezel=True,
    )
