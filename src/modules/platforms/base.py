from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class AbstractWindowManager(ABC):
    __slots__ = ()

    @abstractmethod
    def get_foreground_window(self) -> int:
        raise NotImplementedError

    @abstractmethod
    def is_window_valid(self, window_id: int) -> bool:
        raise NotImplementedError

    @abstractmethod
    def is_window_visible(self, window_id: int) -> bool:
        raise NotImplementedError

    @abstractmethod
    def get_window_class_name(self, window_id: int) -> str:
        raise NotImplementedError

    @abstractmethod
    def find_window_by_title(self, title: str) -> Any | None:
        raise NotImplementedError

    @abstractmethod
    def find_window_ids_by_class(self, class_name: str | None) -> list:
        raise NotImplementedError

    @abstractmethod
    def get_window_dimensions(self, window_id: int) -> tuple[int, int]:
        raise NotImplementedError

    @abstractmethod
    def get_window_position(self, window_id: int) -> tuple[int, int]:
        raise NotImplementedError

    @abstractmethod
    def is_cursor_visible(
        self, last_state: bool, last_check_time: int
    ) -> tuple[bool, int]:
        raise NotImplementedError

    @abstractmethod
    def get_screen_dimensions(self) -> tuple[int, int]:
        raise NotImplementedError

    @abstractmethod
    def find_visible_windows(self) -> dict[int, dict]:
        raise NotImplementedError


class AbstractBridge(ABC):
    __slots__ = ()

    @abstractmethod
    def start_worker_processes(
        self, k_device_handle: int | None, m_device_handle: int | None
    ) -> None:
        raise NotImplementedError

    @abstractmethod
    def reload_devices(
        self, new_k_handle: int | None, new_m_handle: int | None
    ) -> None:
        """Hot-reloads driver devices and restarts workers."""
        raise NotImplementedError

    @abstractmethod
    def key_down(self, code: int) -> None:
        raise NotImplementedError

    @abstractmethod
    def key_up(self, code: int) -> None:
        raise NotImplementedError

    @abstractmethod
    def mouse_move_rel(self, dx: int, dy: int) -> None:
        raise NotImplementedError

    @abstractmethod
    def mouse_move_abs(self, x: int, y: int) -> None:
        raise NotImplementedError

    @abstractmethod
    def left_click_down(self) -> None:
        raise NotImplementedError

    @abstractmethod
    def left_click_up(self) -> None:
        raise NotImplementedError

    @abstractmethod
    def right_click_down(self) -> None:
        raise NotImplementedError

    @abstractmethod
    def right_click_up(self) -> None:
        raise NotImplementedError

    @abstractmethod
    def middle_click_down(self) -> None:
        raise NotImplementedError

    @abstractmethod
    def middle_click_up(self) -> None:
        raise NotImplementedError

    @abstractmethod
    def wheel(self, dx: float, dy: float) -> None:
        raise NotImplementedError

    @abstractmethod
    def update_typematic(
        self,
        enabled: bool,
        delay_ms: float,
        rate_hz: float,
        exclude_scancodes: set[int],
    ) -> None:
        raise NotImplementedError

    @abstractmethod
    def health_check(self) -> None:
        raise NotImplementedError

    @abstractmethod
    def shutdown(self) -> None:
        raise NotImplementedError

    @abstractmethod
    def release_all(self) -> None:
        raise NotImplementedError

    @abstractmethod
    def set_respawn_callback(self, callback) -> None:
        raise NotImplementedError


class AbstractSystemConfig(ABC):
    __slots__ = ()

    @abstractmethod
    def set_dpi_awareness(self) -> None:
        raise NotImplementedError

    @abstractmethod
    def set_timer_resolution(self) -> None:
        raise NotImplementedError

    @abstractmethod
    def set_high_priority(self, pid: int | None, label: str) -> None:
        raise NotImplementedError


class AbstractMapping(ABC):
    __slots__ = ()

    @abstractmethod
    def get_key_name_from_code(self, key_code: int) -> str:
        """Translates a platform native scancode into a key token."""
        raise NotImplementedError

    @abstractmethod
    def get_key_code_from_name(self, key_name: str) -> int:
        """Translates a key token into a platform native scancode."""
        raise NotImplementedError