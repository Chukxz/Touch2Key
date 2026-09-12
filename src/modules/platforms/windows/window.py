from typing import Any
from ..base import AbstractWindowManager
from modules.utils import CURSOR_CHECK_DELAY_NS, MAX_CLASS_NAME
import ctypes
from ctypes import wintypes
import win32gui
import time

CURSOR_SHOWING = 0x1


class _RECT(ctypes.Structure):
    _fields_ = [
        ("left", ctypes.c_long),
        ("top", ctypes.c_long),
        ("right", ctypes.c_long),
        ("bottom", ctypes.c_long),
    ]


class _POINT(ctypes.Structure):
    _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]


class WindowManager(AbstractWindowManager):
    _EnumWindowsProc = ctypes.WINFUNCTYPE(ctypes.c_bool, wintypes.HWND, wintypes.LPARAM)

    def get_foreground_window(self) -> int:
        return win32gui.GetForegroundWindow()

    def is_window_valid(self, window_id: int) -> bool:
        return bool(ctypes.windll.user32.IsWindow(window_id))

    def is_window_visible(self, window_id: int) -> bool:
        return bool(ctypes.windll.user32.IsWindowVisible(window_id))

    def get_window_class_name(self, window_id: int) -> str:
        buffer = ctypes.create_unicode_buffer(MAX_CLASS_NAME)
        ctypes.windll.user32.GetClassNameW(window_id, buffer, MAX_CLASS_NAME)
        return buffer.value

    def find_window_by_title(self, title: str) -> Any | None:
        hwnd = ctypes.windll.user32.FindWindowW(None, title)
        return hwnd if hwnd != 0 else None

    def _enum_class_windows_callback(
        self, hwnd: wintypes.HWND, lParam: wintypes.LPARAM
    ) -> bool:
        target_class = ctypes.cast(
            lParam, ctypes.POINTER(ctypes.py_object)
        ).contents.value["class_name"]
        results = ctypes.cast(lParam, ctypes.POINTER(ctypes.py_object)).contents.value[
            "results"
        ]

        buffer = ctypes.create_unicode_buffer(MAX_CLASS_NAME)
        ctypes.windll.user32.GetClassNameW(hwnd, buffer, MAX_CLASS_NAME)
        if buffer.value == target_class:
            results.append(hwnd)
        return True

    def find_window_ids_by_class(self, class_name: str | None) -> list:
        results = []
        data = ctypes.py_object({"class_name": class_name, "results": results})
        ctypes.windll.user32.EnumWindows(
            self._EnumWindowsProc(self._enum_class_windows_callback), ctypes.byref(data)
        )
        return results

    def get_window_dimensions(self, window_id: int) -> tuple[int, int]:
        rect = _RECT()
        ctypes.windll.user32.GetClientRect(window_id, ctypes.byref(rect))
        width = rect.right - rect.left
        height = rect.bottom - rect.top
        return width, height

    def get_window_position(self, window_id: int) -> tuple[int, int]:
        pt = _POINT()
        pt.x = 0
        pt.y = 0
        ctypes.windll.user32.ClientToScreen(window_id, ctypes.byref(pt))
        return pt.x, pt.y

    def is_cursor_visible(
        self, last_state: bool, last_check_time: int
    ) -> tuple[bool, int]:
        now = time.monotonic_ns()
        if now - last_check_time < CURSOR_CHECK_DELAY_NS:
            return last_state, last_check_time

        try:
            flags, _, _ = win32gui.GetCursorInfo()  # type: ignore
            return bool(flags & CURSOR_SHOWING), now
        except Exception:
            return last_state, now

    def get_screen_dimensions(self) -> tuple[int, int]:
        w = ctypes.windll.user32.GetSystemMetrics(0)
        h = ctypes.windll.user32.GetSystemMetrics(1)
        return w, h

    def _enum_visible_windows_callback(self, hwnd: int, results: dict) -> bool:
        if not win32gui.IsWindowVisible(hwnd):
            return True
        title = win32gui.GetWindowText(hwnd)
        buffer = ctypes.create_unicode_buffer(MAX_CLASS_NAME)
        ctypes.windll.user32.GetClassNameW(hwnd, buffer, MAX_CLASS_NAME)
        class_name = buffer.value
        if title or class_name:
            results[hwnd] = {"title": title, "class_name": class_name}
        return True

    def find_visible_windows(self) -> dict[int, dict]:
        results = {}
        win32gui.EnumWindows(self._enum_visible_windows_callback, results)
        return results
