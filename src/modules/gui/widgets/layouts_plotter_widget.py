from __future__ import annotations

import sys
import datetime
import math
import os
from pathlib import Path
from PIL import Image

from modules.platforms import get_platform, get_specific_mt_key
get_platform().SystemConfig().set_dpi_awareness()

from modules.utils import (
    BEZEL_DP_THICKNESS,
    CIRCLE,
    RECTANGLE,
    BASELINE_DPI,
    IMAGES_FOLDER,
    MOUSE_WHEEL_SIMULATOR_CODE,
    SPRINT_DISTANCE_CODE,
    IDLE,
    BEZEL,
    TOP_BEZEL_ID,
    BOTTOM_BEZEL_ID,
    dp_to_px,
    get_scancode_and_bridge_key_from_key,
    get_key_from_scancode,
    rotate_resolution,
    get_vibrant_random_color,
    get_dulled_hue_color,
    get_hue_modified_alpha_from_hsv,
    make_copy_name,
)

from modules.core.pipeline import PipelineConfig
from modules.database import store

if sys.platform == "win32":
    os.environ["QT_LOGGING_RULES"] = "qt.qpa.window=false"

import matplotlib
matplotlib.use("qtagg")
from matplotlib.figure import Figure
from matplotlib.patches import Circle, Rectangle
from matplotlib.text import Text
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg as FigureCanvas

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QWidget, QVBoxLayout
from PySide6.QtGui import QKeySequence, QShortcut

COLLECTING = "COLLECTING"
WAITING_FOR_KEY = "WAITING_FOR_KEY"
NAMING = "NAMING"
DELETING = "DELETING"
MARKING = "MARKING"
CONFIRM_DELETE_ALL = "CONFIRM_DELETE_ALL"
CONFIRM_EXIT = "CONFIRM_EXIT"

INDICATED_EDGE_COLOR = (0.85, 0.88, 0.92)
ACTIVE_EDGE_COLOR = (0.7, 0.7, 0.7, 0.8)
DEFAULT_EDGE_COLOR = (0.3, 0.3, 0.3, 0.8)
DEFAULT_MOUSE_WHEEL_FACE_COLOR = (0.0, 0.8, 0.8, 0.4)
DEFAULT_SPRINT_DISTANCE_FACE_COLOR = (1.0, 0.2, 0.2, 0.5)
DEFAULT_FACE_COLOR_ALPHA = 0.4
DEFAULT_SMALL_LINE_WIDTH = 1.5
DEFAULT_MEDIUM_LINE_WIDTH = 2
DEFAULT_LARGE_LINE_WIDTH = 3

def calculate_raw_rect(values: tuple[tuple[float, float], tuple[float, float]]):
    if len(values) < 2: return None, None, None, None
    xs = [v[0] for v in values]
    ys = [v[1] for v in values]
    return (int(round(sum(xs) / 2)), int(round(sum(ys) / 2)), None, ((min(xs), min(ys)), (max(xs), max(ys))))

class _CursorManager:
    def __init__(self, canvas: FigureCanvas):
        self.canvas = canvas
        self.state_map = {
            IDLE: Qt.CursorShape.ArrowCursor,
            COLLECTING: Qt.CursorShape.CrossCursor,
            WAITING_FOR_KEY: Qt.CursorShape.PointingHandCursor,
            NAMING: Qt.CursorShape.IBeamCursor,
            DELETING: Qt.CursorShape.ForbiddenCursor,
            MARKING: Qt.CursorShape.PointingHandCursor,
            CONFIRM_DELETE_ALL: Qt.CursorShape.WaitCursor,
            CONFIRM_EXIT: Qt.CursorShape.WaitCursor,
        }

    def set_state_cursor(self, state: str):
        self.canvas.setCursor(self.state_map.get(state, Qt.CursorShape.ArrowCursor))

    def set_custom_cursor(self, shape: Qt.CursorShape):
        self.canvas.setCursor(shape)

class _Draggable:
    def __init__(self, entry_id: int, is_shape: bool, plotter_ref):
        self.entry_id = entry_id
        self.plotter = plotter_ref
        self.cursor_manager = plotter_ref.cursor_manager
        self.min_move_distance = 3
        self.is_shape = is_shape

        if is_shape:
            self.artist_id = "shape_" + str(entry_id)
            self.default_face_color = self.plotter.shapes_artists[entry_id].get_facecolor()
        else:
            self.artist_id = "label_" + str(entry_id)
            label_bbox = self.plotter.labels_artists[entry_id].get_bbox_patch()
            self.default_face_color = label_bbox.get_facecolor() if label_bbox else None

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
                idx = self.plotter.draggables_ids.index(self.plotter.last_artist_id)
                self.plotter.iter_count = 0
                return self.plotter.draggables_ids[(idx + 1) % len(self.plotter.draggables_ids)]
            else:
                return self.plotter.last_artist_id
        else:
            self.plotter.iter_count = 0
            return self.plotter.draggables_ids[0]

    def indicate_current_draggable_id(self):
        curr_id = self.plotter.current_draggable_id
        if curr_id is None: return

        self.plotter.zone_selected.emit(self.entry_id)
        priority = self.plotter.shapes[self.entry_id].get("priority", 0)
        pointer_info = "Pointer Enabled" if self.plotter.shapes[self.entry_id]["pointer"] else "Pointer Disabled"

        if curr_id.startswith("label_"):
            draggable_artist = self.plotter.label_drag_managers.get(self.entry_id)
            if draggable_artist and draggable_artist.artist_id == curr_id:
                label_bbox = draggable_artist.label_artist.get_bbox_patch()
                if label_bbox:
                    label_bbox.set_edgecolor(INDICATED_EDGE_COLOR)
                    label_bbox.set_linewidth(DEFAULT_MEDIUM_LINE_WIDTH)
                self.plotter.update_title(f"Current Artist: {curr_id} (ID: {self.entry_id}, Prio: {priority}) | Drag/Nudge | {pointer_info}", True)
            self.plotter.current_draggable = draggable_artist

        elif curr_id.startswith("shape_"):
            draggable_artist = self.plotter.shape_drag_managers.get(self.entry_id)
            if draggable_artist and draggable_artist.artist_id == curr_id:
                if (shape_artist := draggable_artist.shape_artist) is not None:
                    shape_artist.set_edgecolor(INDICATED_EDGE_COLOR)
                    shape_artist.set_linewidth(DEFAULT_LARGE_LINE_WIDTH)
                self.plotter.update_title(f"Current Artist: {curr_id} (ID: {self.entry_id}, Prio: {priority}) | Drag/Resize/Nudge | {pointer_info}", True)
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
            shape.set_facecolor(get_dulled_hue_color(*get_hue_modified_alpha_from_hsv(self.default_face_color)))
        else:
            label_bbox = self.plotter.labels_artists[self.entry_id].get_bbox_patch()
            if label_bbox:
                label_bbox.set_facecolor(get_dulled_hue_color(*get_hue_modified_alpha_from_hsv(self.default_face_color)))

    def restore_face_color(self):
        if self.is_shape:
            self.plotter.shapes_artists[self.entry_id].set_facecolor(self.default_face_color)
        else:
            label_bbox = self.plotter.labels_artists[self.entry_id].get_bbox_patch()
            if label_bbox:
                label_bbox.set_facecolor(self.default_face_color)

class _DraggableLabel(_Draggable):
    def __init__(self, entry_id: int, plotter_ref):
        super().__init__(entry_id, False, plotter_ref)
        self.label_artist = self.plotter.labels_artists[entry_id]
        self.shape_artist = self.plotter.shapes_artists[entry_id]
        self.canvas = self.plotter.canvas
        self.press = None
        self.drag_bg = None
        self._connect_cids()

    def _connect_cids(self):
        if self.canvas.supports_blit:
            self.cids = [
                self.canvas.mpl_connect("button_press_event", self._on_press),
                self.canvas.mpl_connect("motion_notify_event", self._on_motion),
                self.canvas.mpl_connect("button_release_event", self._on_release),
            ]

    def _on_press(self, event):
        self.plotter.ignore_current_draggable_id_n += 1
        self._on_press_helper(event)
        self.plotter.fire_on_motion = True

    def _on_press_helper(self, event):
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
        if label_bbox: label_bbox.set_edgecolor("black")
        if self.label_artist.get_visible():
            self.shape_artist.set_visible(True)
            self.populate_draggables_list()

        self.canvas.draw_idle()

    def _on_motion(self, event):
        if not self.plotter.fire_on_motion or self.label_artist.axes is None: return
        if self.press is None or event.inaxes != self.label_artist.axes: return

        if self.plotter.current_draggable_id is None:
            self.plotter.current_draggable_id = self.select_current_draggable_id()
            self.indicate_current_draggable_id()

        if self.plotter.current_draggable_id != self.artist_id: return

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
            if self.label_artist.axes.bbox.width > 0 and self.label_artist.axes.bbox.height > 0:
                self.drag_bg = self.canvas.copy_from_bbox(self.label_artist.axes.bbox)
            self.label_artist.set_visible(True)
            self.plotter.drawn = True

        _, _, xdata_press, ydata_press, xpx_press, ypx_press = self.press
        dx = event.xdata - xdata_press
        dy = event.ydata - ydata_press
        dx_press = event.x - xpx_press
        dy_press = event.y - ypx_press
        self.plotter.current_move_distance = ((dx_press**2) + (dy_press**2)) ** 0.5

        if self.drag_bg is not None:
            self.canvas.restore_region(self.drag_bg)
        self.move_label(dx, dy)
        self.label_artist.axes.draw_artist(self.label_artist)
        self.canvas.blit(self.label_artist.axes.bbox)

    def move_label(self, dx, dy):
        if not self.press: return
        x0, y0, _, _, _, _ = self.press
        self.label_artist.set_position((x0 + dx, y0 + dy))

    def _move(self, dx, dy):
        if not self.press: return
        _, _, xdata_press, ydata_press, xpx_press, ypx_press = self.press
        x, y = self.label_artist.get_position()
        self.press = x, y, xdata_press, ydata_press, xpx_press, ypx_press
        self.move_label(dx, dy)
        self.canvas.draw()
        self.plotter.drawn = False

    def _on_release(self, event):
        self._partial_release()
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

    def _partial_release(self):
        if self.plotter.ignore_current_draggable_id_n <= 0:
            self.plotter.update_title(f"OVERLAYS: {'VISIBLE' if self.plotter.show_overlays else 'HIDDEN'}", True)

        label_bbox = self.label_artist.get_bbox_patch()
        if label_bbox:
            label_bbox.set_edgecolor("black")
            label_bbox.set_linewidth(DEFAULT_SMALL_LINE_WIDTH)

    def _disconnect_cids(self):
        for cid in self.cids:
            self.canvas.mpl_disconnect(cid)

class _DraggableShape(_Draggable):
    def __init__(self, entry_id: int, plotter_ref):
        super().__init__(entry_id, True, plotter_ref)
        self.label_artist = self.plotter.labels_artists[entry_id]
        self.shape_artist = None
        self.canvas = self.plotter.canvas
        self.press = None
        self.drag_bg = None
        self.shape_mode = None
        self.cids = []

        self.radial_tolerance = 5
        self.edge_tolerance = 5
        self.vertex_tolerance = 10
        self.min_rectangle_dist = 50
        self.min_circle_dist = 30
        self.spec_max_ratio = 0.3

    def _connect_cids(self) -> None: ...
    def _move(self, dx, dy) -> None: ...

    def _on_press(self, event):
        self.plotter.ignore_current_draggable_id_n += 1
        self._on_press_helper(event)
        self.plotter.fire_on_motion = True

    def _on_press_helper(self, event):
        if self.shape_artist is None: return
        self.plotter.fire_on_motion = False
        self.press = None
        self.drag_bg = None
        self.shape_mode = None

        if event.inaxes != self.shape_artist.axes:
            self.plotter.ignore_current_draggable_id_n -= 1
            return

        contains, _ = self.shape_artist.contains(event)
        if not contains:
            self.plotter.ignore_current_draggable_id_n -= 1
            return

        coords = self._on_press_shape_helper(event)
        if coords is not None:
            self.press = *coords, event.xdata, event.ydata, event.x, event.y

        self.shape_artist.set_edgecolor(DEFAULT_EDGE_COLOR)
        if self.shape_artist.get_visible():
            self.label_artist.set_visible(True)
            self.populate_draggables_list()

        self.canvas.draw_idle()

    def _on_press_shape_helper(self, event) -> tuple[float, float] | None: ...
    def _shape_transform(self, event) -> None: ...

    def _on_motion(self, event):
        if not isinstance(self.shape_artist, Circle): return
        if not self.plotter.fire_on_motion or self.shape_artist.axes is None: return
        if self.press is None or event.inaxes != self.shape_artist.axes: return

        if self.plotter.current_draggable_id is None:
            self.plotter.current_draggable_id = self.select_current_draggable_id()
            self.indicate_current_draggable_id()

        if self.plotter.current_draggable_id != self.artist_id: return
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
            if self.shape_artist.axes.bbox.width > 0 and self.shape_artist.axes.bbox.height > 0:
                self.drag_bg = self.canvas.copy_from_bbox(self.shape_artist.axes.bbox)
            self.shape_artist.set_visible(True)
            self.plotter.drawn = True

        _, _, _, _, xpx_press, ypx_press = self.press
        dx_press = event.x - xpx_press
        dy_press = event.y - ypx_press
        self.plotter.current_move_distance = ((dx_press**2) + (dy_press**2)) ** 0.5

        if self.drag_bg is not None:
            self.canvas.restore_region(self.drag_bg)

        self._shape_transform(event)
        self.shape_artist.axes.draw_artist(self.shape_artist)
        self.canvas.blit(self.shape_artist.axes.bbox)

    def _on_release(self, event):
        if self.shape_artist is None: return
        self._partial_release()
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

    def _partial_release(self):
        if self.shape_artist is None: return
        if self.plotter.ignore_current_draggable_id_n <= 0:
            self.plotter.update_title(f"OVERLAYS: {'VISIBLE' if self.plotter.show_overlays else 'HIDDEN'}", True)

        self.shape_artist.set_edgecolor(DEFAULT_EDGE_COLOR)
        self.shape_artist.set_linewidth(DEFAULT_MEDIUM_LINE_WIDTH)

    def _disconnect_cids(self):
        for cid in self.cids:
            self.canvas.mpl_disconnect(cid)


class _DraggableCircle(_DraggableShape):
    def __init__(self, entry_id: int, plotter_ref):
        super().__init__(entry_id, plotter_ref)
        if not isinstance(self.shape_artist, Circle): return
        new_r = max(self.shape_artist.get_radius(), self.min_circle_dist)
        self.shape_artist.set_radius(new_r)
        self.plotter.shapes[self.entry_id]["r"] = new_r
        self._connect_cids()

    def _connect_cids(self):
        if self.canvas.supports_blit:
            self.cids.extend([
                self.canvas.mpl_connect("button_press_event", self._on_press),
                self.canvas.mpl_connect("motion_notify_event", self._on_motion),
                self.canvas.mpl_connect("button_release_event", self._on_release),
            ])

    def _on_press_shape_helper(self, event):
        if not isinstance(self.shape_artist, Circle): return
        cx, cy = self.shape_artist.get_center()
        self.shape_mode = self._get_circumference(event, cx, cy)
        return float(cx), float(cy)

    def _shape_transform(self, event) -> None:
        self._circle_transform(event)

    def _circle_transform(self, event):
        if self.shape_mode is None or not isinstance(self.shape_artist, Circle) or self.press is None: return
        xdata, ydata = event.xdata, event.ydata
        old_cx, old_cy = self.shape_artist.get_center()
        old_r = self.shape_artist.get_radius()
        new_cx, new_cy = old_cx, old_cy

        if self.shape_mode == "resize":
            self._update_radius(xdata, ydata)
        elif self.shape_mode == "drag":
            _, _, xdata_press, ydata_press, _, _ = self.press
            dx = xdata - xdata_press
            dy = ydata - ydata_press
            new_cx, new_cy = self._move_circle(dx, dy)

        self._circle_transform_helper(old_cx, old_cy, old_r, new_cx, new_cy)

    def _circle_transform_helper(self, old_cx, old_cy, old_r, new_cx, new_cy):
        if not isinstance(self.shape_artist, Circle): return
        current_shape = self.plotter.shapes[self.entry_id]

        if self.plotter.saved_mouse_wheel and current_shape["bridge_key"] == MOUSE_WHEEL_SIMULATOR_CODE:
            self.plotter.mouse_wheel_cx = new_cx
            self.plotter.mouse_wheel_cy = new_cy
            self.plotter.mouse_wheel_radius = current_shape["r"]

            if self.plotter.saved_sprint_distance and self.plotter.sprint_artist_id is not None:
                sprint_artist = self.plotter.shape_drag_managers[self.plotter.sprint_artist_id]
                if (sprint_shape_artist := sprint_artist.shape_artist) is not None and isinstance(sprint_shape_artist, Circle):
                    cx, cy = sprint_shape_artist.get_center()
                    actual_dist = self.plotter.euclidean_distance(cx, cy, new_cx, new_cy)

                    if actual_dist <= self.plotter.mouse_wheel_radius:
                        r = self.plotter.mouse_wheel_radius
                        screen_rect = ((0, 0), (self.plotter.img_width, self.plotter.img_height))
                        sp_x, sp_y = self.plotter.constrain_point_to_rect_radial(
                            new_cx, new_cy - r - 1, new_cx, new_cy, screen_rect
                        )
                        sp_x, sp_y = int(round(sp_x)), int(round(sp_y))

                        sprint_shape = self.plotter.shapes[self.plotter.sprint_artist_id]
                        sprint_shape_artist.set_center((sp_x, sp_y))
                        sprint_shape["cx"] = sp_x
                        sprint_shape["cy"] = sp_y
                        self.plotter.sprint_distance = self.plotter.euclidean_distance(sp_x, sp_y, new_cx, new_cy)
                    else:
                        self.plotter.sprint_distance = actual_dist

        if self.plotter.saved_sprint_distance and current_shape["bridge_key"] == SPRINT_DISTANCE_CODE:
            actual_dist = self.plotter.euclidean_distance(new_cx, new_cy, self.plotter.mouse_wheel_cx, self.plotter.mouse_wheel_cy)
            if actual_dist <= self.plotter.mouse_wheel_radius:
                self.shape_artist.set_center((old_cx, old_cy))
                self.shape_artist.set_radius(old_r)
                current_shape["cx"] = old_cx
                current_shape["cy"] = old_cy
                current_shape["r"] = old_r
            else:
                self.plotter.sprint_distance = actual_dist

    def _get_circumference(self, event, cx, cy):
        if not isinstance(self.shape_artist, Circle) or self.shape_artist.axes is None: return
        r = self.shape_artist.get_radius()
        cx_px, cy_px = self.shape_artist.axes.transData.transform((cx, cy))
        rim_x_px, _ = self.shape_artist.axes.transData.transform((cx + r, cy))
        r_px = abs(rim_x_px - cx_px)
        dist_px = ((event.x - cx_px) ** 2 + (event.y - cy_px) ** 2) ** 0.5
        diff_px = abs(dist_px - r_px)

        if diff_px <= self.radial_tolerance: return "resize"
        if dist_px <= r_px: return "drag"
        return

    def _update_radius(self, xdata, ydata):
        if not isinstance(self.shape_artist, Circle): return
        cx, cy = self.shape_artist.get_center()
        new_r = int(round(((xdata - cx) ** 2 + (ydata - cy) ** 2) ** 0.5))
        current_shape = self.plotter.shapes[self.entry_id]
        new_sp_r = None

        if self.plotter.saved_mouse_wheel and current_shape["bridge_key"] == MOUSE_WHEEL_SIMULATOR_CODE:
            new_r = min(new_r, int(round(self.spec_max_ratio * ((self.plotter.img_width + self.plotter.img_height) / 2))))
            if self.plotter.saved_sprint_distance and self.plotter.sprint_artist_id is not None:
                sprint_artist = self.plotter.shape_drag_managers[self.plotter.sprint_artist_id]
                if (sprint_shape_artist := sprint_artist.shape_artist) is not None and isinstance(sprint_shape_artist, Circle):
                    if new_r < sprint_shape_artist.get_radius():
                        new_sp_r = new_r

        if self.plotter.saved_sprint_distance and current_shape["bridge_key"] == SPRINT_DISTANCE_CODE:
            new_r = min(new_r, self.plotter.mouse_wheel_radius)

        if new_r >= self.min_circle_dist:
            self.shape_artist.set_radius(new_r)
            current_shape["r"] = new_r
            if new_sp_r is not None and self.plotter.sprint_artist_id is not None:
                sprint_artist = self.plotter.shape_drag_managers[self.plotter.sprint_artist_id]
                if (sprint_shape_artist := sprint_artist.shape_artist) is not None and isinstance(sprint_shape_artist, Circle):
                    sprint_shape = self.plotter.shapes[self.plotter.sprint_artist_id]
                    sprint_shape_artist.set_radius(new_sp_r)
                    sprint_shape["r"] = new_sp_r

    def _move_circle(self, dx, dy):
        if isinstance(self.shape_artist, Circle):
            x0, y0, _, _, _, _ = self.press
            new_cx = int(round(x0 + dx))
            new_cy = int(round(y0 + dy))
            self.shape_artist.set_center((new_cx, new_cy))
            self.plotter.shapes[self.entry_id]["cx"] = new_cx
            self.plotter.shapes[self.entry_id]["cy"] = new_cy
            return new_cx, new_cy
        return dx, dy

    def _move(self, dx, dy):
        if not isinstance(self.shape_artist, Circle) or not self.press: return
        _, _, xdata_press, ydata_press, xpx_press, ypx_press = self.press
        cx, cy = self.shape_artist.get_center()
        self.press = cx, cy, xdata_press, ydata_press, xpx_press, ypx_press
        old_cx, old_cy = self.shape_artist.get_center()
        old_r = self.shape_artist.get_radius()
        new_cx, new_cy = self._move_circle(dx, dy)
        self._circle_transform_helper(old_cx, old_cy, old_r, new_cx, new_cy)
        self.canvas.draw()
        self.plotter.drawn = False

class _DraggableRectangle(_DraggableShape):
    def __init__(self, entry_id: int, plotter_ref):
        super().__init__(entry_id, plotter_ref)
        if not isinstance(self.shape_artist, Rectangle): return
        x, y = self.shape_artist.get_xy()
        self._update_rectangle_safe(x, y, self.shape_artist.get_width(), self.shape_artist.get_height())
        self._connect_cids()

    def _connect_cids(self):
        if self.canvas.supports_blit:
            self.cids.extend([
                self.canvas.mpl_connect("button_press_event", self._on_press),
                self.canvas.mpl_connect("motion_notify_event", self._on_motion),
                self.canvas.mpl_connect("button_release_event", self._on_release),
            ])

    def _on_press(self, event):
        self.plotter.ignore_current_draggable_id_n += 1
        self._on_press_helper(event)
        self.plotter.fire_on_motion = True

    def _on_press_shape_helper(self, event):
        if not isinstance(self.shape_artist, Rectangle): return
        x, y = self.shape_artist.get_xy()
        self.shape_mode = self._get_corner_under_mouse(event) or self._get_edge_under_mouse(event)
        return x, y

    def _shape_transform(self, event) -> None:
        self._rect_transform(event)

    def _rect_transform(self, event):
        if self.shape_mode is None or self.press is None: return
        xdata, ydata = event.xdata, event.ydata
        if self._update_corner(self.shape_mode, xdata, ydata): return
        if self._update_edge(self.shape_mode, xdata, ydata): return
        if self.shape_mode == "drag":
            _, _, xdata_press, ydata_press, _, _ = self.press
            self._move_rect(xdata - xdata_press, ydata - ydata_press)

    def _get_corner_under_mouse(self, event):
        if not isinstance(self.shape_artist, Rectangle) or self.shape_artist.axes is None: return
        x, y = self.shape_artist.get_xy()
        w, h = self.shape_artist.get_width(), self.shape_artist.get_height()
        corners = {
            "top_left": (x, y), "top_right": (x + w, y),
            "bottom_left": (x, y + h), "bottom_right": (x + w, y + h),
        }
        for name, (cx, cy) in corners.items():
            cx_px, cy_px = self.shape_artist.axes.transData.transform((cx, cy))
            if ((event.x - cx_px) ** 2 + (event.y - cy_px) ** 2) ** 0.5 <= self.vertex_tolerance:
                return name
        return

    def _get_edge_under_mouse(self, event):
        if not isinstance(self.shape_artist, Rectangle): return
        mx, my = event.x, event.y
        bbox = self.shape_artist.get_window_extent()
        is_h = bbox.xmin <= mx <= bbox.xmax
        is_v = bbox.ymin <= my <= bbox.ymax

        if abs(mx - bbox.xmin) <= self.edge_tolerance and is_v: return "left"
        if abs(mx - bbox.xmax) <= self.edge_tolerance and is_v: return "right"
        if abs(my - bbox.ymin) <= self.edge_tolerance and is_h: return "bottom"
        if abs(my - bbox.ymax) <= self.edge_tolerance and is_h: return "top"
        if is_h and is_v: return "drag"
        return None

    def _update_corner(self, corner, xdata, ydata):
        if not isinstance(self.shape_artist, Rectangle) or corner is None: return False
        xdata, ydata = int(round(xdata)), int(round(ydata))
        x, y = self.shape_artist.get_xy()
        w, h = self.shape_artist.get_width(), self.shape_artist.get_height()

        if corner == "top_left": return self._update_rectangle_safe(xdata, ydata, (x + w) - xdata, (y + h) - ydata) or True
        if corner == "top_right": return self._update_rectangle_safe(x, ydata, xdata - x, (y + h) - ydata) or True
        if corner == "bottom_left": return self._update_rectangle_safe(xdata, y, (x + w) - xdata, ydata - y) or True
        if corner == "bottom_right": return self._update_rectangle_safe(x, y, xdata - x, ydata - y) or True
        return False

    def _update_edge(self, edge, xdata, ydata):
        if not isinstance(self.shape_artist, Rectangle) or edge is None: return False
        xdata, ydata = int(round(xdata)), int(round(ydata))
        x, y = self.shape_artist.get_xy()
        w, h = self.shape_artist.get_width(), self.shape_artist.get_height()

        if edge == "right": return self._update_rectangle_safe(x, y, xdata - x, h) or True
        if edge == "left": return self._update_rectangle_safe(xdata, y, (x + w) - xdata, h) or True
        if edge == "bottom": return self._update_rectangle_safe(x, y, w, ydata - y) or True
        if edge == "top": return self._update_rectangle_safe(x, ydata, w, (y + h) - ydata) or True
        return False

    def _update_rectangle_safe(self, x, y, w, h):
        if not isinstance(self.shape_artist, Rectangle): return
        x, y, w, h = int(round(x)), int(round(y)), int(round(w)), int(round(h))
        if w < 0 or h < 0: return

        changed = [True, True]
        if w >= self.min_rectangle_dist:
            self.shape_artist.set_x(x)
            self.shape_artist.set_width(w)
        else:
            x = int(round(self.shape_artist.get_x()))
            w = max(int(round(self.shape_artist.get_width())), self.min_rectangle_dist)
            changed[0] = False

        if h >= self.min_rectangle_dist:
            self.shape_artist.set_y(y)
            self.shape_artist.set_height(h)
        else:
            y = int(round(self.shape_artist.get_y()))
            h = max(int(round(self.shape_artist.get_height())), self.min_rectangle_dist)
            changed[1] = False

        if any(changed):
            cx, cy, _, bb = calculate_raw_rect(((x, y), (x + w, y + h)))
            self.plotter.shapes[self.entry_id]["cx"] = cx
            self.plotter.shapes[self.entry_id]["cy"] = cy
            self.plotter.shapes[self.entry_id]["bb"] = bb

    def _move_rect(self, dx, dy):
        if not isinstance(self.shape_artist, Rectangle) or self.press is None: return
        x0, y0, _, _, _, _ = self.press
        self._update_rectangle_safe(int(round(x0 + dx)), int(round(y0 + dy)), self.shape_artist.get_width(), self.shape_artist.get_height())

    def _move(self, dx, dy):
        if not isinstance(self.shape_artist, Rectangle) or not self.press: return
        _, _, xdata_press, ydata_press, xpx_press, ypx_press = self.press
        x, y = self.shape_artist.get_xy()
        self.press = x, y, xdata_press, ydata_press, xpx_press, ypx_press
        self._move_rect(dx, dy)
        self.canvas.draw()
        self.plotter.drawn = False

class LayoutsPlotterWidget(QWidget):
    layout_saved = Signal(str, int)
    zone_selected = Signal(int)
    status_updated = Signal(str) # NEW: Broadcaster for UI text

    def __init__(self, parent: QWidget | None = None, standalone: bool = False):
        super().__init__(parent)
        self.standalone = standalone
        self.is_fatal_state = False

        self.root_layout = QVBoxLayout(self)
        self.root_layout.setContentsMargins(0, 0, 0, 0)

        self.fig = Figure()
        self.canvas = FigureCanvas(self.fig)
        self.ax = self.fig.add_subplot(111)

        for key in list(self.canvas.callbacks.callbacks.keys()):
            if "key_press_event" in key:
                self.canvas.callbacks.callbacks[key].clear()

        self.root_layout.addWidget(self.canvas)
        self.cursor_manager = _CursorManager(self.canvas)
        
        self.points = []
        self.point_artists = []
        self.mode = None
        self.state = IDLE
        self.input_buffer = ""
        self.bg_cache = None
        self.active_layout = None
        
        self.shapes_artists: dict[int, Circle | Rectangle] = {}
        self.labels_artists: dict[int, Text] = {}
        self.label_drag_managers: dict[int, _DraggableLabel] = {}
        self.shape_drag_managers: dict[int, _DraggableShape] = {}

        self.top_bezel_id = None
        self.top_bezel_label_artist = Text()
        self.top_bezel_shape_artist = Rectangle((0, 0), 0, 0)
        self.bottom_bezel_id = None
        self.bottom_bezel_label_artist = Text()
        self.bottom_bezel_shape_artist = Rectangle((0, 0), 0, 0)

        self.init_params_helper()
        self.canvas.mpl_connect("motion_notify_event", self.on_mouse_move)
        self.canvas.mpl_connect("key_press_event", self.on_key_press)
        self.canvas.mpl_connect("button_press_event", self.on_click)
        self.canvas.mpl_connect("resize_event", self.on_resize)
        self.fig.subplots_adjust(left=0, right=1, top=1, bottom=0)
        self.canvas.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

        self._setup_shortcuts()
        self.reload_active_layout()

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
        self.img_width: int = 0
        self.img_height: int = 0
        self.img_dpi: float = 0

        for uid in list(self.shapes_artists.keys()): self.shapes_artists[uid].remove()
        self.shapes_artists = {}
        for uid in list(self.labels_artists.keys()): self.labels_artists[uid].remove()
        self.labels_artists = {}
        for uid in list(self.label_drag_managers.keys()): self.label_drag_managers[uid]._disconnect_cids()
        self.label_drag_managers = {}
        for uid in list(self.shape_drag_managers.keys()): self.shape_drag_managers[uid]._disconnect_cids()
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

    def init_crosshairs(self):
        self.crosshair_h_bg = self.ax.axhline(0, color="black", linewidth=1.5, alpha=0.8, visible=False, zorder=10, animated=True)
        self.crosshair_v_bg = self.ax.axvline(0, color="black", linewidth=1.5, alpha=0.8, visible=False, zorder=10, animated=True)
        self.crosshair_h_fg = self.ax.axhline(0, color="white", linewidth=0.6, alpha=1.0, visible=False, zorder=11, animated=True)
        self.crosshair_v_fg = self.ax.axvline(0, color="white", linewidth=0.6, alpha=1.0, visible=False, zorder=11, animated=True)

    def _setup_shortcuts(self) -> None:
        context = Qt.ShortcutContext.WindowShortcut if self.standalone else Qt.ShortcutContext.WidgetWithChildrenShortcut
        shortcuts = [
            ("F4", self.toggle_visibility),
            ("F6", lambda: self.start_mode(CIRCLE, 3)),
            ("F7", lambda: self.start_mode(RECTANGLE, 4)),
            ("F8", self.reset_state),
            ("F9", self.print_data),
            ("F12", self.enter_naming_mode),
            ("Delete", self.enter_deleting_mode),
            ("Space", self.enter_marking_mode),
            ("Esc", self._on_escape_pressed),
        ]
        self._shortcuts_registry = []
        for key_seq, callback in shortcuts:
            sc = QShortcut(QKeySequence(key_seq), self, callback)
            sc.setContext(context)
            self._shortcuts_registry.append(sc)

    def _on_escape_pressed(self) -> None:
        if self.is_fatal_state: return
        if self.state == IDLE and self.standalone:
            parent_window = self.window()
            if parent_window: parent_window.close()
        else:
            self.reset_state()

    def reload_active_layout(self) -> bool:
        self.active_layout = store.get_active_layout()
        if not self.active_layout:
            self._render_empty_state("Fatal: No active layout set. Please select or create a layout first.")
            return False

        if not self.active_layout.image_path:
            self._render_empty_state(f"Layout '{self.active_layout.name}' has no assigned HUD image.")
            return False

        img_path = Path(self.active_layout.image_path)
        if not img_path.is_absolute(): img_path = Path(IMAGES_FOLDER) / img_path

        if not img_path.exists():
            self._render_empty_state(f"Image '{img_path.as_posix()}' does not exist on disk.")
            return False

        img = self.load_image()
        if img is None:
            self._render_empty_state("Could not load image file.")
            return False

        self.image_path = img_path
        self.is_fatal_state = False
        self.ax.clear()
        self.init_params_helper()
        self.update_image_params(img)
        self.ax.imshow(img)

        self.update_title(f"OVERLAYS: {'VISIBLE' if self.show_overlays else 'HIDDEN'}")
        self.init_crosshairs()
        self.bg_cache = None

        self.load_active_layout_zones()
        self._render_bezels_notch()
        self.canvas.draw_idle()
        return True

    def _render_bezels_notch(self):
        if self.img_width <= 0 or self.img_height <= 0: return

        top_kwargs = self._render_bezel_notch(self.top_bezel_id, True)
        bot_kwargs = self._render_bezel_notch(self.bottom_bezel_id, False)

        if top_kwargs:
            self.top_bezel_label_artist.set(**top_kwargs[0])
            self.top_bezel_shape_artist.set(**top_kwargs[1])
        else:
            self.top_bezel_label_artist.remove()
            self.top_bezel_shape_artist.remove()

        if bot_kwargs:
            self.bottom_bezel_label_artist.set(**bot_kwargs[0])
            self.bottom_bezel_shape_artist.set(**bot_kwargs[1])
        else:
            self.bottom_bezel_label_artist.remove()
            self.bottom_bezel_shape_artist.remove()

        for art in [self.top_bezel_label_artist, self.top_bezel_shape_artist, self.bottom_bezel_label_artist, self.bottom_bezel_shape_artist]:
            art.set_visible(self.show_overlays)
            if art.axes is None:
                if isinstance(art, Text): self.ax.add_artist(art)
                else: self.ax.add_patch(art)

    def _render_bezel_notch(self, bezel_id: int | None, is_top: bool):
        from modules.utils import BEZEL_DP_THICKNESS, dp_to_px
        bezel_px_thickness = float(dp_to_px(float(BEZEL_DP_THICKNESS), self.active_layout.dpi))
        
        store_bezel_zone = store.zones.get(bezel_id)
        if store_bezel_zone:
            bezel_px_thickness = store_bezel_zone.get_bezel_thickness_px(self.active_layout.dpi)

        y = self.img_height - bezel_px_thickness if is_top else 0.0

        return (
            {
                "x": self.img_width / 2.0, "y": bezel_px_thickness / 2.0,
                "text": f"Bezel Notch ({bezel_px_thickness:.0f}px)",
                "color": "white", "fontsize": 7, "ha": "center", "va": "center",
                "zorder": 9, "alpha": 0.8,
            },
            {
                "xy": (0.0, y), "width": self.img_width, "height": bezel_px_thickness,
                "fill": True, "facecolor": (1.0, 0.2, 0.2, 0.25), "edgecolor": (1.0, 0.4, 0.4, 0.7),
                "linewidth": 1.0, "linestyle": "--", "zorder": 8,
            }
        )

    def _render_empty_state(self, message: str) -> None:
        self.is_fatal_state = True
        self.ax.clear()
        self.ax.text(0.5, 0.5, message, ha="center", va="center", transform=self.ax.transAxes, color="gray", fontsize=12)
        self.ax.set_xticks([])
        self.ax.set_yticks([])
        self.update_title("ERROR: Missing Active Layout")
        self.canvas.draw_idle()

    def load_image(self):
        try: return Image.open(self.image_path)
        except Exception as e: print(f"Error loading image: {e}"); return None

    def update_image_params(self, img):
        self.img_width, self.img_height = img.size
        try:
            parts = self.image_path.stem.split("_")
            if parts[-1].startswith("r"):
                _w, _h = rotate_resolution(self.img_width, self.img_height, int(parts[-1][1:]))
                if _w is not None and _h is not None:
                    self.img_width, self.img_height = _w, _h
        except Exception: pass
        self.img_dpi = int(round(img.info.get("dpi", BASELINE_DPI)[0]))

    def update_title(self, text: str, idle_override: bool = False):
        """Sets the matplotlib title and broadcasts it to the Qt parent UI."""
        self.ax.set_title(text)
        self.status_updated.emit(text)
        self.cursor_manager.set_state_cursor(self.state)
        
        if idle_override: 
            self.fig.canvas.draw_idle()
        else: 
            self.fig.canvas.draw()

    def clear_visuals(self):
        for artist in self.point_artists: artist.remove()
        self.point_artists = []
        self.fig.canvas.draw()

    def reset_state(self):
        self.clear_visuals()
        self.state, self.mode, self.points = IDLE, None, []
        self.input_buffer, self.buffer_default = "", True
        self.update_title(f"OVERLAYS: {'VISIBLE' if self.show_overlays else 'HIDDEN'}")
        if self.ax.bbox.width > 0 and self.ax.bbox.height > 0:
            self.bg_cache = self.canvas.copy_from_bbox(self.ax.bbox)

    def start_mode(self, mode: str, num_points: int):
        self.reset_state()
        self.mode, self.artists_points, self.state = mode, num_points, COLLECTING
        self.update_title(f"MODE: {mode}. Click {num_points} points on the image.")

    def load_active_layout_zones(self):
        if not self.active_layout: return

        zones = store.zones.list_for_layout(self.active_layout.id)
        w, h, dpi = self.img_width, self.img_height, self.img_dpi
        self.init_params_helper()
        self.img_width, self.img_height, self.img_dpi = w, h, dpi
        self.reset_state()

        scale_x = self.img_width / self.active_layout.width
        scale_y = self.img_height / self.active_layout.height

        for zone in zones:
            if zone.zone_type == BEZEL:
                if str(zone.scancode) == str(TOP_BEZEL_ID): self.top_bezel_id = zone.id
                elif str(zone.scancode) == str(BOTTOM_BEZEL_ID): self.bottom_bezel_id = zone.id
                continue

            zone.set_parsed_config_from_json()
            key_name = get_key_from_scancode(zone.scancode)
            if not key_name: continue
            
            _, bridge_key = get_scancode_and_bridge_key_from_key(key_name)
            self.mode = zone.zone_type
            cx = int(round((zone.cx or 0.0) * scale_x))
            cy = int(round((zone.cy or 0.0) * scale_y))

            r, bb = None, None
            if zone.zone_type == CIRCLE:
                r = int(round((zone.r or 0.0) * ((scale_x + scale_y) / 2)))
            elif zone.zone_type == RECTANGLE:
                bb = (
                    (int(round((zone.x1 or 0.0) * scale_x)), int(round((zone.y1 or 0.0) * scale_y))),
                    (int(round((zone.x2 or 0.0) * scale_x)), int(round((zone.y2 or 0.0) * scale_y))),
                )

            self.finalize_shape(cx=cx, cy=cy, r=r, bb=bb, bridge_key=bridge_key or zone.name, hex_code=zone.scancode, pointer=zone.pointer, priority=zone.priority, pipeline_json=zone.pipeline_json, ignore_app_settings=zone.ignore_app_settings)

        self.mouse_wheel_radius = self.active_layout.mouse_wheel_radius
        self.sprint_distance = self.active_layout.sprint_distance
        self.reset_state()

    def toggle_visibility(self):
        if self.is_fatal_state: return
        self.show_overlays = not self.show_overlays
        for d in (self.shapes_artists, self.labels_artists):
            for art in d.values(): art.set_visible(self.show_overlays)
        
        for art in (self.top_bezel_label_artist, self.top_bezel_shape_artist, self.bottom_bezel_label_artist, self.bottom_bezel_shape_artist):
            art.set_visible(self.show_overlays)
        self.update_title(f"OVERLAYS: {'VISIBLE' if self.show_overlays else 'HIDDEN'}")

    def label(self, center_x, center_y, label_text, fc):
        scaled_font = max(5, int(round(self.fig.get_size_inches()[1] * 72 * 0.02)))
        return Text(center_x, center_y, label_text, color="white", fontsize=scaled_font, fontweight="bold", ha="center", va="center", zorder=12, bbox=dict(fc=fc, ec="black", lw=1.5, boxstyle="round,pad=0.3"))

    def on_mouse_move(self, event):
        if self.is_fatal_state: return
        if self.state == COLLECTING and event.inaxes == self.ax:
            x, y = int(round(event.xdata)), int(round(event.ydata))
            if self.bg_cache is None and self.ax.bbox.width > 0 and self.ax.bbox.height > 0:
                self.bg_cache = self.canvas.copy_from_bbox(self.ax.bbox)

            if self.bg_cache is not None:
                self.canvas.restore_region(self.bg_cache)
                for line in [self.crosshair_h_bg, self.crosshair_h_fg]:
                    line.set_visible(True); line.set_ydata([y, y]); self.ax.draw_artist(line)
                for line in [self.crosshair_v_bg, self.crosshair_v_fg]:
                    line.set_visible(True); line.set_xdata([x, x]); self.ax.draw_artist(line)
                self.fig.canvas.blit(self.ax.bbox)
        else:
            if hasattr(self, "crosshair_h_bg") and self.crosshair_h_bg.get_visible():
                for line in [self.crosshair_h_bg, self.crosshair_h_fg, self.crosshair_v_bg, self.crosshair_v_fg]: line.set_visible(False)
                self.cursor_manager.set_state_cursor(self.state)
                self.fig.canvas.draw_idle()

        if self.state == IDLE and not self.drawn and event.button is None and event.inaxes == self.ax:
            if self.ignore_current_draggable_id_n > 0: return

            hovering = None
            for uid, mgr in self.label_drag_managers.items():
                if mgr.label_artist.contains(event)[0]: hovering = (uid, mgr, "label"); break
            if not hovering:
                for uid, mgr in self.shape_drag_managers.items():
                    if mgr.shape_artist and mgr.shape_artist.contains(event)[0]: hovering = (uid, mgr, "shape"); break

            if hovering:
                uid, mgr, m_type = hovering
                if (curr_id := m_type + "_" + str(uid)) != self.current_draggable_id:
                    self.partial_release_all()
                    mgr._on_press_helper(event)
                    self.current_draggable_id = curr_id
                    mgr.indicate_current_draggable_id()
                    self.fire_on_motion = False
            else:
                self.partial_release_all()
                self.update_title(f"OVERLAYS: {'VISIBLE' if self.show_overlays else 'HIDDEN'}", True)

    def partial_release_all(self):
        for mgr in self.label_drag_managers.values(): mgr._partial_release()
        for mgr in self.shape_drag_managers.values(): mgr._partial_release()
        self.current_draggable_id = None
        self.zone_selected.emit(-1)
        self.fig.canvas.draw_idle()

    def on_click(self, event):
        if self.is_fatal_state: return
        if self.state == IDLE: self.ignore_current_draggable_id_n = 0
        if self.state == WAITING_FOR_KEY:
            if btn := {1: "MOUSE_LEFT", 2: "MOUSE_MIDDLE", 3: "MOUSE_RIGHT"}.get(event.button): self.calculate_shape(btn)
            return
        if self.state != COLLECTING or event.xdata is None or event.ydata is None: return

        self.points.append((int(round(event.xdata)), int(round(event.ydata))))
        dot, = self.ax.plot(event.xdata, event.ydata, "ro")
        self.point_artists.append(dot)
        self.fig.canvas.draw()
        self.bg_cache = None

        if (rem := self.artists_points - len(self.points)) > 0:
            self.update_title(f"MODE: {self.mode}. {rem} points remaining (F8 to Cancel).")
        else:
            self.state = WAITING_FOR_KEY
            self.update_title("Shape Defined! Press KEY or CLICK MOUSE to bind.")

    def on_key_press(self, event):
        if self.is_fatal_state: return
        
        state_handlers = {
            NAMING: self.handle_naming_input,
            DELETING: self.handle_deleting_input,
            MARKING: self.handle_marking_input,
        }
        
        if self.state in state_handlers:
            state_handlers[self.state](event.key)
            return

        if self.state == CONFIRM_DELETE_ALL:
            self.delete_all_shapes() if event.key == "enter" else self.reset_state()
            return
        if self.state in (CONFIRM_EXIT, COLLECTING):
            if event.key in ("escape", "f8"): self.reset_state()
            return
        if self.state == WAITING_FOR_KEY:
            self.calculate_shape(get_specific_mt_key(event))
            return

        if self.state == IDLE:
            if event.key == "f1": self.reset_state()
            elif event.key == "f2":
                self.state = CONFIRM_DELETE_ALL
                self.update_title("[DELETE ALL?] Press ENTER to Confirm or Any other key to Cancel.")
            elif event.key == "f4": self.toggle_visibility()
            elif event.key == "f6": self.start_mode(CIRCLE, 3)
            elif event.key == "f7": self.start_mode(RECTANGLE, 4)
            elif event.key == "f9": self.print_data()
            elif event.key == "f12": self.enter_naming_mode()
            elif event.key == "delete": self.enter_deleting_mode()
            elif event.key == " ": self.enter_marking_mode()
            elif event.key == "escape": self.reset_state()
            elif event.key in ("p", "o") and self.current_draggable:
                eid = self.current_draggable.entry_id
                self.shapes[eid]["priority"] += 1 if event.key == "p" else -1
                self.update_title(f"Priority {'increased' if event.key == 'p' else 'decreased'}: {self.shapes[eid]['priority']} (ID: {eid})", True)
                self.zone_selected.emit(eid)
            else:
                step = 5 if event.key.startswith("shift+") else 1
                clean_key = event.key.replace("shift+", "")
                dirs = {"left": (-step, 0), "right": (step, 0), "up": (0, -step), "down": (0, step)}
                if clean_key in dirs and self.current_draggable:
                    self.current_draggable._move(*dirs[clean_key])

    def enter_deleting_mode(self):
        if not self.shapes: self.update_title(f"List empty. Nothing to delete"); return
        self.state, self.input_buffer = DELETING, ""
        self.update_title("DELETE MODE: Type ID... (Enter to Confirm | Esc to Cancel)")

    def delete_all_shapes(self):
        if not self.shapes: self.update_title(f"List empty. Nothing to delete."); return
        for uid in list(self.shapes.keys()): self.delete_entry(uid)
        self.count = 0
        self.reset_state()

    def handle_deleting_input(self, key):
        if key == "escape": self.reset_state(); return
        if key == "enter":
            if self.input_buffer:
                try:
                    if (uid := int(self.input_buffer)) in self.shapes:
                        self.delete_entry(uid); self.update_title(f"Deleted ID {uid}. Returning to IDLE..."); self.reset_state()
                    else:
                        self.update_title(f"Error: ID {uid} not found. Try again or Press ESC to Cancel."); self.input_buffer = ""
                except ValueError:
                    self.update_title("Error: Invalid Number. Try again or Press ESC to Cancel."); self.input_buffer = ""
            return
        if key.isdigit():
            self.input_buffer += key
            self.update_title(f"DELETE MODE: ID [{self.input_buffer}] (Enter to delete | Esc to Cancel)")
        elif key == "backspace":
            self.input_buffer = self.input_buffer[:-1]
            self.update_title(f"DELETE MODE: ID [{self.input_buffer}] (Enter to delete | Esc to Cancel)")

    def delete_entry(self, uid):
        if uid not in self.shapes: return
        bkey = self.shapes[uid]["bridge_key"]
        if bkey == MOUSE_WHEEL_SIMULATOR_CODE:
            for sid in [k for k, v in self.shapes.items() if v["bridge_key"] == SPRINT_DISTANCE_CODE]: self.delete_entry(sid)
            self.saved_mouse_wheel, self.mouse_wheel_radius, self.mouse_wheel_cx, self.mouse_wheel_cy = False, 0.0, 0.0, 0.0
        elif bkey == SPRINT_DISTANCE_CODE:
            self.saved_sprint_distance, self.sprint_artist_id, self.sprint_distance = False, None, 0.0

        if self.current_draggable_id in [f"shape_{uid}", f"label_{uid}"]: self.current_draggable_id = self.current_draggable = None
        del self.shapes[uid]
        if uid in self.shapes_artists: self.shapes_artists.pop(uid).remove()
        if uid in self.labels_artists: self.labels_artists.pop(uid).remove()
        if uid in self.label_drag_managers: self.label_drag_managers.pop(uid)._disconnect_cids()
        if uid in self.shape_drag_managers: self.shape_drag_managers.pop(uid)._disconnect_cids()
        if self.last_artist_id in [f"shape_{uid}", f"label_{uid}"]: self.last_artist_id = None
        
        self.zone_selected.emit(-1)

    def enter_marking_mode(self):
        if not self.shapes: self.update_title(f"List empty. Nothing to mark."); return
        self.state, self.input_buffer = MARKING, ""
        self.update_title("MARK MODE: Type ID... (Enter to Confirm | Esc to Cancel)")

    def handle_marking_input(self, key):
        if key == "escape": self.reset_state(); return
        if key == "enter":
            if self.input_buffer:
                try:
                    if (uid := int(self.input_buffer)) in self.shapes:
                        self.shapes[uid]["pointer"] = not self.shapes[uid]["pointer"]
                        if self.shapes[uid]["pointer"]:
                            self.label_drag_managers[uid].dull_face_color(); self.shape_drag_managers[uid].dull_face_color()
                        else:
                            self.label_drag_managers[uid].restore_face_color(); self.shape_drag_managers[uid].restore_face_color()
                        self.update_title(f"{'Marked' if self.shapes[uid]['pointer'] else 'Unmarked'} ID {uid}. Returning to IDLE...")
                        self.reset_state()
                        self.zone_selected.emit(uid)
                    else:
                        self.update_title(f"Error: ID {uid} not found. Try again or Press ESC to Cancel."); self.input_buffer = ""
                except ValueError:
                    self.update_title("Error: Invalid Number. Try again or Press ESC to Cancel."); self.input_buffer = ""
            return
        if key.isdigit():
            self.input_buffer += key
            self.update_title(f"MARK MODE: ID [{self.input_buffer}] (Enter to mark | Esc to Cancel)")
        elif key == "backspace":
            self.input_buffer = self.input_buffer[:-1]
            self.update_title(f"MARK MODE: ID [{self.input_buffer}] (Enter to mark | Esc to Cancel)")

    def calculate_shape(self, key_name):
        hex_code, bridge_key = get_scancode_and_bridge_key_from_key(key_name)
        if not hex_code or not bridge_key: print(f'[PLOTTER] - Key "{key_name}" not mapped.'); return

        cx, cy, r, bb = None, None, None, None
        if self.mode == CIRCLE: cx, cy, r, bb = self.calculate_circle()
        elif self.mode == RECTANGLE: cx, cy, r, bb = self.calculate_rect()

        self.finalize_shape(cx=cx, cy=cy, r=r, bb=bb, bridge_key=bridge_key, hex_code=hex_code, pointer=False, priority=0, pipeline_json="{}", ignore_app_settings=False)
        self.reset_state()

    def finalize_shape(self, cx, cy, r, bb, bridge_key, hex_code, pointer=False, priority=0, pipeline_json="{}", ignore_app_settings=False):
        if cx is None: return
        saved, entry_id = self.save_entry(bridge_key, hex_code, cx, cy, r, bb, pointer, priority, pipeline_json, ignore_app_settings)
        if not saved: return

        label = "MOUSE_WHEEL" if bridge_key == MOUSE_WHEEL_SIMULATOR_CODE else "SPRINT_DISTANCE" if bridge_key == SPRINT_DISTANCE_CODE else bridge_key.split("E0_")[-1]

        if self.mode == CIRCLE and r:
            fc = DEFAULT_MOUSE_WHEEL_FACE_COLOR if bridge_key == MOUSE_WHEEL_SIMULATOR_CODE else DEFAULT_SPRINT_DISTANCE_FACE_COLOR if bridge_key == SPRINT_DISTANCE_CODE else get_vibrant_random_color(DEFAULT_FACE_COLOR_ALPHA)
            art = Circle((cx, cy), r, fill=True, lw=2, fc=fc, ec=DEFAULT_EDGE_COLOR)
            self.shapes_artists[entry_id] = art
            self.shape_drag_managers[entry_id] = _DraggableCircle(entry_id, self)
        elif self.mode == RECTANGLE and bb:
            fc = get_vibrant_random_color(DEFAULT_FACE_COLOR_ALPHA)
            (x1, y1), (x2, y2) = bb
            art = Rectangle((x1, y1), x2 - x1, y2 - y1, fill=True, lw=2, fc=fc, ec=DEFAULT_EDGE_COLOR)
            self.shapes_artists[entry_id] = art
            self.shape_drag_managers[entry_id] = _DraggableRectangle(entry_id, self)
        else: return

        art.set_visible(self.show_overlays)
        self.ax.add_patch(art)

        lbl = self.label(cx, cy, label, fc)
        lbl.set_visible(self.show_overlays)
        self.ax.add_artist(lbl)
        self.labels_artists[entry_id] = lbl
        self.label_drag_managers[entry_id] = _DraggableLabel(entry_id, self)

        if pointer:
            self.label_drag_managers[entry_id].dull_face_color(); self.shape_drag_managers[entry_id].dull_face_color()

    def enter_naming_mode(self):
        if not self.shapes: self.update_title(f"Nothing to save!"); return
        self.state, self.buffer_default = NAMING, True
        self.input_buffer = self.active_layout.name
        self.update_title(f"SAVE: [{self.input_buffer}] | Enter: Save/Rename | Shift+Enter: Save as Copy | Esc: Cancel")

    def handle_naming_input(self, key):
        if key == "escape": self.reset_state(); return
        if key in ("enter", "shift+enter", "ctrl+s"):
            self.save_to_database(self.input_buffer.strip() or self.active_layout.name, as_copy=key != "enter")
            self.reset_state()
            return
        if key == "backspace":
            if self.buffer_default: self.input_buffer, self.buffer_default = "", False
            else: self.input_buffer = self.input_buffer[:-1]
        elif len(key) == 1 and (key.isalnum() or key in "_ -.()"):
            if self.buffer_default: self.input_buffer, self.buffer_default = "", False
            self.input_buffer += key
        self.update_title(f"SAVE: [{self.input_buffer or self.active_layout.name}] | Enter: Save/Rename | Shift+Enter: Save as Copy | Esc: Cancel")

    def save_to_database(self, user_name: str, as_copy=False):
        output = []
        for _, data in self.shapes.items():
            entry = {
                "name": data["bridge_key"], "scancode": data["m_code"], "type": data["type"],
                "cx": data["cx"], "cy": data["cy"], "val1": 0, "val2": 0, "val3": 0, "val4": 0,
                "ignore_app_settings": data.get("ignore_app_settings", False)
            }

            p_cfg = PipelineConfig()
            p_cfg.set_pipeline_config_from_json(data.get("pipeline_json", "{}"))

            if data["type"] == CIRCLE:
                region_idx = 1; entry["val1"] = data["r"]
            else:
                region_idx = 2
                (x_min, y_min), (x_max, y_max) = data["bb"]
                entry["val1"], entry["val2"], entry["val3"], entry["val4"] = x_min, y_min, x_max, y_max

            if data.get("pipeline_json", "{}") == "{}":
                bkey = data["bridge_key"]
                p_cfg.set_origin_config(idx=0 if bkey == MOUSE_WHEEL_SIMULATOR_CODE else 1)
                p_cfg.set_constraint_config(idx=1 if bkey == MOUSE_WHEEL_SIMULATOR_CODE else 0)
                p_cfg.set_transform_config(idx=2 if bkey == MOUSE_WHEEL_SIMULATOR_CODE else 1)
                if bkey != SPRINT_DISTANCE_CODE: p_cfg.set_semantic_config(idx=1 if bkey == MOUSE_WHEEL_SIMULATOR_CODE else 0)

            p_cfg.set_region_config(idx=region_idx, priority=data.get("priority", 0))
            p_cfg.set_semantic_config(pointer=data.get("pointer", False))
            entry["pipeline_json"] = p_cfg.get_pipeline_json_from_config()
            output.append(entry)

        rel_img_path = self.image_path.name if self.image_path.parent == Path(IMAGES_FOLDER) else str(self.image_path)
        is_new_name = user_name != self.active_layout.name
        
        if as_copy or is_new_name:
            if as_copy and not is_new_name: user_name = make_copy_name(user_name)
            layout_id = store.layouts.create(
                name=user_name, width=self.img_width, height=self.img_height, dpi=self.img_dpi,
                mouse_wheel_radius=self.mouse_wheel_radius, sprint_distance=self.sprint_distance, image_path=rel_img_path,
            ).id
        else:
            layout_id = self.active_layout.id
            store.layouts.update(
                layout_id, width=self.img_width, height=self.img_height, dpi=self.img_dpi,
                mouse_wheel_radius=self.mouse_wheel_radius, sprint_distance=self.sprint_distance, image_path=rel_img_path,
            )
            store.zones.delete_all_for_layout(layout_id) # Relies on list_for_layout native healing

        for item in output:
            store.zones.create(
                layout_id=layout_id, scancode=str(item["scancode"]), name=item["name"], zone_type=item["type"],
                cx=float(item["cx"]), cy=float(item["cy"]), r=float(item["val1"]) if item["type"] == CIRCLE else None,
                x1=float(item["val1"]) if item["type"] == RECTANGLE else None,
                y1=float(item["val2"]) if item["type"] == RECTANGLE else None,
                x2=float(item["val3"]) if item["type"] == RECTANGLE else None,
                y2=float(item["val4"]) if item["type"] == RECTANGLE else None,
                ignore_app_settings=item["ignore_app_settings"], pipeline_json=item["pipeline_json"],
            )

        store.set_active_layout(layout_id)
        self.active_layout = store.layouts.get(layout_id)
        self.layout_saved.emit(user_name, layout_id)
        self.update_title(f"SAVED: {user_name}")

    def save_entry(self, bridge_key, hex_code, cx, cy, r, bb, pointer, priority=0, pipeline_json="{}", ignore_app_settings=False):
        uid, inc_count = self.count, True
        if bridge_key == MOUSE_WHEEL_SIMULATOR_CODE:
            if self.mode == RECTANGLE: return False, uid
            if self.saved_mouse_wheel:
                for k, v in list(self.shapes.items()):
                    if v["bridge_key"] == MOUSE_WHEEL_SIMULATOR_CODE:
                        uid, inc_count = k, False; self.shapes.pop(k)
                        for d in (self.shapes_artists, self.labels_artists):
                            if k in d: d.pop(k).remove()
                        for d in (self.label_drag_managers, self.shape_drag_managers):
                            if k in d: d.pop(k)._disconnect_cids()
                        break
            self.mouse_wheel_radius, self.mouse_wheel_cx, self.mouse_wheel_cy, self.saved_mouse_wheel = r, cx, cy, True
        elif bridge_key == SPRINT_DISTANCE_CODE:
            if self.mode == RECTANGLE or not self.saved_mouse_wheel: return False, uid
            if self.saved_sprint_distance:
                for k, v in list(self.shapes.items()):
                    if v["bridge_key"] == SPRINT_DISTANCE_CODE:
                        uid, inc_count = k, False; self.shapes.pop(k)
                        for d in (self.shapes_artists, self.labels_artists):
                            if k in d: d.pop(k).remove()
                        for d in (self.label_drag_managers, self.shape_drag_managers):
                            if k in d: d.pop(k)._disconnect_cids()
                        break
            actual_dist = self.euclidean_distance(cx, cy, self.mouse_wheel_cx, self.mouse_wheel_cy)
            if actual_dist <= self.mouse_wheel_radius: return False, uid
            self.sprint_distance, self.saved_sprint_distance, self.sprint_artist_id = actual_dist, True, uid

        self.shapes[uid] = {
            "bridge_key": bridge_key, "m_code": hex_code, "type": self.mode, "cx": cx, "cy": cy,
            "r": r, "bb": bb, "pointer": pointer, "priority": priority, "pipeline_json": pipeline_json,
            "ignore_app_settings": ignore_app_settings
        }
        if inc_count: self.count += 1
        return True, uid

    def print_data(self):
        if not self.shapes: self.update_title(f"List empty. Nothing to print."); return
        print("\nCurrent Shapes:")
        for k, v in self.shapes.items(): print(k, v)
        print("\n")

    def calculate_circle(self):
        if len(self.points) < 3: return None, None, None, None
        x1, y1, x2, y2, x3, y3 = *self.points[0], *self.points[1], *self.points[2]
        d = 2 * (x1 * (y2 - y3) + x2 * (y3 - y1) + x3 * (y1 - y2))
        if d == 0: self.update_title("Error: Points are collinear."); return None, None, None, None
        h = ((x1**2 + y1**2) * (y2 - y3) + (x2**2 + y2**2) * (y3 - y1) + (x3**2 + y3**2) * (y1 - y2)) / d
        k = ((x1**2 + y1**2) * (x3 - x2) + (x2**2 + y2**2) * (x1 - x3) + (x3**2 + y3**2) * (x2 - x1)) / d
        return int(round(h)), int(round(k)), int(round(math.sqrt((x1 - h)**2 + (y1 - k)**2))), None

    def calculate_rect(self):
        if len(self.points) < 4: return None, None, None, None
        xs, ys = [p[0] for p in self.points], [p[1] for p in self.points]
        return int(round(sum(xs) / 4)), int(round(sum(ys) / 4)), None, ((min(xs), min(ys)), (max(xs), max(ys)))

    def euclidean_distance(self, x1, y1, x2, y2): return math.sqrt((x2 - x1)**2 + (y2 - y1)**2)

    def constrain_point_to_rect_radial(self, cx, cy, px, py, rect_bb):
        (x_min, y_min), (x_max, y_max) = rect_bb
        if x_min <= cx <= x_max and y_min <= cy <= y_max: return cx, cy
        radius = math.sqrt((cx - px)**2 + (cy - py)**2)
        if radius < 1e-9: return cx, cy

        current_angle = math.atan2(cy - py, cx - px)
        valid = []

        def on_seg(x, y, x1, y1, x2, y2):
            return min(x1, x2) - 1e-9 <= x <= max(x1, x2) + 1e-9 and min(y1, y2) - 1e-9 <= y <= max(y1, y2) + 1e-9

        for x1, y1, x2, y2 in [(x_min, y_min, x_min, y_max), (x_max, y_min, x_max, y_max), (x_min, y_min, x_max, y_min), (x_min, y_max, x_max, y_max)]:
            if abs(x1 - x2) < 1e-9:
                if abs(dx := x1 - px) <= radius:
                    dy = math.sqrt(radius**2 - dx**2)
                    for iy in (py + dy, py - dy):
                        if on_seg(x1, iy, x1, y1, x2, y2): valid.append((x1, iy))
            else:
                if abs(dy := y1 - py) <= radius:
                    dx = math.sqrt(radius**2 - dy**2)
                    for ix in (px + dx, px - dx):
                        if on_seg(ix, y1, x1, y1, x2, y2): valid.append((ix, y1))

        if not valid: return max(x_min, min(cx, x_max)), max(y_min, min(cy, y_max))
        candidates = []
        for ix, iy in valid:
            ta = math.atan2(iy - py, ix - px)
            candidates.append({"pt": (ix, iy), "diff": abs(math.atan2(math.sin(ta - current_angle), math.cos(ta - current_angle))), "y": iy})
        return sorted(candidates, key=lambda c: (round(c["diff"], 5), c["y"]))[0]["pt"]
