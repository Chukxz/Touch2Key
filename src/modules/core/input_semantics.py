from __future__ import annotations

import math
import sys
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Generic, Protocol, TypeVar

from modules.utils import Point, Vector, TouchEvent, TouchPhase


class OutputSink(Protocol):
    def key_down(self, key: str) -> None: ...
    def key_up(self, key: str) -> None: ...
    def mouse_down(self, button: str) -> None: ...
    def mouse_up(self, button: str) -> None: ...
    def mouse_move(self, dx: float, dy: float) -> None: ...


class Region(ABC):
    @abstractmethod
    def activates(self, event: TouchEvent) -> bool: ...

    @property
    @abstractmethod
    def area(self) -> float: ...


class AlwaysRegion(Region):
    def activates(self, event: TouchEvent) -> bool:
        return True

    @property
    def area(self) -> float:
        return float("inf")


@dataclass(slots=True)
class CircularRegion(Region):
    center: Point
    radius: float

    def activates(self, event: TouchEvent) -> bool:
        return (event.position - self.center).magnitude_squared <= (self.radius * self.radius)

    @property
    def area(self) -> float:
        return math.pi * (self.radius ** 2)


@dataclass(slots=True)
class RectangularRegion(Region):
    top_left: Point
    bottom_right: Point

    def activates(self, event: TouchEvent) -> bool:
        return (
            self.top_left.x <= event.position.x <= self.bottom_right.x
            and self.top_left.y <= event.position.y <= self.bottom_right.y
        )

    @property
    def area(self) -> float:
        w = max(0.0, self.bottom_right.x - self.top_left.x)
        h = max(0.0, self.bottom_right.y - self.top_left.y)
        return w * h


# ---------------------------------------------------------------------------
# Constraints, Origins, Transforms, Semantics (Standard Definition)
# ---------------------------------------------------------------------------

class Constraint(ABC):
    @abstractmethod
    def apply(self, origin: Point, position: Point) -> Point: ...

@dataclass(slots=True)
class RadialConstraint(Constraint):
    radius: float
    def apply(self, origin: Point, position: Point) -> Point:
        delta = position - origin
        dist_sq = delta.magnitude_squared
        if dist_sq <= self.radius * self.radius:
            return position
        scale = self.radius / math.sqrt(dist_sq)
        return Point(origin.x + delta.x * scale, origin.y + delta.y * scale)

class NoConstraint(Constraint):
    def apply(self, origin: Point, position: Point) -> Point:
        return position

@dataclass(slots=True)
class LeashConstraint(Constraint):
    leash_radius: float
    def apply(self, origin: Point, position: Point) -> Point:
        return position

class Origin(ABC):
    @abstractmethod
    def begin(self, position: Point) -> None: ...
    @abstractmethod
    def get(self) -> Point: ...
    @abstractmethod
    def update(self, position: Point, constraint: Constraint) -> None: ...
    @abstractmethod
    def end(self) -> None: ...

@dataclass(slots=True)
class FixedOrigin(Origin):
    position: Point
    def begin(self, position: Point) -> None: pass
    def get(self) -> Point: return self.position
    def update(self, position: Point, constraint: Constraint) -> None: pass
    def end(self) -> None: pass

@dataclass(slots=True)
class DynamicOrigin(Origin):
    _position: Point | None = field(init=False, default=None)
    def begin(self, position: Point) -> None: self._position = position
    def get(self) -> Point:
        if self._position is None:
            raise RuntimeError("DynamicOrigin not initialized.")
        return self._position
    def update(self, position: Point, constraint: Constraint) -> None:
        if isinstance(constraint, LeashConstraint) and self._position is not None:
            delta = position - self._position
            dist = delta.magnitude
            if dist > constraint.leash_radius and dist > 0:
                scale = constraint.leash_radius / dist
                self._position = Point(position.x - (delta.x * scale), position.y - (delta.y * scale))
    def end(self) -> None: self._position = None

@dataclass(slots=True, frozen=True)
class PipelineContext:
    event: TouchEvent
    origin: Point
    constrained_position: Point
    delta: Vector
    frame_delta: Vector

class Unit: __slots__ = ()
UNIT = Unit()
T = TypeVar("T")

class Transformation(ABC, Generic[T]):
    @abstractmethod
    def apply(self, context: PipelineContext) -> T: ...
    def reset(self) -> None: pass

class IdentityTransform(Transformation[Unit]):
    def apply(self, context: PipelineContext) -> Unit: return UNIT

@dataclass(slots=True)
class DeltaTransform(Transformation[Vector]):
    sensitivity_x: float = 1.0
    sensitivity_y: float = 1.0
    def apply(self, context: PipelineContext) -> Vector:
        return Vector(context.frame_delta.x * self.sensitivity_x, context.frame_delta.y * self.sensitivity_y)

@dataclass(slots=True)
class JoystickSectorTransform(Transformation[frozenset[str]]):
    dead_zone: float
    walk_radius: float
    sprint_radius: float
    hysteresis_rad: float = math.radians(5.0)
    up: str = "w"
    down: str = "s"
    left: str = "a"
    right: str = "d"
    sprint_key: str = "shift"
    _last_sector: int | None = field(init=False, default=None)
    _PI_8: float = field(init=False, default=math.pi / 8.0)
    _INV_PI_4: float = field(init=False, default=1.0 / (math.pi / 4.0))

    def reset(self) -> None: self._last_sector = None
    def apply(self, context: PipelineContext) -> frozenset[str]:
        dist_sq = context.delta.magnitude_squared
        if dist_sq <= self.dead_zone * self.dead_zone:
            self._last_sector = None
            return frozenset()
        angle_rad = math.atan2(context.delta.y, context.delta.x)
        if angle_rad < 0: angle_rad += 2 * math.pi
        new_sector = int((angle_rad + self._PI_8) * self._INV_PI_4) % 8
        if self._last_sector is not None:
            current_center = self._last_sector * (math.pi / 4.0)
            angle_diff = (angle_rad - current_center + math.pi) % (2 * math.pi) - math.pi
            if abs(angle_diff) < (self._PI_8 + self.hysteresis_rad):
                new_sector = self._last_sector
        self._last_sector = new_sector
        sector_map = {
            0: {self.right}, 1: {self.down, self.right}, 2: {self.down}, 3: {self.down, self.left},
            4: {self.left}, 5: {self.up, self.left}, 6: {self.up}, 7: {self.up, self.right}
        }
        active_keys = set(sector_map.get(new_sector, set()))
        if self.sprint_radius > 0 and dist_sq > (self.sprint_radius * self.sprint_radius):
            active_keys.add(self.sprint_key)
        return frozenset(active_keys)

class Semantic(ABC, Generic[T]):
    @abstractmethod
    def process(self, context: PipelineContext, value: T, output: OutputSink) -> None: ...
    def reset(self, output: OutputSink) -> None: pass

@dataclass(slots=True)
class ButtonSemantic(Semantic[T], Generic[T]):
    output: str
    mouse_button: bool = False
    def process(self, context: PipelineContext, value: T, output: OutputSink) -> None:
        if context.event.phase is TouchPhase.DOWN:
            (output.mouse_down if self.mouse_button else output.key_down)(self.output)
        elif context.event.phase is TouchPhase.UP:
            (output.mouse_up if self.mouse_button else output.key_up)(self.output)
    def reset(self, output: OutputSink) -> None:
        (output.mouse_up if self.mouse_button else output.key_up)(self.output)

@dataclass(slots=True)
class DirectionalKeySemantic(Semantic[frozenset[str]]):
    _active: frozenset[str] = field(init=False, default_factory=frozenset)
    def process(self, context: PipelineContext, value: frozenset[str], output: OutputSink) -> None:
        if context.event.phase is TouchPhase.UP:
            self.reset(output)
            return
        for key in self._active - value: output.key_up(key)
        for key in value - self._active: output.key_down(key)
        self._active = value
    def reset(self, output: OutputSink) -> None:
        for key in self._active: output.key_up(key)
        self._active = frozenset()

class PointerMoveSemantic(Semantic[Vector]):
    def process(self, context: PipelineContext, value: Vector, output: OutputSink) -> None:
        if context.event.phase is TouchPhase.MOVE and (value.x or value.y):
            output.mouse_move(value.x, value.y)


# ---------------------------------------------------------------------------
# Pipeline with Touch Ownership & Priority Contract
# ---------------------------------------------------------------------------

@dataclass
class Pipeline(Generic[T]):
    region: Region
    origin: Origin
    constraint: Constraint
    transformation: Transformation[T]
    semantics: list[Semantic[T]]
    priority: int = 0
    type_precedence: int = 0   # 2: Button, 1: Joystick, 0: Mouse
    creation_id: int = 0
    allow_multi_claim: bool = False  # True ONLY for Button types

    _owned_contact: int | None = field(init=False, default=None)
    _prev_position: Point | None = field(init=False, default=None)

    def claims(self, event: TouchEvent) -> bool:
        return self._owned_contact is None and self.region.activates(event)

    def owns(self, contact_id: int) -> bool:
        return self._owned_contact == contact_id

    def reset(self, output: OutputSink) -> None:
        for semantic in self.semantics:
            semantic.reset(output)
        self.transformation.reset()
        self.origin.end()
        self._owned_contact = None
        self._prev_position = None

    def process(self, event: TouchEvent, output: OutputSink) -> bool:
        """Processes the touch event. Returns True if this pipeline owns/claims the touch."""
        if event.phase is TouchPhase.DOWN:
            if self._owned_contact is not None:
                return False
            if not self.region.activates(event):
                return False
            self._owned_contact = event.contact_id
            self.origin.begin(event.position)

        if event.contact_id != self._owned_contact:
            return False

        self.origin.update(event.position, self.constraint)
        origin_point = self.origin.get()
        constrained = self.constraint.apply(origin_point, event.position)

        if event.phase is TouchPhase.DOWN or self._prev_position is None:
            self._prev_position = constrained

        context = PipelineContext(
            event=event,
            origin=origin_point,
            constrained_position=constrained,
            delta=constrained - origin_point,
            frame_delta=constrained - self._prev_position,
        )

        value = self.transformation.apply(context)
        for semantic in self.semantics:
            semantic.process(context, value, output)

        self._prev_position = constrained

        if event.phase is TouchPhase.UP:
            self.origin.end()
            self.transformation.reset()
            self._owned_contact = None
            self._prev_position = None

        return True


# ---------------------------------------------------------------------------
# Factory Constructors with Priority Contracts
# ---------------------------------------------------------------------------

def Button(
    output: str,
    region: Region | None = None,
    mouse_button: bool = False,
    priority: int = 0,
    creation_id: int = 0,
) -> Pipeline[Unit]:
    return Pipeline(
        region=region or AlwaysRegion(),
        origin=FixedOrigin(Point(0.0, 0.0)),
        constraint=NoConstraint(),
        transformation=IdentityTransform(),
        semantics=[ButtonSemantic(output=output, mouse_button=mouse_button)],
        priority=priority,
        type_precedence=2,
        creation_id=creation_id,
        allow_multi_claim=True,
    )


def TrackFire(
    button: str = "mouse_left",
    region: Region | None = None,
    sensitivity_x: float = 1.0,
    sensitivity_y: float = 1.0,
    priority: int = 0,
    creation_id: int = 0,
) -> Pipeline[Vector]:
    return Pipeline(
        region=region or AlwaysRegion(),
        origin=DynamicOrigin(),
        constraint=NoConstraint(),
        transformation=DeltaTransform(sensitivity_x, sensitivity_y),
        semantics=[
            ButtonSemantic(output=button, mouse_button=True),
            PointerMoveSemantic(),
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
    sprint_radius: float = 0.0,
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
        transformation=JoystickSectorTransform(
            dead_zone=dead_zone,
            walk_radius=walk_radius,
            sprint_radius=sprint_radius,
            hysteresis_rad=math.radians(hysteresis_deg),
            up=up,
            down=down,
            left=left,
            right=right,
            sprint_key=sprint_key,
        ),
        semantics=[DirectionalKeySemantic()],
        priority=priority,
        type_precedence=1,
        creation_id=creation_id,
    )


def FloatingJoystick(
    region: Region,
    dead_zone: float,
    walk_radius: float,
    sprint_radius: float = 0.0,
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
    constraint = LeashConstraint(leash_radius=leash_radius) if leash_radius > 0 else NoConstraint()
    return Pipeline(
        region=region,
        origin=DynamicOrigin(),
        constraint=constraint,
        transformation=JoystickSectorTransform(
            dead_zone=dead_zone,
            walk_radius=walk_radius,
            sprint_radius=sprint_radius,
            hysteresis_rad=math.radians(hysteresis_deg),
            up=up,
            down=down,
            left=left,
            right=right,
            sprint_key=sprint_key,
        ),
        semantics=[DirectionalKeySemantic()],
        priority=priority,
        type_precedence=1,
        creation_id=creation_id,
    )


def RelativePointer(
    region: Region | None = None,
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
        semantics=[PointerMoveSemantic()],
        priority=priority,
        type_precedence=0,
        creation_id=creation_id,
    )