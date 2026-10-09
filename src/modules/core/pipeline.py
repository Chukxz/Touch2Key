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
# Constraints, Origins, Transforms, Semantics
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class Constraint(ABC):
    @abstractmethod
    def apply(self, origin: Point, position: Point) -> Point: ...

    def update_origin(self, origin: Point, position: Point) -> Point:
        """Allows leash-type constraints to drag the origin dynamically."""
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

    def reset(self) -> None:
        self._last_sector = None

    def apply(self, context: PipelineContext) -> frozenset[str]:
        dist_sq = context.delta.magnitude_squared
        if dist_sq <= self.dead_zone * self.dead_zone:
            self._last_sector = None
            return frozenset()
        angle_rad = math.atan2(context.delta.y, context.delta.x)
        if angle_rad < 0:
            angle_rad += 2 * math.pi
        new_sector = int((angle_rad + self._PI_8) * self._INV_PI_4) % 8
        if self._last_sector is not None:
            current_center = self._last_sector * (math.pi / 4.0)
            angle_diff = (angle_rad - current_center + math.pi) % (
                2 * math.pi
            ) - math.pi
            if abs(angle_diff) < (self._PI_8 + self.hysteresis_rad):
                new_sector = self._last_sector
        self._last_sector = new_sector
        sector_map = {
            0: {self.right},
            1: {self.down, self.right},
            2: {self.down},
            3: {self.down, self.left},
            4: {self.left},
            5: {self.up, self.left},
            6: {self.up},
            7: {self.up, self.right},
        }
        active_keys = set(sector_map.get(new_sector, set()))
        if self.sprint_distance > 0 and dist_sq > (
            self.sprint_distance * self.sprint_distance
        ):
            active_keys.add(self.sprint_key)
        return frozenset(active_keys)


@dataclass(slots=True)
class Semantic(ABC, Generic[T]):
    @abstractmethod
    def process(
        self, context: PipelineContext, value: T, output_sink: OutputSink
    ) -> None: ...
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

    def process(
        self, context: PipelineContext, value: frozenset[str], output_sink: OutputSink
    ) -> None:
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

    def process(
        self, context: PipelineContext, value: Vector, output_sink: OutputSink
    ) -> None:
        if (
            self.pointer
            and context.event.phase is TouchPhase.MOVE
            and (value.x or value.y)
        ):
            output_sink.mouse_move(value.x, value.y)


@dataclass(slots=True)
class ToggleSemantic(Semantic[Unit]):
    """
    Executes a system toggle command on touch UP, strictly enforcing tap constraints
    to prevent accidental triggers from Android system edge swipes or long presses.
    """

    output: str

    # Tap constraint parameters
    max_duration_s: float = 0.3
    max_drift_px: float = 30.0

    _start_time: float | None = field(init=False, default=None)
    _start_pos: Point | None = field(init=False, default=None)

    def process(
        self, context: PipelineContext, value: Unit, output_sink: OutputSink
    ) -> None:
        phase = context.event.phase

        # 1. Record initial contact
        if phase is TouchPhase.DOWN:
            self._start_time = context.event.timestamp
            self._start_pos = context.event.position
            return

        # 2. Evaluate on release
        if phase is TouchPhase.UP:
            if self._start_time is None or self._start_pos is None:
                return

            duration = context.event.timestamp - self._start_time
            drift = (context.event.position - self._start_pos).magnitude

            # Reset state for next interaction
            self._start_time = None
            self._start_pos = None

            # 3. Fire only if it passes the strict tap constraint
            if duration <= self.max_duration_s and drift <= self.max_drift_px:
                if self.output == TOGGLE_MODE:
                    output_sink.toggle_menu_mode()
                elif self.output == TOGGLE_VKB:
                    output_sink.toggle_virtual_keyboard()
                else:
                    pass

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
        if pipeline_config is None:
            self.is_last_set_config_self = True
        else:
            self.is_last_set_config_self = False

    def get_region_config(self, pipeline_config: dict | None = None) -> tuple[int, str, float, int]:
        pipeline_config = (
            pipeline_config if pipeline_config is not None else self.pipeline_config
        )

        region = pipeline_config.get("region", {})
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

        pipeline_config = (
            pipeline_config if pipeline_config is not None else self.pipeline_config
        )

        prev_idx, prev_mode, prev_bezel_dp_thickness, prev_priority = (
            self.get_region_config(pipeline_config)
        )

        # Resolve Target IDX
        if idx is not None:
            target_idx = idx
        elif keep_previous:
            target_idx = prev_idx
        else:
            target_idx = -1

        # Resolve Target Mode
        if 0 <= target_idx < len(REGION_MODES):
            target_mode = REGION_MODES[target_idx]
        elif keep_previous:
            target_mode = prev_mode
        else:
            target_mode = ""

        # Resolve Target Bezel DP Thickness
        if bezel_dp_thickness is not None:
            target_bezel_dp_thickness = bezel_dp_thickness
        elif keep_previous:
            target_bezel_dp_thickness = prev_bezel_dp_thickness
        else:
            target_bezel_dp_thickness = float(BEZEL_DP_THICKNESS)

        # Resolve Target Priority
        if priority is not None:
            target_priority = priority
        elif keep_previous:
            target_priority = prev_priority
        else:
            target_priority = 0

        region = pipeline_config.setdefault("region", {})
        region.update(
            {
                "idx": target_idx,
                "mode": target_mode,
                "bezel_dp_thickness": target_bezel_dp_thickness,
                "priority": target_priority,
            }
        )

    def get_origin_config(self, pipeline_config: dict | None = None) -> tuple[int, str]:
        pipeline_config = (
            pipeline_config if pipeline_config is not None else self.pipeline_config
        )

        origin = pipeline_config.get("origin", {})
        idx = int(origin.get("idx", -1))
        mode = str(origin.get("mode", ""))

        return (idx, mode)

    def set_origin_config(
        self,
        idx: int | None = None,
        pipeline_config: dict | None = None,
        keep_previous: bool = True,
    ) -> None:
        self._monitor_last_set_config(pipeline_config)
        if pipeline_config is None:
            self.should_get_config = True

        pipeline_config = (
            pipeline_config if pipeline_config is not None else self.pipeline_config
        )

        prev_idx, prev_mode = self.get_origin_config(pipeline_config)

        # Resolve Target IDX
        if idx is not None:
            target_idx = idx
        elif keep_previous:
            target_idx = prev_idx
        else:
            target_idx = -1

        # Resolve Target Mode
        if 0 <= target_idx < len(ORIGIN_MODES):
            target_mode = ORIGIN_MODES[target_idx]
        elif keep_previous:
            target_mode = prev_mode
        else:
            target_mode = ""

        origin = pipeline_config.setdefault("origin", {})
        origin.update(
            {
                "idx": target_idx,
                "mode": target_mode,
            }
        )

    def get_constraint_config(self, pipeline_config: dict | None = None) -> tuple[int, str]:
        pipeline_config = (
            pipeline_config if pipeline_config is not None else self.pipeline_config
        )

        constraint = pipeline_config.get("constraint", {})
        idx = int(constraint.get("idx", -1))
        mode = str(constraint.get("mode", ""))

        return (idx, mode)

    def set_constraint_config(
        self,
        idx: int | None = None,
        pipeline_config: dict | None = None,
        keep_previous: bool = True,
    ) -> None:
        self._monitor_last_set_config(pipeline_config)
        if pipeline_config is None:
            self.should_get_config = True

        pipeline_config = (
            pipeline_config if pipeline_config is not None else self.pipeline_config
        )

        prev_idx, prev_mode = self.get_constraint_config(pipeline_config)

        # Resolve Target IDX
        if idx is not None:
            target_idx = idx
        elif keep_previous:
            target_idx = prev_idx
        else:
            target_idx = -1

        # Resolve Target Mode
        if 0 <= target_idx < len(CONSTRAINT_MODES):
            target_mode = CONSTRAINT_MODES[target_idx]
        elif keep_previous:
            target_mode = prev_mode
        else:
            target_mode = ""

        constraint = pipeline_config.setdefault("constraint", {})
        constraint.update(
            {
                "idx": target_idx,
                "mode": target_mode,
            }
        )

    def get_transform_config(
        self, pipeline_config: dict | None = None
    ) -> tuple[int, str, float, float, float, float]:
        pipeline_config = (
            pipeline_config if pipeline_config is not None else self.pipeline_config
        )

        transform = pipeline_config.get("transform", {})
        idx = int(transform.get("idx", -1))
        mode = str(transform.get("mode", ""))
        sensitivity_x = float(transform.get("sensitivity_x", 1.0))
        sensitivity_y = float(transform.get("sensitivity_y", 1.0))
        deadzone = float(transform.get("deadzone", 0.1))
        hysteresis = float(transform.get("hysteresis", 5.0))

        return (
            idx,
            mode,
            sensitivity_x,
            sensitivity_y,
            deadzone,
            hysteresis,
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

        pipeline_config = (
            pipeline_config if pipeline_config is not None else self.pipeline_config
        )

        (
            prev_idx,
            prev_mode,
            prev_sensitivity_x,
            prev_sensitivity_y,
            prev_deadzone,
            prev_hysteresis,
        ) = self.get_transform_config(pipeline_config)

        # Resolve Target IDX
        if idx is not None:
            target_idx = idx
        elif keep_previous:
            target_idx = prev_idx
        else:
            target_idx = -1

        # Resolve Target Mode
        if 0 <= target_idx < len(TRANSFORM_MODES):
            target_mode = TRANSFORM_MODES[target_idx]
        elif keep_previous:
            target_mode = prev_mode
        else:
            target_mode = ""

        # Resolve Target X sensitivity
        if sensitivity_x is not None:
            target_sensitivity_x = sensitivity_x
        elif keep_previous:
            target_sensitivity_x = prev_sensitivity_x
        else:
            target_sensitivity_x = 1.0

        # Resolve Target Y sensitivity
        if sensitivity_y is not None:
            target_sensitivity_y = sensitivity_y
        elif keep_previous:
            target_sensitivity_y = prev_sensitivity_y
        else:
            target_sensitivity_y = 1.0

        # Resolve Target Deadzone
        if deadzone is not None:
            target_deadzone = deadzone
        elif keep_previous:
            target_deadzone = prev_deadzone
        else:
            target_deadzone = 0.1

        # Resolve Target Hysteresis
        if hysteresis is not None:
            target_hysteresis = hysteresis
        elif keep_previous:
            target_hysteresis = prev_hysteresis
        else:
            target_hysteresis = 5.0

        transform = pipeline_config.setdefault("transform", {})
        transform.update(
            {
                "idx": target_idx,
                "mode": target_mode,
                "sensitivity_x": target_sensitivity_x,
                "sensitivity_y": target_sensitivity_y,
                "deadzone": target_deadzone,
                "hysteresis": target_hysteresis,
            }
        )

    def get_semantic_config(
        self, pipeline_config: dict | None = None
    ) -> tuple[int, str, bool]:
        pipeline_config = (
            pipeline_config if pipeline_config is not None else self.pipeline_config
        )

        semantic = pipeline_config.get("semantic", {})
        idx = int(semantic.get("idx", -1))
        mode = str(semantic.get("mode", ""))
        pointer = bool(semantic.get("pointer", False))

        return (idx, mode, pointer)

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

        pipeline_config = (
            pipeline_config if pipeline_config is not None else self.pipeline_config
        )

        prev_idx, prev_mode, prev_pointer = self.get_semantic_config(pipeline_config)

        # Resolve Target IDX
        if idx is not None:
            target_idx = idx
        elif keep_previous:
            target_idx = prev_idx
        else:
            target_idx = -1

        # Resolve Target Mode
        if 0 <= target_idx < len(SEMANTIC_MODES):
            target_mode = SEMANTIC_MODES[target_idx]
        elif keep_previous:
            target_mode = prev_mode
        else:
            target_mode = ""

        # Resolve Target Pointer
        if pointer is not None:
            target_pointer = pointer
        elif keep_previous:
            target_pointer = prev_pointer
        else:
            target_pointer = False

        semantic = pipeline_config.setdefault("semantic", {})
        semantic.update(
            {
                "idx": target_idx,
                "mode": target_mode,
                "pointer": target_pointer,
            }
        )

    def get_pipeline_json_from_config(self, pipeline_config: dict | None = None) -> str:
        pipeline_config = (
            pipeline_config if pipeline_config is not None else self.pipeline_config
        )
        try:
            return json.dumps(pipeline_config)
        except (TypeError, ValueError) as exc:
            logger.error("Failed to dump pipeline configuration to JSON: %s", exc)
            return "{}"

    def set_pipeline_config_from_json(
        self, pipeline_json: str = "{}", pipeline_config: dict | None = None
    ) -> None:
        self._monitor_last_set_config(pipeline_config)
        if pipeline_config is None:
            self.should_get_config = False

        pipeline_config = (
            pipeline_config if pipeline_config is not None else self.pipeline_config
        )

        try:
            _pipeline_config = json.loads(pipeline_json)
            if not isinstance(_pipeline_config, dict):
                logger.error(
                    "Invalid root type in pipeline JSON; expected dict, got %s",
                    type(_pipeline_config).__name__,
                )
                _pipeline_config = {}
        except (json.JSONDecodeError, TypeError, ValueError) as exc:
            logger.error("Failed to load pipeline configuration from JSON: %s", exc)
            _pipeline_config = {}

        pipeline_config.clear()
        pipeline_config.update(_pipeline_config)
