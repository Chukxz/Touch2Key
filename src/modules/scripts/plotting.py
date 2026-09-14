from __future__ import annotations
from typing import TYPE_CHECKING

import os
import sys
import math
import datetime
from pathlib import Path
from PIL import Image

from modules.platforms import get_platform, get_specific_mt_key

get_platform().SystemConfig().set_dpi_awareness()

from modules.utils import (
    CIRCLE,
    RECTANGLE,
    DEF_DPI,
    IMAGES_FOLDER,
    MOUSE_WHEEL_CODE,
    SPRINT_DISTANCE_CODE,
    IDLE,
    SYSTEM,
    get_scancode_and_bridge_key_from_key,
    get_key_from_scancode,
    rotate_resolution,
    get_vibrant_random_color,
    get_dulled_hue_color,
    get_hue_modified_alpha_from_hsv,
)
from modules.database.repositories import (
    AppSettingsRepository,
    LayoutsRepository,
    LayoutZonesRepository,
)

if SYSTEM == "Windows":
    os.environ["QT_LOGGING_RULES"] = "qt.qpa.window=false"

import matplotlib

matplotlib.use("qtagg")

from matplotlib.figure import Figure
from matplotlib.patches import Circle, Rectangle
from matplotlib.text import Text

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QMainWindow, QVBoxLayout, QWidget
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.backends.backend_qt import NavigationToolbar2QT as NavigationToolbar

COLLECTING = "COLLECTING"
WAITING_FOR_KEY = "WAITING_FOR_KEY"
NAMING = "NAMING"
DELETING = "DELETING"
MARKING = "MARKING"
CONFIRM_DELETE_ALL = "CONFIRM_DELETE_ALL"
CONFIRM_EXIT = "CONFIRM_EXIT"
HELP_STR = "F1 (Help)"
DEF_STR = (
    "MODE: IDLE | F12 (Save to DB) | Esc (Exit) | F6 (Circle) | F7 (RECTANGLE) | F8 (Cancel)\n"
    "    Del (Delete) | F2 (Delete All) | F9 (List Shapes) | F4 (Toggle Overlays)\n"
    "    [ (Sprint Threshold) | ] (Mouse Wheel) | Space (Toggle Move Camera)\n"
    "    Arrows: Nudge | Shift+Arrows: Fast Nudge | Double Click: Change Artist"
)

INDICATED_EDGE_COLOR = (0.85, 0.88, 0.92)
ACTIVE_EDGE_COLOR = (0.7, 0.7, 0.7, 0.8)
DEFAULT_EDGE_COLOR = (0.3, 0.3, 0.3, 0.8)
DEFAULT_MOUSE_WHEEL_FACE_COLOR = (0.0, 0.8, 0.8, 0.4)
DEFAULT_SPRINT_DISTANCE_FACE_COLOR = (1.0, 0.2, 0.2, 0.5)
DEFAULT_FACE_COLOR_ALPHA = 0.4
DEFAULT_SMALL_LINE_WIDTH = 1.5
DEFAULT_MEDIUM_LINE_WIDTH = 2
DEFAULT_LARGE_LINE_WIDTH = 3

if TYPE_CHECKING:
    from PySide6.QtCore import QCoreApplication


class _CursorManager:
    def __init__(self, canvas: FigureCanvas):
        self.canvas = canvas
        self.state_map = {
            "IDLE": Qt.CursorShape.ArrowCursor,
            "COLLECTING": Qt.CursorShape.CrossCursor,
            "WAITING_FOR_KEY": Qt.CursorShape.PointingHandCursor,
            "NAMING": Qt.CursorShape.IBeamCursor,
            "DELETING": Qt.CursorShape.ForbiddenCursor,
            "MARKING": Qt.CursorShape.PointingHandCursor,
            "CONFIRM_DELETE_ALL": Qt.CursorShape.WaitCursor,
            "CONFIRM_EXIT": Qt.CursorShape.WaitCursor,
        }

    def set_state_cursor(self, state):
        shape = self.state_map.get(state, Qt.CursorShape.ArrowCursor)
        self.canvas.setCursor(shape)

    def set_custom_cursor(self, shape):
        self.canvas.setCursor(shape)


class _Draggable:
    def __init__(self, entry_id: int, is_shape: bool, plotter_ref: Plotter):
        self.entry_id = entry_id
        self.plotter = plotter_ref
        self.cursor_manager = plotter_ref.cursor_manager
        self.min_move_distance = 3
        self.is_shape = is_shape

        if is_shape:
            self.artist_id = "shape_" + str(entry_id)
            shape = self.plotter.shapes_artists[entry_id]
            self.default_face_color = shape.get_facecolor()
        else:
            self.artist_id = "label_" + str(entry_id)
            label = self.plotter.labels_artists[entry_id]
            label_bbox = label.get_bbox_patch()
            if label_bbox:
                self.default_face_color = label_bbox.get_facecolor()

    def populate_draggables_list(self):
        self.plotter.draggables_ids.append(self.artist_id)

    def select_current_draggable_id(self):
        if not self.plotter.draggables_ids:
            self.plotter.iter_count = 0
            return None

        if self.plotter.last_artist_id is None:
            self.plotter.iter_count = 0
            return self.plotter.draggables_ids[0]

        if self.plotter.last_artist_id in self.plotter.draggables_ids:
            if self.plotter.iter_count >= 2:
                total = len(self.plotter.draggables_ids)
                i = self.plotter.draggables_ids.index(self.plotter.last_artist_id)
                n = (i + 1) % total
                self.plotter.iter_count = 0
                return self.plotter.draggables_ids[n]
            else:
                return self.plotter.last_artist_id
        else:
            self.plotter.iter_count = 0
            return self.plotter.draggables_ids[0]

    def indicate_current_draggable_id(self):
        curr_id = self.plotter.current_draggable_id
        if curr_id is None:
            return

        if curr_id.startswith("label_"):
            draggable_artist = self.plotter.label_drag_managers.get(self.entry_id)
            if draggable_artist and draggable_artist.artist_id == curr_id:
                label_bbox = draggable_artist.label_artist.get_bbox_patch()
                if label_bbox:
                    label_bbox.set_edgecolor(INDICATED_EDGE_COLOR)
                    label_bbox.set_linewidth(DEFAULT_MEDIUM_LINE_WIDTH)
                move_camera_info = (
                    "Move Camera Enabled"
                    if self.plotter.shapes[self.entry_id]["move_camera"]
                    else "Move Camera Disabled"
                )
                self.plotter.update_title(
                    f"Current Artist: {curr_id} (ID: {self.entry_id}) | Click to Drag | Arrows to Nudge | {move_camera_info} | {HELP_STR}",
                    True,
                )
            self.plotter.current_draggable = draggable_artist

        elif curr_id.startswith("shape_"):
            draggable_artist = self.plotter.shape_drag_managers.get(self.entry_id)
            if draggable_artist and draggable_artist.artist_id == curr_id:
                draggable_artist.shape_artist.set_edgecolor(INDICATED_EDGE_COLOR)
                draggable_artist.shape_artist.set_linewidth(DEFAULT_LARGE_LINE_WIDTH)
                move_camera_info = (
                    "Move Camera Enabled"
                    if self.plotter.shapes[self.entry_id]["move_camera"]
                    else "Move Camera Disabled"
                )
                self.plotter.update_title(
                    f"Current Artist: {curr_id} (ID: {self.entry_id}) | Click to Drag or Resize | Arrows to Nudge | {move_camera_info} | {HELP_STR}",
                    True,
                )
            self.plotter.current_draggable = draggable_artist

        self.cursor_manager.set_custom_cursor(Qt.CursorShape.SizeAllCursor)

    def clean_up_current_draggable_id(self):
        self.indicate_current_draggable_id()
        if self.plotter.current_move_distance <= self.min_move_distance:
            self.plotter.iter_count += 1
        else:
            self.plotter.iter_count = 0

        self.plotter.drawn = False
        self.plotter.last_artist_id = self.plotter.current_draggable_id
        self.plotter.current_draggable_id = None
        self.plotter.current_move_distance = 0.0
        self.plotter.draggables_ids = []

    def dull_face_color(self):
        if self.is_shape:
            shape = self.plotter.shapes_artists[self.entry_id]
            dulled_face_color = get_dulled_hue_color(
                *get_hue_modified_alpha_from_hsv(self.default_face_color)
            )
            shape.set_facecolor(dulled_face_color)
        else:
            label = self.plotter.labels_artists[self.entry_id]
            label_bbox = label.get_bbox_patch()
            if label_bbox:
                dulled_face_color = get_dulled_hue_color(
                    *get_hue_modified_alpha_from_hsv(self.default_face_color)
                )
                label_bbox.set_facecolor(dulled_face_color)

    def restore_face_color(self):
        if self.is_shape:
            shape = self.plotter.shapes_artists[self.entry_id]
            shape.set_facecolor(self.default_face_color)
        else:
            label = self.plotter.labels_artists[self.entry_id]
            label_bbox = label.get_bbox_patch()
            if label_bbox:
                label_bbox.set_facecolor(self.default_face_color)


class _DraggableLabel(_Draggable):
    def __init__(self, entry_id: int, plotter_ref: Plotter):
        super().__init__(entry_id, False, plotter_ref)
        self.label_artist = self.plotter.labels_artists[entry_id]
        self.shape_artist = self.plotter.shapes_artists[entry_id]

        self.canvas = self.plotter.canvas

        self.press = None
        self.drag_bg = None

        if self.canvas.supports_blit:
            self.cids = [
                self.canvas.mpl_connect("button_press_event", self.on_press),
                self.canvas.mpl_connect("motion_notify_event", self.on_motion),
                self.canvas.mpl_connect("button_release_event", self.on_release),
            ]

    def on_press(self, event):
        self.plotter.ignore_current_draggable_id_n += 1
        self.on_press_helper(event)
        self.plotter.fire_on_motion = True

    def on_press_helper(self, event):
        self.plotter.fire_on_motion = False
        self.press = None
        self.drag_bg = None

        if event.inaxes != self.shape_artist.axes:
            self.plotter.ignore_current_draggable_id_n -= 1
            return

        contains, _ = self.label_artist.contains(event)
        if not contains:
            self.plotter.ignore_current_draggable_id_n -= 1
            return

        x, y = self.label_artist.get_position()
        self.press = x, y, event.xdata, event.ydata, event.x, event.y

        label_bbox = self.label_artist.get_bbox_patch()
        if label_bbox:
            label_bbox.set_edgecolor("black")

        if self.label_artist.get_visible():
            self.shape_artist.set_visible(True)
            self.populate_draggables_list()

        self.canvas.draw_idle()

    def on_motion(self, event):
        if not self.plotter.fire_on_motion:
            return
        if self.label_artist.axes == None:
            return
        if self.press is None or event.inaxes != self.label_artist.axes:
            return

        if self.plotter.current_draggable_id is None:
            self.plotter.current_draggable_id = self.select_current_draggable_id()
            self.indicate_current_draggable_id()

        if self.plotter.current_draggable_id != self.artist_id:
            return

        self.plotter.ignore_current_draggable_id_n = 1

        if not self.plotter.drawn:
            label_bbox = self.label_artist.get_bbox_patch()
            if label_bbox:
                label_bbox.set_edgecolor(ACTIVE_EDGE_COLOR)
                label_bbox.set_linewidth(DEFAULT_LARGE_LINE_WIDTH)
            self.label_artist.set_visible(False)

            self.shape_artist.set_edgecolor(ACTIVE_EDGE_COLOR)
            self.shape_artist.set_linewidth(DEFAULT_LARGE_LINE_WIDTH)

            self.canvas.draw()
            self.drag_bg = self.canvas.copy_from_bbox(self.label_artist.axes.bbox)
            self.label_artist.set_visible(True)
            self.plotter.drawn = True

        _, _, xdata_press, ydata_press, xpx_press, ypx_press = self.press
        dx = event.xdata - xdata_press
        dy = event.ydata - ydata_press
        dx_press = event.x - xpx_press
        dy_press = event.y - ypx_press
        dist_px = ((dx_press**2) + (dy_press**2)) ** 0.5
        self.plotter.current_move_distance = dist_px

        self.canvas.restore_region(self.drag_bg)
        self.move_label(dx, dy)
        self.label_artist.axes.draw_artist(self.label_artist)
        self.canvas.blit(self.label_artist.axes.bbox)

    def move_label(self, dx, dy):
        if not self.press:
            return
        x0, y0, _, _, _, _ = self.press
        self.label_artist.set_position((x0 + dx, y0 + dy))

    def move(self, dx, dy):
        if not self.press:
            return
        _, _, xdata_press, ydata_press, xpx_press, ypx_press = self.press
        x, y = self.label_artist.get_position()
        self.press = x, y, xdata_press, ydata_press, xpx_press, ypx_press
        self.move_label(dx, dy)
        self.canvas.draw()
        self.plotter.drawn = False

    def on_release(self, event):
        self.partial_release()
        if self.plotter.current_draggable_id is None and self.plotter.draggables_ids:
            self.plotter.current_draggable_id = self.select_current_draggable_id()
            self.indicate_current_draggable_id()

        if self.artist_id == self.plotter.current_draggable_id:
            if self.plotter.drawn:
                self.shape_artist.set_edgecolor(DEFAULT_EDGE_COLOR)
                self.shape_artist.set_linewidth(DEFAULT_MEDIUM_LINE_WIDTH)

            self.clean_up_current_draggable_id()
            self.label_artist.remove()
            self.plotter.ax.add_artist(self.label_artist)

        self.canvas.draw_idle()

    def partial_release(self):
        if self.plotter.ignore_current_draggable_id_n <= 0:
            state_str = "VISIBLE" if self.plotter.show_overlays else "HIDDEN"
            self.plotter.update_title(f"OVERLAYS: {state_str} | {DEF_STR}", True)

        label_bbox = self.label_artist.get_bbox_patch()
        if label_bbox:
            label_bbox.set_edgecolor("black")
            label_bbox.set_linewidth(DEFAULT_SMALL_LINE_WIDTH)

    def disconnect(self):
        for cid in self.cids:
            self.canvas.mpl_disconnect(cid)


class _DraggableShape(_Draggable):
    def __init__(self, entry_id: int, plotter_ref: Plotter, shape_type: str):
        super().__init__(entry_id, True, plotter_ref)
        self.shape_type = shape_type
        self.label_artist = self.plotter.labels_artists[entry_id]
        self.shape_artist = self.plotter.shapes_artists[entry_id]

        self.canvas = self.plotter.canvas

        self.press = None
        self.drag_bg = None
        self.shape_mode = None

        self.radial_tolerance = 5
        self.edge_tolerance = 5
        self.vertex_tolerance = 10
        self.min_rect_dist = 50
        self.min_circ_dist = 30
        self.spec_max_ratio = 0.3

        if self.shape_type == CIRCLE:
            r = self.shape_artist.get_radius()
            new_r = max(r, self.min_circ_dist)
            self.shape_artist.set_radius(new_r)
            self.plotter.shapes[self.entry_id]["r"] = new_r
        elif self.shape_type == RECTANGLE:
            x, y = self.shape_artist.get_xy()
            w = self.shape_artist.get_width()
            h = self.shape_artist.get_height()
            self.update_rect_safe(x, y, w, h)
        else:
            return

        if self.canvas.supports_blit:
            self.cids = [
                self.canvas.mpl_connect("button_press_event", self.on_press),
                self.canvas.mpl_connect("motion_notify_event", self.on_motion),
                self.canvas.mpl_connect("button_release_event", self.on_release),
            ]

    def on_press(self, event):
        self.plotter.ignore_current_draggable_id_n += 1
        self.on_press_helper(event)
        self.plotter.fire_on_motion = True

    def on_press_helper(self, event):
        self.plotter.fire_on_motion = False
        self.press = None
        self.drag_bg = None
        self.shape_mode = None

        if event.inaxes != self.shape_artist.axes:
            self.plotter.ignore_current_draggable_id_n -= 1
            return False

        contains, _ = self.shape_artist.contains(event)
        if not contains:
            self.plotter.ignore_current_draggable_id_n -= 1
            return False

        if self.shape_type == CIRCLE:
            cx, cy = self.shape_artist.get_center()
            self.shape_mode = self.get_circumference(event, cx, cy)
            self.press = cx, cy, event.xdata, event.ydata, event.x, event.y
        elif self.shape_type == RECTANGLE:
            x, y = self.shape_artist.get_xy()
            self.shape_mode = self.get_corner_under_mouse(event)
            if self.shape_mode is None:
                self.shape_mode = self.get_edge_under_mouse(event)
            self.press = x, y, event.xdata, event.ydata, event.x, event.y

        self.shape_artist.set_edgecolor(DEFAULT_EDGE_COLOR)

        if self.shape_artist.get_visible():
            self.label_artist.set_visible(True)
            self.populate_draggables_list()

        self.canvas.draw_idle()

    def on_motion(self, event):
        if not self.plotter.fire_on_motion:
            return
        if self.shape_artist.axes == None:
            return
        if self.press is None or event.inaxes != self.shape_artist.axes:
            return

        if self.plotter.current_draggable_id is None:
            self.plotter.current_draggable_id = self.select_current_draggable_id()
            self.indicate_current_draggable_id()

        if self.plotter.current_draggable_id != self.artist_id:
            return

        self.plotter.ignore_current_draggable_id_n = 1

        if not self.plotter.drawn:
            self.shape_artist.set_edgecolor(ACTIVE_EDGE_COLOR)
            self.shape_artist.set_linewidth(DEFAULT_LARGE_LINE_WIDTH)
            self.shape_artist.set_visible(False)

            label_bbox = self.label_artist.get_bbox_patch()
            if label_bbox:
                label_bbox.set_edgecolor(ACTIVE_EDGE_COLOR)
                label_bbox.set_linewidth(DEFAULT_LARGE_LINE_WIDTH)

            self.canvas.draw()
            self.drag_bg = self.canvas.copy_from_bbox(self.shape_artist.axes.bbox)
            self.shape_artist.set_visible(True)
            self.plotter.drawn = True

        _, _, _, _, xpx_press, ypx_press = self.press
        dx_press = event.x - xpx_press
        dy_press = event.y - ypx_press
        dist_px = ((dx_press**2) + (dy_press**2)) ** 0.5
        self.plotter.current_move_distance = dist_px

        self.canvas.restore_region(self.drag_bg)
        if self.shape_type == CIRCLE:
            self.circle_transform(event)
        elif self.shape_type == RECTANGLE:
            self.rect_transform(event)
        else:
            return

        self.shape_artist.axes.draw_artist(self.shape_artist)
        self.canvas.blit(self.shape_artist.axes.bbox)

    def circle_transform(self, event):
        if self.press is None:
            return
        xdata, ydata = event.xdata, event.ydata
        old_cx, old_cy = self.shape_artist.get_center()
        old_r = self.shape_artist.get_radius()
        new_cx, new_cy = old_cx, old_cy

        if self.shape_mode == "resize":
            self.update_radius(xdata, ydata)
        elif self.shape_mode == "drag":
            _, _, xdata_press, ydata_press, _, _ = self.press
            dx = xdata - xdata_press
            dy = ydata - ydata_press
            new_cx, new_cy = self.move_circle(dx, dy)

        self.circle_transform_helper(old_cx, old_cy, old_r, new_cx, new_cy)

    def circle_transform_helper(self, old_cx, old_cy, old_r, new_cx, new_cy):
        current_shape = self.plotter.shapes[self.entry_id]

        if (
            self.plotter.saved_mouse_wheel
            and current_shape["bridge_key"] == MOUSE_WHEEL_CODE
        ):
            self.plotter.mouse_wheel_cx = new_cx
            self.plotter.mouse_wheel_cy = new_cy
            self.plotter.mouse_wheel_radius = current_shape["r"]

            if (
                self.plotter.saved_sprint_distance
                and self.plotter.sprint_artist_id is not None
            ):
                sprint_artist = self.plotter.shape_drag_managers[
                    self.plotter.sprint_artist_id
                ]
                sprint_shape = self.plotter.shapes[self.plotter.sprint_artist_id]
                cx, cy = sprint_artist.shape_artist.get_center()
                actual_dist = self.plotter.euclidean_distance(cx, cy, new_cx, new_cy)

                if actual_dist <= self.plotter.mouse_wheel_radius:
                    r = self.plotter.mouse_wheel_radius
                    screen_rect = ((0, 0), (self.plotter.width, self.plotter.height))
                    sp_x, sp_y = self.plotter.constrain_point_to_rect_radial(
                        new_cx, new_cy - r - 1, new_cx, new_cy, screen_rect
                    )
                    sp_x, sp_y = int(round(sp_x)), int(round(sp_y))
                    sprint_artist.shape_artist.set_center((sp_x, sp_y))
                    sprint_shape["cx"] = sp_x
                    sprint_shape["cy"] = sp_y
                    self.plotter.sprint_distance = self.plotter.euclidean_distance(
                        sp_x, sp_y, new_cx, new_cy
                    )
                else:
                    self.plotter.sprint_distance = actual_dist

        if (
            self.plotter.saved_sprint_distance
            and current_shape["bridge_key"] == SPRINT_DISTANCE_CODE
        ):
            actual_dist = self.plotter.euclidean_distance(
                new_cx, new_cy, self.plotter.mouse_wheel_cx, self.plotter.mouse_wheel_cy
            )
            if actual_dist <= self.plotter.mouse_wheel_radius:
                self.shape_artist.set_center((old_cx, old_cy))
                self.shape_artist.set_radius(old_r)
                current_shape["cx"] = old_cx
                current_shape["cy"] = old_cy
                current_shape["r"] = old_r
            else:
                self.plotter.sprint_distance = actual_dist

    def rect_transform(self, event):
        if self.press is None:
            return
        xdata, ydata = event.xdata, event.ydata
        if self.update_corner(self.shape_mode, xdata, ydata):
            return
        if self.update_edge(self.shape_mode, xdata, ydata):
            return
        if self.shape_mode == "drag":
            _, _, xdata_press, ydata_press, _, _ = self.press
            dx = xdata - xdata_press
            dy = ydata - ydata_press
            self.move_rect(dx, dy)

    def get_circumference(self, event, cx, cy):
        r = self.shape_artist.get_radius()
        cx_px, cy_px = self.shape_artist.axes.transData.transform((cx, cy))
        rim_x_px, _ = self.shape_artist.axes.transData.transform((cx + r, cy))
        r_px = abs(rim_x_px - cx_px)
        dist_px = ((event.x - cx_px) ** 2 + (event.y - cy_px) ** 2) ** 0.5
        diff_px = abs(dist_px - r_px)
        if diff_px <= self.radial_tolerance:
            return "resize"
        if dist_px <= r_px:
            return "drag"
        return None

    def update_radius(self, xdata, ydata):
        cx, cy = self.shape_artist.get_center()
        new_r = int(round(((xdata - cx) ** 2 + (ydata - cy) ** 2) ** 0.5))
        current_shape = self.plotter.shapes[self.entry_id]
        new_sp_r = None

        if (
            self.plotter.saved_mouse_wheel
            and current_shape["bridge_key"] == MOUSE_WHEEL_CODE
        ):
            new_r = min(
                new_r,
                int(
                    round(
                        self.spec_max_ratio
                        * ((self.plotter.width + self.plotter.height) / 2)
                    )
                ),
            )
            if (
                self.plotter.saved_sprint_distance
                and self.plotter.sprint_artist_id is not None
            ):
                sprint_artist = self.plotter.shape_drag_managers[
                    self.plotter.sprint_artist_id
                ]
                sp_r = sprint_artist.shape_artist.get_radius()
                if new_r < sp_r:
                    new_sp_r = new_r

        if (
            self.plotter.saved_sprint_distance
            and current_shape["bridge_key"] == SPRINT_DISTANCE_CODE
        ):
            new_r = min(new_r, self.plotter.mouse_wheel_radius)

        if new_r >= self.min_circ_dist:
            self.shape_artist.set_radius(new_r)
            current_shape["r"] = new_r
            if new_sp_r is not None and self.plotter.sprint_artist_id is not None:
                sprint_artist = self.plotter.shape_drag_managers[
                    self.plotter.sprint_artist_id
                ]
                sprint_shape = self.plotter.shapes[self.plotter.sprint_artist_id]
                sprint_artist.shape_artist.set_radius(new_sp_r)
                sprint_shape["r"] = new_sp_r

    def get_corner_under_mouse(self, event):
        x, y = self.shape_artist.get_xy()
        w, h = self.shape_artist.get_width(), self.shape_artist.get_height()
        corners = {
            "top_left": (x, y),
            "top_right": (x + w, y),
            "bottom_left": (x, y + h),
            "bottom_right": (x + w, y + h),
        }
        for name, (cx, cy) in corners.items():
            cx_px, cy_px = self.shape_artist.axes.transData.transform((cx, cy))
            dist_px = ((event.x - cx_px) ** 2 + (event.y - cy_px) ** 2) ** 0.5
            if dist_px <= self.vertex_tolerance:
                return name
        return None

    def get_edge_under_mouse(self, event):
        mx, my = event.x, event.y
        bbox = self.shape_artist.get_window_extent()
        is_within_horizontal = bbox.x0 <= mx <= bbox.x1
        is_within_vertical = bbox.y0 <= my <= bbox.y1

        if abs(mx - bbox.x0) <= self.edge_tolerance and is_within_vertical:
            return "left"
        if abs(mx - bbox.x1) <= self.edge_tolerance and is_within_vertical:
            return "right"
        if abs(my - bbox.y1) <= self.edge_tolerance and is_within_horizontal:
            return "top"
        if abs(my - bbox.y0) <= self.edge_tolerance and is_within_horizontal:
            return "bottom"
        if is_within_horizontal and is_within_vertical:
            return "drag"
        return None

    def update_corner(self, corner, xdata, ydata):
        if corner is None:
            return False
        xdata, ydata = int(round(xdata)), int(round(ydata))
        x, y = self.shape_artist.get_xy()
        w = self.shape_artist.get_width()
        h = self.shape_artist.get_height()

        if corner == "bottom_right":
            self.update_rect_safe(x, y, xdata - x, ydata - y)
            return True
        if corner == "top_left":
            self.update_rect_safe(xdata, ydata, (x + w) - xdata, (y + h) - ydata)
            return True
        if corner == "top_right":
            self.update_rect_safe(x, ydata, xdata - x, (y + h) - ydata)
            return True
        if corner == "bottom_left":
            self.update_rect_safe(xdata, y, (x + w) - xdata, ydata - y)
            return True
        return False

    def update_edge(self, edge, xdata, ydata):
        if edge is None:
            return False
        xdata, ydata = int(round(xdata)), int(round(ydata))
        x, y = self.shape_artist.get_xy()
        w = self.shape_artist.get_width()
        h = self.shape_artist.get_height()

        if edge == "right":
            self.update_rect_safe(x, y, xdata - x, h)
            return True
        if edge == "left":
            self.update_rect_safe(xdata, y, (x + w) - xdata, h)
            return True
        if edge == "bottom":
            self.update_rect_safe(x, y, w, ydata - y)
            return True
        if edge == "top":
            self.update_rect_safe(x, ydata, w, (y + h) - ydata)
            return True
        return False

    def update_rect_safe(self, x, y, w, h):
        x, y, w, h = int(round(x)), int(round(y)), int(round(w)), int(round(h))
        if w < 0 or h < 0:
            return

        if w >= self.min_rect_dist:
            self.shape_artist.set_x(x)
            self.shape_artist.set_width(w)
        else:
            old_x = int(round(self.shape_artist.get_x()))
            x = old_x
            old_w = int(round(self.shape_artist.get_width()))
            w = max(old_w, self.min_rect_dist)

        if h >= self.min_rect_dist:
            self.shape_artist.set_y(y)
            self.shape_artist.set_height(h)
        else:
            old_y = int(round(self.shape_artist.get_y()))
            y = old_y
            old_h = int(round(self.shape_artist.get_height()))
            h = max(old_h, self.min_rect_dist)

        raw_bb = (x, y), (x + w, y + h)
        cx, cy, _, bb = self.plotter.calculate_raw_rect(raw_bb)
        self.plotter.shapes[self.entry_id]["cx"] = cx
        self.plotter.shapes[self.entry_id]["cy"] = cy
        self.plotter.shapes[self.entry_id]["bb"] = bb

    def move_circle(self, dx, dy):
        if self.press is not None:
            x0, y0, _, _, _, _ = self.press
            new_cx = int(round(x0 + dx))
            new_cy = int(round(y0 + dy))
            self.shape_artist.set_center((new_cx, new_cy))
            self.plotter.shapes[self.entry_id]["cx"] = new_cx
            self.plotter.shapes[self.entry_id]["cy"] = new_cy
            return new_cx, new_cy
        return dx, dy

    def move_rect(self, dx, dy):
        if self.press is not None:
            x0, y0, _, _, _, _ = self.press
            new_x = int(round(x0 + dx))
            new_y = int(round(y0 + dy))
            w = self.shape_artist.get_width()
            h = self.shape_artist.get_height()
            self.update_rect_safe(new_x, new_y, w, h)

    def move(self, dx, dy):
        if not self.press:
            return
        if self.shape_type == CIRCLE:
            _, _, xdata_press, ydata_press, xpx_press, ypx_press = self.press
            cx, cy = self.shape_artist.get_center()
            self.press = cx, cy, xdata_press, ydata_press, xpx_press, ypx_press
            old_cx, old_cy = self.shape_artist.get_center()
            old_r = self.shape_artist.get_radius()
            new_cx, new_cy = self.move_circle(dx, dy)
            self.circle_transform_helper(old_cx, old_cy, old_r, new_cx, new_cy)
        elif self.shape_type == RECTANGLE:
            _, _, xdata_press, ydata_press, xpx_press, ypx_press = self.press
            x, y = self.shape_artist.get_xy()
            self.press = x, y, xdata_press, ydata_press, xpx_press, ypx_press
            self.move_rect(dx, dy)

        self.canvas.draw()
        self.plotter.drawn = False

    def on_release(self, event):
        self.partial_release()
        if self.plotter.current_draggable_id is None and self.plotter.draggables_ids:
            self.plotter.current_draggable_id = self.select_current_draggable_id()
            self.indicate_current_draggable_id()

        if self.artist_id == self.plotter.current_draggable_id:
            if self.plotter.drawn:
                label_bbox = self.label_artist.get_bbox_patch()
                if label_bbox:
                    label_bbox.set_edgecolor("black")
                    label_bbox.set_linewidth(DEFAULT_SMALL_LINE_WIDTH)

            self.clean_up_current_draggable_id()
            self.shape_artist.remove()
            self.plotter.ax.add_patch(self.shape_artist)

        self.canvas.draw_idle()

    def partial_release(self):
        if self.plotter.ignore_current_draggable_id_n <= 0:
            state_str = "VISIBLE" if self.plotter.show_overlays else "HIDDEN"
            self.plotter.update_title(f"OVERLAYS: {state_str} | {DEF_STR}", True)

        self.shape_artist.set_edgecolor(DEFAULT_EDGE_COLOR)
        self.shape_artist.set_linewidth(DEFAULT_MEDIUM_LINE_WIDTH)

    def disconnect(self):
        for cid in self.cids:
            self.canvas.mpl_disconnect(cid)


class Plotter(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Touch2Key - HUD Layout Editor")

        self.settings_repo = AppSettingsRepository()
        self.layouts_repo = LayoutsRepository()
        self.zones_repo = LayoutZonesRepository()

        current_settings = self.settings_repo.get()
        if current_settings.active_layout_id is None:
            raise RuntimeError(
                "[PLOTTER] - Error: No active layout set in the database. Open Layout Manager first."
            )

        self.active_layout = self.layouts_repo.get(current_settings.active_layout_id)
        if not self.active_layout:
            raise RuntimeError(
                f"[PLOTTER] - Error: Active Layout ID {current_settings.active_layout_id} not found."
            )

        if not self.active_layout.image_path:
            raise RuntimeError(
                f"[PLOTTER] - Error: Layout '{self.active_layout.name}' has no assigned HUD image."
            )

        img_path = Path(self.active_layout.image_path)
        if not img_path.is_absolute():
            img_path = Path(IMAGES_FOLDER) / img_path

        if not img_path.exists():
            raise RuntimeError(
                f"[PLOTTER] - Error: Image file '{img_path.as_posix()}' does not exist on disk."
            )

        self.image_path = img_path
        img = self.load_image()
        if img is None:
            raise RuntimeError("[PLOTTER] - Error: Could not load image.")

        # Create the Figure and Canvas
        self.fig = Figure()
        self.canvas = FigureCanvas(self.fig)
        self.ax = self.fig.add_subplot(111)

        # Disable Matplotlib default keybindings on the canvas
        for key in list(self.canvas.callbacks.callbacks.keys()):
            if "key_press_event" in key:
                self.canvas.callbacks.callbacks[key].clear()

        # Set Up Qt UI Layout
        central_widget = QWidget()
        layout = QVBoxLayout(central_widget)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.canvas)
        self.setCentralWidget(central_widget)

        # Initialize Managers and Events
        self.cursor_manager = _CursorManager(self.canvas)
        self.points = []
        self.point_artists = []
        self.mode = None
        self.state = IDLE
        self.input_buffer = ""
        self.shapes_artists: dict[int, Circle | Rectangle] = {}
        self.labels_artists: dict[int, Text] = {}
        self.label_drag_managers: dict[int, _DraggableLabel] = {}
        self.shape_drag_managers: dict[int, _DraggableShape] = {}

        self.init_params_helper()
        self.update_image_params(img)
        self.ax.imshow(img)

        state_str = "VISIBLE" if self.show_overlays else "HIDDEN"
        self.update_title(f"OVERLAYS: {state_str} | {DEF_STR}")

        self.init_crosshairs()
        self.bg_cache = None

        # Connect Matplotlib Canvas events
        self.canvas.mpl_connect("motion_notify_event", self.on_mouse_move)
        self.canvas.mpl_connect("key_press_event", self.on_key_press)
        self.canvas.mpl_connect("button_press_event", self.on_click)
        self.canvas.mpl_connect("resize_event", self.on_resize)

        self.load_active_layout_zones()

        self.fig.subplots_adjust(left=0, right=1, top=1, bottom=0)
        self.showMaximized()
        self.canvas.setFocus()

    def load_image(self):
        try:
            img = Image.open(self.image_path)
        except Exception as e:
            print(f"Error loading image: {e}")
            return None
        print(f"[PLOTTER] - HUD Image: {self.image_path.as_posix()} loaded.")
        return img

    def update_image_params(self, img):
        self.width, self.height = img.size
        try:
            parts = self.image_path.stem.split("_")
            rotation_part = parts[-1]
            if rotation_part.startswith("r"):
                rot = int(rotation_part[1:])
                self.width, self.height = rotate_resolution(
                    self.width, self.height, rot
                )
        except Exception:
            pass
        self.dpi = int(round(img.info.get("dpi", DEF_DPI)[0]))

    def init_crosshairs(self):
        self.crosshair_h_bg = self.ax.axhline(
            0,
            color="black",
            linewidth=1.5,
            alpha=0.8,
            visible=False,
            zorder=10,
            animated=True,
        )
        self.crosshair_v_bg = self.ax.axvline(
            0,
            color="black",
            linewidth=1.5,
            alpha=0.8,
            visible=False,
            zorder=10,
            animated=True,
        )
        self.crosshair_h_fg = self.ax.axhline(
            0,
            color="white",
            linewidth=0.6,
            alpha=1.0,
            visible=False,
            zorder=11,
            animated=True,
        )
        self.crosshair_v_fg = self.ax.axvline(
            0,
            color="white",
            linewidth=0.6,
            alpha=1.0,
            visible=False,
            zorder=11,
            animated=True,
        )

    def init_params_helper(self):
        self.input_buffer = ""
        self.buffer_default = True
        self.shapes = {}
        self.count = 0
        self.artists_points = 0
        self.saved_mouse_wheel = False
        self.saved_sprint_distance = False
        self.sprint_artist_id: int | None = None
        self.mouse_wheel_radius = 0.0
        self.mouse_wheel_cx = 0.0
        self.mouse_wheel_cy = 0.0
        self.sprint_distance = 0.0
        self.show_overlays = True
        self.width = 0
        self.height = 0
        self.dpi = 0

        for uid in list(self.shapes_artists.keys()):
            self.shapes_artists[uid].remove()
        self.shapes_artists = {}
        for uid in list(self.labels_artists.keys()):
            self.labels_artists[uid].remove()
        self.labels_artists = {}
        for uid in list(self.label_drag_managers.keys()):
            self.label_drag_managers[uid].disconnect()
        self.label_drag_managers = {}
        for uid in list(self.shape_drag_managers.keys()):
            self.shape_drag_managers[uid].disconnect()
        self.shape_drag_managers = {}

        self.last_artist_id: str | None = None
        self.ignore_current_draggable_id_n = 0
        self.current_draggable_id = None
        self.current_draggable: _DraggableLabel | _DraggableShape | None = None
        self.draggables_ids = []
        self.drawn = False
        self.current_move_distance = 0.0
        self.iter_count = 0
        self.fire_on_motion = False

    def update_title(self, text, idle_override=False):
        self.ax.set_title(text)
        self.cursor_manager.set_state_cursor(self.state)
        if idle_override:
            self.fig.canvas.draw_idle()
        else:
            self.fig.canvas.draw()

    def clear_visuals(self):
        for artist in self.point_artists:
            artist.remove()
        self.point_artists = []
        self.fig.canvas.draw()

    def reset_state(self):
        self.clear_visuals()
        self.state = IDLE
        self.mode = None
        self.points = []
        self.input_buffer = ""
        self.buffer_default = True
        state_str = "VISIBLE" if self.show_overlays else "HIDDEN"
        self.update_title(f"OVERLAYS: {state_str} | {DEF_STR}")
        self.bg_cache = self.canvas.copy_from_bbox(self.ax.bbox)

    def start_mode(self, mode, num_points):
        self.reset_state()
        self.mode = mode
        self.artists_points = num_points
        self.state = COLLECTING
        self.update_title(
            f"MODE: {mode}. Click {num_points} points on the image (F8 to Cancel)."
        )

    def load_active_layout_zones(self):
        zones = self.zones_repo.list_for_layout(self.active_layout.id)
        w, h, dpi = self.width, self.height, self.dpi
        self.init_params_helper()
        self.width, self.height, self.dpi = w, h, dpi
        self.reset_state()

        scale_x = self.width / (self.active_layout.width or self.width)
        scale_y = self.height / (self.active_layout.height or self.height)

        for zone in zones:
            key_name = get_key_from_scancode(zone.scancode)
            _, bridge_key = get_scancode_and_bridge_key_from_key(key_name)
            self.mode = zone.zone_type
            cx = int(round((zone.cx or 0.0) * scale_x))
            cy = int(round((zone.cy or 0.0) * scale_y))

            r = None
            bb = None
            if zone.zone_type == CIRCLE:
                scale_r = (scale_x + scale_y) / 2
                r = int(round((zone.r or 0.0) * scale_r))
            elif zone.zone_type == RECTANGLE:
                bb = (
                    (
                        int(round((zone.x1 or 0.0) * scale_x)),
                        int(round((zone.y1 or 0.0) * scale_y)),
                    ),
                    (
                        int(round((zone.x2 or 0.0) * scale_x)),
                        int(round((zone.y2 or 0.0) * scale_y)),
                    ),
                )

            self.finalize_shape(
                cx,
                cy,
                r,
                bb,
                key_name,
                bridge_key or zone.name,
                zone.scancode,
                zone.move_camera,
            )

        self.mouse_wheel_radius = self.active_layout.mouse_wheel_radius
        self.sprint_distance = self.active_layout.sprint_distance
        self.reset_state()
        print(
            f"[PLOTTER] - Loaded {len(zones)} zones for layout '{self.active_layout.name}' from SQLite."
        )

    def toggle_visibility(self):
        self.show_overlays = not self.show_overlays
        state_str = "VISIBLE" if self.show_overlays else "HIDDEN"
        for artist in self.shapes_artists.values():
            artist.set_visible(self.show_overlays)
        for artist in self.labels_artists.values():
            artist.set_visible(self.show_overlays)
        self.update_title(f"OVERLAYS: {state_str} | {DEF_STR}")

    def label(self, center_x, center_y, label_text, fc):
        fig_height_pts = self.fig.get_size_inches()[1] * 72
        scaled_font = max(5, int(round(fig_height_pts * 0.02)))
        return Text(
            center_x,
            center_y,
            label_text,
            color="white",
            fontsize=scaled_font,
            fontweight="bold",
            ha="center",
            va="center",
            zorder=12,
            bbox=dict(fc=fc, ec="black", lw=1.5, boxstyle="round,pad=0.3"),
        )

    def on_mouse_move(self, event):
        if self.state == COLLECTING and event.inaxes == self.ax:
            x, y = int(round(event.xdata)), int(round(event.ydata))
            if self.bg_cache is None:
                self.bg_cache = self.canvas.copy_from_bbox(self.ax.bbox)

            self.canvas.restore_region(self.bg_cache)
            for line in [self.crosshair_h_bg, self.crosshair_h_fg]:
                line.set_visible(True)
                line.set_ydata([y, y])
                self.ax.draw_artist(line)

            for line in [self.crosshair_v_bg, self.crosshair_v_fg]:
                line.set_visible(True)
                line.set_xdata([x, x])
                self.ax.draw_artist(line)

            self.fig.canvas.blit(self.ax.bbox)
        else:
            if self.crosshair_h_bg.get_visible():
                for line in [
                    self.crosshair_h_bg,
                    self.crosshair_h_fg,
                    self.crosshair_v_bg,
                    self.crosshair_v_fg,
                ]:
                    line.set_visible(False)
                self.cursor_manager.set_state_cursor(self.state)
                self.fig.canvas.draw_idle()

        if (
            self.state == IDLE
            and not self.drawn
            and event.button is None
            and event.inaxes == self.ax
        ):
            if self.ignore_current_draggable_id_n > 0:
                return

            hovering_now = None
            for uid, manager in self.label_drag_managers.items():
                contains, _ = manager.label_artist.contains(event)
                if contains:
                    hovering_now = (uid, manager, "label")
                    break

            if not hovering_now:
                for uid, manager in self.shape_drag_managers.items():
                    contains, _ = manager.shape_artist.contains(event)
                    if contains:
                        hovering_now = (uid, manager, "shape")
                        break

            if hovering_now:
                uid, manager, m_type = hovering_now
                target = (
                    manager.label_artist.get_bbox_patch()
                    if m_type == "label"
                    else manager.shape_artist
                )
                if target:
                    curr_id = m_type + "_" + str(uid)
                    if self.current_draggable_id != curr_id:
                        self.partial_release_all()
                        manager.on_press_helper(event)
                        self.current_draggable_id = curr_id
                        manager.indicate_current_draggable_id()
                        self.fire_on_motion = False
            else:
                self.partial_release_all()
                state_str = "VISIBLE" if self.show_overlays else "HIDDEN"
                self.update_title(f"OVERLAYS: {state_str} | {DEF_STR}", True)

    def partial_release_all(self):
        for draggable in self.label_drag_managers.values():
            draggable.partial_release()
        for draggable in self.shape_drag_managers.values():
            draggable.partial_release()
        self.current_draggable_id = None
        self.fig.canvas.draw_idle()

    def on_click(self, event):
        if self.state == IDLE:
            self.ignore_current_draggable_id_n = 0

        if self.state == WAITING_FOR_KEY:
            mouse_map = {1: "MOUSE_LEFT", 2: "MOUSE_MIDDLE", 3: "MOUSE_RIGHT"}
            button_name = mouse_map.get(event.button)
            if button_name:
                self.calculate_shape(button_name)
            return

        if self.state != COLLECTING:
            return
        if event.xdata is None or event.ydata is None:
            return

        self.points.append((int(round(event.xdata)), int(round(event.ydata))))
        (dot,) = self.ax.plot(event.xdata, event.ydata, "ro")
        self.point_artists.append(dot)
        self.fig.canvas.draw()
        self.bg_cache = None

        remaining = self.artists_points - len(self.points)
        if remaining > 0:
            self.update_title(
                f"MODE: {self.mode}. {remaining} points remaining (F8 to Cancel)."
            )
        else:
            self.state = WAITING_FOR_KEY
            self.update_title("Shape Defined! Press KEY or CLICK MOUSE to bind.")

    def on_key_press(self, event):
        if self.state == NAMING:
            self.handle_naming_input(event.key)
            return
        if self.state == DELETING:
            self.handle_deleting_input(event.key)
            return
        if self.state == MARKING:
            self.handle_marking_input(event.key)
            return
        if self.state == CONFIRM_DELETE_ALL:
            if event.key == "enter":
                self.delete_all_shapes()
            else:
                self.reset_state()
            return
        if self.state == CONFIRM_EXIT:
            if event.key == "enter":
                self.close()  # Closes QMainWindow
            else:
                self.reset_state()
            return
        if self.state == COLLECTING:
            if event.key == "f8":
                self.reset_state()
            return
        if self.state == WAITING_FOR_KEY:
            precise_key = get_specific_mt_key(event)
            self.calculate_shape(precise_key)
            return

        if self.state == IDLE:
            if event.key == "f1":
                self.reset_state()
            elif event.key == "f2":
                self.state = CONFIRM_DELETE_ALL
                self.update_title(
                    "[DELETE ALL?] Press ENTER to Confirm or Any other key to Cancel."
                )
            elif event.key == "f4":
                self.toggle_visibility()
            elif event.key == "f6":
                self.start_mode(CIRCLE, 3)
            elif event.key == "f7":
                self.start_mode(RECTANGLE, 4)
            elif event.key == "f9":
                self.print_data()
            elif event.key == "f12":
                self.enter_naming_mode()
            elif event.key == "delete":
                self.enter_deleting_mode()
            elif event.key == " ":
                self.enter_marking_mode()
            elif event.key == "escape":
                self.state = CONFIRM_EXIT
                self.update_title(
                    "[EXIT?] Press ENTER to Quit or Any other key to Cancel."
                )
            else:
                step = 5 if event.key.startswith("shift+") else 1
                clean_key = event.key.replace("shift+", "")
                if clean_key == "left" and self.current_draggable:
                    self.current_draggable.move(-step, 0)
                elif clean_key == "right" and self.current_draggable:
                    self.current_draggable.move(step, 0)
                elif clean_key == "up" and self.current_draggable:
                    self.current_draggable.move(0, -step)
                elif clean_key == "down" and self.current_draggable:
                    self.current_draggable.move(0, step)

    def on_resize(self, event):
        if not self.labels_artists:
            return
        fig_height_pts = self.fig.get_size_inches()[1] * 72
        scaled_font = max(5, int(round(fig_height_pts * 0.02)))
        for label_artist in self.labels_artists.values():
            label_artist.set_fontsize(scaled_font)
        self.fig.canvas.draw_idle()

    def enter_deleting_mode(self):
        if not self.shapes:
            self.update_title(f"List empty. Nothing to delete | {HELP_STR}")
            return
        self.state = DELETING
        self.input_buffer = ""
        self.update_title("DELETE MODE: Type ID... (Enter to Confirm | Esc to Cancel)")

    def delete_all_shapes(self):
        if not self.shapes:
            self.update_title(f"List empty. Nothing to delete | {HELP_STR}")
            return
        for uid in list(self.shapes.keys()):
            self.delete_entry(uid)
        self.count = 0
        self.reset_state()

    def handle_deleting_input(self, key):
        if key == "escape":
            self.reset_state()
            return
        if key == "enter":
            if self.input_buffer:
                try:
                    uid = int(self.input_buffer)
                    if uid in self.shapes:
                        self.delete_entry(uid)
                        self.update_title(f"Deleted ID {uid}. Returning to IDLE...")
                        self.reset_state()
                    else:
                        self.update_title(
                            f"Error: ID {uid} not found. Try again or Press ESC to Cancel."
                        )
                        self.input_buffer = ""
                except ValueError:
                    self.update_title(
                        "Error: Invalid Number. Try again or Press ESC to Cancel."
                    )
                    self.input_buffer = ""
            return
        if key.isdigit():
            self.input_buffer += key
            self.update_title(
                f"DELETE MODE: ID [{self.input_buffer}] (Enter to delete | Esc to Cancel)"
            )
        elif key == "backspace":
            self.input_buffer = self.input_buffer[:-1]
            self.update_title(
                f"DELETE MODE: ID [{self.input_buffer}] (Enter to delete | Esc to Cancel)"
            )

    def delete_entry(self, uid):
        if uid not in self.shapes:
            return
        shape_data = self.shapes[uid]
        bridge_key = shape_data["bridge_key"]

        if bridge_key == MOUSE_WHEEL_CODE:
            sprint_uids = [
                k
                for k, v in self.shapes.items()
                if v["bridge_key"] == SPRINT_DISTANCE_CODE
            ]
            for sid in sprint_uids:
                self.delete_entry(sid)
            self.saved_mouse_wheel = False
            self.mouse_wheel_radius = 0.0
            self.mouse_wheel_cx = 0.0
            self.mouse_wheel_cy = 0.0

        elif bridge_key == SPRINT_DISTANCE_CODE:
            self.saved_sprint_distance = False
            self.sprint_artist_id = None
            self.sprint_distance = 0.0

        if self.current_draggable_id in [f"shape_{uid}", f"label_{uid}"]:
            self.current_draggable_id = None
            self.current_draggable = None

        del self.shapes[uid]
        if uid in self.shapes_artists:
            self.shapes_artists[uid].remove()
            del self.shapes_artists[uid]
        if uid in self.labels_artists:
            self.labels_artists[uid].remove()
            del self.labels_artists[uid]
        if uid in self.label_drag_managers:
            self.label_drag_managers[uid].disconnect()
            del self.label_drag_managers[uid]
        if uid in self.shape_drag_managers:
            self.shape_drag_managers[uid].disconnect()
            del self.shape_drag_managers[uid]
        if self.last_artist_id in [f"shape_{uid}", f"label_{uid}"]:
            self.last_artist_id = None

    def enter_marking_mode(self):
        if not self.shapes:
            self.update_title(f"List empty. Nothing to mark | {HELP_STR}")
            return
        self.state = MARKING
        self.input_buffer = ""
        self.update_title("MARK MODE: Type ID... (Enter to Confirm | Esc to Cancel)")

    def handle_marking_input(self, key):
        if key == "escape":
            self.reset_state()
            return
        if key == "enter":
            if self.input_buffer:
                try:
                    uid = int(self.input_buffer)
                    if uid in self.shapes:
                        was_marked = self.shapes[uid]["move_camera"]
                        self.shapes[uid]["move_camera"] = not was_marked
                        if not was_marked:
                            self.label_drag_managers[uid].dull_face_color()
                            self.shape_drag_managers[uid].dull_face_color()
                            self.update_title(
                                f"Marked ID {uid} for Camera Follow. Returning to IDLE..."
                            )
                        else:
                            self.label_drag_managers[uid].restore_face_color()
                            self.shape_drag_managers[uid].restore_face_color()
                            self.update_title(
                                f"Unmarked ID {uid}. Returning to IDLE..."
                            )
                        self.reset_state()
                    else:
                        self.update_title(
                            f"Error: ID {uid} not found. Try again or Press ESC to Cancel."
                        )
                        self.input_buffer = ""
                except ValueError:
                    self.update_title(
                        "Error: Invalid Number. Try again or Press ESC to Cancel."
                    )
                    self.input_buffer = ""
            return
        if key.isdigit():
            self.input_buffer += key
            self.update_title(
                f"MARK MODE: ID [{self.input_buffer}] (Enter to mark | Esc to Cancel)"
            )
        elif key == "backspace":
            self.input_buffer = self.input_buffer[:-1]
            self.update_title(
                f"MARK MODE: ID [{self.input_buffer}] (Enter to mark | Esc to Cancel)"
            )

    def calculate_shape(self, key_name):
        hex_code, bridge_key = get_scancode_and_bridge_key_from_key(key_name)
        if hex_code is None:
            print(f'[PLOTTER] - Key "{key_name}" not mapped.')
            return

        cx, cy, r, bb = None, None, None, None
        if self.mode == CIRCLE:
            cx, cy, r, bb = self.calculate_circle()
        elif self.mode == RECTANGLE:
            cx, cy, r, bb = self.calculate_rect()

        self.finalize_shape(cx, cy, r, bb, key_name, bridge_key, hex_code)
        self.reset_state()

    def finalize_shape(
        self, cx, cy, r, bb, key_name, bridge_key, hex_code, move_camera=False
    ):
        if cx is None:
            return

        saved, entry_id = self.save_entry(
            bridge_key, hex_code, cx, cy, r, bb, move_camera
        )
        if not saved:
            return

        label = bridge_key
        if bridge_key == MOUSE_WHEEL_CODE:
            label = "MOUSE_WHEEL"
        elif bridge_key == SPRINT_DISTANCE_CODE:
            label = "SPRINT_DISTANCE"
        else:
            label = label.split("E0_")[-1]

        if self.mode == CIRCLE and cx and cy and r:
            if bridge_key == MOUSE_WHEEL_CODE:
                fc = DEFAULT_MOUSE_WHEEL_FACE_COLOR
            elif bridge_key == SPRINT_DISTANCE_CODE:
                fc = DEFAULT_SPRINT_DISTANCE_FACE_COLOR
            else:
                fc = get_vibrant_random_color(DEFAULT_FACE_COLOR_ALPHA)

            shape_artist = Circle(
                (cx, cy), r, fill=True, lw=2, fc=fc, ec=DEFAULT_EDGE_COLOR
            )
            shape_artist.set_visible(self.show_overlays)
            self.ax.add_patch(shape_artist)
            self.shapes_artists[entry_id] = shape_artist

            label_artist = self.label(cx, cy, label, fc)
            label_artist.set_visible(self.show_overlays)
            self.ax.add_artist(label_artist)
            self.labels_artists[entry_id] = label_artist

            self.label_drag_managers[entry_id] = _DraggableLabel(entry_id, self)
            self.shape_drag_managers[entry_id] = _DraggableShape(entry_id, self, CIRCLE)

            if move_camera:
                self.label_drag_managers[entry_id].dull_face_color()
                self.shape_drag_managers[entry_id].dull_face_color()

        elif self.mode == RECTANGLE and cx and cy and bb:
            fc = get_vibrant_random_color(DEFAULT_FACE_COLOR_ALPHA)
            (x1, y1), (x2, y2) = bb
            shape_artist = Rectangle(
                (x1, y1),
                x2 - x1,
                y2 - y1,
                fill=True,
                lw=2,
                fc=fc,
                ec=DEFAULT_EDGE_COLOR,
            )
            shape_artist.set_visible(self.show_overlays)
            self.ax.add_patch(shape_artist)
            self.shapes_artists[entry_id] = shape_artist

            label_artist = self.label(cx, cy, label, fc)
            label_artist.set_visible(self.show_overlays)
            self.ax.add_artist(label_artist)
            self.labels_artists[entry_id] = label_artist

            self.label_drag_managers[entry_id] = _DraggableLabel(entry_id, self)
            self.shape_drag_managers[entry_id] = _DraggableShape(
                entry_id, self, RECTANGLE
            )

            if move_camera:
                self.label_drag_managers[entry_id].dull_face_color()
                self.shape_drag_managers[entry_id].dull_face_color()

    def enter_naming_mode(self):
        if not self.shapes:
            self.update_title(f"Nothing to save! | {HELP_STR}")
            return
        self.state = NAMING
        self.input_buffer = ""
        self.buffer_default = True

        default_name = self.active_layout.name if self.active_layout else ""
        if default_name:
            self.input_buffer = default_name
            self.update_title(
                f"SAVE: [{self.input_buffer}] | Enter: Save/Rename | Shift+Enter: Save as Copy | Esc: Cancel"
            )
        else:
            self.update_title("SAVE: Type Name... | Enter: Save | Esc: Cancel")

    def handle_naming_input(self, key):
        if key == "escape":
            self.reset_state()
            return

        is_save_as_copy = key in ["shift+enter", "ctrl+s"]
        is_regular_save = key == "enter"

        if is_regular_save or is_save_as_copy:
            final_name = self.input_buffer.strip()
            if not final_name and self.active_layout:
                final_name = self.active_layout.name
            elif not final_name:
                final_name = datetime.datetime.now().strftime("map_%Y%m%d_%H%M%S")

            self.save_to_database(final_name, delete_former=is_regular_save)
            self.reset_state()
            return

        if key == "backspace":
            if self.buffer_default and self.active_layout:
                self.input_buffer = ""
                self.buffer_default = False
            else:
                self.input_buffer = self.input_buffer[:-1]
        elif len(key) == 1 and (key.isalnum() or key in ["_", " ", "-", "."]):
            if self.buffer_default:
                self.input_buffer = ""
                self.buffer_default = False
            self.input_buffer += key

        display_name = self.input_buffer if self.input_buffer else "[Auto-Timestamp]"
        self.update_title(
            f"SAVE: [{display_name}] | Enter: Save/Rename | Shift+Enter: Save as Copy | Esc: Cancel"
        )

    def save_to_database(self, user_name: str, delete_former: bool = False):
        output = []
        for _, data in self.shapes.items():
            entry = {
                "name": data["bridge_key"],
                "scancode": data["m_code"],
                "type": data["type"],
                "cx": data["cx"],
                "cy": data["cy"],
                "val1": 0,
                "val2": 0,
                "val3": 0,
                "val4": 0,
                "move_camera": data["move_camera"],
            }
            if data["type"] == CIRCLE:
                entry["val1"] = data["r"]
            elif data["type"] == RECTANGLE:
                (x_min, y_min), (x_max, y_max) = data["bb"]
                entry["val1"] = x_min
                entry["val2"] = y_min
                entry["val3"] = x_max
                entry["val4"] = y_max
            output.append(entry)

        rel_img_path = (
            self.image_path.name
            if self.image_path.parent == Path(IMAGES_FOLDER)
            else str(self.image_path)
        )
        existing_layout = self.layouts_repo.get_by_name(user_name)
        former_layout = self.active_layout

        if (
            former_layout is not None and former_layout.name == user_name
        ):  # is_same_layout
            layout_id = former_layout.id
            self.layouts_repo.update(
                layout_id,
                width=self.width,
                height=self.height,
                dpi=self.dpi,
                mouse_wheel_radius=self.mouse_wheel_radius,
                sprint_distance=self.sprint_distance,
                image_path=rel_img_path,
            )
            self.zones_repo.delete_all_for_layout(layout_id)

        else:
            if existing_layout:
                layout_id = existing_layout.id
                self.layouts_repo.update(
                    layout_id,
                    width=self.width,
                    height=self.height,
                    dpi=self.dpi,
                    mouse_wheel_radius=self.mouse_wheel_radius,
                    sprint_distance=self.sprint_distance,
                    image_path=rel_img_path,
                )
                self.zones_repo.delete_all_for_layout(layout_id)

            else:
                new_layout = self.layouts_repo.create(
                    name=user_name,
                    width=self.width,
                    height=self.height,
                    dpi=self.dpi,
                    mouse_wheel_radius=self.mouse_wheel_radius,
                    sprint_distance=self.sprint_distance,
                    image_path=rel_img_path,
                )
                layout_id = new_layout.id

            if (
                delete_former
                and former_layout is not None
                and former_layout.id != layout_id
            ):
                self.zones_repo.delete_all_for_layout(former_layout.id)
                self.layouts_repo.delete(former_layout.id)
                print(
                    f"[PLOTTER] - Former layout '{former_layout.name}' (ID: {former_layout.id}) deleted."
                )

        for item in output:
            if item["type"] == CIRCLE:
                self.zones_repo.create(
                    layout_id=layout_id,
                    scancode=str(item["scancode"]),
                    name=item["name"],
                    zone_type="CIRCLE",
                    cx=float(item["cx"]),
                    cy=float(item["cy"]),
                    r=float(item["val1"]),
                    move_camera=bool(item["move_camera"]),
                )

            else:
                self.zones_repo.create(
                    layout_id=layout_id,
                    scancode=str(item["scancode"]),
                    name=item["name"],
                    zone_type="RECTANGLE",
                    x1=float(item["val1"]),
                    y1=float(item["val2"]),
                    x2=float(item["val3"]),
                    y2=float(item["val4"]),
                    move_camera=bool(item["move_camera"]),
                )

        self.settings_repo.update(active_layout_id=layout_id)
        self.active_layout = self.layouts_repo.get(layout_id)

        action_str = "Renamed/Saved" if delete_former else "Saved as Copy"
        print(
            f"[PLOTTER] - {action_str}: '{user_name}' (ID: {layout_id}) committed directly to database."
        )
        self.update_title(f"SAVED: {user_name} | {HELP_STR}")

    def save_entry(self, bridge_key, hex_code, cx, cy, r, bb, move_camera):
        uid = self.count
        inc_count = True
        saved = False

        if bridge_key == MOUSE_WHEEL_CODE:
            if self.mode == CIRCLE:
                if self.saved_mouse_wheel:
                    for k, v in list(self.shapes.items()):
                        if v["bridge_key"] == MOUSE_WHEEL_CODE:
                            uid = k
                            inc_count = False
                            self.shapes.pop(k)
                            if uid in self.shapes_artists:
                                self.shapes_artists[uid].remove()
                                del self.shapes_artists[uid]
                            if uid in self.labels_artists:
                                self.labels_artists[uid].remove()
                                del self.labels_artists[uid]
                            if uid in self.label_drag_managers:
                                self.label_drag_managers[uid].disconnect()
                                del self.label_drag_managers[uid]
                            if uid in self.shape_drag_managers:
                                self.shape_drag_managers[uid].disconnect()
                                del self.shape_drag_managers[uid]
                            break

                self.mouse_wheel_radius = r
                self.mouse_wheel_cx = cx
                self.mouse_wheel_cy = cy
                self.saved_mouse_wheel = True
            elif self.mode == RECTANGLE:
                return saved, uid

        elif bridge_key == SPRINT_DISTANCE_CODE:
            if self.mode == CIRCLE:
                if not self.saved_mouse_wheel:
                    return saved, uid

                if self.saved_sprint_distance:
                    for k, v in list(self.shapes.items()):
                        if v["bridge_key"] == SPRINT_DISTANCE_CODE:
                            uid = k
                            inc_count = False
                            self.shapes.pop(k)
                            if uid in self.shapes_artists:
                                self.shapes_artists[uid].remove()
                                del self.shapes_artists[uid]
                            if uid in self.labels_artists:
                                self.labels_artists[uid].remove()
                                del self.labels_artists[uid]
                            if uid in self.label_drag_managers:
                                self.label_drag_managers[uid].disconnect()
                                del self.label_drag_managers[uid]
                            if uid in self.shape_drag_managers:
                                self.shape_drag_managers[uid].disconnect()
                                del self.shape_drag_managers[uid]
                            break

                actual_dist = self.euclidean_distance(
                    cx, cy, self.mouse_wheel_cx, self.mouse_wheel_cy
                )
                if actual_dist <= self.mouse_wheel_radius:
                    return False, uid

                self.sprint_distance = actual_dist
                self.saved_sprint_distance = True
                self.sprint_artist_id = uid
            elif self.mode == RECTANGLE:
                return saved, uid

        entry = {
            "bridge_key": bridge_key,
            "m_code": hex_code,
            "type": self.mode,
            "cx": cx,
            "cy": cy,
            "r": r,
            "bb": bb,
            "move_camera": move_camera,
        }

        self.shapes[uid] = entry
        if inc_count:
            self.count += 1
        return True, uid

    def print_data(self):
        if not self.shapes:
            self.update_title(f"List empty. Nothing to print | {HELP_STR}")
            return
        print("\nCurrent Shapes:")
        for k, v in self.shapes.items():
            print(k, v)
        print("\n")

    def calculate_circle(self):
        if len(self.points) < 3:
            return None, None, None, None
        x1, y1 = self.points[0]
        x2, y2 = self.points[1]
        x3, y3 = self.points[2]
        d = 2 * (x1 * (y2 - y3) + x2 * (y3 - y1) + x3 * (y1 - y2))
        if d == 0:
            self.update_title("Error: Points are collinear.")
            return None, None, None, None
        h = (
            (x1**2 + y1**2) * (y2 - y3)
            + (x2**2 + y2**2) * (y3 - y1)
            + (x3**2 + y3**2) * (y1 - y2)
        ) / d
        k = (
            (x1**2 + y1**2) * (x3 - x2)
            + (x2**2 + y2**2) * (x1 - x3)
            + (x3**2 + y3**2) * (x2 - x1)
        ) / d
        r = math.sqrt((x1 - h) ** 2 + (y1 - k) ** 2)
        return int(round(h)), int(round(k)), int(round(r)), None

    def calculate_rect(self):
        if len(self.points) < 4:
            return None, None, None, None
        xs = [pt[0] for pt in self.points]
        ys = [pt[1] for pt in self.points]
        return (
            int(round(sum(xs) / 4)),
            int(round(sum(ys) / 4)),
            None,
            ((min(xs), min(ys)), (max(xs), max(ys))),
        )

    def calculate_raw_rect(self, values):
        if len(values) < 2:
            return None, None, None, None
        xs = [v[0] for v in values]
        ys = [v[1] for v in values]
        return (
            int(round(sum(xs) / 2)),
            int(round(sum(ys) / 2)),
            None,
            ((min(xs), min(ys)), (max(xs), max(ys))),
        )

    def euclidean_distance(self, x1, y1, x2, y2):
        return math.sqrt((x2 - x1) ** 2 + (y2 - y1) ** 2)

    def constrain_point_to_rect_radial(self, cx, cy, px, py, rect_bb):
        (x_min, y_min), (x_max, y_max) = rect_bb
        if x_min <= cx <= x_max and y_min <= cy <= y_max:
            return cx, cy

        radius = math.sqrt((cx - px) ** 2 + (cy - py) ** 2)
        if radius < 1e-9:
            return cx, cy

        current_angle = math.atan2(cy - py, cx - px)
        valid_intersections = []

        def on_segment(x, y, x1, y1, x2, y2):
            eps = 1e-9
            return (
                min(x1, x2) - eps <= x <= max(x1, x2) + eps
                and min(y1, y2) - eps <= y <= max(y1, y2) + eps
            )

        edges = [
            (x_min, y_min, x_min, y_max),
            (x_max, y_min, x_max, y_max),
            (x_min, y_min, x_max, y_min),
            (x_min, y_max, x_max, y_max),
        ]

        for x1, y1, x2, y2 in edges:
            if abs(x1 - x2) < 1e-9:
                dx = x1 - px
                if abs(dx) <= radius:
                    dy = math.sqrt(radius**2 - dx**2)
                    for ix, iy in [(x1, py + dy), (x1, py - dy)]:
                        if on_segment(ix, iy, x1, y1, x2, y2):
                            valid_intersections.append((ix, iy))
            else:
                dy = y1 - py
                if abs(dy) <= radius:
                    dx = math.sqrt(radius**2 - dy**2)
                    for ix, iy in [(px + dx, y1), (px - dx, y1)]:
                        if on_segment(ix, iy, x1, y1, x2, y2):
                            valid_intersections.append((ix, iy))

        if not valid_intersections:
            return max(x_min, min(cx, x_max)), max(y_min, min(cy, y_max))

        candidates = []
        for ix, iy in valid_intersections:
            target_angle = math.atan2(iy - py, ix - px)
            diff = math.atan2(
                math.sin(target_angle - current_angle),
                math.cos(target_angle - current_angle),
            )
            candidates.append({"pt": (ix, iy), "diff": abs(diff), "y": iy})

        candidates.sort(key=lambda c: (round(c["diff"], 5), c["y"]))
        return candidates[0]["pt"]


def run():
    app = QApplication.instance() or QApplication(sys.argv)
    try:
        plotter = Plotter()
        plotter.show()
    except RuntimeError as e:
        print(e)
        sys.exit(1)

    sys.exit(app.exec())


if __name__ == "__main__":
    run()
