from typing import Any
from ..base import AbstractWindowManager
from modules.utils import CURSOR_CHECK_DELAY_NS
from Xlib import display, X, error
from Xlib.ext import xfixes
import time


class WindowManager(AbstractWindowManager):
    def __init__(self):
        # Connect to the local X server display
        try:
            self.disp = display.Display()
            self.root = self.disp.screen().root
            self.xfixes_supported = False
            self._checked_xfixes = False

            # X11 uses "Atoms" (cached strings) to query window properties
            self.NET_ACTIVE_WINDOW = self.disp.intern_atom("_NET_ACTIVE_WINDOW")
            self.NET_WM_NAME = self.disp.intern_atom("_NET_WM_NAME")
        except Exception as e:
            print(
                f"[WINDOW MANAGER] - Failed to connect to X11 Display. Ensure you are on X11. {e}"
            )
            self.disp = None

    def _get_window_obj(self, xid: int):
        """Helper to cast an integer ID back to an Xlib Window object."""
        if not self.disp:
            return None
        return self.disp.create_resource_object("window", xid)

    def _get_all_top_level_windows(self) -> list:
        """Returns a flat list of immediate top-level windows under the X11 root."""
        if not self.disp:
            return []

        try:
            return self.root.query_tree().children
        except error.BadWindow:
            return []

    def get_foreground_window(self) -> int:
        if not self.disp:
            return 0
        try:
            win_id = self.root.get_full_property(
                self.NET_ACTIVE_WINDOW, X.AnyPropertyType
            )
            if win_id and win_id.value:
                return win_id.value
        except Exception:
            pass
        return 0

    def is_window_valid(self, window_id: int) -> bool:
        if window_id == 0:
            return False
        try:
            win = self._get_window_obj(window_id)
            if not win:
                return False
            win.get_attributes()  # Will throw BadWindow if invalid
            return True
        except error.BadWindow:
            return False

    def is_window_visible(self, window_id: int) -> bool:
        if window_id == 0:
            return False
        try:
            win = self._get_window_obj(window_id)
            if not win:
                return False
            attr = win.get_attributes()
            return attr.map_state == X.IsViewable
        except error.BadWindow:
            return False

    def get_window_class_name(self, window_id: int) -> str:
        if window_id == 0:
            return ""
        try:
            win = self._get_window_obj(window_id)
            if not win:
                return ""
            wm_class = win.get_wm_class()
            # X11 classes are tuples: ('instance_name', 'Class_Name')
            if wm_class and len(wm_class) > 1:
                return wm_class[1]
        except Exception:
            pass
        return ""

    def find_window_by_title(self, title: str) -> Any | None:
        if not self.disp:
            return None
        # X11 requires searching the tree to find titles
        titles_dict = self._find_window_titles()
        for hwnd, win_title in titles_dict.items():
            if win_title == title:
                return hwnd
        return None

    def find_window_ids_by_class(self, class_name: str | None) -> list:
        if not self.disp or not class_name:
            return []
        results = []
        for win in self._get_all_top_level_windows():
            try:
                wm_class = win.get_wm_class()
                if wm_class and len(wm_class) > 1 and wm_class[1] == class_name:
                    results.append(win.id)
            except error.BadWindow:
                continue
        return results

    def get_window_dimensions(self, window_id: int) -> tuple[int, int]:
        if window_id == 0:
            return 0, 0
        try:
            win = self._get_window_obj(window_id)
            if not win:
                return 0, 0
            geom = win.get_geometry()
            # X11 get_geometry returns inner client dimensions, excluding WM borders
            return geom.width, geom.height
        except Exception:
            return 0, 0

    def get_window_position(self, window_id: int) -> tuple[int, int]:
        if window_id == 0:
            return 0, 0
        try:
            win = self._get_window_obj(window_id)
            if not win:
                return 0, 0
            # Translate local coordinates (0, 0) to global root/screen coordinates
            coords = win.translate_coords(self.root, 0, 0)
            return coords.x, coords.y
        except Exception:
            return 0, 0

    def _ensure_xfixes(self):
        """Perform the handshake once and cache the result."""
        if self._checked_xfixes:
            return self.xfixes_supported

        try:
            # Negotiate version 5.0 (which is required for get_cursor_image)
            version = xfixes.query_version(self.disp, 5, 0)

            # Verify if the server actually gave us what we need
            if version.major_version >= 5:
                self.xfixes_supported = True
            else:
                print(
                    f"[WINDOW MANAGER] XFixes too old: {version.major_version}.{version.minor_version}, requires: ≥5.0."
                )
                self.xfixes_supported = False
        except Exception:
            self.xfixes_supported = False

        self._checked_xfixes = True
        return self.xfixes_supported

    def is_cursor_visible(
        self, last_state: bool, last_check_time: int
    ) -> tuple[bool, int]:
        if not self.disp:
            return last_state, last_check_time

        now = time.monotonic_ns()
        if now - last_check_time < CURSOR_CHECK_DELAY_NS:
            return last_state, last_check_time

        # Check if XFixes is supported before attempting to use it
        if not self._ensure_xfixes():
            return (
                last_state,
                last_check_time,
            )  # Fallback if xFixes extension is not available

        cursor = xfixes.get_cursor_image(self.disp, self.root)
        return cursor.width > 0 and cursor.height > 0, now

    def get_screen_dimensions(self) -> tuple[int, int]:
        if not self.disp:
            return 1920, 1080  # Safe fallback
        screen = self.disp.screen()
        return screen.width_in_pixels, screen.height_in_pixels

    def _find_window_titles(self) -> dict:
        if not self.disp:
            return {}
        results = {}
        for win in self._get_all_top_level_windows():
            try:
                # Check legacy WM_NAME first
                name = win.get_wm_name()
                if not name:
                    # Fallback to modern EWMH _NET_WM_NAME
                    net_name = win.get_full_property(self.NET_WM_NAME, 0)
                    if net_name:
                        name = net_name.value.decode("utf-8", errors="ignore")
                if name:
                    results[win.id] = name
            except Exception:
                continue
        return results

    def find_visible_windows(self) -> dict[int, dict]:
        if not self.disp:
            return {}
        results = {}
        for win in self._get_all_top_level_windows():
            try:
                attr = win.get_attributes()
                if attr.map_state != X.IsViewable:
                    continue

                name = win.get_wm_name()
                if not name:
                    net_name = win.get_full_property(self.NET_WM_NAME, 0)
                    if net_name:
                        name = net_name.value.decode("utf-8", errors="ignore")

                wm_class = win.get_wm_class()
                class_name = wm_class[1] if wm_class and len(wm_class) > 1 else ""

                if name or class_name:
                    results[win.id] = {"title": name or "", "class_name": class_name}
            except Exception:
                continue
        return results
