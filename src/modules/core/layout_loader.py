from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING

from modules.core.pipeline import CircularRegion, RectangularRegion, Region
from modules.database import store
from modules.utils import (
    BEZEL,
    CIRCLE,
    MOUSE_WHEEL_SIMULATOR_CODE,
    RECTANGLE,
    SPRINT_DISTANCE_CODE,
    Point,
)

if TYPE_CHECKING:
    from modules.database import AppSettings, Layout, LayoutZone
    from modules.utils import MapperEventDispatcher

logger = logging.getLogger("modules.core.layout_loader")

POINTER_SEMANTIC_IDX = 2
# up, left, down, right (W, A, S, D)
_DEFAULT_WHEEL_KEYS: tuple[int, int, int, int] = (0x11, 0x1E, 0x1F, 0x20)
_WHEEL_KEY_NAMES = ("up", "left", "down", "right")


@dataclass(frozen=True, slots=True)
class ZoneData:
    """One zone in DEVICE PIXELS (the layout's own coordinate space)."""

    id: int
    scancode: int
    name: str
    zone_type: str
    priority: int
    pointer: bool
    semantic_idx: int
    ignore_app_settings: bool
    sensitivity_x: float
    sensitivity_y: float
    deadzone: float
    hysteresis: float
    cx: float = 0.0
    cy: float = 0.0
    r: float = 0.0
    x1: float = 0.0
    y1: float = 0.0
    x2: float = 0.0
    y2: float = 0.0

    @property
    def center(self) -> Point:
        return Point(self.cx, self.cy)

    def region(self) -> Region | None:
        if self.zone_type == CIRCLE:
            return CircularRegion(center=Point(self.cx, self.cy), radius=self.r)
        if self.zone_type in (RECTANGLE, BEZEL):
            return RectangularRegion(
                top_left=Point(self.x1, self.y1),
                bottom_right=Point(self.x2, self.y2),
            )
        return None


@dataclass(frozen=True, slots=True)
class LayoutSnapshot:
    """Everything the mappers need for one reload, read once and never mutated."""

    settings: AppSettings
    layout: Layout | None = None
    keys: tuple[ZoneData, ...] = ()  # circle/rect zones, wheel and sprint excluded
    bezels: tuple[ZoneData, ...] = ()
    wheel: ZoneData | None = None
    wheel_keys: tuple[int, int, int, int] = _DEFAULT_WHEEL_KEYS
    look_zone: ZoneData | None = None  # first zone whose semantic is POINTER


class LayoutLoader:
    """Reads the active layout, its zones and the app settings ONCE per reload
    and publishes them as an immutable LayoutSnapshot (device pixels throughout).

    Mappers read `loader.snapshot` (a single atomic attribute read) instead of
    hitting the database themselves, so every mapper sees the same layout.
    ON_RELOAD callbacks run in registration order, and this loader is created
    before any mapper, so the snapshot is always fresh when they rebuild.
    """

    def __init__(self, dispatcher: MapperEventDispatcher):
        self.dispatcher = dispatcher
        self.snapshot: LayoutSnapshot

        self.load_layout()
        self.dispatcher.register_callback("ON_RELOAD", self.load_layout)

    @staticmethod
    def _wheel_keys(zone: LayoutZone) -> tuple[int, int, int, int]:
        cfg = zone.CONFIG_HELPER.pipeline_config
        try:
            return tuple(  # type: ignore[return-value]
                int(cfg.get(name, default))
                for name, default in zip(_WHEEL_KEY_NAMES, _DEFAULT_WHEEL_KEYS)
            )
        except (TypeError, ValueError):
            logger.warning("Invalid wheel key config; using WASD.")
            return _DEFAULT_WHEEL_KEYS

    @staticmethod
    def _to_zone_data(zone: LayoutZone) -> ZoneData:
        zone.set_parsed_config_from_json()
        helper = zone.CONFIG_HELPER
        _, _, _, priority = helper.get_region_config()
        sem_idx, _, pointer = helper.get_semantic_config()
        _, _, sens_x, sens_y, deadzone, hysteresis = helper.get_transform_config()
        return ZoneData(
            id=zone.id,
            scancode=zone.scancode,
            name=zone.name,
            zone_type=zone.zone_type,
            priority=priority,
            pointer=pointer,
            semantic_idx=sem_idx,
            ignore_app_settings=bool(zone.ignore_app_settings),
            sensitivity_x=sens_x,
            sensitivity_y=sens_y,
            deadzone=deadzone,
            hysteresis=hysteresis,
            cx=float(zone.cx or 0.0),
            cy=float(zone.cy or 0.0),
            r=float(zone.r or 0.0),
            x1=float(zone.x1 or 0.0),
            y1=float(zone.y1 or 0.0),
            x2=float(zone.x2 or 0.0),
            y2=float(zone.y2 or 0.0),
        )

    def load_layout(self) -> None:
        settings = store.settings.get()
        layout = store.get_active_layout()
        if layout is None:
            logger.warning("No active layout found in SQLite database.")
            self.snapshot = LayoutSnapshot(settings=settings)
            return

        # list_for_layout auto-heals the bezels.
        zones = store.zones.list_for_layout(layout.id)

        keys: list[ZoneData] = []
        bezels: list[ZoneData] = []
        wheel: ZoneData | None = None
        wheel_keys = _DEFAULT_WHEEL_KEYS
        look_zone: ZoneData | None = None

        for zone in zones:
            if zone.scancode == SPRINT_DISTANCE_CODE:
                continue

            data = self._to_zone_data(zone)

            if zone.zone_type == BEZEL:
                bezels.append(data)
                continue
            if zone.zone_type not in (CIRCLE, RECTANGLE):
                continue

            if zone.scancode == MOUSE_WHEEL_SIMULATOR_CODE:
                if wheel is None and zone.zone_type == CIRCLE:
                    wheel = data
                    wheel_keys = self._wheel_keys(zone)
                continue

            keys.append(data)
            if look_zone is None and data.semantic_idx == POINTER_SEMANTIC_IDX:
                look_zone = data

        self.snapshot = LayoutSnapshot(
            settings=settings,
            layout=layout,
            keys=tuple(keys),
            bezels=tuple(bezels),
            wheel=wheel,
            wheel_keys=wheel_keys,
            look_zone=look_zone,
        )

        logger.info(
            "Active layout '%s' loaded. (%dx%d @ %d DPI, %d zones)",
            layout.name,
            layout.width,
            layout.height,
            layout.dpi,
            len(zones),
        )