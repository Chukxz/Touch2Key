from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class AbstractWindowManager(ABC):
    @abstractmethod
    def get_foreground_window(self) -> int:
        pass

    @abstractmethod
    def is_window_valid(self, window_id: int) -> bool:
        pass

    @abstractmethod
    def is_window_visible(self, window_id: int) -> bool:
        pass

    @abstractmethod
    def get_window_class_name(self, window_id: int) -> str:
        pass

    @abstractmethod
    def find_window_by_title(self, title: str) -> Any | None:
        pass

    @abstractmethod
    def find_window_ids_by_class(self, class_name: str | None) -> list:
        pass

    @abstractmethod
    def get_window_dimensions(self, window_id: int) -> tuple[int, int]:
        pass

    @abstractmethod
    def get_window_position(self, window_id: int) -> tuple[int, int]:
        pass

    @abstractmethod
    def is_cursor_visible(
        self, last_state: bool, last_check_time: int
    ) -> tuple[bool, int]:
        pass

    @abstractmethod
    def get_screen_dimensions(self) -> tuple[int, int]:
        pass

    @abstractmethod
    def find_visible_windows(self) -> dict[int, dict]:
        pass


class AbstractBridge(ABC):
    @abstractmethod
    def start_worker_processes(
        self, k_device_handle: int | None, m_device_handle: int | None
    ) -> None:
        pass

    @abstractmethod
    def reload_devices(
        self, new_k_handle: int | None, new_m_handle: int | None
    ) -> None:
        """Hot-reloads driver devices and restarts workers."""
        pass

    @abstractmethod
    def key_down(self, code: int) -> None:
        pass

    @abstractmethod
    def key_up(self, code: int) -> None:
        pass

    @abstractmethod
    def mouse_move_rel(self, dx: int, dy: int) -> None:
        pass

    @abstractmethod
    def mouse_move_abs(self, x: int, y: int) -> None:
        pass

    @abstractmethod
    def left_click_down(self) -> None:
        pass

    @abstractmethod
    def left_click_up(self) -> None:
        pass

    @abstractmethod
    def right_click_down(self) -> None:
        pass

    @abstractmethod
    def right_click_up(self) -> None:
        pass

    @abstractmethod
    def middle_click_down(self) -> None:
        pass

    @abstractmethod
    def middle_click_up(self) -> None:
        pass

    @abstractmethod
    def health_check(self) -> None:
        pass

    @abstractmethod
    def shutdown(self) -> None:
        pass

    @abstractmethod
    def release_all(self) -> None:
        pass

    @abstractmethod
    def set_respawn_callback(self, callback) -> None:
        pass


class AbstractSystemConfig(ABC):
    @abstractmethod
    def set_dpi_awareness(self) -> None:
        pass

    @abstractmethod
    def set_timer_resolution(self) -> None:
        pass

    @abstractmethod
    def set_high_priority(self, pid: int | None, label: str) -> None:
        pass


class AbstractMapping(ABC):
    @abstractmethod
    def get_key_from_scancode(self, scancode: int) -> str:
        pass

    @abstractmethod
    def get_scancode_from_key(self, key_name: str) -> int:
        pass
