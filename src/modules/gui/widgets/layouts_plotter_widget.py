from __future__ import annotations

import math
import os
import sys
from pathlib import Path
from PIL import Image
from typing import TYPE_CHECKING, Optional, Any

from modules.platforms import get_platform, get_specific_mt_key
from modules.database import store

get_platform().SystemConfig().set_dpi_awareness()

from modules.utils import (
    BASELINE_DPI,
    BEZEL,
    BEZEL_DP_THICKNESS,
    BOTTOM_BEZEL_ID,
    BOTTOM_BEZEL_NAME,
    CIRCLE,
    IDLE,
    IMAGES_FOLDER,
    MOUSE_WHEEL_SIMULATOR_CODE,
    RECTANGLE,
    SPRINT_DISTANCE_CODE,
    TOP_BEZEL_ID,
    TOP_BEZEL_NAME,
    get_dulled_hue_color,
    get_hue_modified_alpha_from_hsv,
    get_key_from_scancode,
    get_scancode_from_key,
    get_vibrant_random_color,
    make_copy_name,
)

from modules.core.pipeline import PipelineConfig

if sys.platform == "win32":
    os.environ["QT_LOGGING_RULES"] = "qt.qpa.window=false"

import matplotlib

matplotlib.use("qtagg")
from matplotlib.figure import Figure
from matplotlib.patches import Circle, Rectangle
from matplotlib.text import Text
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QWidget, QVBoxLayout

if TYPE_CHECKING:
    from modules.database import Layout

COLLECTING = "COLLECTING"
WAITING_FOR_KEY = "WAITING_FOR_KEY"
WAITING_FOR_WHEEL_INDICATOR = "WAITING_FOR_WHEEL_INDICATOR"
NAMING = "NAMING"
DELETING = "DELETING"
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
DEFAULT_MIN_CIRCLE_R = 30
DEFAULT_MIN_RECTANGLE_DIST = 50
DEFAULT_MIN_MOVE_DIST = 3
DEFAULT_RADIAL_TOLERANCE = 5
DEFAULT_EDGE_TOLERANCE = 5
DEFAULT_VERTEX_TOLERANCE = 10
DEFAULT_SPEC_MAX_RATIO = 0.3


def calculate_raw_rectangle(values: tuple[tuple[float, float], tuple[float, float]]):
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


class _CursorManager:
    def __init__(self, canvas: FigureCanvasQTAgg):
        self.canvas = canvas
        self.state_map = {
            IDLE: Qt.CursorShape.ArrowCursor,
            COLLECTING: Qt.CursorShape.CrossCursor,
            WAITING_FOR_KEY: Qt.CursorShape.PointingHandCursor,
            WAITING_FOR_WHEEL_INDICATOR: Qt.CursorShape.PointingHandCursor,
            NAMING: Qt.CursorShape.IBeamCursor,
            DELETING: Qt.CursorShape.ForbiddenCursor,
            CONFIRM_DELETE_ALL: Qt.CursorShape.WaitCursor,
            CONFIRM_EXIT: Qt.CursorShape.WaitCursor,
        }

    def set_state_cursor(self, state: str):
        self.canvas.setCursor(self.state_map.get(state, Qt.CursorShape.ArrowCursor))

    def set_custom_cursor(self, shape: Qt.CursorShape):
        self.canvas.setCursor(shape)


class _Draggable:
    def __init__(
        self, entry_id: int, is_shape: bool, plotter_ref: LayoutsPlotterWidget
    ):
        self.entry_id = entry_id
        self.plotter = plotter_ref
        self.cursor_manager = plotter_ref.cursor_manager
        self.is_shape = is_shape

        if is_shape:
            self.artist_id = "shape_" + str(entry_id)
            self.default_face_color = self.plotter.shapes_artists[
                entry_id
            ].get_facecolor()
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
                return self.plotter.draggables_ids[
                    (idx + 1) % len(self.plotter.draggables_ids)
                ]
            else:
                return self.plotter.last_artist_id
        else:
            self.plotter.iter_count = 0
            return self.plotter.draggables_ids[0]

    def indicate_current_draggable_id(self):
        curr_id = self.plotter.current_draggable_id
        if curr_id is None:
            return

        self.plotter.zone_selected.emit(self.entry_id)
        priority = self.plotter.shapes[self.entry_id].get("priority", 0)
        pointer_info = (
            "Pointer Enabled"
            if self.plotter.shapes[self.entry_id]["pointer"]
            else "Pointer Disabled"
        )

        if curr_id.startswith("label_"):
            draggable_artist = self.plotter.labels_drag_managers.get(self.entry_id)
            if draggable_artist and draggable_artist.artist_id == curr_id:
                if (
                    label_bbox := draggable_artist.label_artist.get_bbox_patch()
                ) is not None:
                    label_bbox.set_edgecolor(INDICATED_EDGE_COLOR)
                    label_bbox.set_linewidth(DEFAULT_MEDIUM_LINE_WIDTH)
                self.plotter.update_title(
                    f"Current Artist: {curr_id} (ID: {self.entry_id}, Prio: {priority}) | Drag/Nudge | {pointer_info}",
                    True,
                )
            self.plotter.current_draggable = draggable_artist

        elif curr_id.startswith("shape_"):
            draggable_artist = self.plotter.shapes_drag_managers.get(self.entry_id)
            if draggable_artist and draggable_artist.artist_id == curr_id:
                shape_artist = draggable_artist.shape_artist
                shape_artist.set_edgecolor(INDICATED_EDGE_COLOR)
                shape_artist.set_linewidth(DEFAULT_LARGE_LINE_WIDTH)
                self.plotter.update_title(
                    f"Current Artist: {curr_id} (ID: {self.entry_id}, Prio: {priority}) | Drag/Resize/Nudge | {pointer_info}",
                    True,
                )
            self.plotter.current_draggable = draggable_artist

        self.cursor_manager.set_custom_cursor(Qt.CursorShape.SizeAllCursor)

    def clean_up_current_draggable_id(self):
        self.indicate_current_draggable_id()
        if self.plotter.current_move_distance <= DEFAULT_MIN_MOVE_DIST:
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
            shape.set_facecolor(
                get_dulled_hue_color(
                    *get_hue_modified_alpha_from_hsv(self.default_face_color)
                )
            )
        else:
            if (
                label_bbox := self.plotter.labels_artists[
                    self.entry_id
                ].get_bbox_patch()
            ) is not None:
                label_bbox.set_facecolor(
                    get_dulled_hue_color(
                        *get_hue_modified_alpha_from_hsv(self.default_face_color)
                    )
                )

    def restore_face_color(self):
        if self.is_shape:
            self.plotter.shapes_artists[self.entry_id].set_facecolor(
                self.default_face_color
            )
        else:
            if (
                label_bbox := self.plotter.labels_artists[
                    self.entry_id
                ].get_bbox_patch()
            ) is not None:
                label_bbox.set_facecolor(self.default_face_color)


class _DraggableLabel(_Draggable):
    def __init__(self, entry_id: int, plotter_ref: LayoutsPlotterWidget):
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
        if (
            self.plotter.is_fatal_state
            or self.plotter.state != IDLE
            or self.label_artist.axes is None
        ):
            return

        self.plotter.ignore_current_draggable_id_n += 1
        self._on_press_helper(event)
        self.plotter.fire_on_motion = True

        if (label_bbox := self.label_artist.get_bbox_patch()) is not None:
            label_bbox.set_edgecolor(ACTIVE_EDGE_COLOR)
            label_bbox.set_linewidth(DEFAULT_LARGE_LINE_WIDTH)

        self.label_artist.set_visible(False)
        self.shape_artist.set_edgecolor(ACTIVE_EDGE_COLOR)
        self.shape_artist.set_linewidth(DEFAULT_LARGE_LINE_WIDTH)

        self.canvas.draw()
        ax = self.label_artist.axes
        if ax.bbox.width > 0 and ax.bbox.height > 0:
            dpi_ratio = (
                self.canvas.device_pixel_ratio
                if hasattr(self.canvas, "device_pixel_ratio")
                else 1.0
            )
            pad = 5 * dpi_ratio
            padded_bbox = ax.bbox.padded(pad)
            self.drag_bg = self.canvas.copy_from_bbox(padded_bbox)

        self.label_artist.set_visible(True)
        self.plotter.drawn = True

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

        if (label_bbox := self.label_artist.get_bbox_patch()) is not None:
            label_bbox.set_edgecolor("black")
        if self.label_artist.get_visible():
            self.shape_artist.set_visible(True)
            self.populate_draggables_list()

        self.canvas.draw_idle()

    def _on_motion(self, event):
        if not self.plotter.fire_on_motion or self.label_artist.axes is None:
            return
        if self.press is None or event.inaxes != self.label_artist.axes:
            return

        if self.plotter.current_draggable_id is None:
            self.plotter.current_draggable_id = self.select_current_draggable_id()
            self.indicate_current_draggable_id()

        if self.plotter.current_draggable_id != self.artist_id:
            return

        self.plotter.ignore_current_draggable_id_n = 1

        _, _, xdata_press, ydata_press, xpx_press, ypx_press = self.press
        dx = event.xdata - xdata_press
        dy = event.ydata - ydata_press
        dx_press = event.x - xpx_press
        dy_press = event.y - ypx_press
        self.plotter.current_move_distance = ((dx_press**2) + (dy_press**2)) ** 0.5

        if self.drag_bg is not None:
            self.canvas.restore_region(self.drag_bg)

        self._move_label(dx, dy)
        self.label_artist.axes.draw_artist(self.label_artist)
        self.canvas.blit(self.label_artist.axes.bbox)

    def _move_label(self, dx, dy):
        if not self.press:
            return
        x0, y0, _, _, _, _ = self.press
        self.label_artist.set_position((x0 + dx, y0 + dy))

    def _move(self, dx, dy):
        if not self.press:
            return
        _, _, xdata_press, ydata_press, xpx_press, ypx_press = self.press
        x, y = self.label_artist.get_position()
        self.press = x, y, xdata_press, ydata_press, xpx_press, ypx_press
        self._move_label(dx, dy)
        self.canvas.draw()
        self.plotter.drawn = False

    def _on_release(self, event=None):
        if self.plotter.is_fatal_state or self.plotter.state != IDLE:
            return

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
            self.plotter.update_title(
                f"OVERLAYS: {'VISIBLE' if self.plotter.show_overlays else 'HIDDEN'}",
                True,
            )

        if (label_bbox := self.label_artist.get_bbox_patch()) is not None:
            label_bbox.set_edgecolor("black")
            label_bbox.set_linewidth(DEFAULT_SMALL_LINE_WIDTH)

    def _disconnect_cids(self):
        for cid in self.cids:
            self.canvas.mpl_disconnect(cid)


class _DraggableShape(_Draggable):
    def __init__(self, entry_id: int, plotter_ref: LayoutsPlotterWidget):
        super().__init__(entry_id, True, plotter_ref)
        self.label_artist = self.plotter.labels_artists[entry_id]
        self.shape_artist = self.plotter.shapes_artists[entry_id]
        self.canvas = self.plotter.canvas
        self.press = None
        self.drag_bg = None
        self.shape_mode = None
        self.cids: list[int] = []

    def _connect_cids(self) -> None:
        raise NotImplementedError()

    def _move(self, dx, dy) -> None:
        raise NotImplementedError()

    def _on_press(self, event):
        if (
            self.plotter.is_fatal_state
            or self.plotter.state != IDLE
            or self.shape_artist.axes is None
        ):
            return

        self.plotter.ignore_current_draggable_id_n += 1
        self._on_press_helper(event)
        self.plotter.fire_on_motion = True

        self.shape_artist.set_edgecolor(ACTIVE_EDGE_COLOR)
        self.shape_artist.set_linewidth(DEFAULT_LARGE_LINE_WIDTH)
        self.shape_artist.set_visible(False)

        if (label_bbox := self.label_artist.get_bbox_patch()) is not None:
            label_bbox.set_edgecolor(ACTIVE_EDGE_COLOR)
            label_bbox.set_linewidth(DEFAULT_LARGE_LINE_WIDTH)

        self.canvas.draw()
        ax = self.shape_artist.axes
        if ax.bbox.width > 0 and ax.bbox.height > 0:
            # Pad the bbox by 5 pixels in display coordinates to capture thick stroke outlines
            dpi_ratio = (
                self.canvas.device_pixel_ratio
                if hasattr(self.canvas, "device_pixel_ratio")
                else 1.0
            )
            pad = 5 * dpi_ratio
            padded_bbox = ax.bbox.padded(pad)
            self.drag_bg = self.canvas.copy_from_bbox(padded_bbox)

        self.shape_artist.set_visible(True)
        self.plotter.drawn = True

    def _on_press_helper(self, event):
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

    def _on_press_shape_helper(self, event) -> tuple[float, float] | None:
        raise NotImplementedError()

    def _shape_transform(self, event) -> None:
        raise NotImplementedError()

    def _on_motion(self, event):
        if not self.plotter.fire_on_motion or self.shape_artist.axes is None:
            return
        if self.press is None or event.inaxes != self.shape_artist.axes:
            return

        if self.plotter.current_draggable_id is None:
            self.plotter.current_draggable_id = self.select_current_draggable_id()
            self.indicate_current_draggable_id()

        if self.plotter.current_draggable_id != self.artist_id:
            return
        self.plotter.ignore_current_draggable_id_n = 1

        _, _, _, _, xpx_press, ypx_press = self.press
        dx_press = event.x - xpx_press
        dy_press = event.y - ypx_press
        self.plotter.current_move_distance = ((dx_press**2) + (dy_press**2)) ** 0.5

        if self.drag_bg is not None:
            self.canvas.restore_region(self.drag_bg)

        self._shape_transform(event)
        self.shape_artist.axes.draw_artist(self.shape_artist)
        self.canvas.blit(self.shape_artist.axes.bbox)

    def _on_release(self, event=None):
        if self.plotter.is_fatal_state or self.plotter.state:
            return

        self._partial_release()

        if self.plotter.current_draggable_id is None and self.plotter.draggables_ids:
            self.plotter.current_draggable_id = self.select_current_draggable_id()
            self.indicate_current_draggable_id()

        if self.artist_id == self.plotter.current_draggable_id:
            if self.plotter.drawn:
                if (label_bbox := self.label_artist.get_bbox_patch()) is not None:
                    label_bbox.set_edgecolor("black")
                    label_bbox.set_linewidth(DEFAULT_SMALL_LINE_WIDTH)

            self.clean_up_current_draggable_id()
            self.shape_artist.remove()
            self.plotter.ax.add_patch(self.shape_artist)

        self.canvas.draw_idle()

    def _partial_release(self):
        if self.plotter.ignore_current_draggable_id_n <= 0:
            self.plotter.update_title(
                f"OVERLAYS: {'VISIBLE' if self.plotter.show_overlays else 'HIDDEN'}",
                True,
            )

        self.shape_artist.set_edgecolor(DEFAULT_EDGE_COLOR)
        self.shape_artist.set_linewidth(DEFAULT_MEDIUM_LINE_WIDTH)

    def _disconnect_cids(self):
        for cid in self.cids:
            self.canvas.mpl_disconnect(cid)


class _DraggableCircle(_DraggableShape):
    def __init__(self, entry_id: int, plotter_ref: LayoutsPlotterWidget):
        super().__init__(entry_id, plotter_ref)
        if not isinstance(self.shape_artist, Circle):
            return
        new_r = max(self.shape_artist.get_radius(), DEFAULT_MIN_CIRCLE_R)
        self.shape_artist.set_radius(new_r)
        self.plotter.shapes[self.entry_id]["r"] = new_r
        self._connect_cids()

    def _connect_cids(self):
        if self.canvas.supports_blit:
            self.cids.extend(
                [
                    self.canvas.mpl_connect("button_press_event", self._on_press),
                    self.canvas.mpl_connect("motion_notify_event", self._on_motion),
                    self.canvas.mpl_connect("button_release_event", self._on_release),
                ]
            )

    def _on_press(self, event):
        if self.plotter.is_fatal_state or self.plotter.state != IDLE:
            return

        self.plotter.ignore_current_draggable_id_n += 1
        self._on_press_helper(event)
        self.plotter.fire_on_motion = True

    def _on_press_shape_helper(self, event):
        if not isinstance(self.shape_artist, Circle):
            return
        cx, cy = self.shape_artist.get_center()  # type: ignore
        self.shape_mode = self._get_circumference(event, cx, cy)
        return float(cx), float(cy)

    def _shape_transform(self, event) -> None:
        self._circle_transform(event)

    def _circle_transform(self, event):
        if (
            self.shape_mode is None
            or not isinstance(self.shape_artist, Circle)
            or self.press is None
        ):
            return

        xdata, ydata = event.xdata, event.ydata
        old_cx, old_cy = self.shape_artist.get_center()  # type: ignore
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
        if not isinstance(self.shape_artist, Circle):
            return
        current_shape = self.plotter.shapes[self.entry_id]

        if (
            self.plotter.saved_mouse_wheel
            and current_shape["scancode"] == MOUSE_WHEEL_SIMULATOR_CODE
        ):
            self.plotter.mouse_wheel_cx = new_cx
            self.plotter.mouse_wheel_cy = new_cy
            self.plotter.mouse_wheel_radius = current_shape["r"]
            self.plotter.mouse_wheel_indicators.move_mouse_wheel_indicators()

            if (
                self.plotter.saved_sprint_distance
                and self.plotter.sprint_artist_id is not None
            ):
                sprint_artist = self.plotter.shapes_drag_managers[
                    self.plotter.sprint_artist_id
                ]
                if (
                    sprint_shape_artist := sprint_artist.shape_artist
                ) is not None and isinstance(sprint_shape_artist, Circle):
                    cx, cy = sprint_shape_artist.get_center()  # type: ignore
                    actual_dist = self.plotter._euclidean_distance(
                        cx, cy, new_cx, new_cy
                    )

                    if actual_dist <= self.plotter.mouse_wheel_radius:
                        r = self.plotter.mouse_wheel_radius
                        screen_rect = (
                            (0, 0),
                            (self.plotter.img_width, self.plotter.img_height),
                        )
                        sp_x, sp_y = self.plotter._constrain_point_to_rect_radial(
                            new_cx, new_cy - r - 1, new_cx, new_cy, screen_rect
                        )
                        sp_x, sp_y = int(round(sp_x)), int(round(sp_y))

                        sprint_shape = self.plotter.shapes[
                            self.plotter.sprint_artist_id
                        ]
                        sprint_shape_artist.set_center((sp_x, sp_y))
                        sprint_shape["cx"] = sp_x
                        sprint_shape["cy"] = sp_y
                        self.plotter.sprint_distance = self.plotter._euclidean_distance(
                            sp_x, sp_y, new_cx, new_cy
                        )
                    else:
                        self.plotter.sprint_distance = actual_dist

        if (
            self.plotter.saved_sprint_distance
            and current_shape["scancode"] == SPRINT_DISTANCE_CODE
        ):
            actual_dist = self.plotter._euclidean_distance(
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

    def _get_circumference(self, event, cx, cy):
        if not isinstance(self.shape_artist, Circle) or self.shape_artist.axes is None:
            return
        r = self.shape_artist.get_radius()
        cx_px, cy_px = self.shape_artist.axes.transData.transform((cx, cy))
        rim_x_px, _ = self.shape_artist.axes.transData.transform((cx + r, cy))
        r_px = abs(rim_x_px - cx_px)
        dist_px = ((event.x - cx_px) ** 2 + (event.y - cy_px) ** 2) ** 0.5
        diff_px = abs(dist_px - r_px)

        if diff_px <= DEFAULT_RADIAL_TOLERANCE:
            return "resize"
        if dist_px <= r_px:
            return "drag"
        return

    def _update_radius(self, xdata, ydata):
        if not isinstance(self.shape_artist, Circle):
            return
        cx, cy = self.shape_artist.get_center()  # type: ignore
        new_r = int(round(((xdata - cx) ** 2 + (ydata - cy) ** 2) ** 0.5))
        current_shape = self.plotter.shapes[self.entry_id]
        new_sp_r = None

        if (
            self.plotter.saved_mouse_wheel
            and current_shape["scancode"] == MOUSE_WHEEL_SIMULATOR_CODE
        ):
            new_r = min(
                new_r,
                int(
                    round(
                        DEFAULT_SPEC_MAX_RATIO
                        * ((self.plotter.img_width + self.plotter.img_height) / 2)
                    )
                ),
            )
            if (
                self.plotter.saved_sprint_distance
                and self.plotter.sprint_artist_id is not None
            ):
                sprint_artist = self.plotter.shapes_drag_managers[
                    self.plotter.sprint_artist_id
                ]
                if (
                    sprint_shape_artist := sprint_artist.shape_artist
                ) is not None and isinstance(sprint_shape_artist, Circle):
                    if new_r < sprint_shape_artist.get_radius():
                        new_sp_r = new_r

        if (
            self.plotter.saved_sprint_distance
            and current_shape["scancode"] == SPRINT_DISTANCE_CODE
        ):
            new_r = min(new_r, self.plotter.mouse_wheel_radius)

        if new_r >= DEFAULT_MIN_CIRCLE_R:
            self.shape_artist.set_radius(new_r)
            current_shape["r"] = new_r
            if new_sp_r is not None and self.plotter.sprint_artist_id is not None:
                sprint_artist = self.plotter.shapes_drag_managers[
                    self.plotter.sprint_artist_id
                ]
                if (
                    sprint_shape_artist := sprint_artist.shape_artist
                ) is not None and isinstance(sprint_shape_artist, Circle):
                    sprint_shape = self.plotter.shapes[self.plotter.sprint_artist_id]
                    sprint_shape_artist.set_radius(new_sp_r)
                    sprint_shape["r"] = new_sp_r

    def _move_circle(self, dx, dy):
        if isinstance(self.shape_artist, Circle):
            x0, y0, _, _, _, _ = self.press
            new_cx = int(round(x0 + dx))
            new_cy = int(round(y0 + dy))
            self.shape_artist.set_center((new_cx, new_cy))

            current_shape = self.plotter.shapes[self.entry_id]
            current_shape["cx"] = new_cx
            current_shape["cy"] = new_cy

            return new_cx, new_cy
        return dx, dy

    def _move(self, dx, dy):
        if not isinstance(self.shape_artist, Circle) or not self.press:
            return
        _, _, xdata_press, ydata_press, xpx_press, ypx_press = self.press
        cx, cy = self.shape_artist.get_center()  # type: ignore
        self.press = cx, cy, xdata_press, ydata_press, xpx_press, ypx_press
        old_cx, old_cy = self.shape_artist.get_center()  # type: ignore
        old_r = self.shape_artist.get_radius()
        new_cx, new_cy = self._move_circle(dx, dy)
        self._circle_transform_helper(old_cx, old_cy, old_r, new_cx, new_cy)
        self.canvas.draw()
        self.plotter.drawn = False


class _DraggableRectangle(_DraggableShape):
    def __init__(self, entry_id: int, plotter_ref: LayoutsPlotterWidget):
        super().__init__(entry_id, plotter_ref)
        if not isinstance(self.shape_artist, Rectangle):
            return
        x, y = self.shape_artist.get_xy()
        self._update_rectangle_safe(
            x, y, self.shape_artist.get_width(), self.shape_artist.get_height()
        )
        self._connect_cids()

    def _connect_cids(self):
        if self.canvas.supports_blit:
            self.cids.extend(
                [
                    self.canvas.mpl_connect("button_press_event", self._on_press),
                    self.canvas.mpl_connect("motion_notify_event", self._on_motion),
                    self.canvas.mpl_connect("button_release_event", self._on_release),
                ]
            )

    def _on_press(self, event):
        if self.plotter.is_fatal_state or self.plotter.state != IDLE:
            return

        self.plotter.ignore_current_draggable_id_n += 1
        self._on_press_helper(event)
        self.plotter.fire_on_motion = True

    def _on_press_shape_helper(self, event):
        if not isinstance(self.shape_artist, Rectangle):
            return
        x, y = self.shape_artist.get_xy()
        self.shape_mode = self._get_corner_under_mouse(
            event
        ) or self._get_edge_under_mouse(event)
        return x, y

    def _shape_transform(self, event) -> None:
        self._rectangle_transform(event)

    def _rectangle_transform(self, event):
        if self.shape_mode is None or self.press is None:
            return
        xdata, ydata = event.xdata, event.ydata
        if self._update_corner(self.shape_mode, xdata, ydata):
            return
        if self._update_edge(self.shape_mode, xdata, ydata):
            return
        if self.shape_mode == "drag":
            _, _, xdata_press, ydata_press, _, _ = self.press
            self._move_rectangle(xdata - xdata_press, ydata - ydata_press)

    def _get_corner_under_mouse(self, event):
        if (
            not isinstance(self.shape_artist, Rectangle)
            or self.shape_artist.axes is None
        ):
            return
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
            if (
                (event.x - cx_px) ** 2 + (event.y - cy_px) ** 2
            ) ** 0.5 <= DEFAULT_VERTEX_TOLERANCE:
                return name
        return

    def _get_edge_under_mouse(self, event):
        if not isinstance(self.shape_artist, Rectangle):
            return
        mx, my = event.x, event.y
        bbox = self.shape_artist.get_window_extent()
        is_h = bbox.xmin <= mx <= bbox.xmax
        is_v = bbox.ymin <= my <= bbox.ymax

        if abs(mx - bbox.xmin) <= DEFAULT_EDGE_TOLERANCE and is_v:
            return "left"
        if abs(mx - bbox.xmax) <= DEFAULT_EDGE_TOLERANCE and is_v:
            return "right"
        if abs(my - bbox.ymin) <= DEFAULT_EDGE_TOLERANCE and is_h:
            return "bottom"
        if abs(my - bbox.ymax) <= DEFAULT_EDGE_TOLERANCE and is_h:
            return "top"
        if is_h and is_v:
            return "drag"
        return None

    def _update_corner(self, corner, xdata, ydata):
        if not isinstance(self.shape_artist, Rectangle) or corner is None:
            return False
        xdata, ydata = int(round(xdata)), int(round(ydata))
        x, y = self.shape_artist.get_xy()
        w, h = self.shape_artist.get_width(), self.shape_artist.get_height()

        if corner == "top_left":
            return (
                self._update_rectangle_safe(
                    xdata, ydata, (x + w) - xdata, (y + h) - ydata
                )
                or True
            )
        if corner == "top_right":
            return (
                self._update_rectangle_safe(x, ydata, xdata - x, (y + h) - ydata)
                or True
            )
        if corner == "bottom_left":
            return (
                self._update_rectangle_safe(xdata, y, (x + w) - xdata, ydata - y)
                or True
            )
        if corner == "bottom_right":
            return self._update_rectangle_safe(x, y, xdata - x, ydata - y) or True
        return False

    def _update_edge(self, edge, xdata, ydata):
        if not isinstance(self.shape_artist, Rectangle) or edge is None:
            return False
        xdata, ydata = int(round(xdata)), int(round(ydata))
        x, y = self.shape_artist.get_xy()
        w, h = self.shape_artist.get_width(), self.shape_artist.get_height()

        if edge == "right":
            return self._update_rectangle_safe(x, y, xdata - x, h) or True
        if edge == "left":
            return self._update_rectangle_safe(xdata, y, (x + w) - xdata, h) or True
        if edge == "bottom":
            return self._update_rectangle_safe(x, y, w, ydata - y) or True
        if edge == "top":
            return self._update_rectangle_safe(x, ydata, w, (y + h) - ydata) or True
        return False

    def _update_rectangle_safe(self, x, y, w, h):
        if not isinstance(self.shape_artist, Rectangle):
            return
        x, y, w, h = int(round(x)), int(round(y)), int(round(w)), int(round(h))
        if w < 0 or h < 0:
            return

        changed = [True, True]
        if w >= DEFAULT_MIN_RECTANGLE_DIST:
            self.shape_artist.set_x(x)
            self.shape_artist.set_width(w)
        else:
            x = int(round(self.shape_artist.get_x()))
            w = max(
                int(round(self.shape_artist.get_width())), DEFAULT_MIN_RECTANGLE_DIST
            )
            changed[0] = False

        if h >= DEFAULT_MIN_RECTANGLE_DIST:
            self.shape_artist.set_y(y)
            self.shape_artist.set_height(h)
        else:
            y = int(round(self.shape_artist.get_y()))
            h = max(
                int(round(self.shape_artist.get_height())), DEFAULT_MIN_RECTANGLE_DIST
            )
            changed[1] = False

        if any(changed):
            cx, cy, _, bb = calculate_raw_rectangle(((x, y), (x + w, y + h)))

            current_shape = self.plotter.shapes[self.entry_id]
            current_shape["cx"] = cx
            current_shape["cy"] = cy
            current_shape["bb"] = bb

    def _move_rectangle(self, dx, dy):
        if not isinstance(self.shape_artist, Rectangle) or self.press is None:
            return
        x0, y0, _, _, _, _ = self.press
        self._update_rectangle_safe(
            int(round(x0 + dx)),
            int(round(y0 + dy)),
            self.shape_artist.get_width(),
            self.shape_artist.get_height(),
        )

    def _move(self, dx, dy):
        if not isinstance(self.shape_artist, Rectangle) or not self.press:
            return
        _, _, xdata_press, ydata_press, xpx_press, ypx_press = self.press
        x, y = self.shape_artist.get_xy()
        self.press = x, y, xdata_press, ydata_press, xpx_press, ypx_press
        self._move_rectangle(dx, dy)
        self.canvas.draw()
        self.plotter.drawn = False


class _MouseWheelDragManager:
    def __init__(self, entry_id: int, plotter_ref: LayoutsPlotterWidget):
        self.cids: list[int] = []
        self.entry_id = entry_id
        self.plotter = plotter_ref
        self._connect_cids()

    def _connect_cids(self):
        self.cids.extend(
            [self.plotter.canvas.mpl_connect("button_press_event", self._on_press)]
        )

    def _on_press(self, event):
        if (
            self.plotter.is_fatal_state
            or self.plotter.state != IDLE
            or not self.plotter.saved_mouse_wheel
            or not self.plotter.show_overlays
            or event.inaxes != self.plotter.ax
        ):
            return

        indicators = self.plotter.mouse_wheel_indicators
        lbl = indicators.mouse_wheel_labels_artists.get(self.entry_id)
        shp = indicators.mouse_wheel_shapes_artists.get(self.entry_id)

        hit_lbl = lbl.contains(event)[0] if lbl and lbl.get_visible() else False
        hit_shp = shp.contains(event)[0] if shp and shp.get_visible() else False

        if not (hit_lbl or hit_shp):
            return

        # Prevent the underlying mouse wheel circle from starting a drag/resize
        self.plotter.fire_on_motion = False
        self.plotter.draggables_ids.clear()

        self.plotter.state = WAITING_FOR_WHEEL_INDICATOR
        indicators.current_mouse_wheel_indicator = self.entry_id
        self.plotter.mouse_wheel_indicators.highlight_mouse_wheel_indicator(
            self.entry_id
        )
        self.plotter.update_title(
            "Press KEY to bind or click anywhere outside the indicator to cancel."
        )

    def _disconnect_cids(self):
        for cid in self.cids:
            self.plotter.canvas.mpl_disconnect(cid)


class MouseWheelIndicators:
    def __init__(self, plotter_ref: LayoutsPlotterWidget) -> None:
        self.mouse_wheel_indicators_map: dict[int, int] = {}

        self.mouse_wheel_shapes_artists: dict[int, Circle] = {}
        self.mouse_wheel_labels_artists: dict[int, Text] = {}
        self.mouse_wheel_labels_drag_managers: dict[int, _MouseWheelDragManager] = {}
        self.current_mouse_wheel_indicator: int | None = None
        self.plotter = plotter_ref

    def _calculate_translations(self) -> dict[int, tuple[float, float]]:
        cx = self.plotter.mouse_wheel_cx
        cy = self.plotter.mouse_wheel_cy
        r = self.plotter.mouse_wheel_radius
        # 0: Up (cy - r), 1: Left (cx - r), 2: Down (cy + r), 3: Right (cx + r)
        return {0: (cx, cy - r), 1: (cx - r, cy), 2: (cx, cy + r), 3: (cx + r, cy)}

    def create_mouse_wheel_indicators(self):
        directional_scancodes = store.zones.get_mouse_wheel_directional_scancodes(
            self.plotter.active_layout
        )
        translations = self._calculate_translations()
        for i in range(4):
            self.mouse_wheel_indicators_map[i] = directional_scancodes[i]
            lbl_txt = (get_key_from_scancode(directional_scancodes[i]) or "").upper()
            cx, cy = translations[i]

            lbl = self.plotter._create_label(
                cx, cy, lbl_txt, DEFAULT_MOUSE_WHEEL_FACE_COLOR
            )
            art = self.plotter._create_circle(
                cx, cy, DEFAULT_MIN_CIRCLE_R, DEFAULT_MOUSE_WHEEL_FACE_COLOR
            )

            self.mouse_wheel_labels_artists[i] = lbl
            self.mouse_wheel_shapes_artists[i] = art
            self.mouse_wheel_labels_drag_managers[i] = _MouseWheelDragManager(
                i, self.plotter
            )

            is_vis = (
                self.plotter.show_overlays if self.plotter.saved_mouse_wheel else False
            )
            lbl.set_visible(is_vis)
            self.plotter.ax.add_artist(lbl)

            art.set_visible(is_vis)
            self.plotter.ax.add_patch(art)

    def update_mouse_wheel_indicator_from_key(self, key_name: str):
        current_indicator = self.current_mouse_wheel_indicator

        if current_indicator is not None:
            scancode = get_scancode_from_key(key_name)

            if not scancode:
                msg = f"Key '{key_name}' not mapped."
                self.plotter.update_title(msg)
                print(msg)
                return

            if scancode == MOUSE_WHEEL_SIMULATOR_CODE:
                msg = f"Key '{key_name}' with scancode '{scancode}' cannot be bound to the indicator as it is the mouse wheel code."
                self.plotter.update_title(msg)
                print(msg)
                return

            elif scancode == SPRINT_DISTANCE_CODE:
                msg = f"Key '{key_name}' with scancode '{scancode}' cannot be bound to the indicator as it is the sprint code."
                self.plotter.update_title(msg)
                print(msg)
                return

            self.update_mouse_wheel_indicator_from_scancode(
                current_indicator, key_name, scancode
            )

    def update_mouse_wheel_indicator_from_scancode(
        self, current_indicator: int, key_name: str, scancode: int
    ):
        scancode_key_name = get_key_from_scancode(scancode)
        if not scancode_key_name:
            msg = f"Key '{key_name}' with scancode '{scancode}' has no equivalent key name."
            self.plotter.update_title(msg)
            print(msg)
            return

        self.mouse_wheel_indicators_map[current_indicator] = scancode

        if current_indicator in self.mouse_wheel_labels_artists:
            self.mouse_wheel_labels_artists[current_indicator].set_text(
                scancode_key_name.upper()
            )

        self.current_mouse_wheel_indicator = None
        self.unhighlight_mouse_wheel_indicator(current_indicator)
        self.plotter.reset_state()

    def delete_mouse_wheel_indicators(self):
        for uid in list(self.mouse_wheel_labels_artists.keys()):
            label_artist = self.mouse_wheel_labels_artists[uid]
            if label_artist in self.plotter.ax.artists:
                label_artist.remove()
        self.mouse_wheel_labels_artists = {}

        for uid in list(self.mouse_wheel_shapes_artists.keys()):
            shape_artist = self.mouse_wheel_shapes_artists[uid]
            if shape_artist in self.plotter.ax.patches:
                shape_artist.remove()
        self.mouse_wheel_shapes_artists = {}

        for uid in list(self.mouse_wheel_labels_drag_managers.keys()):
            self.mouse_wheel_labels_drag_managers[uid]._disconnect_cids()
        self.mouse_wheel_labels_drag_managers = {}

    def set_indicators_visible(self, visible: bool) -> None:
        target_vis = (
            visible and self.plotter.saved_mouse_wheel and self.plotter.show_overlays
        )
        for i in range(4):
            if i in self.mouse_wheel_labels_artists:
                self.mouse_wheel_labels_artists[i].set_visible(target_vis)
            if i in self.mouse_wheel_shapes_artists:
                self.mouse_wheel_shapes_artists[i].set_visible(target_vis)

    def move_mouse_wheel_indicators(self):
        translations = self._calculate_translations()
        for i in range(4):
            if (
                i not in self.mouse_wheel_labels_artists
                or i not in self.mouse_wheel_shapes_artists
            ):
                continue
            cx, cy = translations[i]
            label_artist = self.mouse_wheel_labels_artists[i]
            shape_artist = self.mouse_wheel_shapes_artists[i]

            label_artist.set_position((cx, cy))
            shape_artist.set_center((cx, cy))

    def highlight_mouse_wheel_indicator(self, index: int | None):
        if index is None:
            return

        if index in self.mouse_wheel_labels_artists:
            if (
                label_bbox := self.mouse_wheel_labels_artists[index].get_bbox_patch()
            ) is not None:
                label_bbox.set_edgecolor(ACTIVE_EDGE_COLOR)
                label_bbox.set_linewidth(DEFAULT_LARGE_LINE_WIDTH)

        if index in self.mouse_wheel_shapes_artists:
            shape_artist = self.mouse_wheel_shapes_artists[index]
            shape_artist.set_edgecolor(ACTIVE_EDGE_COLOR)
            shape_artist.set_linewidth(DEFAULT_LARGE_LINE_WIDTH)

    def unhighlight_mouse_wheel_indicator(self, index: int | None):
        if index is None:
            return

        if index in self.mouse_wheel_labels_artists:
            if (
                label_bbox := self.mouse_wheel_labels_artists[index].get_bbox_patch()
            ) is not None:
                label_bbox.set_edgecolor("black")
                label_bbox.set_linewidth(DEFAULT_SMALL_LINE_WIDTH)

        if index in self.mouse_wheel_shapes_artists:
            shape_artist = self.mouse_wheel_shapes_artists[index]
            shape_artist.set_edgecolor(DEFAULT_EDGE_COLOR)
            shape_artist.set_linewidth(DEFAULT_MEDIUM_LINE_WIDTH)


class LayoutsPlotterWidget(QWidget):
    layout_saved = Signal(str, int)
    zone_selected = Signal(int)
    status_updated = Signal(str)

    def __init__(self, parent: QWidget | None = None, standalone: bool = False):
        super().__init__(parent)
        self.standalone = standalone
        self.is_fatal_state = False

        self.fig = Figure()
        self.fig.subplots_adjust(left=0, right=1, top=1, bottom=0)

        self.canvas = FigureCanvasQTAgg(self.fig)
        self.canvas.setMinimumSize(1, 1)
        self.canvas.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

        self.ax = self.fig.add_subplot(1, 1, 1)
        self.ax.set_axis_off()
        self.ax.set_position((0, 0, 1, 1))

        self.fig.patch.set_visible(False)
        self.ax.patch.set_visible(False)

        self.root_layout = QVBoxLayout(self)
        self.root_layout.setContentsMargins(0, 0, 0, 0)
        self.root_layout.setSpacing(0)
        self.root_layout.addWidget(self.canvas)

        for key in list(self.canvas.callbacks.callbacks.keys()):
            if "key_press_event" in key:
                self.canvas.callbacks.callbacks[key].clear()

        self.cursor_manager = _CursorManager(self.canvas)
        self.active_layout: Layout | None = None

        self.shapes_artists: dict[int, Circle | Rectangle] = {}
        self.labels_artists: dict[int, Text] = {}
        self.labels_drag_managers: dict[int, _DraggableLabel] = {}
        self.shapes_drag_managers: dict[int, _DraggableShape] = {}

        self.top_bezel_id: int | None = None
        self.top_bezel_label_artist = Text()
        self.top_bezel_shape_artist = Rectangle((0, 0), 0, 0)
        self.bottom_bezel_id: int | None = None
        self.bottom_bezel_label_artist = Text()
        self.bottom_bezel_shape_artist = Rectangle((0, 0), 0, 0)

        self.mouse_wheel_indicators = MouseWheelIndicators(self)

        self.canvas.mpl_connect("motion_notify_event", self._on_mouse_move)
        self.canvas.mpl_connect("key_press_event", self._on_key_press)
        self.canvas.mpl_connect("button_press_event", self._on_click)
        self.canvas.mpl_connect("resize_event", self.on_resize)
        self.canvas.mpl_connect("draw_event", self._on_draw)
        self.canvas.mpl_connect("axes_leave_event", self._on_mouse_leave)
        self.canvas.mpl_connect("figure_leave_event", self._on_mouse_leave)

        self.reload_active_layout()

    def _init_params_helper(self):
        self.points = []
        self.point_artists = []
        self.mode = None
        self.state = IDLE
        self.input_buffer = ""
        self.current_bound_keys: list[str] = []

        self.buffer_default = True
        self.shapes: dict[int, Any] = {}
        self.count = 0
        self.artists_points = 0
        self.saved_mouse_wheel = False
        self.saved_sprint_distance = False
        self.sprint_artist_id: int | None = None
        self.mouse_wheel_radius: float = 0.0
        self.mouse_wheel_cx: int = 0
        self.mouse_wheel_cy: int = 0
        self.sprint_distance: float = 0.0
        self.show_overlays = True
        self.img_width: int = 0
        self.img_height: int = 0
        self.img_dpi: float = 0
        self.bg_cache = None

        for uid in list(self.labels_artists.keys()):
            label_artist = self.labels_artists[uid]
            if label_artist in self.ax.artists:
                label_artist.remove()
        self.labels_artists = {}

        for uid in list(self.shapes_artists.keys()):
            shape_artist = self.shapes_artists[uid]
            if shape_artist in self.ax.patches:
                shape_artist.remove()
        self.shapes_artists = {}

        for uid in list(self.labels_drag_managers.keys()):
            self.labels_drag_managers[uid]._disconnect_cids()
        self.labels_drag_managers = {}
        for uid in list(self.shapes_drag_managers.keys()):
            self.shapes_drag_managers[uid]._disconnect_cids()
        self.shapes_drag_managers = {}

        self.last_artist_id: str | None = None
        self.ignore_current_draggable_id_n = 0
        self.current_draggable_id = None
        self.current_draggable: _DraggableLabel | _DraggableShape | None = None
        self.draggables_ids = []
        self.drawn = False
        self.current_move_distance = 0.0
        self.iter_count = 0
        self.fire_on_motion = False

    def _init_crosshairs(self):
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

    def reload_active_layout(
        self,
        img: Optional[Image.Image] = None,
        image_params: Optional[tuple[int, int, int, int, int]] = None,
    ) -> bool:
        self.active_layout = store.get_active_layout()
        if not self.active_layout:
            self._render_empty_state(
                "No active layout set. Please select or create a layout first."
            )
            return False

        if not self.active_layout.image_path:
            self._render_empty_state(
                f"Layout '{self.active_layout.name}' has no assigned HUD image."
            )
            return False

        img_path = Path(self.active_layout.image_path)
        if not img_path.is_absolute():
            img_path = Path(IMAGES_FOLDER) / img_path

        if not img_path.exists():
            self._render_empty_state(
                f"Image '{img_path.as_posix()}' does not exist on disk."
            )
            return False

        # Try to get the layout's image with its parameters if it wasn't provided
        if img is None or image_params is None:
            img, image_params = self.get_image_params(self.active_layout)

        if img is None:
            self._render_empty_state("Could not load image file.")
            return False

        if image_params is None:
            self._render_empty_state("Could not get image parameters")
            return False

        self.is_fatal_state = False
        self.ax.clear()
        self._init_params_helper()
        self._init_crosshairs()

        old_width, old_height = self._update_image_params(*image_params)
        self.ax.imshow(img, aspect="equal")
        self.ax.set_xlim(-0.5, img.width - 0.5)
        self.ax.set_ylim(img.height - 0.5, -0.5)

        self._load_active_layout_zones(old_width, old_height)
        self._render_bezels_notch()

        self.mouse_wheel_indicators.delete_mouse_wheel_indicators()
        self.mouse_wheel_indicators.create_mouse_wheel_indicators()

        self.update_title(f"OVERLAYS: {'VISIBLE' if self.show_overlays else 'HIDDEN'}")
        self.canvas.draw_idle()

        return True

    def _render_bezels_notch(self):
        if self.img_width <= 0 or self.img_height <= 0:
            return

        top_kwargs = self._render_bezel_notch(self.top_bezel_id, True)
        bot_kwargs = self._render_bezel_notch(self.bottom_bezel_id, False)

        if top_kwargs:
            self.top_bezel_label_artist.set(**top_kwargs[0])
            self.top_bezel_shape_artist.set(**top_kwargs[1])
        else:
            if self.top_bezel_label_artist in self.ax.artists:
                self.top_bezel_label_artist.remove()
            if self.top_bezel_shape_artist in self.ax.patches:
                self.top_bezel_shape_artist.remove()

        if bot_kwargs:
            self.bottom_bezel_label_artist.set(**bot_kwargs[0])
            self.bottom_bezel_shape_artist.set(**bot_kwargs[1])
        else:
            if self.bottom_bezel_label_artist in self.ax.artists:
                self.bottom_bezel_label_artist.remove()
            if self.bottom_bezel_shape_artist in self.ax.patches:
                self.bottom_bezel_shape_artist.remove()

        for art in [
            self.top_bezel_label_artist,
            self.top_bezel_shape_artist,
            self.bottom_bezel_label_artist,
            self.bottom_bezel_shape_artist,
        ]:
            art.set_visible(self.show_overlays)
            if art.axes is None:
                if isinstance(art, Text):
                    self.ax.add_artist(art)
                else:
                    self.ax.add_patch(art)

    def _render_bezel_notch(self, bezel_id: int | None, is_top: bool):
        dpi = (
            int(self.active_layout.dpi)
            if self.active_layout
            else (int(self.img_dpi) if self.img_dpi > 0 else BASELINE_DPI)
        )

        store_bezel_zone = store.zones.get(bezel_id)
        if store_bezel_zone:
            bezel_px_thickness = store_bezel_zone.get_bezel_thickness_px(dpi)
            _x = store_bezel_zone.x1
            _y = store_bezel_zone.y1
            _width = store_bezel_zone.x2

            if _x is None or _y is None or _width is None:
                return

        else:
            return

        label_y = (
            (bezel_px_thickness / 2.0)
            if is_top
            else (self.img_height - bezel_px_thickness / 2.0)
        )

        return (
            {
                "x": _width / 2.0,
                "y": label_y,
                "text": f"Bezel Notch ({bezel_px_thickness:.0f}px)",
                "color": "white",
                "fontsize": self._get_scaled_font_size(),
                "ha": "center",
                "va": "center",
                "zorder": 9,
                "alpha": 0.8,
            },
            {
                "xy": (_x, _y),
                "width": _width,
                "height": bezel_px_thickness,
                "fill": True,
                "facecolor": (1.0, 0.2, 0.2, 0.25),
                "edgecolor": (1.0, 0.4, 0.4, 0.7),
                "linewidth": 1.0,
                "linestyle": "--",
                "zorder": 8,
            },
        )

    def _render_empty_state(self, message: str) -> None:
        self.is_fatal_state = True
        self.ax.clear()
        self.update_title("ERROR: Missing Active Layout")
        self.canvas.draw_idle()

    def _load_image(self, path: Optional[Path] = None) -> Optional[Image.Image]:
        target_path = path
        if target_path is None:
            return

        try:
            img = Image.open(target_path)

            # If the raw file is in portrait but tagged for landscape rotation, rotate the PIL buffer
            parts = target_path.stem.split("_")
            if parts[-1].startswith("r"):
                try:
                    rot = int(parts[-1][1:])
                    if rot in (1, 3) and img.width < img.height:
                        img = img.rotate(270 if rot == 1 else 90, expand=True)
                except ValueError:
                    pass

            return img

        except Exception as exc:
            self.update_title("Image could not be loaded.")
            print(f"Error loading image: {exc}")
            return

    def get_image_params(
        self, active_layout: Layout, img_path: Optional[Path] = None
    ) -> tuple[Optional[Image.Image], Optional[tuple[int, int, int, int, int]]]:
        """Gets canvas dimensions directly from the image buffer generated by loading the image from the image path."""
        if img_path is None:
            active_path = active_layout.image_path
            if active_path is None:
                return None, None

            img_path = Path(active_path)
            if not img_path.is_absolute():
                img_path = Path(IMAGES_FOLDER) / img_path

        if (img := self._load_image(img_path)) is None:
            return None, None

        img_width, img_height = img.size

        # Safely extract DPI from image metadata without scalar indexing errors
        dpi_meta = img.info.get("dpi", (BASELINE_DPI, BASELINE_DPI))
        if isinstance(dpi_meta, (tuple, list)):
            img_dpi = int(round(dpi_meta[0]))
        else:
            img_dpi = int(round(dpi_meta)) if dpi_meta else BASELINE_DPI

        # Store clean filename if placed in data/images/ for cross-machine portability
        saved_img_ref = (
            img_path.name
            if img_path.parent.resolve() == IMAGES_FOLDER.resolve()
            else str(img_path.resolve())
        )

        old_width = active_layout.width
        old_height = active_layout.height

        store.layouts.update(
            active_layout.id,
            width=img_width,
            height=img_height,
            dpi=img_dpi,
            image_path=saved_img_ref,
        )

        return img, (img_width, img_height, img_dpi, old_width, old_height)

    def _update_image_params(
        self, width: int, height: int, dpi: int, old_width: int, old_height: int
    ) -> tuple[int, int]:
        """Sets canvas dimensions"""
        self.img_width = width
        self.img_height = height
        self.img_dpi = dpi

        return old_width, old_height

    def update_title(self, text: str, idle_override: bool = False):
        # self.ax.set_title(text)
        self.status_updated.emit(text)
        self.cursor_manager.set_state_cursor(self.state)

        if idle_override:
            self.fig.canvas.draw_idle()
        else:
            self.fig.canvas.draw()

    def _clear_visuals(self):
        for artist in self.point_artists:
            artist.remove()
        self.point_artists = []
        self.fig.canvas.draw()

    def reset_state(self):
        if self.is_fatal_state:
            return

        self._clear_visuals()
        self.state, self.mode, self.points = IDLE, None, []
        self.input_buffer, self.buffer_default = "", True
        self.update_title(f"OVERLAYS: {'VISIBLE' if self.show_overlays else 'HIDDEN'}")
        if self.ax.bbox.width > 0 and self.ax.bbox.height > 0:
            self.bg_cache = self.canvas.copy_from_bbox(self.ax.bbox)

    def start_mode(self, mode: str, num_points: int):
        if self.state != IDLE:
            return

        self.reset_state()
        self.mode, self.artists_points, self.state = mode, num_points, COLLECTING
        self.update_title(f"MODE: {mode}. Click {num_points} points on the image.")

    def _load_active_layout_zones(self, old_width: int, old_height: int) -> None:
        if not self.active_layout:
            return

        zones = store.zones.list_for_layout(self.active_layout.id)
        self.reset_state()

        scale_x = old_width / self.active_layout.width
        scale_y = old_height / self.active_layout.height

        for zone in zones:
            if zone.zone_type == BEZEL:
                if zone.scancode == TOP_BEZEL_ID:
                    self.top_bezel_id = zone.id
                elif zone.scancode == BOTTOM_BEZEL_ID:
                    self.bottom_bezel_id = zone.id
                continue

            self.mode = zone.zone_type
            cx = int(round((zone.cx or 0.0) * scale_x))
            cy = int(round((zone.cy or 0.0) * scale_y))

            r, bb = None, None
            if zone.zone_type == CIRCLE:
                r = int(round((zone.r or 0.0) * ((scale_x + scale_y) / 2)))
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

            self._finalize_shape(
                cx=cx,
                cy=cy,
                r=r,
                bb=bb,
                key_name=zone.name,
                scancode=zone.scancode,
                pointer=zone.pointer,
                priority=zone.priority,
                pipeline_json=zone.pipeline_json,
                ignore_app_settings=zone.ignore_app_settings,
            )

        self.mouse_wheel_radius = self.active_layout.mouse_wheel_radius
        self.sprint_distance = self.active_layout.sprint_distance
        self.reset_state()

    def toggle_visibility(self):
        if self.is_fatal_state:
            return
        if self.state != IDLE:
            return

        self.show_overlays = not self.show_overlays
        for d in (self.labels_artists, self.shapes_artists):
            for art in d.values():
                art.set_visible(self.show_overlays)

        for art in (
            self.top_bezel_label_artist,
            self.top_bezel_shape_artist,
            self.bottom_bezel_label_artist,
            self.bottom_bezel_shape_artist,
        ):
            art.set_visible(self.show_overlays)

        for d in (
            self.mouse_wheel_indicators.mouse_wheel_labels_artists,
            self.mouse_wheel_indicators.mouse_wheel_shapes_artists,
        ):
            for art in d.values():
                art.set_visible(self.show_overlays if self.saved_mouse_wheel else False)

        self.update_title(f"OVERLAYS: {'VISIBLE' if self.show_overlays else 'HIDDEN'}")

    def _get_scaled_font_size(self) -> int:
        """Calculates label font size proportional to the rendered image viewport."""
        if (
            self.img_width > 0
            and self.img_height > 0
            and self.ax.bbox.width > 0
            and self.ax.bbox.height > 0
        ):
            scale = min(
                self.ax.bbox.width / self.img_width,
                self.ax.bbox.height / self.img_height,
            )
            rendered_img_height_px = self.img_height * scale

            # Convert pixels to points (72 points per inch / figure DPI)
            px_to_pt = 72.0 / self.fig.dpi
            return max(5, int(round(rendered_img_height_px * px_to_pt * 0.02)))

        return max(5, int(round(self.fig.get_size_inches()[1] * 72 * 0.02)))

    def _create_label(
        self,
        center_x: float,
        center_y: float,
        label_text: str,
        fc: tuple[float, float, float, float],
    ):
        return Text(
            center_x,
            center_y,
            label_text,
            color="white",
            fontsize=self._get_scaled_font_size(),
            fontweight="bold",
            ha="center",
            va="center",
            zorder=12,
            bbox=dict(
                fc=fc, ec="black", lw=DEFAULT_SMALL_LINE_WIDTH, boxstyle="round,pad=0.3"
            ),
        )

    def _create_circle(
        self, cx: float, cy: float, r: float, fc: tuple[float, float, float, float]
    ):
        return Circle(
            (cx, cy),
            r,
            fill=True,
            lw=DEFAULT_MEDIUM_LINE_WIDTH,
            fc=fc,
            ec=DEFAULT_EDGE_COLOR,
        )

    def _create_rectangle(
        self,
        x1: float,
        y1: float,
        x2: float,
        y2: float,
        fc: tuple[float, float, float, float],
    ):
        return Rectangle(
            (x1, y1),
            x2 - x1,
            y2 - y1,
            fill=True,
            lw=DEFAULT_MEDIUM_LINE_WIDTH,
            fc=fc,
            ec=DEFAULT_EDGE_COLOR,
        )

    def _hide_crosshairs(self) -> bool:
        """Hides crosshair artists and returns True if they were previously visible."""
        if not hasattr(self, "crosshair_h_bg") or not self.crosshair_h_bg.get_visible():
            return False

        for line in (
            self.crosshair_h_bg,
            self.crosshair_h_fg,
            self.crosshair_v_bg,
            self.crosshair_v_fg,
        ):
            line.set_visible(False)
        return True

    def _on_draw(self, event=None) -> None:
        """Captures a fresh background cache immediately after every full render.
        Because crosshairs use animated=True, this snapshot is always clean
        and matches the exact post-resize ax.bbox dimensions."""
        if self.is_fatal_state:
            return
        if self.ax.bbox.width > 0 and self.ax.bbox.height > 0:
            self.bg_cache = self.canvas.copy_from_bbox(self.ax.bbox)

    def _on_mouse_leave(self, event=None) -> None:
        """Cleans up crosshairs and hover states when the cursor moves onto a splitter or toolbar."""
        if self.is_fatal_state:
            return

        if self._hide_crosshairs():
            if self.bg_cache is not None:
                self.canvas.restore_region(self.bg_cache)
                self.canvas.blit(self.ax.bbox)
            else:
                self.canvas.draw_idle()

        if (
            self.state == IDLE
            and not self.drawn
            and self.current_draggable_id is not None
        ):
            self._partial_release_all()
            self.update_title(
                f"OVERLAYS: {'VISIBLE' if self.show_overlays else 'HIDDEN'}", True
            )

    def on_resize(self, event=None) -> None:
        """Keeps overlays and blit caches dynamically aligned to the canvas viewport on resize.
        Invalidates stale blit caches on resize so _on_draw rebuilds them cleanly."""
        if self.is_fatal_state:
            return

        # Invalidate stale blit cache from previous viewport dimensions
        self.bg_cache = None
        self.drawn = False
        self._hide_crosshairs()

        # Rescale all zone and mouse wheel indicator labels to match new viewport size
        scaled_font = self._get_scaled_font_size()
        for lbl in self.labels_artists.values():
            lbl.set_fontsize(scaled_font)

        for lbl in self.mouse_wheel_indicators.mouse_wheel_labels_artists.values():
            lbl.set_fontsize(scaled_font)

        self.top_bezel_label_artist.set_fontsize(scaled_font)
        self.bottom_bezel_label_artist.set_fontsize(scaled_font)

        self.canvas.draw_idle()

    def _on_mouse_move(self, event):
        if self.is_fatal_state:
            return

        if self.state == COLLECTING and event.inaxes == self.ax:
            x, y = int(round(event.xdata)), int(round(event.ydata))
            if (
                self.bg_cache is None
                and self.ax.bbox.width > 0
                and self.ax.bbox.height > 0
            ):
                self.bg_cache = self.canvas.copy_from_bbox(self.ax.bbox)

            if self.bg_cache is not None:
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

            hovering = None
            for uid, mgr in self.labels_drag_managers.items():
                if mgr.label_artist.contains(event)[0]:
                    hovering = (uid, mgr, "label")
                    break
            if not hovering:
                for uid, mgr in self.shapes_drag_managers.items():
                    if mgr.shape_artist and mgr.shape_artist.contains(event)[0]:
                        hovering = (uid, mgr, "shape")
                        break

            if hovering:
                uid, mgr, m_type = hovering
                if (curr_id := m_type + "_" + str(uid)) != self.current_draggable_id:
                    self._partial_release_all()
                    mgr._on_press_helper(event)
                    self.current_draggable_id = curr_id
                    mgr.indicate_current_draggable_id()
                    self.fire_on_motion = False
            else:
                self._partial_release_all()
                self.update_title(
                    f"OVERLAYS: {'VISIBLE' if self.show_overlays else 'HIDDEN'}", True
                )

    def _partial_release_all(self):
        for mgr in self.labels_drag_managers.values():
            mgr._partial_release()
        for mgr in self.shapes_drag_managers.values():
            mgr._partial_release()
        self.current_draggable_id = None
        self.zone_selected.emit(-1)
        self.fig.canvas.draw_idle()

    def _on_click(self, event):
        if self.is_fatal_state:
            return

        if self.state == IDLE:
            self.ignore_current_draggable_id_n = 0
        if self.state == WAITING_FOR_KEY:
            btn_map = {
                1: "mouse_left",
                2: "mouse_middle",
                3: "mouse_right",
                8: "mouse_back",
                9: "mouse_forward",
            }
            if btn := btn_map.get(event.button):
                self.calculate_shape(btn)
            return

        if self.state == WAITING_FOR_WHEEL_INDICATOR:
            current_indicator = (
                self.mouse_wheel_indicators.current_mouse_wheel_indicator
            )
            self.mouse_wheel_indicators.current_mouse_wheel_indicator = None
            self.mouse_wheel_indicators.unhighlight_mouse_wheel_indicator(
                current_indicator
            )
            self.reset_state()
            return

        if self.state != COLLECTING or event.xdata is None or event.ydata is None:
            return

        self.points.append((int(round(event.xdata)), int(round(event.ydata))))
        (dot,) = self.ax.plot(event.xdata, event.ydata, "ro")
        self.point_artists.append(dot)
        self.fig.canvas.draw()
        # self.bg_cache = None

        if (rem := self.artists_points - len(self.points)) > 0:
            self.update_title(
                f"MODE: {self.mode}. {rem} points remaining (Esc to Cancel)."
            )
        else:
            self.state = WAITING_FOR_KEY
            self.update_title("Shape Defined! Press KEY or CLICK MOUSE to bind.")

    def _on_key_press(self, event):
        if self.is_fatal_state:
            return

        state_handlers = {
            NAMING: self._handle_naming_input,
            DELETING: self._handle_deleting_input,
        }

        if self.state in state_handlers:
            state_handlers[self.state](event.key)
            return

        if self.state == CONFIRM_DELETE_ALL:
            self._delete_all_shapes() if event.key == "enter" else self.reset_state()
            return
        if self.state in (CONFIRM_EXIT, COLLECTING):
            if event.key == "escape":
                self.reset_state()
            return
        if self.state == WAITING_FOR_KEY:
            self.calculate_shape(get_specific_mt_key(event))
            return
        if self.state == WAITING_FOR_WHEEL_INDICATOR:
            self.mouse_wheel_indicators.update_mouse_wheel_indicator_from_key(
                get_specific_mt_key(event)
            )
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
                self._print_data()
            elif event.key == "f12":
                self._enter_naming_mode()
            elif event.key == "delete":
                self._enter_deleting_mode()
            elif event.key == "escape":
                self.reset_state()
            elif event.key in ("p", "o") and self.current_draggable:
                eid = self.current_draggable.entry_id
                self.shapes[eid]["priority"] += 1 if event.key == "p" else -1
                self.shapes[eid]["priority"] = max(
                    -100, min(100, self.shapes[eid]["priority"])
                )
                self.update_title(
                    f"Priority {'increased' if event.key == 'p' else 'decreased'}: {self.shapes[eid]['priority']} (ID: {eid})",
                    True,
                )
                self.zone_selected.emit(eid)
            else:
                step = 5 if event.key.startswith("shift+") else 1
                clean_key = event.key.replace("shift+", "")
                dirs = {
                    "left": (-step, 0),
                    "right": (step, 0),
                    "up": (0, -step),
                    "down": (0, step),
                }
                if clean_key in dirs and self.current_draggable:
                    self.current_draggable._move(*dirs[clean_key])

    def _enter_deleting_mode(self):
        if self.state != IDLE:
            return

        if not self.shapes:
            self.update_title("List empty. Nothing to delete")
            return
        self.state, self.input_buffer = DELETING, ""
        self.update_title("DELETE MODE: Type ID... (Enter to Confirm | Esc to Cancel)")

    def _delete_all_shapes(self):
        if not self.shapes:
            self.update_title("List empty. Nothing to delete.")
            return
        for uid in list(self.shapes.keys()):
            self._delete_entry(uid)
        self.count = 0
        self.reset_state()

    def _handle_deleting_input(self, key):
        if key == "escape":
            self.reset_state()
            return
        if key == "enter":
            if self.input_buffer:
                try:
                    if (uid := int(self.input_buffer)) in self.shapes:
                        self._delete_entry(uid)
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

    def _delete_entry(self, uid):
        if uid not in self.shapes:
            return
        entry_scancode = int(self.shapes[uid]["scancode"])
        entry_key_name = str(self.shapes[uid]["key_name"])

        if entry_scancode == MOUSE_WHEEL_SIMULATOR_CODE:
            for sid in [
                k
                for k, v in self.shapes.items()
                if v["scancode"] == SPRINT_DISTANCE_CODE
            ]:
                self._delete_entry(sid)
            self.saved_mouse_wheel = False
            self.mouse_wheel_radius = 0.0
            self.mouse_wheel_cx = 0
            self.mouse_wheel_cy = 0

        elif entry_scancode == SPRINT_DISTANCE_CODE:
            self.saved_sprint_distance = False
            self.sprint_artist_id = None
            self.sprint_distance = 0.0

        if self.current_draggable_id in [f"shape_{uid}", f"label_{uid}"]:
            self.current_draggable_id = self.current_draggable = None
        del self.shapes[uid]
        if uid in self.shapes_artists:
            self.shapes_artists.pop(uid).remove()
        if uid in self.labels_artists:
            self.labels_artists.pop(uid).remove()
        if uid in self.labels_drag_managers:
            self.labels_drag_managers.pop(uid)._disconnect_cids()
        if uid in self.shapes_drag_managers:
            self.shapes_drag_managers.pop(uid)._disconnect_cids()
        if self.last_artist_id in [f"shape_{uid}", f"label_{uid}"]:
            self.last_artist_id = None

        try:
            self.current_bound_keys.remove(entry_key_name)
        except ValueError:
            pass

        self.zone_selected.emit(-1)

    def calculate_shape(self, key_name: str):
        scancode = get_scancode_from_key(key_name)
        if not scancode:
            msg = f"Key '{key_name}' not mapped."
            self.update_title(msg)
            print(msg)
            return

        scancode_key_name = get_key_from_scancode(scancode)
        if not scancode_key_name:
            msg = f"Key '{key_name}' with scancode '{scancode}' has no equivalent key name."
            self.update_title(msg)
            print(msg)
            return

        cx, cy, r, bb = None, None, None, None
        if self.mode == CIRCLE:
            cx, cy, r, bb = self._calculate_circle()
        elif self.mode == RECTANGLE:
            cx, cy, r, bb = self._calculate_rectangle()

        self._finalize_shape(
            cx=cx,
            cy=cy,
            r=r,
            bb=bb,
            key_name=scancode_key_name,
            scancode=scancode,
            pointer=False,
            priority=0,
            pipeline_json="{}",
            ignore_app_settings=False,
        )
        self.reset_state()

    def _finalize_shape(
        self,
        cy: Optional[int],
        cx: Optional[int],
        r: Optional[int],
        bb: Optional[tuple[tuple[int, int], tuple[int, int]]],
        key_name: str,
        scancode: int,
        pointer: bool,
        priority: int,
        pipeline_json: str,
        ignore_app_settings: bool,
    ):
        if cx is None or cy is None:
            return

        saved, entry_id = self._save_entry(
            key_name,
            scancode,
            cx,
            cy,
            r,
            bb,
            pointer,
            priority,
            pipeline_json,
            ignore_app_settings,
        )
        if not saved:
            return

        label = (
            "MOUSE\nWHEEL"
            if scancode == MOUSE_WHEEL_SIMULATOR_CODE
            else (
                "SPRINT\nDISTANCE"
                if scancode == SPRINT_DISTANCE_CODE
                else key_name.upper()
            )
        )

        if self.mode == CIRCLE and r is not None:
            fc = (
                DEFAULT_MOUSE_WHEEL_FACE_COLOR
                if scancode == MOUSE_WHEEL_SIMULATOR_CODE
                else (
                    DEFAULT_SPRINT_DISTANCE_FACE_COLOR
                    if scancode == SPRINT_DISTANCE_CODE
                    else get_vibrant_random_color(DEFAULT_FACE_COLOR_ALPHA)
                )
            )

            lbl = self._create_label(cx, cy, label, fc)
            art = self._create_circle(cx, cy, r, fc)

            self.labels_artists[entry_id] = lbl
            self.shapes_artists[entry_id] = art
            self.labels_drag_managers[entry_id] = _DraggableLabel(entry_id, self)
            self.shapes_drag_managers[entry_id] = _DraggableCircle(entry_id, self)

            if scancode == MOUSE_WHEEL_SIMULATOR_CODE:
                self.mouse_wheel_indicators.move_mouse_wheel_indicators()
                self.mouse_wheel_indicators.set_indicators_visible(True)

        elif self.mode == RECTANGLE and bb is not None:
            fc = get_vibrant_random_color(DEFAULT_FACE_COLOR_ALPHA)
            (x1, y1), (x2, y2) = bb

            lbl = self._create_label(cx, cy, label, fc)
            art = self._create_rectangle(x1, y1, x2, y2, fc)

            self.labels_artists[entry_id] = lbl
            self.shapes_artists[entry_id] = art
            self.labels_drag_managers[entry_id] = _DraggableLabel(entry_id, self)
            self.shapes_drag_managers[entry_id] = _DraggableRectangle(entry_id, self)
        else:
            return

        lbl.set_visible(self.show_overlays)
        self.ax.add_artist(lbl)

        art.set_visible(self.show_overlays)
        self.ax.add_patch(art)

        if pointer:
            self.labels_drag_managers[entry_id].dull_face_color()
            self.shapes_drag_managers[entry_id].dull_face_color()

        self.current_bound_keys.append(key_name)

    def _enter_naming_mode(self):
        if self.state != IDLE:
            return

        self.state, self.buffer_default = NAMING, True

        if self.active_layout is None:
            return

        self.input_buffer = self.active_layout.name
        self.update_title(
            f"SAVE: [{self.input_buffer}] | Enter: Save/Rename | Shift+Enter: Save as Copy | Esc: Cancel"
        )

    def _handle_naming_input(self, key):
        if key == "escape":
            self.reset_state()
            return

        if self.active_layout is None:
            return

        if key in ("enter", "shift+enter"):
            self.save_to_database(
                self.input_buffer.strip() or self.active_layout.name,
                as_copy=key != "enter",
            )
            self.reset_state()
            return
        if key == "backspace":
            if self.buffer_default:
                self.input_buffer, self.buffer_default = "", False
            else:
                self.input_buffer = self.input_buffer[:-1]
        elif len(key) == 1 and (key.isalnum() or key in "_ -.()"):
            if self.buffer_default:
                self.input_buffer, self.buffer_default = "", False
            self.input_buffer += key
        self.update_title(
            f"SAVE: [{self.input_buffer or self.active_layout.name}] | Enter: Save/Rename | Shift+Enter: Save as Copy | Esc: Cancel"
        )

    def on_pointer_marked(self, uid):
        if self.shapes[uid]["pointer"]:
            self.labels_drag_managers[uid].dull_face_color()
            self.shapes_drag_managers[uid].dull_face_color()
        else:
            self.labels_drag_managers[uid].restore_face_color()
            self.shapes_drag_managers[uid].restore_face_color()

    def save_to_database(self, user_name: str, as_copy=False):
        if self.active_layout is None:
            return

        output = []
        for _, data in self.shapes.items():
            entry = {
                "name": data["key_name"],
                "scancode": data["scancode"],
                "type": data["type"],
                "cx": data["cx"],
                "cy": data["cy"],
                "val1": 0,
                "val2": 0,
                "val3": 0,
                "val4": 0,
                "ignore_app_settings": data.get("ignore_app_settings", False),
            }

            pipeline_json_src = data.get("pipeline_json", "{}")
            p_cfg = PipelineConfig()
            p_cfg.set_pipeline_config_from_json(pipeline_json=pipeline_json_src)

            if data["type"] == CIRCLE:
                region_idx = 1
                entry["val1"] = data["r"]
            else:
                region_idx = 2
                (x_min, y_min), (x_max, y_max) = data["bb"]
                entry["val1"], entry["val2"], entry["val3"], entry["val4"] = (
                    x_min,
                    y_min,
                    x_max,
                    y_max,
                )

            entry_scancode = int(data["scancode"])

            if entry_scancode == MOUSE_WHEEL_SIMULATOR_CODE:
                p_cfg.pipeline_config["up"] = (
                    self.mouse_wheel_indicators.mouse_wheel_indicators_map[0]
                )
                p_cfg.pipeline_config["left"] = (
                    self.mouse_wheel_indicators.mouse_wheel_indicators_map[1]
                )
                p_cfg.pipeline_config["down"] = (
                    self.mouse_wheel_indicators.mouse_wheel_indicators_map[2]
                )
                p_cfg.pipeline_config["right"] = (
                    self.mouse_wheel_indicators.mouse_wheel_indicators_map[3]
                )

            p_cfg.set_origin_config(
                idx=0 if entry_scancode == MOUSE_WHEEL_SIMULATOR_CODE else 1
            )
            p_cfg.set_constraint_config(
                idx=1 if entry_scancode == MOUSE_WHEEL_SIMULATOR_CODE else 0
            )
            p_cfg.set_transform_config(
                idx=2 if entry_scancode == MOUSE_WHEEL_SIMULATOR_CODE else 1
            )
            p_cfg.set_semantic_config(
                idx=1 if entry_scancode == MOUSE_WHEEL_SIMULATOR_CODE else 0
            )

            p_cfg.set_region_config(idx=region_idx, priority=data.get("priority", 0))
            p_cfg.set_semantic_config(pointer=data.get("pointer", False))
            entry["pipeline_json"] = p_cfg.get_pipeline_json_from_config()
            output.append(entry)

        is_new_name = user_name != self.active_layout.name

        if as_copy or is_new_name:
            if as_copy and not is_new_name:
                user_name = make_copy_name(user_name)

            layout_id = store.layouts.create(
                name=user_name,
                width=self.img_width,
                height=self.img_height,
                dpi=self.img_dpi,
                mouse_wheel_radius=self.mouse_wheel_radius,
                sprint_distance=self.sprint_distance,
                image_path=self.active_layout.image_path,
            ).id

        else:
            layout_id = self.active_layout.id

            store.layouts.update(
                layout_id,
                width=self.img_width,
                height=self.img_height,
                dpi=self.img_dpi,
                mouse_wheel_radius=self.mouse_wheel_radius,
                sprint_distance=self.sprint_distance,
            )

        # Cache the bezel zones dp_thicknesses if they exist else fallback to defaults
        top_bezel_thickness_dp: float = float(BEZEL_DP_THICKNESS)
        bottom_bezel_thickness_dp: float = float(BEZEL_DP_THICKNESS)

        top_bezel = store.zones.get(self.top_bezel_id)
        if top_bezel:
            top_bezel.set_parsed_config_from_json()
            _, _, top_bezel_thickness_dp, _ = (
                top_bezel.CONFIG_HELPER.get_region_config()
            )

        bottom_bezel = store.zones.get(self.bottom_bezel_id)
        if bottom_bezel:
            bottom_bezel.set_parsed_config_from_json()
            _, _, bottom_bezel_thickness_dp, _ = (
                bottom_bezel.CONFIG_HELPER.get_region_config()
            )

        # Clear the database layout of all zones
        store.zones.delete_all_for_layout(layout_id)

        # Ensure the bezels exist (removing duplicates) and update them with the cached dp_thicknesses
        target_layout = store.layouts.get(layout_id)
        if target_layout:
            store.zones.create_bezel(
                target_layout,
                TOP_BEZEL_ID,
                TOP_BEZEL_NAME,
                True,
                int(top_bezel_thickness_dp),
            )
            store.zones.create_bezel(
                target_layout,
                BOTTOM_BEZEL_ID,
                BOTTOM_BEZEL_NAME,
                False,
                int(bottom_bezel_thickness_dp),
            )

        # Repopulate the other zones
        for item in output:
            store.zones.create(
                layout_id=layout_id,
                scancode=str(item["scancode"]),
                name=item["name"],
                zone_type=item["type"],
                cx=float(item["cx"]),
                cy=float(item["cy"]),
                r=float(item["val1"]) if item["type"] == CIRCLE else None,
                x1=float(item["val1"]) if item["type"] == RECTANGLE else None,
                y1=float(item["val2"]) if item["type"] == RECTANGLE else None,
                x2=float(item["val3"]) if item["type"] == RECTANGLE else None,
                y2=float(item["val4"]) if item["type"] == RECTANGLE else None,
                ignore_app_settings=item["ignore_app_settings"],
                pipeline_json=item["pipeline_json"],
            )

        # Refresh local active layout model and verify bezel integrity
        store.set_active_layout(layout_id)
        self.active_layout = store.layouts.get(layout_id)

        if self.active_layout:
            for zone in store.zones.list_for_layout(layout_id, auto_heal=True):
                if zone.zone_type == BEZEL:
                    if zone.scancode == TOP_BEZEL_ID:
                        self.top_bezel_id = zone.id
                    elif zone.scancode == BOTTOM_BEZEL_ID:
                        self.bottom_bezel_id = zone.id

        self.layout_saved.emit(user_name, layout_id)
        self.update_title(f"SAVED: {user_name}")

    def _save_entry(
        self,
        key_name: str,
        scancode: int,
        cx: int,
        cy: int,
        r: Optional[int],
        bb: Optional[tuple[tuple[int, int], tuple[int, int]]],
        pointer: bool,
        priority: int,
        pipeline_json: str,
        ignore_app_settings: bool,
    ):
        uid, inc_count = self.count, True
        if scancode == MOUSE_WHEEL_SIMULATOR_CODE:
            if self.mode == RECTANGLE or r is None:
                msg = "Mouse wheel cannot be a rectangle."
                self.update_title(msg)
                print(msg)
                return False, uid

            if self.saved_mouse_wheel:
                for k, v in list(self.shapes.items()):
                    if v["scancode"] == MOUSE_WHEEL_SIMULATOR_CODE:
                        uid, inc_count = k, False
                        self.shapes.pop(k)
                        for d in (self.labels_artists, self.shapes_artists):
                            if k in d:
                                d.pop(k).remove()
                        for d in (self.labels_drag_managers, self.shapes_drag_managers):
                            if k in d:
                                d.pop(k)._disconnect_cids()
                        break

            self.mouse_wheel_radius = r
            self.mouse_wheel_cx = cx
            self.mouse_wheel_cy = cy
            self.saved_mouse_wheel = True

        elif scancode == SPRINT_DISTANCE_CODE:
            if self.mode == RECTANGLE:
                msg = "Sprint cannot be a rectangle."
                self.update_title(msg)
                print(msg)
                return False, uid

            if not self.saved_mouse_wheel:
                msg = "No mouse wheel found, create one first before attempting to create sprint."
                self.update_title(msg)
                print(msg)
                return False, uid

            if self.saved_sprint_distance:
                for k, v in list(self.shapes.items()):
                    if v["scancode"] == SPRINT_DISTANCE_CODE:
                        uid, inc_count = k, False
                        self.shapes.pop(k)
                        for d in (self.labels_artists, self.shapes_artists):
                            if k in d:
                                d.pop(k).remove()
                        for d in (self.labels_drag_managers, self.shapes_drag_managers):
                            if k in d:
                                d.pop(k)._disconnect_cids()
                        break

            actual_dist = self._euclidean_distance(
                cx, cy, self.mouse_wheel_cx, self.mouse_wheel_cy
            )

            if actual_dist <= self.mouse_wheel_radius:
                msg = "Sprint is too close to mouse wheel."
                self.update_title(msg)
                print(msg)
                return False, uid

            self.sprint_distance = actual_dist
            self.saved_sprint_distance = True
            self.sprint_artist_id = uid

        self.shapes[uid] = {
            "key_name": key_name,
            "scancode": scancode,
            "type": self.mode,
            "cx": cx,
            "cy": cy,
            "r": r,
            "bb": bb,
            "pointer": pointer,
            "priority": priority,
            "pipeline_json": pipeline_json,
            "ignore_app_settings": ignore_app_settings,
        }
        if inc_count:
            self.count += 1
        return True, uid

    def _print_data(self):
        if self.state != IDLE:
            return

        if not self.shapes:
            self.update_title("List empty. Nothing to print.")
            return
        print("\nCurrent Shapes:")
        for k, v in self.shapes.items():
            print(k, v)
        print("\n")

    def _calculate_circle(self):
        if len(self.points) < 3:
            return None, None, None, None
        x1, y1, x2, y2, x3, y3 = *self.points[0], *self.points[1], *self.points[2]
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
        return (
            int(round(h)),
            int(round(k)),
            int(round(math.sqrt((x1 - h) ** 2 + (y1 - k) ** 2))),
            None,
        )

    def _calculate_rectangle(self):
        if len(self.points) < 4:
            return None, None, None, None
        xs, ys = [p[0] for p in self.points], [p[1] for p in self.points]
        return (
            int(round(sum(xs) / 4)),
            int(round(sum(ys) / 4)),
            None,
            ((min(xs), min(ys)), (max(xs), max(ys))),
        )

    def _euclidean_distance(self, x1: float, y1: float, x2: float, y2: float):
        return math.sqrt((x2 - x1) ** 2 + (y2 - y1) ** 2)

    def _constrain_point_to_rect_radial(self, cx, cy, px, py, rect_bb):
        (x_min, y_min), (x_max, y_max) = rect_bb
        if x_min <= cx <= x_max and y_min <= cy <= y_max:
            return cx, cy
        radius = math.sqrt((cx - px) ** 2 + (cy - py) ** 2)
        if radius < 1e-9:
            return cx, cy

        current_angle = math.atan2(cy - py, cx - px)
        valid = []

        def on_seg(x, y, x1, y1, x2, y2):
            return (
                min(x1, x2) - 1e-9 <= x <= max(x1, x2) + 1e-9
                and min(y1, y2) - 1e-9 <= y <= max(y1, y2) + 1e-9
            )

        for x1, y1, x2, y2 in [
            (x_min, y_min, x_min, y_max),
            (x_max, y_min, x_max, y_max),
            (x_min, y_min, x_max, y_min),
            (x_min, y_max, x_max, y_max),
        ]:
            if abs(x1 - x2) < 1e-9:
                if abs(dx := x1 - px) <= radius:
                    dy = math.sqrt(radius**2 - dx**2)
                    for iy in (py + dy, py - dy):
                        if on_seg(x1, iy, x1, y1, x2, y2):
                            valid.append((x1, iy))
            else:
                if abs(dy := y1 - py) <= radius:
                    dx = math.sqrt(radius**2 - dy**2)
                    for ix in (px + dx, px - dx):
                        if on_seg(ix, y1, x1, y1, x2, y2):
                            valid.append((ix, y1))

        if not valid:
            return max(x_min, min(cx, x_max)), max(y_min, min(cy, y_max))
        candidates = []
        for ix, iy in valid:
            ta = math.atan2(iy - py, ix - px)
            candidates.append(
                {
                    "pt": (ix, iy),
                    "diff": abs(
                        math.atan2(
                            math.sin(ta - current_angle), math.cos(ta - current_angle)
                        )
                    ),
                    "y": iy,
                }
            )
        return sorted(candidates, key=lambda c: (round(c["diff"], 5), c["y"]))[0]["pt"]
