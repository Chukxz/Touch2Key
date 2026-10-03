from __future__ import annotations

import logging
import threading
from typing import TYPE_CHECKING, Any

from modules.database import store, AppSettings
from modules.utils import MapperEvent

if TYPE_CHECKING:
    from modules.utils import MapperEventDispatcher

logger = logging.getLogger("modules.core.config")


class AppConfig:
    """Database-backed application configuration adapter.
    Preserves backward-compatible .get() and .reload_config() interfaces.
    """

    def __init__(self, mapper_event_dispatcher: MapperEventDispatcher):
        self.mapper_event_dispatcher = mapper_event_dispatcher
        self.config_lock = threading.Lock()
        self.settings: AppSettings = store.settings.get()

    def reload_config(self) -> None:
        """Reloads settings from the SQLite database and dispatches reload events."""
        with self.config_lock:
            self.settings = store.settings.get()
        logger.info("Configuration reloaded from SQLite database.")
        self.mapper_event_dispatcher.dispatch(MapperEvent(action="ON_CONFIG_RELOAD"))

    def switch_handedness(self) -> bool:
        """Toggles left-handed mode directly in the database."""
        with self.config_lock:
            new_val = not self.settings.left_handed
            self.settings = store.settings.update(left_handed=int(new_val))
        self.mapper_event_dispatcher.dispatch(MapperEvent(action="ON_CONFIG_RELOAD"))
        return self.settings.left_handed

    def set_floating(self, enabled: bool) -> bool:
        """Toggles floating mode and dispatches reload."""
        with self.config_lock:
            self.settings = store.settings.update(floating_joystick=enabled)
        self.mapper_event_dispatcher.dispatch(MapperEvent(action="ON_CONFIG_RELOAD"))
        return self.settings.floating_joystick

    def set_anchored(self, enabled: bool) -> bool:
        """Toggles anchored mode and dispatches reload."""
        with self.config_lock:
            self.settings = store.settings.update(anchored_joystick=enabled)
        self.mapper_event_dispatcher.dispatch(MapperEvent(action="ON_CONFIG_RELOAD"))
        return self.settings.anchored_joystick

    def get(self, section: str, default: Any = None) -> dict[str, Any]:
        """Backward-compatible mapping accessor over AppSettings properties."""
        with self.config_lock:
            s = self.settings

        if section == "system":
            active_layout = store.get_active_layout()
            return {
                "left_handed": s.left_handed,
                "json_dev_res": [
                    active_layout.width if active_layout else s.json_dev_width,
                    active_layout.height if active_layout else s.json_dev_height,
                ],
                "json_dev_dpi": active_layout.dpi if active_layout else s.json_dev_dpi,
                "image_path": active_layout.image_path if active_layout else "",
                "double_tap_enabled": s.double_tap_enabled,
                "bezel_toggle_enabled": s.bezel_toggle_enabled,
            }
        elif section == "joystick":
            active_layout = store.get_active_layout()
            return {
                "deadzone": s.deadzone,
                "hysteresis": s.hysteresis,
                "anchored_joystick": s.anchored_joystick,
                "mouse_wheel_radius": (
                    active_layout.mouse_wheel_radius if active_layout else 50.0
                ),
                "sprint_distance": (
                    active_layout.sprint_distance if active_layout else 10.0
                ),
            }
        elif section == "mouse":
            return {
                "sensitivity_x": s.sensitivity_x,
                "sensitivity_y": s.sensitivity_y,
            }
        elif section == "keys":
            return {
                "toggle_key": s.toggle_key or "",
                "sprint_key": s.sprint_key or "",
            }

        return default if default is not None else {}