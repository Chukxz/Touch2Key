from __future__ import annotations

import json
import logging
import math
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Generic, TypeVar

from modules.utils import (
    BEZEL_DP_THICKNESS,
    CONSTRAINT_MODES,
    ORIGIN_MODES,
    REGION_MODES,
    SEMANTIC_MODES,
    TOGGLE_MODE,
    TOGGLE_VKB,
    TRANSFORM_MODES,
    Point,
    TouchEvent,
    TouchPhase,
    Vector,
)

logger = logging.getLogger("modules.pipeline")

# Pipeline: Region ⟶ Origin ⟶ Constraint ⟶ Transformation ⟶ Semantic


@dataclass(slots=True)
class OutputSink(ABC):
    @abstractmethod
    def key_down(self, key: str) -> None:
        raise NotImplementedError

    @abstractmethod
    def key_up(self, key: str) -> None:
        raise NotImplementedError

    @abstractmethod
    def mouse_move(self, dx: float, dy: float) -> None:
        raise NotImplementedError

    @abstractmethod
    def flush_mouse_move(self) -> None:
        raise NotImplementedError

    @abstractmethod
    def reset_mouse_accumulators(self) -> None:
        raise NotImplementedError

    @abstractmethod
    def mouse_up(self, button: str) -> None:
        raise NotImplementedError

    @abstractmethod
    def mouse_down(self, button: str) -> None:
        raise NotImplementedError

    @abstractmethod
    def toggle_menu_mode(self) -> None:
        raise NotImplementedError

    @abstractmethod
    def toggle_virtual_keyboard(self) -> None:
        raise NotImplementedError


@dataclass(slots=True)
class Region(ABC):
    @abstractmethod
    def activates(self, event: TouchEvent) -> bool: ...

    @property
    @abstractmethod
    def area(self) -> float: ...


@dataclass(slots=True)
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
        return (event.position - self.center).magnitude_squared <= (
            self.radius * self.radius
        )

    @property
    def area(self) -> float:
        return math.pi * (self.radius**2)


@dataclass(slots=True)
class RectangularRegion(Region):
    top_left: Point
    bottom_right: Point
    _x1: float = field(init=False)
    _y1: float = field(init=False)
    _x2: float = field(init=False)
    _y2: float = field(init=False)

    def __post_init__(self) -> None:
        self._x1 = min(self.top_left.x, self.bottom_right.x)
        self._y1 = min(self.top_left.y, self.bottom_right.y)
        self._x2 = max(self.top_left.x, self.bottom_right.x)
        self._y2 = max(self.top_left.y, self.bottom_right.y)

    def activates(self, event: TouchEvent) -> bool:
        return self._x1 <= event.position.x <= self._x2 and self._y1 <= event.position.y <= self._y2

    @property
    def area(self) -> float:
        return (self._x2 - self._x1) * (self._y2 - self._y1)


# ---------------------------------------------------------------------------
# Constraints, Origins, Transforms, Semantics
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class Constraint(ABC):
    @abstractmethod
    def apply(self, origin: Point, position: Point) -> Point: ...

    def update_origin(self, origin: Point, position: Point) -> Point:
        return origin


@dataclass(slots=True)
class NoConstraint(Constraint):
    def apply(self, origin: Point, position: Point) -> Point:
        return position


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


@dataclass(slots=True)
class LeashConstraint(Constraint):
    leash_radius: float

    def apply(self, origin: Point, position: Point) -> Point:
        return position

    def update_origin(self, origin: Point, position: Point) -> Point:
        delta = position - origin
        dist = delta.magnitude
        if dist > self.leash_radius and dist > 0.0:
            scale = self.leash_radius / dist
            return Point(
                position.x - (delta.x * scale),
                position.y - (delta.y * scale),
            )
        return origin


@dataclass(slots=True)
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

    def begin(self, position: Point) -> None:
        pass

    def get(self) -> Point:
        return self.position

    def update(self, position: Point, constraint: Constraint) -> None:
        pass

    def end(self) -> None:
        pass


@dataclass(slots=True)
class DynamicOrigin(Origin):
    _position: Point | None = field(init=False, default=None)

    def begin(self, position: Point) -> None:
        self._position = position

    def get(self) -> Point:
        if self._position is None:
            return Point(0.0, 0.0)
        return self._position

    def update(self, position: Point, constraint: Constraint) -> None:
        if self._position is not None:
            self._position = constraint.update_origin(self._position, position)

    def end(self) -> None:
        self._position = None


@dataclass(slots=True)
class AnchoredOrigin(Origin):
    default_anchor: Point
    snap_radius: float = 80.0
    _position: Point | None = field(init=False, default=None)

    def begin(self, position: Point) -> None:
        delta = position - self.default_anchor
        if delta.magnitude_squared <= (self.snap_radius * self.snap_radius):
            self._position = self.default_anchor
        else:
            self._position = position

    def get(self) -> Point:
        if self._position is None:
            return self.default_anchor
        return self._position

    def update(self, position: Point, constraint: Constraint) -> None:
        if self._position is not None:
            self._position = constraint.update_origin(self._position, position)

    def end(self) -> None:
        self._position = None


@dataclass(slots=True, frozen=True)
class PipelineContext:
    event: TouchEvent
    origin: Point
    constrained_position: Point
    delta: Vector
    frame_delta: Vector


class Unit:
    __slots__ = ()


UNIT = Unit()
T = TypeVar("T")


@dataclass(slots=True)
class Transformation(ABC, Generic[T]):
    @abstractmethod
    def apply(self, context: PipelineContext) -> T: ...
    def reset(self) -> None:
        pass


@dataclass(slots=True)
class IdentityTransform(Transformation[Unit]):
    def apply(self, context: PipelineContext) -> Unit:
        return UNIT


@dataclass(slots=True)
class DeltaTransform(Transformation[Vector]):
    sensitivity_x: float = 1.0
    sensitivity_y: float = 1.0

    def apply(self, context: PipelineContext) -> Vector:
        return Vector(
            context.frame_delta.x * self.sensitivity_x,
            context.frame_delta.y * self.sensitivity_y,
        )


@dataclass(slots=True)
class JoystickTransform(Transformation[frozenset[str]]):
    dead_zone: float
    walk_radius: float
    sprint_distance: float
    hysteresis_rad: float = math.radians(5.0)
    up: str = "w"
    down: str = "s"
    left: str = "a"
    right: str = "d"
    sprint_key: str = "shift"

    _last_sector: int | None = field(init=False, default=None)
    _PI_8: float = field(init=False, default=math.pi / 8.0)
    _INV_PI_4: float = field(init=False, default=1.0 / (math.pi / 4.0))
    _sector_map: tuple[frozenset[str], ...] = field(init=False)
    _sprint_set: frozenset[str] = field(init=False)

    def __post_init__(self) -> None:
        self._sprint_set = frozenset({self.sprint_key})
        self._sector_map = (
            frozenset({self.right}),
            frozenset({self.down, self.right}),
            frozenset({self.down}),
            frozenset({self.down, self.left}),
            frozenset({self.left}),
            frozenset({self.up, self.left}),
            frozenset({self.up}),
            frozenset({self.up, self.right}),
        )

    def reset(self) -> None:
        self._last_sector = None

    def apply(self, context: PipelineContext) -> frozenset[str]:
        dist_sq = context.delta.magnitude_squared
        if dist_sq <= self.dead_zone * self.dead_zone:
            self._last_sector = None
            return frozenset()

        angle_rad = math.atan2(context.delta.y, context.delta.x)
        if angle_rad < 0.0:
            angle_rad += 2.0 * math.pi

        new_sector = int((angle_rad + self._PI_8) * self._INV_PI_4) % 8

        if self._last_sector is not None:
            current_center = self._last_sector * (math.pi / 4.0)
            angle_diff = (angle_rad - current_center + math.pi) % (2.0 * math.pi) - math.pi
            if abs(angle_diff) < (self._PI_8 + self.hysteresis_rad):
                new_sector = self._last_sector

        self._last_sector = new_sector
        base_keys = self._sector_map[new_sector]

        if self.sprint_distance > 0.0 and dist_sq > (self.sprint_distance * self.sprint_distance):
            return base_keys | self._sprint_set

        return base_keys


@dataclass(slots=True)
class Semantic(ABC, Generic[T]):
    @abstractmethod
    def process(self, context: PipelineContext, value: T, output_sink: OutputSink) -> None: ...
    def reset(self, output_sink: OutputSink) -> None:
        pass


@dataclass(slots=True)
class ButtonSemantic(Semantic[T], Generic[T]):
    output: str
    mouse_button: bool = False

    def process(self, context: PipelineContext, value: T, output_sink: OutputSink) -> None:
        if context.event.phase is TouchPhase.DOWN:
            (output_sink.mouse_down if self.mouse_button else output_sink.key_down)(self.output)
        elif context.event.phase is TouchPhase.UP:
            (output_sink.mouse_up if self.mouse_button else output_sink.key_up)(self.output)

    def reset(self, output_sink: OutputSink) -> None:
        (output_sink.mouse_up if self.mouse_button else output_sink.key_up)(self.output)


@dataclass(slots=True)
class DirectionalSemantic(Semantic[frozenset[str]]):
    _active: frozenset[str] = field(init=False, default_factory=frozenset)

    def process(self, context: PipelineContext, value: frozenset[str], output_sink: OutputSink) -> None:
        if context.event.phase is TouchPhase.UP:
            self.reset(output_sink)
            return

        for key in self._active - value:
            output_sink.key_up(key)
        for key in value - self._active:
            output_sink.key_down(key)
        self._active = value

    def reset(self, output_sink: OutputSink) -> None:
        for key in self._active:
            output_sink.key_up(key)
        self._active = frozenset()


@dataclass(slots=True)
class PointerSemantic(Semantic[Vector]):
    pointer: bool = True

    def process(self, context: PipelineContext, value: Vector, output_sink: OutputSink) -> None:
        if self.pointer and context.event.phase is TouchPhase.MOVE and (value.x or value.y):
            output_sink.mouse_move(value.x, value.y)


@dataclass(slots=True)
class ToggleSemantic(Semantic[Unit]):
    output: str
    max_duration_s: float = 0.3
    max_drift_px: float = 30.0

    _start_time: float | None = field(init=False, default=None)
    _start_pos: Point | None = field(init=False, default=None)

    def process(self, context: PipelineContext, value: Unit, output_sink: OutputSink) -> None:
        phase = context.event.phase

        if phase is TouchPhase.DOWN:
            self._start_time = context.event.timestamp
            self._start_pos = context.event.position
            return

        if phase is TouchPhase.UP:
            if self._start_time is None or self._start_pos is None:
                return

            duration = context.event.timestamp - self._start_time
            drift = (context.event.position - self._start_pos).magnitude

            self._start_time = None
            self._start_pos = None

            if duration <= self.max_duration_s and drift <= self.max_drift_px:
                if self.output == TOGGLE_MODE:
                    output_sink.toggle_menu_mode()
                elif self.output == TOGGLE_VKB:
                    output_sink.toggle_virtual_keyboard()

    def reset(self, output_sink: OutputSink | None = None) -> None:
        self._start_time = None
        self._start_pos = None


# ---------------------------------------------------------------------------
# Pipeline with Touch Ownership & Priority Contract
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class Pipeline(Generic[T]):
    region: Region
    origin: Origin
    constraint: Constraint
    transformation: Transformation[T]
    semantics: list[Semantic[T]]
    priority: int = 0
    type_precedence: int = 0
    creation_id: int = 0
    allow_multi_claim: bool = False
    is_system: bool = False

    _owned_contact: int | None = field(init=False, default=None)
    _prev_position: Point | None = field(init=False, default=None)

    def claims(self, event: TouchEvent) -> bool:
        return self._owned_contact is None and self.region.activates(event)

    def owns(self, contact_id: int) -> bool:
        return self._owned_contact == contact_id

    def reset(self, output_sink: OutputSink) -> None:
        for semantic in self.semantics:
            semantic.reset(output_sink)
        self.transformation.reset()
        self.origin.end()
        self._owned_contact = None
        self._prev_position = None

    def process(self, event: TouchEvent, output_sink: OutputSink) -> bool:
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
            semantic.process(context, value, output_sink)

        self._prev_position = constrained

        if event.phase is TouchPhase.UP:
            self.origin.end()
            self.transformation.reset()
            self._owned_contact = None
            self._prev_position = None

        return True


# ---------------------------------------------------------------------------
# Pipeline Configs
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class PipelineConfig:
    is_last_set_config_self: bool = False
    should_get_config: bool = True
    pipeline_config: dict = field(default_factory=dict)

    def _monitor_last_set_config(self, pipeline_config: dict | None = None) -> None:
        self.is_last_set_config_self = pipeline_config is None

    def get_region_config(self, pipeline_config: dict | None = None) -> tuple[int, str, float, int]:
        cfg = pipeline_config if pipeline_config is not None else self.pipeline_config
        region = cfg.get("region", {})
        idx = int(region.get("idx", -1))
        mode = str(region.get("mode", ""))
        bezel_dp_thickness = float(region.get("bezel_dp_thickness", BEZEL_DP_THICKNESS))
        priority = int(region.get("priority", 0))
        return (idx, mode, bezel_dp_thickness, priority)

    def set_region_config(
        self,
        idx: int | None = None,
        bezel_dp_thickness: float | None = None,
        priority: int | None = None,
        pipeline_config: dict | None = None,
        keep_previous: bool = True,
    ) -> None:
        self._monitor_last_set_config(pipeline_config)
        if pipeline_config is None:
            self.should_get_config = True

        cfg = pipeline_config if pipeline_config is not None else self.pipeline_config
        prev_idx, prev_mode, prev_bezel_dp_thickness, prev_priority = self.get_region_config(cfg)

        target_idx = idx if idx is not None else (prev_idx if keep_previous else -1)
        if 0 <= target_idx < len(REGION_MODES):
            target_mode = REGION_MODES[target_idx]
        else:
            target_mode = prev_mode if keep_previous else ""

        target_bezel_dp_thickness = (
            bezel_dp_thickness
            if bezel_dp_thickness is not None
            else (prev_bezel_dp_thickness if keep_previous else float(BEZEL_DP_THICKNESS))
        )
        target_priority = priority if priority is not None else (prev_priority if keep_previous else 0)

        region = cfg.setdefault("region", {})
        region.update({
            "idx": target_idx,
            "mode": target_mode,
            "bezel_dp_thickness": target_bezel_dp_thickness,
            "priority": target_priority,
        })

    def get_origin_config(self, pipeline_config: dict | None = None) -> tuple[int, str]:
        cfg = pipeline_config if pipeline_config is not None else self.pipeline_config
        origin = cfg.get("origin", {})
        return (int(origin.get("idx", -1)), str(origin.get("mode", "")))

    def set_origin_config(
        self,
        idx: int | None = None,
        pipeline_config: dict | None = None,
        keep_previous: bool = True,
    ) -> None:
        self._monitor_last_set_config(pipeline_config)
        if pipeline_config is None:
            self.should_get_config = True

        cfg = pipeline_config if pipeline_config is not None else self.pipeline_config
        prev_idx, prev_mode = self.get_origin_config(cfg)

        target_idx = idx if idx is not None else (prev_idx if keep_previous else -1)
        if 0 <= target_idx < len(ORIGIN_MODES):
            target_mode = ORIGIN_MODES[target_idx]
        else:
            target_mode = prev_mode if keep_previous else ""

        origin = cfg.setdefault("origin", {})
        origin.update({"idx": target_idx, "mode": target_mode})

    def get_constraint_config(self, pipeline_config: dict | None = None) -> tuple[int, str]:
        cfg = pipeline_config if pipeline_config is not None else self.pipeline_config
        constraint = cfg.get("constraint", {})
        return (int(constraint.get("idx", -1)), str(constraint.get("mode", "")))

    def set_constraint_config(
        self,
        idx: int | None = None,
        pipeline_config: dict | None = None,
        keep_previous: bool = True,
    ) -> None:
        self._monitor_last_set_config(pipeline_config)
        if pipeline_config is None:
            self.should_get_config = True

        cfg = pipeline_config if pipeline_config is not None else self.pipeline_config
        prev_idx, prev_mode = self.get_constraint_config(cfg)

        target_idx = idx if idx is not None else (prev_idx if keep_previous else -1)
        if 0 <= target_idx < len(CONSTRAINT_MODES):
            target_mode = CONSTRAINT_MODES[target_idx]
        else:
            target_mode = prev_mode if keep_previous else ""

        constraint = cfg.setdefault("constraint", {})
        constraint.update({"idx": target_idx, "mode": target_mode})

    def get_transform_config(
        self, pipeline_config: dict | None = None
    ) -> tuple[int, str, float, float, float, float]:
        cfg = pipeline_config if pipeline_config is not None else self.pipeline_config
        transform = cfg.get("transform", {})
        return (
            int(transform.get("idx", -1)),
            str(transform.get("mode", "")),
            float(transform.get("sensitivity_x", 1.0)),
            float(transform.get("sensitivity_y", 1.0)),
            float(transform.get("deadzone", 0.1)),
            float(transform.get("hysteresis", 5.0)),
        )

    def set_transform_config(
        self,
        idx: int | None = None,
        sensitivity_x: float | None = None,
        sensitivity_y: float | None = None,
        deadzone: float | None = None,
        hysteresis: float | None = None,
        pipeline_config: dict | None = None,
        keep_previous: bool = True,
    ) -> None:
        self._monitor_last_set_config(pipeline_config)
        if pipeline_config is None:
            self.should_get_config = True

        cfg = pipeline_config if pipeline_config is not None else self.pipeline_config
        (
            prev_idx,
            prev_mode,
            prev_sens_x,
            prev_sens_y,
            prev_deadzone,
            prev_hysteresis,
        ) = self.get_transform_config(cfg)

        target_idx = idx if idx is not None else (prev_idx if keep_previous else -1)
        if 0 <= target_idx < len(TRANSFORM_MODES):
            target_mode = TRANSFORM_MODES[target_idx]
        else:
            target_mode = prev_mode if keep_previous else ""

        transform = cfg.setdefault("transform", {})
        transform.update({
            "idx": target_idx,
            "mode": target_mode,
            "sensitivity_x": sensitivity_x if sensitivity_x is not None else (prev_sens_x if keep_previous else 1.0),
            "sensitivity_y": sensitivity_y if sensitivity_y is not None else (prev_sens_y if keep_previous else 1.0),
            "deadzone": deadzone if deadzone is not None else (prev_deadzone if keep_previous else 0.1),
            "hysteresis": hysteresis if hysteresis is not None else (prev_hysteresis if keep_previous else 5.0),
        })

    def get_semantic_config(
        self, pipeline_config: dict | None = None
    ) -> tuple[int, str, bool]:
        cfg = pipeline_config if pipeline_config is not None else self.pipeline_config
        semantic = cfg.get("semantic", {})
        return (
            int(semantic.get("idx", -1)),
            str(semantic.get("mode", "")),
            bool(semantic.get("pointer", False)),
        )

    def set_semantic_config(
        self,
        idx: int | None = None,
        pointer: bool | None = None,
        pipeline_config: dict | None = None,
        keep_previous: bool = True,
    ) -> None:
        self._monitor_last_set_config(pipeline_config)
        if pipeline_config is None:
            self.should_get_config = True

        cfg = pipeline_config if pipeline_config is not None else self.pipeline_config
        prev_idx, prev_mode, prev_pointer = self.get_semantic_config(cfg)

        target_idx = idx if idx is not None else (prev_idx if keep_previous else -1)
        if 0 <= target_idx < len(SEMANTIC_MODES):
            target_mode = SEMANTIC_MODES[target_idx]
        else:
            target_mode = prev_mode if keep_previous else ""

        semantic = cfg.setdefault("semantic", {})
        semantic.update({
            "idx": target_idx,
            "mode": target_mode,
            "pointer": pointer if pointer is not None else (prev_pointer if keep_previous else False),
        })

    def get_pipeline_json_from_config(self, pipeline_config: dict | None = None) -> str:
        cfg = pipeline_config if pipeline_config is not None else self.pipeline_config
        try:
            return json.dumps(cfg)
        except (TypeError, ValueError) as exc:
            logger.error("Failed to dump pipeline configuration to JSON: %s", exc)
            return "{}"

    def set_pipeline_config_from_json(
        self, pipeline_json: str = "{}", pipeline_config: dict | None = None
    ) -> None:
        self._monitor_last_set_config(pipeline_config)
        if pipeline_config is None:
            self.should_get_config = False

        cfg = pipeline_config if pipeline_config is not None else self.pipeline_config

        try:
            parsed = json.loads(pipeline_json)
            if not isinstance(parsed, dict):
                logger.error(
                    "Invalid root type in pipeline JSON; expected dict, got %s",
                    type(parsed).__name__,
                )
                parsed = {}
        except (json.JSONDecodeError, TypeError, ValueError) as exc:
            logger.error("Failed to load pipeline configuration from JSON: %s", exc)
            parsed = {}

        cfg.clear()
        cfg.update(parsed)
