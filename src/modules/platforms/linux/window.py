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
            self.NET_CLIENT_LIST = self.disp.intern_atom("_NET_CLIENT_LIST")
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
        """Returns a flat list of client windows using EWMH _NET_CLIENT_LIST, falling back to query_tree."""
        if not self.disp:
            return []

        try:
            # Attempt modern EWMH client list first to avoid WM decoration frames
            prop = self.root.get_full_property(self.NET_CLIENT_LIST, X.AnyPropertyType)
            if prop and prop.value:
                windows = []
                for xid in prop.value:
                    try:
                        win = self._get_window_obj(xid)
                        # Verify window is still valid
                        if win:
                            win.get_attributes()
                            windows.append(win)
                    except error.BadWindow:
                        continue
                if windows:
                    return windows
        except Exception:
            pass

        # Fallback to query_tree if EWMH is unavailable
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
                return int(win_id.value[0])
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
            # Window.translate_coords(src, x, y) converts (x, y) from src's
            # space into *this* window's space. To get the window origin in
            # root (screen) space, the root must be the receiver and the
            # window the source: root.translate_coords(win, 0, 0). The reverse
            # call returns the negated position.
            coords = self.root.translate_coords(win, 0, 0)
            return coords.x, coords.y
        except Exception:
            return 0, 0

    def _ensure_xfixes(self):
        """Perform the handshake once and cache the result."""
        if self._checked_xfixes:
            return self.xfixes_supported

        try:
            version = xfixes.query_version(self.disp, 5, 0)
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

        if not self._ensure_xfixes():
            return last_state, last_check_time

        try:
            cursor = xfixes.get_cursor_image(self.disp, self.root)
        except Exception:
            return last_state, now

        if not cursor or cursor.width <= 0 or cursor.height <= 0:
            return False, now

        # Check alpha channel to handle engines rendering hidden cursors as transparent 1x1 textures
        has_visible_pixels = False
        if hasattr(cursor, "cursor_image") and cursor.cursor_image:
            # XFixes cursor image pixels are usually 32-bit ARGB values.
            # We check if any pixel has a non-zero alpha channel value (> 0).
            # Depending on python-xlib version, cursor_image might be a list/bytes of ints.
            pixels = cursor.cursor_image
            # Fast alpha check: step through bytes/ints looking for non-zero alpha (typically highest byte in 32-bit ARGB)
            try:
                for pixel in pixels:
                    # In ARGB32, alpha is the topmost byte ((pixel >> 24) & 0xFF)
                    if ((pixel >> 24) & 0xFF) > 0:
                        has_visible_pixels = True
                        break
            except TypeError:
                # Fallback if pixel iteration format differs across bindings
                has_visible_pixels = True
        else:
            has_visible_pixels = True

        return has_visible_pixels, now

    def get_screen_dimensions(self) -> tuple[int, int, int, int]:
        if not self.disp:
            return 0, 0, 1920, 1080

        screen = self.disp.screen()
        return 0, 0, screen.width_in_pixels, screen.height_in_pixels

    def _find_window_titles(self) -> dict:
        if not self.disp:
            return {}
        results = {}
        for win in self._get_all_top_level_windows():
            try:
                name = win.get_wm_name()
                if not name:
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
