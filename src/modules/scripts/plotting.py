from __future__ import annotations
from modules.platforms import get_platform, get_specific_mt_key

get_platform().SystemConfig().set_dpi_awareness()

import sys
from modules.utils import (
    CIRCLE,
    RECT,
    DEF_DPI,
    IMAGES_FOLDER,
    JSONS_FOLDER,
    TOML_PATH,
    MOUSE_WHEEL_CODE,
    SPRINT_DISTANCE_CODE,
    IDLE,
    SYSTEM,
    get_scancode_and_bridge_key_from_key,
    get_key_from_scancode,
    rotate_resolution,
    update_toml,
    get_vibrant_random_color,
    get_dulled_hue_color,
    get_hue_modified_alpha_from_hsv,
)

import os

if SYSTEM == "Windows":
    # Suppress Qt QPA Windows-specific warnings
    os.environ["QT_LOGGING_RULES"] = "qt.qpa.window=false"

import matplotlib

matplotlib.use("qtagg")
import matplotlib.pyplot as plt
from matplotlib.patches import Circle, Rectangle
from matplotlib.text import Text
from PySide6.QtCore import Qt
from PIL import Image
import tomlkit
import math
from PySide6.QtWidgets import QApplication, QFileDialog, QMessageBox
import json
import datetime
from pathlib import Path

COLLECTING = "COLLECTING"
WAITING_FOR_KEY = "WAITING_FOR_KEY"
NAMING = "NAMING"
DELETING = "DELETING"
MARKING = "MARKING"
CONFIRM_DELETE_ALL = "CONFIRM_DELETE_ALL"
CONFIRM_EXIT = "CONFIRM_EXIT"
CONFIRM_DELETE_EXIT = "CONFIRM_DELETE_EXIT"
CONFIRM_NAMING_EXIT = "CONFIRM_NAMING_EXIT"
HELP_STR = "F1 (Help)"
DEF_STR = "MODE: IDLE | F3 (Load JSON) | F5 (Load Image) | F12 (Save) | Esc (Exit)\n\
    F6 (Circle) | F7 (Rect) | F8 (Cancel) | Del (Delete) | F2 (Delete All) | F9 (List Current Shapes in Terminal)\n\
    F4 (Toggle Artist Visibility) | [ (Sprint Threshold) | ] (Mouse Wheel) | Space (Toggle Move Camera)\n\
    Arrows: Nudge | Shift+Arrows: Fast Nudge | Double Click: Change Selected Artist"

INDICATED_EDGE_COLOR = (0.85, 0.88, 0.92)
ACTIVE_EDGE_COLOR = (0.7, 0.7, 0.7, 0.8)
DEFAULT_EDGE_COLOR = (0.3, 0.3, 0.3, 0.8)
DEFAULT_MOUSE_WHEEL_FACE_COLOR = (0.0, 0.8, 0.8, 0.4)  # Bright Cyan/Teal
DEFAULT_SPRINT_DISTANCE_FACE_COLOR = (1.0, 0.2, 0.2, 0.5)  # Bright Red
DEFAULT_FACE_COLOR_ALPHA = 0.4
DEFAULT_SMALL_LINE_WIDTH = 1.5
DEFAULT_MEDIUM_LINE_WIDTH = 2
DEFAULT_LARGE_LINE_WIDTH = 3


class _CursorManager:
    def __init__(self, canvas):
        self.canvas = canvas

        # Map application states to PySide6 cursor shapes
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
        """Sets the cursor based on the predefined state map."""
        shape = self.state_map.get(state, Qt.CursorShape.ArrowCursor)
        self.canvas.setCursor(shape)

    def set_custom_cursor(self, shape):
        """Allows manual override for specific UI interactions."""
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
        current_draggable_id = None
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
                current_draggable_id = self.plotter.draggables_ids[n]
            else:
                current_draggable_id = self.plotter.last_artist_id

        else:
            self.plotter.iter_count = 0
            current_draggable_id = self.plotter.draggables_ids[0]

        return current_draggable_id

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
                    if self.plotter.shapes[self.entry_id]["move_camera"] == True
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
                    if self.plotter.shapes[self.entry_id]["move_camera"] == True
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
        self.canvas = self.label_artist.figure.canvas

        self.press = None
        self.drag_bg = None

        if self.canvas.supports_blit:
            # Store IDs so we can kill them later
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

        if self.press is None or event.inaxes != self.label_artist.axes:
            return

        if self.plotter.current_draggable_id is None:
            self.plotter.current_draggable_id = self.select_current_draggable_id()
            self.indicate_current_draggable_id()

        if not self.plotter.current_draggable_id == self.artist_id:
            return

        self.plotter.ignore_current_draggable_id_n = 1

        if not self.plotter.drawn:
            # Prepare Background for Blitting
            label_bbox = self.label_artist.get_bbox_patch()
            if label_bbox:
                label_bbox.set_edgecolor(ACTIVE_EDGE_COLOR)
                label_bbox.set_linewidth(DEFAULT_LARGE_LINE_WIDTH)
            self.label_artist.set_visible(False)

            self.shape_artist.set_edgecolor(ACTIVE_EDGE_COLOR)
            self.shape_artist.set_linewidth(DEFAULT_LARGE_LINE_WIDTH)

            self.canvas.draw()
            self.drag_bg = self.canvas.copy_from_bbox(self.label_artist.axes.bbox)  # type: ignore
            self.label_artist.set_visible(True)
            self.plotter.drawn = True

        _, _, xdata_press, ydata_press, xpx_press, ypx_press = self.press
        dx = event.xdata - xdata_press
        dy = event.ydata - ydata_press
        dx_press = event.x - xpx_press
        dy_press = event.y - ypx_press
        dist_px = ((dx_press**2) + (dy_press**2)) ** 0.5
        self.plotter.current_move_distance = dist_px

        # Blitting Loop
        self.canvas.restore_region(self.drag_bg)  # type: ignore
        self.move_label(dx, dy)
        self.label_artist.axes.draw_artist(self.label_artist)  # type: ignore
        self.canvas.blit(self.label_artist.axes.bbox)  # type: ignore

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
                # Reset blitted background
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
        print(f"[PLOTTER] - Event listeners for {self.label_artist} disconnected.")


class _DraggableShape(_Draggable):
    def __init__(self, entry_id: int, plotter_ref: Plotter, shape_type: str):
        super().__init__(entry_id, True, plotter_ref)
        self.shape_type = shape_type
        self.label_artist = self.plotter.labels_artists[entry_id]
        self.shape_artist = self.plotter.shapes_artists[entry_id]
        self.canvas = self.shape_artist.figure.canvas

        self.press = None
        self.drag_bg = None
        self.shape_mode = None

        self.radial_tolerance = 5  # Pixel coordinates
        self.edge_tolerance = 5  # Pixel coordinates
        self.vertex_tolerance = 10  # Pixel coordinates
        self.min_rect_dist = 50  # Data coordinates
        self.min_circ_dist = 30  # Data coordinates
        self.spec_max_ratio = (
            0.3  # max ratio for joystick and sprint distance relative to image size
        )

        if self.shape_type == CIRCLE:
            r = self.shape_artist.get_radius()  # type: ignore
            new_r = max(r, self.min_circ_dist)
            self.shape_artist.set_radius(new_r)  # type: ignore
            self.plotter.shapes[self.entry_id]["r"] = new_r

        elif self.shape_type == RECT:
            x, y = self.shape_artist.get_xy()  # type: ignore
            w = self.shape_artist.get_width()
            h = self.shape_artist.get_height()
            self.update_rect_safe(x, y, w, h)

        else:
            return

        if self.canvas.supports_blit:
            # Store IDs so we can kill them later
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

        contains, _ = self.shape_artist.contains(
            event,
        )
        if not contains:
            self.plotter.ignore_current_draggable_id_n -= 1
            return False

        if self.shape_type == CIRCLE:
            cx, cy = self.shape_artist.get_center()  # type: ignore
            self.shape_mode = self.get_circumference(event, cx, cy)
            self.press = cx, cy, event.xdata, event.ydata, event.x, event.y

        elif self.shape_type == RECT:
            x, y = self.shape_artist.get_xy()  # type: ignore
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

        if self.press is None or event.inaxes != self.shape_artist.axes:
            return

        if self.plotter.current_draggable_id is None:
            self.plotter.current_draggable_id = self.select_current_draggable_id()
            self.indicate_current_draggable_id()

        if not self.plotter.current_draggable_id == self.artist_id:
            return

        self.plotter.ignore_current_draggable_id_n = 1

        if not self.plotter.drawn:
            # Prepare Background for Blitting
            self.shape_artist.set_edgecolor(ACTIVE_EDGE_COLOR)
            self.shape_artist.set_linewidth(DEFAULT_LARGE_LINE_WIDTH)
            self.shape_artist.set_visible(False)

            label_bbox = self.label_artist.get_bbox_patch()
            if label_bbox:
                label_bbox.set_edgecolor(ACTIVE_EDGE_COLOR)
                label_bbox.set_linewidth(DEFAULT_LARGE_LINE_WIDTH)

            self.canvas.draw()
            self.drag_bg = self.canvas.copy_from_bbox(self.shape_artist.axes.bbox)  # type: ignore
            self.shape_artist.set_visible(True)
            self.plotter.drawn = True

        _, _, _, _, xpx_press, ypx_press = self.press
        dx_press = event.x - xpx_press
        dy_press = event.y - ypx_press
        dist_px = ((dx_press**2) + (dy_press**2)) ** 0.5
        self.plotter.current_move_distance = dist_px

        # Blitting Loop
        self.canvas.restore_region(self.drag_bg)  # type: ignore
        if self.shape_type == CIRCLE:
            self.circle_transform(event)
        elif self.shape_type == RECT:
            self.rect_transform(event)
        else:
            return

        self.shape_artist.axes.draw_artist(self.shape_artist)  # type: ignore
        self.canvas.blit(self.shape_artist.axes.bbox)  # type: ignore

    def circle_transform(self, event):
        if self.press is None:
            return
        xdata = event.xdata
        ydata = event.ydata

        old_cx, old_cy = self.shape_artist.get_center()  # type: ignore
        old_r = self.shape_artist.get_radius()  # type: ignore
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
                cx, cy = sprint_artist.shape_artist.get_center()  # type: ignore
                actual_dist = self.plotter.euclidean_distance(cx, cy, new_cx, new_cy)

                # STRICT CHECK: Ensure Sprint is actually outside the Joystick
                if actual_dist <= self.plotter.mouse_wheel_radius:
                    r = self.plotter.mouse_wheel_radius
                    screen_rect = ((0, 0), (self.plotter.width, self.plotter.height))
                    sp_x, sp_y = self.plotter.constrain_point_to_rect_radial(
                        new_cx, new_cy - r - 1, new_cx, new_cy, screen_rect
                    )
                    sp_x, sp_y = int(round(sp_x)), int(round(sp_y))

                    sprint_artist.shape_artist.set_center((sp_x, sp_y))  # type: ignore
                    sprint_shape["cx"] = sp_x
                    sprint_shape["cy"] = sp_y

                    sp_actual_dist = self.plotter.euclidean_distance(
                        sp_x, sp_y, new_cx, new_cy
                    )
                    self.plotter.sprint_distance = sp_actual_dist
                else:
                    self.plotter.sprint_distance = actual_dist

        if (
            self.plotter.saved_sprint_distance
            and current_shape["bridge_key"] == SPRINT_DISTANCE_CODE
        ):
            actual_dist = self.plotter.euclidean_distance(
                new_cx, new_cy, self.plotter.mouse_wheel_cx, self.plotter.mouse_wheel_cy
            )

            # STRICT CHECK: Ensure Sprint is actually outside the Joystick
            if actual_dist <= self.plotter.mouse_wheel_radius:
                self.shape_artist.set_center((old_cx, old_cy))  # type: ignore
                self.shape_artist.set_radius(old_r)  # type: ignore
                current_shape["cx"] = old_cx
                current_shape["cy"] = old_cy
                current_shape["r"] = old_r
            else:
                self.plotter.sprint_distance = actual_dist

    def rect_transform(self, event):
        if self.press is None:
            return
        xdata = event.xdata
        ydata = event.ydata

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
        # Get circle data
        r = self.shape_artist.get_radius()  # type: ignore
        # Convert center to pixels
        cx_px, cy_px = self.shape_artist.axes.transData.transform((cx, cy))  # type: ignore
        # Calculate radius in pixels
        rim_x_px, _ = self.shape_artist.axes.transData.transform((cx + r, cy))  # type: ignore
        r_px = abs(rim_x_px - cx_px)
        # Calculate distance from mouse to center
        dist_px = ((event.x - cx_px) ** 2 + (event.y - cy_px) ** 2) ** 0.5
        # Check if distance is within tolerance of radius, if not check if it is inside the circle
        diff_px = abs(dist_px - r_px)
        if diff_px <= self.radial_tolerance:
            return "resize"
        if dist_px <= r_px:
            return "drag"
        return None

    def update_radius(self, xdata, ydata):
        # Get the fixed center
        cx, cy = self.shape_artist.get_center()  # type: ignore
        # Calculate distance from center to mouse
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
                        (
                            self.spec_max_ratio
                            * ((self.plotter.width + self.plotter.height) / 2)
                        )
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
                sp_r = sprint_artist.shape_artist.get_radius()  # type: ignore
                if new_r < sp_r:
                    new_sp_r = new_r

        if (
            self.plotter.saved_sprint_distance
            and current_shape["bridge_key"] == SPRINT_DISTANCE_CODE
        ):
            new_r = min(new_r, self.plotter.mouse_wheel_radius)

        if new_r >= self.min_circ_dist:
            self.shape_artist.set_radius(new_r)  # type: ignore
            current_shape["r"] = new_r

            if new_sp_r is not None and self.plotter.sprint_artist_id is not None:
                sprint_artist = self.plotter.shape_drag_managers[
                    self.plotter.sprint_artist_id
                ]
                sprint_shape = self.plotter.shapes[self.plotter.sprint_artist_id]
                sprint_artist.shape_artist.set_radius(new_sp_r)  # type: ignore
                sprint_shape["r"] = new_sp_r

    def get_corner_under_mouse(self, event):
        x, y = self.shape_artist.get_xy()  # type: ignore
        w, h = self.shape_artist.get_width(), self.shape_artist.get_height()

        # VISUAL CORNERS (Adjusted for imshow Y-inversion)
        # (x, y) is visually TOP-LEFT
        # (x, y+h) is visually BOTTOM-LEFT
        corners = {
            "top_left": (x, y),
            "top_right": (x + w, y),
            "bottom_left": (x, y + h),
            "bottom_right": (x + w, y + h),
        }

        # Check pixel distance for each corner
        for name, (cx, cy) in corners.items():
            cx_px, cy_px = self.shape_artist.axes.transData.transform((cx, cy))  # type: ignore
            dist_px = ((event.x - cx_px) ** 2 + (event.y - cy_px) ** 2) ** 0.5
            if dist_px <= self.vertex_tolerance:
                return name
        return None

    def get_edge_under_mouse(self, event):
        mx, my = event.x, event.y
        bbox = self.shape_artist.get_window_extent()

        is_within_horizontal = bbox.x0 <= mx <= bbox.x1
        is_within_vertical = bbox.y0 <= my <= bbox.y1

        # NOTE: bbox.y0 is the BOTTOM pixel, bbox.y1 is the TOP pixel in Matplotlib
        # But in imshow (inverted), visual layout is different.
        # We rely on visual consistency relative to the mouse.

        if abs(mx - bbox.x0) <= self.edge_tolerance and is_within_vertical:
            return "left"
        if abs(mx - bbox.x1) <= self.edge_tolerance and is_within_vertical:
            return "right"

        # Visual TOP edge is mathematically the 'min y' (y0 in data, but y1 in pixels typically)
        # Let's trust the pixel bbox: y1 is usually visually Top in MPL GUI, y0 is Bottom
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

        # Get current RAW bounds (un-normalized)
        x, y = self.shape_artist.get_xy()  # type: ignore
        w = self.shape_artist.get_width()
        h = self.shape_artist.get_height()

        # Identify fixed anchor points based on the corner being dragged
        # Note: We use the VISUAL names we defined in get_corner_under_mouse
        if corner == "bottom_right":
            # Fixed Anchor is Top-Left (x, y)
            new_w = xdata - x
            new_h = ydata - y
            self.update_rect_safe(x, y, new_w, new_h)
            return True

        if corner == "top_left":
            # Fixed Anchor is Bottom-Right (x+w, y+h)
            # New x is mouse_x, New y is mouse_y
            # Width changes by (old_right - mouse_x)
            new_w = (x + w) - xdata
            new_h = (y + h) - ydata
            self.update_rect_safe(xdata, ydata, new_w, new_h)
            return True

        if corner == "top_right":
            # Fixed Anchor is Bottom-Left (x, y+h)
            # x is unchanged (visually left), y becomes mouse_y (visually top)
            new_w = xdata - x
            new_h = (y + h) - ydata
            self.update_rect_safe(x, ydata, new_w, new_h)
            return True

        if corner == "bottom_left":
            # Fixed Anchor is Top-Right (x+w, y)
            # x becomes mouse_x, y is unchanged
            new_w = (x + w) - xdata
            new_h = ydata - y
            self.update_rect_safe(xdata, y, new_w, new_h)
            return True

        return False

    def update_edge(self, edge, xdata, ydata):
        if edge is None:
            return False

        xdata, ydata = int(round(xdata)), int(round(ydata))

        # Get current RAW bounds
        x, y = self.shape_artist.get_xy()  # type: ignore
        w = self.shape_artist.get_width()
        h = self.shape_artist.get_height()

        # Determine limits based on the visual edge being dragged
        #    We calculate the new proposed dimensions, then Normalize.

        if edge == "right":
            # Anchor: Left Edge (x) stays fixed.
            # New Width = Mouse X - Left Edge
            new_w = xdata - x
            # Height and Y unchanged
            self.update_rect_safe(x, y, new_w, h)
            return True

        if edge == "left":
            # Anchor: Right Edge (x + w) stays fixed.
            # New Width = Right Edge - Mouse X
            # New X = Mouse X
            right_edge = x + w
            new_w = right_edge - xdata
            # Height and Y unchanged
            self.update_rect_safe(xdata, y, new_w, h)
            return True

        if edge == "bottom":
            # Visual Bottom means mathematically HIGHER Y in typical plots,
            # BUT in imshow (y=0 at top), Bottom has a HIGHER pixel value.

            # Anchor: Top Edge (y) stays fixed.
            # New Height = Mouse Y - Top Edge
            new_h = ydata - y
            # Width and X unchanged
            self.update_rect_safe(x, y, w, new_h)
            return True

        if edge == "top":
            # Visual Top means mathematically LOWER Y in typical plots.
            # In imshow: Top is y=0.

            # Anchor: Bottom Edge (y + h) stays fixed.
            # New Height = Bottom Edge - Mouse Y
            # New Y = Mouse Y
            bottom_edge = y + h
            new_h = bottom_edge - ydata
            # Width and X unchanged
            self.update_rect_safe(x, ydata, w, new_h)
            return True

        return False

    def update_rect_safe(self, x, y, w, h):
        """
        Normalizes rect to always have positive W and H.
        This prevents hit-testing bugs when shapes are inverted.
        """
        x, y, w, h = int(round(x)), int(round(y)), int(round(w)), int(round(h))

        # Shape freezes instead of flipping
        if w < 0:
            return

        if h < 0:
            return

        if w >= self.min_rect_dist:
            self.shape_artist.set_x(x)  # type: ignore
            self.shape_artist.set_width(w)
        else:
            old_x = int(round(self.shape_artist.get_x()))  # type: ignore
            x = old_x
            old_w = int(round(self.shape_artist.get_width()))
            w = max(old_w, self.min_rect_dist)

        if h >= self.min_rect_dist:
            self.shape_artist.set_y(y)  # type: ignore
            self.shape_artist.set_height(h)
        else:
            old_y = int(round(self.shape_artist.get_y()))  # type: ignore
            y = old_y
            old_h = int(round(self.shape_artist.get_height()))
            h = max(old_h, self.min_rect_dist)

        # Recalculate based on new visual shape
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
            self.shape_artist.set_center((new_cx, new_cy))  # type: ignore
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
            cx, cy = self.shape_artist.get_center()  # type: ignore
            self.press = cx, cy, xdata_press, ydata_press, xpx_press, ypx_press

            old_cx, old_cy = self.shape_artist.get_center()  # type: ignore
            old_r = self.shape_artist.get_radius()  # type: ignore
            new_cx, new_cy = self.move_circle(dx, dy)
            self.circle_transform_helper(old_cx, old_cy, old_r, new_cx, new_cy)

        elif self.shape_type == RECT:
            _, _, xdata_press, ydata_press, xpx_press, ypx_press = self.press
            x, y = self.shape_artist.get_xy()  # type: ignore
            self.press = x, y, xdata_press, ydata_press, xpx_press, ypx_press

            self.move_rect(dx, dy)

        else:
            return

        self.canvas.draw()
        self.plotter.drawn = False

    def on_release(self, event):
        self.partial_release()

        if self.plotter.current_draggable_id is None and self.plotter.draggables_ids:
            self.plotter.current_draggable_id = self.select_current_draggable_id()
            self.indicate_current_draggable_id()

        if self.artist_id == self.plotter.current_draggable_id:
            if self.plotter.drawn:
                # Reset blitted background
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
        print(f"[PLOTTER] - Event listeners for {self.shape_artist} disconnected.")


class Plotter:
    def __init__(self, image_path=None):
        self.app = QApplication(sys.argv)

        # SMART PATH DETECTION
        json_file_str = None

        if image_path is None:
            if TOML_PATH.exists():
                try:
                    with open(TOML_PATH, "r", encoding="utf-8") as f:
                        doc = tomlkit.load(f)
                    toml_img_str = doc.get("system", {}).get("hud_image_path", "")
                    json_file_str = doc.get("system", {}).get("json_path", "")
                    if toml_img_str:
                        potential_path = Path(toml_img_str)
                        if potential_path.exists():
                            image_path = potential_path
                            print(
                                f"[PLOTTER] - Auto-loading last HUD: {image_path.as_posix()}"
                            )
                except Exception:
                    pass

            if image_path is None:
                IMAGES_FOLDER.mkdir(parents=True, exist_ok=True)
                print(f"[PLOTTER] - No active HUD found in config. Opening selector...")
                selected = self.select_image_file()
                image_path = Path(selected) if selected else None

        if not image_path:
            print("Exiting: No image selected.")
            return

        self.image_path = Path(image_path)
        img = self.load_image()
        if img is None:
            print("Could not load image, exiting...")
            return

        #  GUI Configuration
        for key in plt.rcParams:
            if key.startswith("keymap."):
                plt.rcParams[key] = []

        # Initiate Parameters
        self.fig, self.ax = plt.subplots()
        self.cursor_manager = _CursorManager(self.fig.canvas)

        self.points = []
        self.point_artists = []
        self.mode = None
        self.state = IDLE
        self.input_buffer = ""
        self.shapes_artists: dict[int, Circle | Rectangle] = {}  # type: ignore
        self.labels_artists: dict[int, Text] = {}  # type: ignore
        self.label_drag_managers: dict[int, _DraggableLabel] = {}
        self.shape_drag_managers: dict[int, _DraggableShape] = {}

        self.init_params_helper()
        self.update_image_params(img)
        self.ax.imshow(img)

        state_str = "VISIBLE" if self.show_overlays else "HIDDEN"
        self.update_title(f"OVERLAYS: {state_str} | {DEF_STR}")

        self.init_crosshairs()
        self.bg_cache = None

        self.fig.canvas.mpl_connect("motion_notify_event", self.on_mouse_move)
        self.fig.canvas.mpl_connect("key_press_event", self.on_key_press)
        self.fig.canvas.mpl_connect("button_press_event", self.on_click)
        self.fig.canvas.mpl_connect("resize_event", self.on_resize)

        if json_file_str:
            json_path = Path(json_file_str)
            if json_path.exists():
                print(f"[PLOTTER] - Auto-loading last JSON: {json_path.as_posix()}")
                self.load_json_from_path(json_path)

        self.fig.subplots_adjust(bottom=0)
        plt.show()

    # Visual & State Management
    def select_image_file(self) -> str:
        file_path, _ = QFileDialog.getOpenFileName(
            None,
            "Select an Image (HUD)",
            str(IMAGES_FOLDER),
            "Image Files (*.jpg *.jpeg *.png *.bmp *.webp);;All Files (*.*)",
        )

        if not file_path:
            print("[PLOTTER] - Image selection cancelled.")
            return ""

        return file_path

    def load_image(self):
        try:
            img = Image.open(self.image_path)
        except Exception as e:
            print(f"Error loading image: {e}")
            return None
        print(f"[PLOTTER] - Image: {self.image_path.as_posix()} loaded successfully.")
        return img

    def update_image_params(self, img):
        self.width, self.height = img.size
        try:
            # self.image_path.stem gets the filename without extension
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
        # Create the "Shadow" (Black, thicker)
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

        # Create the "Core" (White, thinner)
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
        self.json_path = None
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
        for uid in self.shapes_artists:
            self.shapes_artists[uid].remove()
        self.shapes_artists = {}
        for uid in self.labels_artists:
            self.labels_artists[uid].remove()
        self.labels_artists = {}
        for uid in self.label_drag_managers:
            self.label_drag_managers[uid].disconnect()
        self.label_drag_managers = {}
        for uid in self.shape_drag_managers:
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
        self.bg_cache = self.fig.canvas.copy_from_bbox(self.ax.bbox)  # type: ignore

    def start_mode(self, mode, num_points):
        self.reset_state()
        self.mode = mode
        self.artists_points = num_points
        self.state = COLLECTING
        self.update_title(
            f"MODE: {mode}. Click {num_points} points on the image (F8 to Cancel)."
        )

    def load_json(self):
        # Filter for JSON files and set default directory
        file_path, _ = QFileDialog.getOpenFileName(
            None,
            "Select a JSON (Mapping Profile)",
            str(JSONS_FOLDER),
            "JSON files (*.json);;All files (*)",
        )

        if not file_path:
            print("[PLOTTER] - JSON selection cancelled.")
            return

        self.load_json_from_path(file_path)

    def load_json_from_path(self, file_path):
        if not os.path.exists(file_path):
            print(f"Error: File '{file_path}' not found.")
            return

        with open(file_path, mode="r", encoding="utf-8") as f:
            try:
                data = json.load(f)
            except json.JSONDecodeError as e:
                print(f"Invalid JSON syntax in '{file_path}': {e}")
                return

        try:
            metadata = data["metadata"]
            content = data["content"]
            screen_width = metadata["width"]
            screen_height = metadata["height"]
            metadata["dpi"]
            metadata["mouse_wheel_radius"]
            metadata["sprint_distance"]
        except Exception as e:
            print(f"Error loading json file: {e}.")
            return

        scale_x = self.width / screen_width
        scale_y = self.height / screen_height
        item_id = 0
        json_shapes: dict[int, dict] = {}

        for item in content:
            scancode = item.get("scancode")
            if scancode is None:
                continue

            zone_type = item.get("type", "")
            name = item.get("name", "")

            try:
                cx = float(item["cx"])
                cy = float(item["cy"])
                val1 = float(item["val1"])
                val2 = float(item["val2"])
                val3 = float(item["val3"])
                val4 = float(item["val4"])
                move_camera = bool(item["move_camera"])

            except (ValueError, KeyError) as e:
                print(
                    f"Skipping invalid item: {scancode} with name: {name}. Error: {e}"
                )
                continue

            json_shape = {}
            key_name = get_key_from_scancode(scancode)
            _, bridge_key = get_scancode_and_bridge_key_from_key(key_name)
            json_shape["key_name"] = key_name
            json_shape["m_code"] = scancode
            json_shape["type"] = zone_type
            json_shape["cx"] = int(round(cx * scale_x))
            json_shape["cy"] = int(round(cy * scale_y))
            json_shape["move_camera"] = move_camera
            json_shape["bridge_key"] = bridge_key if bridge_key is not None else ""

            if zone_type == CIRCLE:
                scale_r = (scale_x + scale_y) / 2
                json_shape["r"] = int(round(val1 * scale_r))
                json_shape["mode"] = CIRCLE

            elif zone_type == RECT:
                new_x1 = int(round(val1 * scale_x))
                new_y1 = int(round(val2 * scale_y))
                new_x2 = int(round(val3 * scale_x))
                new_y2 = int(round(val4 * scale_y))
                json_shape["bb"] = ((new_x1, new_y1), (new_x2, new_y2))
                json_shape["mode"] = RECT

            json_shapes[item_id] = json_shape
            item_id += 1

        if item_id > 0:
            w, h, dpi = self.width, self.height, self.dpi
            self.init_params_helper()
            self.width, self.height, self.dpi = w, h, dpi
            self.reset_state()
            print("Cleared previous shapes and artists, figure reset.")

            for shape in list(json_shapes.values()):
                cx = shape["cx"]
                cy = shape["cy"]
                r = shape.get("r", None)
                bb = shape.get("bb", None)
                key_name = shape["key_name"]
                l_move_camera = shape["move_camera"]
                bridge_key = shape["bridge_key"]
                hex_code = shape["m_code"]
                self.mode = shape["mode"]

                self.finalize_shape(
                    cx, cy, r, bb, key_name, bridge_key, hex_code, l_move_camera
                )

            self.reset_state()
            self.json_path = Path(file_path)
            print(f"[PLOTTER] - Loaded JSON file: {self.json_path.as_posix()}")

    def change_image(self):
        image_path = self.select_image_file()
        if image_path:
            last_image_path = self.image_path
            self.image_path = Path(image_path)
            img = self.load_image()
            if img is None:
                self.image_path = last_image_path
                print("Could not load image, image path reset to the last value")
                return

            self.init_params_helper()
            self.update_image_params(img)
            self.clear_visuals()  # Call it here so we don't get any errors with reset state trying to remove already removed artists by the ax.clear() in the next line
            self.ax.clear()
            self.ax.imshow(img)

            self.init_crosshairs()
            self.reset_state()
            print("Cleared previous shapes and artists, figure reset.")
            print(f"Swapped HUD to: {self.image_path.as_posix()}")

    def toggle_visibility(self):
        self.show_overlays = not self.show_overlays
        state_str = "VISIBLE" if self.show_overlays else "HIDDEN"
        print(f"[PLOTTER] - Overlays are now {state_str}")

        for artist in self.shapes_artists.values():
            artist.set_visible(self.show_overlays)
        for artist in self.labels_artists.values():
            artist.set_visible(self.show_overlays)

        self.update_title(f"OVERLAYS: {state_str} | {DEF_STR}")

    def label(self, center_x, center_y, label, fc):
        # Get the height of the figure in inches and convert to points
        fig_height_pts = self.fig.get_size_inches()[1] * 72
        scaled_font = max(5, int(round(fig_height_pts * 0.02)))

        return Text(
            center_x,
            center_y,
            label,
            color="white",
            fontsize=scaled_font,
            fontweight="bold",
            ha="center",
            va="center",
            # This zorder keeps the label above the shape
            zorder=12,
            bbox=dict(fc=fc, ec="black", lw=1.5, boxstyle="round,pad=0.3"),
        )

    # Event Handlers
    def on_mouse_move(self, event):
        if self.state == COLLECTING and event.inaxes == self.ax:
            # Round to integer for the "Snap to Pixel" feel
            x, y = int(round(event.xdata)), int(round(event.ydata))

            # Capture background if we don't have it yet
            # Note: We do this only when the mouse is actually inside to save memory
            if self.bg_cache is None:
                self.bg_cache = self.fig.canvas.copy_from_bbox(self.ax.bbox)  # type: ignore

            # Restore the clean background (removes the crosshair from the previous frame)
            self.fig.canvas.restore_region(self.bg_cache)  # type: ignore

            # Update and draw Horizontal lines (BG then FG for proper z-order layering)
            for line in [self.crosshair_h_bg, self.crosshair_h_fg]:
                line.set_visible(True)
                line.set_ydata([y, y])
                self.ax.draw_artist(line)

            # Update and draw Vertical lines (BG then FG for proper z-order layering)
            for line in [self.crosshair_v_bg, self.crosshair_v_fg]:
                line.set_visible(True)
                line.set_xdata([x, x])
                self.ax.draw_artist(line)

            # Push these updates specifically to the axes area (using blitting)
            self.fig.canvas.blit(self.ax.bbox)

        else:
            # If mouse leaves the area or we stop collecting, hide lines and redraw once
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
            hovering_now = None

            if self.ignore_current_draggable_id_n > 0:
                return

            if not hovering_now:
                for uid, manager in self.label_drag_managers.items():
                    contains, _ = manager.label_artist.contains(event)
                    if contains:
                        hovering_now = (uid, manager, "label")
                        break  # Found one, stop looking

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

        # Handle Binding via Mouse Click
        if self.state == WAITING_FOR_KEY:
            # Matplotlib button codes: 1=Left, 2=Middle, 3=Right
            mouse_map = {1: "MOUSE_LEFT", 2: "MOUSE_MIDDLE", 3: "MOUSE_RIGHT"}

            button_name = mouse_map.get(event.button)

            if button_name:
                self.calculate_shape(button_name)
            return

        # Handle Drawing Points
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
            self.update_title(f"Shape Defined! Press KEY or CLICK MOUSE to bind.")

    def on_key_press(self, event):
        """Main Input Router."""
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
                print("[-] Closing application.")
                plt.close()
            else:
                self.reset_state()
            return

        if self.state == COLLECTING:
            if event.key == "f8":
                print("[-] Action Cancelled.")
                self.reset_state()
            else:
                print(
                    f"[PLOTTER] - Blocked: Finish or Cancel (F8) current shape first."
                )
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
            elif event.key == "f3":
                self.load_json()
            elif event.key == "f4":
                self.toggle_visibility()
            elif event.key == "f5":
                self.change_image()
            elif event.key == "f6":
                self.start_mode(CIRCLE, 3)
            elif event.key == "f7":
                self.start_mode(RECT, 4)
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
                if clean_key == "left":
                    if self.current_draggable:
                        self.current_draggable.move(
                            -step, 0
                        )  # x is decreasing leftward, y stays constant
                elif clean_key == "right":
                    if self.current_draggable:
                        self.current_draggable.move(
                            step, 0
                        )  # x is increasing rightward, y stays constants
                elif clean_key == "up":
                    if self.current_draggable:
                        self.current_draggable.move(
                            0, -step
                        )  # y is decreasing upward, x stays constant
                elif clean_key == "down":
                    if self.current_draggable:
                        self.current_draggable.move(
                            0, step
                        )  # y is increasing downward, x stays constant

    def on_resize(self, event):
        """Updates the font size of all labels when the figure is resized."""
        if not self.labels_artists:
            return

        # Recalculate font size based on new figure height
        fig_height_pts = self.fig.get_size_inches()[1] * 72
        scaled_font = max(5, int(round(fig_height_pts * 0.02)))

        # Update the fontsize for all tracked text artists
        for label_artist in self.labels_artists.values():
            label_artist.set_fontsize(scaled_font)

        self.fig.canvas.draw_idle()

    # Delete Logic
    def enter_deleting_mode(self):
        if not self.shapes:
            print("[PLOTTER] - No shapes to delete.")
            self.update_title(f"List empty. Nothing to delete | {HELP_STR}")
            return

        self.state = DELETING
        self.input_buffer = ""
        self.update_title("DELETE MODE: Type ID... (Enter to Confirm | Esc to Cancel)")

    def delete_all_shapes(self):
        if not self.shapes:
            print("[PLOTTER] - No shapes to delete.")
            self.update_title(f"List empty. Nothing to delete | {HELP_STR}")
            return

        for uid in list(self.shapes.keys()):
            self.delete_entry(uid)
        self.count = 0
        self.reset_state()
        print("[PLOTTER] - All shapes deleted.")

    def handle_deleting_input(self, key):
        if key == "escape":
            self.reset_state()
            return

        elif key == "enter":
            if self.input_buffer:
                try:
                    uid = int(self.input_buffer)

                    if uid in self.shapes:
                        if key == "enter" and uid in self.shapes:
                            self.delete_entry(uid)
                            self.update_title(f"Deleted ID {uid}. Returning to IDLE...")
                            self.reset_state()

                    else:
                        print(f"[PLOTTER] - ID {uid} not found.")
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

        elif key.isdigit():
            self.input_buffer += key
            self.update_title(
                f"DELETE MODE: ID [{self.input_buffer}] (Enter to delete | Esc to Cancel)"
            )
        elif key == "backspace":
            self.input_buffer = self.input_buffer[:-1]
            self.update_title(
                f"DELETE MODE: ID [{self.input_buffer}] (Enter to delete | Esc to Cancel)"
            )
        else:
            print("[PLOTTER] - Blocked: Exit Delete Mode (Esc) first.")

    def delete_entry(self, uid):
        """Removes a shape and all its associated resources (artists, labels, listeners)."""
        if uid not in self.shapes:
            return

        shape_data = self.shapes[uid]
        bridge_key = shape_data["bridge_key"]
        shape_type = shape_data["type"]
        hex_code = shape_data["m_code"]

        # CENTRALIZED CASCADE LOGIC
        if bridge_key == MOUSE_WHEEL_CODE:
            # Delete dependent Sprint points automatically
            sprint_uids = [
                k
                for k, v in self.shapes.items()
                if v["bridge_key"] == SPRINT_DISTANCE_CODE
            ]
            for sid in sprint_uids:
                self.delete_entry(sid)  # Recursive call cleans the child

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

        print(
            f'[PLOTTER] - Deleted Shape of type: {shape_type} with ID: {uid} and key: "{bridge_key}" (hex: {hex_code})'
        )

    # Marking Logic
    def enter_marking_mode(self):
        if not self.shapes:
            print("[PLOTTER] - No shapes to mark.")
            self.update_title(f"List empty. Nothing to mark | {HELP_STR}")
            return

        self.state = MARKING
        self.input_buffer = ""
        self.update_title("MARK MODE: Type ID... (Enter to Confirm | Esc to Cancel)")

    def handle_marking_input(self, key):

        if key == "escape":
            self.reset_state()
            return

        elif key == "enter":
            if self.input_buffer:
                try:
                    uid = int(self.input_buffer)

                    if uid in self.shapes:
                        marked_key = self.shapes[uid]
                        was_marked = marked_key["move_camera"]
                        self.shapes[uid]["move_camera"] = not was_marked
                        status = (
                            "MARKED for Camera Follow"
                            if not was_marked
                            else "UNMARKED for Camera Follow"
                        )
                        marked_i_key = marked_key["bridge_key"]
                        marked_m_code = marked_key["m_code"]
                        print(
                            f'[PLOTTER] - {status}: ID {uid} with key "{marked_i_key}" (hex: {marked_m_code})'
                        )

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
                        print(f"[PLOTTER] - ID {uid} not found.")
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

        elif key.isdigit():
            self.input_buffer += key
            self.update_title(
                f"MARK MODE: ID [{self.input_buffer}] (Enter to mark | Esc to Cancel)"
            )
        elif key == "backspace":
            self.input_buffer = self.input_buffer[:-1]
            self.update_title(
                f"MARK MODE: ID [{self.input_buffer}] (Enter to mark | Esc to Cancel)"
            )
        else:
            print("[PLOTTER] - Blocked: Exit Mark Mode (Esc) first.")

    # Shape Calculation & Finalization

    def calculate_shape(self, key_name):
        # 'key_name' might be a key string ('a', 'f1') OR a mouse string ('MOUSE_LEFT')
        hex_code, bridge_key = get_scancode_and_bridge_key_from_key(key_name)

        if hex_code is None:
            print(f'[PLOTTER] - Key "{key_name}" not mapped.')
            return

        cx, cy, r, bb = None, None, None, None
        if self.mode == CIRCLE:
            cx, cy, r, bb = self.calculate_circle()
        elif self.mode == RECT:
            cx, cy, r, bb = self.calculate_rect()

        self.finalize_shape(cx, cy, r, bb, key_name, bridge_key, hex_code)
        self.reset_state()

    def finalize_shape(
        self, cx, cy, r, bb, key_name, bridge_key, hex_code, move_camera=False
    ):
        if cx is not None:
            saved, entry_id = self.save_entry(
                bridge_key, hex_code, cx, cy, r, bb, move_camera
            )

            if saved:
                label = bridge_key
                if bridge_key == MOUSE_WHEEL_CODE:
                    label = "MOUSE_WHEEL"
                elif bridge_key == SPRINT_DISTANCE_CODE:
                    label = "SPRINT_DISTANCE"
                else:
                    label = label.split("E0_")[-1]

                print(
                    f'[PLOTTER] - Saved ID {self.count-1}: {self.mode} bound to key "{key_name}" with interception key: "{bridge_key}" and labelled as: "{label}"'
                )

                if self.mode == CIRCLE and cx and cy and r:
                    if bridge_key == MOUSE_WHEEL_CODE:
                        fc = DEFAULT_MOUSE_WHEEL_FACE_COLOR  # Bright Cyan/Teal
                    elif bridge_key == SPRINT_DISTANCE_CODE:
                        fc = DEFAULT_SPRINT_DISTANCE_FACE_COLOR  # Bright Red
                    else:
                        fc = get_vibrant_random_color(DEFAULT_FACE_COLOR_ALPHA)
                    # Add shape artist
                    shape_artist = Circle(
                        (cx, cy), r, fill=True, lw=2, fc=fc, ec=DEFAULT_EDGE_COLOR
                    )
                    shape_artist.set_visible(self.show_overlays)
                    self.ax.add_patch(shape_artist)
                    self.shapes_artists[entry_id] = shape_artist
                    # Add label artist
                    label_artist = self.label(cx, cy, label, fc)
                    label_artist.set_visible(self.show_overlays)
                    self.ax.add_artist(label_artist)
                    self.labels_artists[entry_id] = label_artist
                    # Make the label draggable
                    self.label_drag_managers[entry_id] = _DraggableLabel(entry_id, self)
                    # Make the shape draggable
                    self.shape_drag_managers[entry_id] = _DraggableShape(
                        entry_id, self, CIRCLE
                    )

                    if move_camera:
                        self.label_drag_managers[entry_id].dull_face_color()
                        self.shape_drag_managers[entry_id].dull_face_color()

                elif self.mode == RECT and cx and cy and bb:
                    if (
                        bridge_key == MOUSE_WHEEL_CODE
                        or bridge_key == SPRINT_DISTANCE_CODE
                    ):
                        print(
                            f'[PLOTTER] - Warning: Special keys like "{bridge_key}" should be bound to CIRCLE shapes for better visualization. Consider re-binding this key to a CIRCLE shape.'
                        )
                    else:
                        fc = get_vibrant_random_color(DEFAULT_FACE_COLOR_ALPHA)
                        (x1, y1), (x2, y2) = bb
                        # Add shape artist
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
                        # Add label artist
                        label_artist = self.label(cx, cy, label, fc)
                        label_artist.set_visible(self.show_overlays)
                        self.ax.add_artist(label_artist)
                        self.labels_artists[entry_id] = label_artist
                        # Make the label draggable
                        self.label_drag_managers[entry_id] = _DraggableLabel(
                            entry_id, self
                        )
                        # Make the shape draggable
                        self.shape_drag_managers[entry_id] = _DraggableShape(
                            entry_id, self, RECT
                        )

                        if move_camera:
                            self.label_drag_managers[entry_id].dull_face_color()
                            self.shape_drag_managers[entry_id].dull_face_color()

    # Naming / Saving Logic
    def enter_naming_mode(self):
        if not self.shapes:
            self.update_title(f"Nothing to save! | {HELP_STR}")
            return

        self.state = NAMING
        self.input_buffer = ""
        self.buffer_default = True

        if self.json_path and self.json_path.exists():
            self.input_buffer = self.json_path.stem
            self.update_title(
                f"SAVE: {self.input_buffer} (Type to Edit | Enter to Save | Esc to Cancel)"
            )
        else:
            self.update_title("SAVE: Type Name... (Enter for Default | Esc to Cancel)")

    def handle_naming_input(self, key):
        if key == "escape":
            self.reset_state()
            return

        elif key == "enter":
            final_name = self.input_buffer.strip()
            self.export_data(final_name if final_name else "")
            self.reset_state()
            return

        elif key == "backspace":
            if not self.input_buffer and self.json_path and self.json_path.exists():
                self.buffer_default = True
                self.input_buffer = self.json_path.stem

            else:
                if self.buffer_default:
                    self.input_buffer = ""
                    self.buffer_default = False
                else:
                    self.input_buffer = self.input_buffer[:-1]

        elif len(key) == 1 and (key.isalnum() or key in ["_"]):
            if self.buffer_default:
                self.input_buffer = ""
                self.buffer_default = False
            self.input_buffer += key

        if not self.input_buffer and self.json_path and self.json_path.exists():
            display_name = "[Auto-Timestamp]"
            instruction = "(Type Name | Backspace to Restore | Esc to Cancel)"
        else:
            display_name = (
                self.input_buffer if self.input_buffer else "[Auto-Timestamp]"
            )
            instruction = "(Enter to Save | Esc to Cancel)"

        self.update_title(f"SAVE: {display_name} {instruction}")

    def export_data(self, user_name):
        if self.buffer_default and self.json_path and self.json_path.exists():
            # Confirm Overwrite
            msg_box = QMessageBox()
            msg_box.setIcon(QMessageBox.Icon.Question)
            msg_box.setText("Overwrite Warning")
            msg_box.setInformativeText(
                f"File '{self.json_path.name}' already exists in the current folder. Overwrite?"
            )
            msg_box.setStandardButtons(
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
            )
            msg_box.setDefaultButton(QMessageBox.StandardButton.No)

            ret = msg_box.exec_()

            if ret == QMessageBox.StandardButton.No:
                print("[PLOTTER] - Save cancelled by user.")
                self.update_title(f"Save cancelled | {HELP_STR}")
                return

            file_path = self.json_path
            print(f"[PLOTTER] - Overwriting existing file: {file_path.as_posix()}")

        else:
            if not user_name:
                user_name = datetime.datetime.now().strftime("map_%Y%m%d_%H%M%S")

            try:
                # Try to mirror the image folder structure
                relative_path_parent = self.image_path.relative_to(
                    Path(IMAGES_FOLDER)
                ).parent
                target_dir = Path(JSONS_FOLDER) / relative_path_parent
            except ValueError:
                # Fallback if image is outside the project folder
                print("[PLOTTER] - Image is external. Saving JSON to root folder.")
                target_dir = Path(JSONS_FOLDER)

            file_path = target_dir / f"{user_name}.json"
            target_dir.mkdir(parents=True, exist_ok=True)

        output = []

        for _, data in self.shapes.items():
            entry = {
                "name": data["bridge_key"],  # Interception Key Name
                "scancode": data["m_code"],  # Saved as hex string "0x..."
                "type": data["type"],
                "cx": data["cx"],
                "cy": data["cy"],
                # Initialize vals to 0/null
                "val1": 0,
                "val2": 0,
                "val3": 0,
                "val4": 0,
                "move_camera": data[
                    "move_camera"
                ],  # Indicates if button should move camera
            }

            if data["type"] == CIRCLE:
                entry["val1"] = data["r"]
                # val 2, 3, 4 remain 0

            elif data["type"] == RECT:
                (x_min, y_min), (x_max, y_max) = data["bb"]
                entry["val1"] = x_min
                entry["val2"] = y_min
                entry["val3"] = x_max
                entry["val4"] = y_max

            output.append(entry)

        json_output = {
            "metadata": {
                "width": self.width,
                "height": self.height,
                "dpi": self.dpi,
                "mouse_wheel_radius": self.mouse_wheel_radius,
                "sprint_distance": self.sprint_distance,
            },
            "content": output,
        }

        try:
            if (not self.saved_mouse_wheel) or (self.saved_sprint_distance == False):
                # Confirm Save without Mouse Wheel or Sprint Distance
                msg_box = QMessageBox()
                msg_box.setIcon(QMessageBox.Icon.Question)
                msg_box.setText("Configuration Warning")
                msg_box.setInformativeText(
                    "Mouse Wheel or Sprint Distance has not been configured. Save?"
                )
                msg_box.setStandardButtons(
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
                )
                msg_box.setDefaultButton(QMessageBox.StandardButton.No)

                ret = msg_box.exec_()

                if ret == QMessageBox.StandardButton.No:
                    print("[PLOTTER] - Save cancelled by user.")
                    self.update_title(f"Save cancelled | {HELP_STR}")
                    return

            with file_path.open("w", encoding="utf-8") as f:
                json.dump(json_output, f, indent=4)

            print(f"[PLOTTER] - JSON file saved to: {file_path.as_posix()}")

            update_toml(
                self.width,
                self.height,
                self.dpi,
                str(self.image_path),
                str(file_path),
                self.mouse_wheel_radius,
                self.sprint_distance,
                True,
            )

            self.json_path = file_path

        except Exception as e:
            print(f"[PLOTTER] - Export Error: {e}")
            self.update_title(f"Error saving: {file_path.name} | {HELP_STR}")
            return

        self.update_title(f"SAVED: {file_path.name} | {HELP_STR}")

    def save_entry(self, bridge_key, hex_code, cx, cy, r, bb, move_camera):
        uid = self.count
        inc_count = True
        saved = False

        if bridge_key == MOUSE_WHEEL_CODE:
            if self.mode == CIRCLE:
                if self.saved_mouse_wheel:
                    print(
                        f"[PLOTTER] - Mouse Wheel already assigned. Overwriting previous assignment."
                    )
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

            elif self.mode == RECT:
                print(
                    f"[PLOTTER] - Error: Mouse Wheel can only be assigned to '{CIRCLE}' not '{RECT}' shapes."
                )
                return saved, uid

        elif bridge_key == SPRINT_DISTANCE_CODE:
            if self.mode == CIRCLE:
                if not self.saved_mouse_wheel:
                    print(
                        f"[PLOTTER] - Error: Mouse Wheel not assigned yet. Please assign it first."
                    )
                    return saved, uid

                if self.saved_sprint_distance:
                    print(
                        f"[PLOTTER] - Error: Sprint Threshold already assigned. Overwriting previous assignment."
                    )
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
                # STRICT CHECK: Ensure Sprint is actually outside the Joystick
                if actual_dist <= self.mouse_wheel_radius:
                    print(
                        f"[PLOTTER] - Error: Sprint point must be OUTSIDE the joystick radius!"
                    )
                    return False, uid

                self.sprint_distance = actual_dist
                self.saved_sprint_distance = True
                self.sprint_artist_id = uid

            elif self.mode == RECT:
                print(
                    f"[PLOTTER] - Error: Sprint Distance can only be assigned to '{CIRCLE}' not '{RECT}' shapes."
                )
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

        saved = True
        return saved, uid

    def print_data(self):
        if not self.shapes:
            print("[PLOTTER] - No shapes to print.")
            self.update_title(f"List empty. Nothing to print | {HELP_STR}")
            return

        print("\n")
        print("Current Shapes:")
        for k, v in self.shapes.items():
            print(k, v)
        print("\n")

    # Math
    def calculate_circle(self):  # 3 Points
        if len(self.points) < 3:
            return None, None, None, None

        x1, y1 = self.points[0]
        x2, y2 = self.points[1]
        x3, y3 = self.points[2]
        D = 2 * (x1 * (y2 - y3) + x2 * (y3 - y1) + x3 * (y1 - y2))
        if D == 0:
            self.update_title("Error: Points are collinear.")
            return None, None, None, None

        h = (
            (x1**2 + y1**2) * (y2 - y3)
            + (x2**2 + y2**2) * (y3 - y1)
            + (x3**2 + y3**2) * (y1 - y2)
        ) / D
        k = (
            (x1**2 + y1**2) * (x3 - x2)
            + (x2**2 + y2**2) * (x1 - x3)
            + (x3**2 + y3**2) * (x2 - x1)
        ) / D
        r = math.sqrt((x1 - h) ** 2 + (y1 - k) ** 2)

        return int(round(h)), int(round(k)), int(round(r)), None

    def calculate_rect(self):  # 4 Points
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

    def calculate_raw_rect(self, values):  # 2 Points
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
        """
        Rotates a point (cx, cy) around a pivot (px, py) until it fits inside a rectangle.
        Maintains the original distance (radius) from the pivot.

        Args:
            cx, cy:   The center of the 'Main Circle' (Sprint point)
            px, py:   The center of the 'Provided Point' (Pivot/Joystick center)
            rect_bb:  Tuple ((x_min, y_min), (x_max, y_max)) bounding box

        Returns:
            (new_x, new_y): The corrected coordinates.
        """
        (x_min, y_min), (x_max, y_max) = rect_bb

        # Check if already inside (Optimization)
        if x_min <= cx <= x_max and y_min <= cy <= y_max:
            return cx, cy

        # Define the fixed orbit radius
        radius = math.sqrt((cx - px) ** 2 + (cy - py) ** 2)
        if radius < 1e-9:
            return cx, cy  # Pivot and point are identical

        current_angle = math.atan2(cy - py, cx - px)
        valid_intersections = []

        # Helper: Check if a point lies on a specific line segment
        def on_segment(x, y, x1, y1, x2, y2):
            # Use epsilon for float comparison stability
            epsilon = 1e-9
            return (
                min(x1, x2) - epsilon <= x <= max(x1, x2) + epsilon
                and min(y1, y2) - epsilon <= y <= max(y1, y2) + epsilon
            )

        # Intersect Orbit Circle with all 4 Rectangle Edges
        # Edges defined as (x1, y1, x2, y2)
        edges = [
            (x_min, y_min, x_min, y_max),  # Left
            (x_max, y_min, x_max, y_max),  # Right
            (x_min, y_min, x_max, y_min),  # Bottom
            (x_min, y_max, x_max, y_max),  # Top
        ]

        for x1, y1, x2, y2 in edges:
            # Vertical Edge (x is constant)
            if abs(x1 - x2) < 1e-9:
                dx = x1 - px
                # Does the circle reach this x-coordinate?
                if abs(dx) <= radius:
                    # Solve: y = py +/- sqrt(r^2 - dx^2)
                    dy = math.sqrt(radius**2 - dx**2)
                    candidates = [(x1, py + dy), (x1, py - dy)]
                    for ix, iy in candidates:
                        if on_segment(ix, iy, x1, y1, x2, y2):
                            valid_intersections.append((ix, iy))

            # Horizontal Edge (y is constant)
            else:
                dy = y1 - py
                # Does the circle reach this y-coordinate?
                if abs(dy) <= radius:
                    # Solve: x = px +/- sqrt(r^2 - dy^2)
                    dx = math.sqrt(radius**2 - dy**2)
                    candidates = [(px + dx, y1), (px - dx, y1)]
                    for ix, iy in candidates:
                        if on_segment(ix, iy, x1, y1, x2, y2):
                            valid_intersections.append((ix, iy))

        # Find the intersection closest to the original angle
        if not valid_intersections:
            # Fallback: Clamp to nearest point on box (changing radius)
            clamped_x = max(x_min, min(cx, x_max))
            clamped_y = max(y_min, min(cy, y_max))
            return clamped_x, clamped_y

        candidates = []

        for ix, iy in valid_intersections:
            # Calculate angle of intersection point
            target_angle = math.atan2(iy - py, ix - px)

            # Get shortest difference between angles
            # This handles the -180 to 180 wrap-around gracefully
            diff = math.atan2(
                math.sin(target_angle - current_angle),
                math.cos(target_angle - current_angle),
            )

            candidates.append({"pt": (ix, iy), "diff": abs(diff), "y": iy})

        # SORTING LOGIC:
        # Primary: Angle Difference (Round to 5 decimals to force ties on float errors)
        # Secondary: Y Coordinate (Ascending = Top of Screen preference)
        candidates.sort(key=lambda c: (round(c["diff"], 5), c["y"]))

        # Return the coordinate of the winner
        return candidates[0]["pt"]

    def _del_(self):
        sys.exit(self.app.exec_())


def run():
    Plotter()


if __name__ == "__main__":
    run()
