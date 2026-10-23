from __future__ import annotations

import logging
import math
import os
import sys
from pathlib import Path
from PIL import Image
from typing import TYPE_CHECKING, Optional, Any
from enum import Enum, auto

from modules.utils import clamp
from modules.platforms import get_platform, get_specific_mt_key
from modules.database import store
from modules.database.repositories import DuplicateNameError

get_platform().SystemConfig().set_dpi_awareness()

from modules.utils import (
    BASELINE_DPI,
    BEZEL,
    BEZEL_DP_THICKNESS,
    BOTTOM_BEZEL_ID,
    CIRCLE,
    IMAGES_FOLDER,
    MAX_BEZEL_DP,
    MAX_PRIORITY,
    MIN_BEZEL_DP,
    MIN_PRIORITY,
    MOUSE_WHEEL_SIMULATOR_CODE,
    RECTANGLE,
    SPRINT_DISTANCE_CODE,
    TOP_BEZEL_ID,
    dp_to_px,
    get_dulled_hue_color,
    get_hue_modified_alpha_from_hsv,
    get_key_from_scancode,
    get_scancode_from_key,
    get_vibrant_random_color,
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

logger = logging.getLogger("modules.gui.layouts_plotter_widget")

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


def _parse_artist_id(artist_id: Optional[str]) -> Optional[int]:
    """'shape_12' / 'label_12' -> 12."""
    if not artist_id:
        return None
    try:
        return int(artist_id.partition("_")[2])
    except ValueError:
        return None


class PlotterState(Enum):
    IDLE = auto()
    COLLECTING = auto()
    WAITING_FOR_KEY = auto()
    WAITING_FOR_WHEEL_INDICATOR = auto()
    DELETING = auto()
    CONFIRM_DELETE_ALL = auto()
    CONFIRM_EXIT = auto()


class _CursorManager:
    def __init__(self, canvas: FigureCanvasQTAgg):
        self.canvas = canvas
        self.state_map = {
            PlotterState.IDLE: Qt.CursorShape.ArrowCursor,
            PlotterState.COLLECTING: Qt.CursorShape.CrossCursor,
            PlotterState.WAITING_FOR_KEY: Qt.CursorShape.PointingHandCursor,
            PlotterState.WAITING_FOR_WHEEL_INDICATOR: Qt.CursorShape.PointingHandCursor,
            PlotterState.DELETING: Qt.CursorShape.ForbiddenCursor,
            PlotterState.CONFIRM_DELETE_ALL: Qt.CursorShape.WaitCursor,
            PlotterState.CONFIRM_EXIT: Qt.CursorShape.WaitCursor,
        }

    def set_state_cursor(self, state: PlotterState):
        self.canvas.setCursor(self.state_map.get(state, Qt.CursorShape.ArrowCursor))

    def set_custom_cursor(self, shape: Qt.CursorShape):
        self.canvas.setCursor(shape)


class _Draggable:
    """Shared base. Event wiring lives in LayoutsPlotterWidget (one connection per event), which dispatches to the _on_press/_on_motion/_reset_edge/_finish_release hooks below."""

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
        if self.artist_id not in self.plotter.draggables_ids:
            self.plotter.draggables_ids.append(self.artist_id)

    def dull_face_color(self):
        if self.default_face_color is None:
            return
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
        if self.default_face_color is None:
            return
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

    # Hooks implemented by subclasses ---------------------------------
    def _on_press(self, event) -> None:
        raise NotImplementedError()

    def _on_motion(self, event) -> None:
        raise NotImplementedError()

    def _reset_edge(self) -> None:
        raise NotImplementedError()

    def _finish_release(self) -> None:
        raise NotImplementedError()

    def _move(self, dx, dy) -> None:
        raise NotImplementedError()


class _DraggableLabel(_Draggable):
    def __init__(self, entry_id: int, plotter_ref: LayoutsPlotterWidget):
        super().__init__(entry_id, False, plotter_ref)
        self.label_artist = self.plotter.labels_artists[entry_id]
        self.shape_artist = self.plotter.shapes_artists[entry_id]
        self.canvas = self.plotter.canvas
        self.press = None

    def _on_press(self, event):
        if (
            self.plotter.is_fatal_state
            or self.plotter.state is not PlotterState.IDLE
            or self.label_artist.axes is None
        ):
            return

        self.plotter.ignore_current_draggable_id_n += 1
        self._on_press_helper(event)
        self.plotter.fire_on_motion = True

    def _on_press_helper(self, event):
        self.plotter.fire_on_motion = False
        self.press = None

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

    def _capture_background(self):
        if (label_bbox := self.label_artist.get_bbox_patch()) is not None:
            label_bbox.set_edgecolor(ACTIVE_EDGE_COLOR)
            label_bbox.set_linewidth(DEFAULT_LARGE_LINE_WIDTH)
        self.label_artist.set_animated(True)

        self.shape_artist.set_edgecolor(ACTIVE_EDGE_COLOR)
        self.shape_artist.set_linewidth(DEFAULT_LARGE_LINE_WIDTH)

        self.canvas.draw()
        self.plotter.bg_cache = self.canvas.copy_from_bbox(self.plotter.ax.bbox)
        self.plotter.captured = True
        # NOTE: dragging a label never moves the wheel indicators, so they stay in the
        # cached background (capturing them here used to make them vanish mid-drag).

    def _on_motion(self, event):
        if not self.plotter.fire_on_motion or self.label_artist.axes is None:
            return
        if self.press is None or event.inaxes != self.label_artist.axes:
            return

        if self.plotter.current_draggable_id is None:
            self.plotter.current_draggable_id = (
                self.plotter._select_current_draggable_id()
            )
            self.plotter._indicate_current_draggable_id()

        if self.plotter.current_draggable_id != self.artist_id:
            return

        self.plotter.ignore_current_draggable_id_n = 1

        _, _, xdata_press, ydata_press, xpx_press, ypx_press = self.press
        dx = event.xdata - xdata_press
        dy = event.ydata - ydata_press
        dx_press = event.x - xpx_press
        dy_press = event.y - ypx_press
        self.plotter.current_move_distance = ((dx_press**2) + (dy_press**2)) ** 0.5
        if self.plotter.current_move_distance > DEFAULT_MIN_MOVE_DIST:
            self.plotter.mark_dirty()

        if not self.plotter.captured:
            self._capture_background()

        if self.plotter.bg_cache is not None:
            self.canvas.restore_region(self.plotter.bg_cache)

        self._move_label(dx, dy)
        self.label_artist.axes.draw_artist(self.label_artist)
        self.canvas.blit(self.plotter.ax.bbox)

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
        self.plotter.mark_dirty()
        self.canvas.draw()
        self.plotter.captured = False

    def _reset_edge(self):
        if (label_bbox := self.label_artist.get_bbox_patch()) is not None:
            label_bbox.set_edgecolor("black")
            label_bbox.set_linewidth(DEFAULT_SMALL_LINE_WIDTH)

    def _finish_release(self):
        if self.plotter.captured:
            self.shape_artist.set_edgecolor(DEFAULT_EDGE_COLOR)
            self.shape_artist.set_linewidth(DEFAULT_MEDIUM_LINE_WIDTH)
            self.label_artist.set_animated(False)


class _DraggableShape(_Draggable):
    def __init__(self, entry_id: int, plotter_ref: LayoutsPlotterWidget):
        super().__init__(entry_id, True, plotter_ref)
        self.label_artist = self.plotter.labels_artists[entry_id]
        self.shape_artist = self.plotter.shapes_artists[entry_id]
        self.canvas = self.plotter.canvas
        self.press = None
        self.drag_bg = None
        self.shape_mode = None

    def _move(self, dx, dy) -> None:
        raise NotImplementedError()

    def _on_press(self, event):
        if (
            self.plotter.is_fatal_state
            or self.plotter.state is not PlotterState.IDLE
            or self.shape_artist.axes is None
        ):
            return

        self.plotter.ignore_current_draggable_id_n += 1
        self._on_press_helper(event)
        self.plotter.fire_on_motion = True

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

    def _capture_background(self):
        self.shape_artist.set_edgecolor(ACTIVE_EDGE_COLOR)
        self.shape_artist.set_linewidth(DEFAULT_LARGE_LINE_WIDTH)
        self.shape_artist.set_animated(True)

        if (label_bbox := self.label_artist.get_bbox_patch()) is not None:
            label_bbox.set_edgecolor(ACTIVE_EDGE_COLOR)
            label_bbox.set_linewidth(DEFAULT_LARGE_LINE_WIDTH)

        self.canvas.draw()
        self.plotter.bg_cache = self.canvas.copy_from_bbox(self.plotter.ax.bbox)
        self.plotter.captured = True

        # Dragging the wheel also moves its 4 indicators (and may move the sprint circle),
        # so those must be animated too, otherwise they ghost in the cached background.
        current_shape = self.plotter.shapes.get(self.entry_id)
        if (
            current_shape is not None
            and int(current_shape["scancode"]) == MOUSE_WHEEL_SIMULATOR_CODE
            and self.plotter.saved_mouse_wheel
            and not self.plotter.mouse_wheel_indicators.mouse_wheel_indicators_captured
        ):
            self.plotter.mouse_wheel_indicators._capture_mouse_wheel_background()

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
            self.plotter.current_draggable_id = (
                self.plotter._select_current_draggable_id()
            )
            self.plotter._indicate_current_draggable_id()

        if self.plotter.current_draggable_id != self.artist_id:
            return
        self.plotter.ignore_current_draggable_id_n = 1

        _, _, _, _, xpx_press, ypx_press = self.press
        dx_press = event.x - xpx_press
        dy_press = event.y - ypx_press
        self.plotter.current_move_distance = ((dx_press**2) + (dy_press**2)) ** 0.5
        if self.plotter.current_move_distance > DEFAULT_MIN_MOVE_DIST:
            self.plotter.mark_dirty()

        if not self.plotter.captured:
            self._capture_background()

        if self.plotter.bg_cache is not None:
            self.canvas.restore_region(self.plotter.bg_cache)

        self._shape_transform(event)
        self.shape_artist.axes.draw_artist(self.shape_artist)
        self.canvas.blit(self.plotter.ax.bbox)

    def _reset_edge(self):
        self.shape_artist.set_edgecolor(DEFAULT_EDGE_COLOR)
        self.shape_artist.set_linewidth(DEFAULT_MEDIUM_LINE_WIDTH)

    def _finish_release(self):
        if self.plotter.captured:
            if (label_bbox := self.label_artist.get_bbox_patch()) is not None:
                label_bbox.set_edgecolor("black")
                label_bbox.set_linewidth(DEFAULT_SMALL_LINE_WIDTH)
            self.shape_artist.set_animated(False)


class _DraggableCircle(_DraggableShape):
    def __init__(self, entry_id: int, plotter_ref: LayoutsPlotterWidget):
        super().__init__(entry_id, plotter_ref)
        if not isinstance(self.shape_artist, Circle):
            return

        old_r = self.shape_artist.get_radius()
        new_r = max(old_r, DEFAULT_MIN_CIRCLE_R)
        if new_r != old_r:
            logger.warning(
                "Zone %s radius %s is below the minimum; raised to %s.",
                entry_id,
                old_r,
                new_r,
            )
            self.shape_artist.set_radius(new_r)
            self.plotter.shapes[self.entry_id]["r"] = new_r

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

        self._circle_transform_helper(old_cx, old_cy, old_r, new_cx, new_cy, True)

    def _circle_transform_helper(
        self, old_cx, old_cy, old_r, new_cx, new_cy, is_blitting: bool
    ):
        if not isinstance(self.shape_artist, Circle):
            return
        plotter = self.plotter
        current_shape = plotter.shapes[self.entry_id]

        if (
            plotter.saved_mouse_wheel
            and current_shape["scancode"] == MOUSE_WHEEL_SIMULATOR_CODE
        ):
            plotter.mouse_wheel_cx = new_cx
            plotter.mouse_wheel_cy = new_cy
            plotter.mouse_wheel_radius = current_shape["r"]

            if plotter.saved_sprint_distance and plotter.sprint_artist_id is not None:
                sprint_shape_artist = plotter.shapes_artists.get(
                    plotter.sprint_artist_id
                )
                sprint_shape = plotter.shapes.get(plotter.sprint_artist_id)
                if isinstance(sprint_shape_artist, Circle) and sprint_shape is not None:
                    cx, cy = sprint_shape_artist.get_center()  # type: ignore
                    actual_dist = plotter._euclidean_distance(cx, cy, new_cx, new_cy)

                    if actual_dist <= plotter.mouse_wheel_radius:
                        r = plotter.mouse_wheel_radius
                        screen_rect = (
                            (0, 0),
                            (plotter.img_width, plotter.img_height),
                        )
                        sp_x, sp_y = plotter._constrain_point_to_rect_radial(
                            new_cx, new_cy - r - 1, new_cx, new_cy, screen_rect
                        )
                        sp_x, sp_y = int(round(sp_x)), int(round(sp_y))

                        sprint_shape_artist.set_center((sp_x, sp_y))
                        sprint_shape["cx"] = sp_x
                        sprint_shape["cy"] = sp_y
                        plotter.sprint_distance = plotter._euclidean_distance(
                            sp_x, sp_y, new_cx, new_cy
                        )
                    else:
                        plotter.sprint_distance = actual_dist

            plotter.mouse_wheel_indicators.move_mouse_wheel_indicators(is_blitting)

        if (
            plotter.saved_sprint_distance
            and current_shape["scancode"] == SPRINT_DISTANCE_CODE
        ):
            actual_dist = plotter._euclidean_distance(
                new_cx, new_cy, plotter.mouse_wheel_cx, plotter.mouse_wheel_cy
            )
            if actual_dist <= plotter.mouse_wheel_radius:
                self.shape_artist.set_center((old_cx, old_cy))
                self.shape_artist.set_radius(old_r)
                current_shape["cx"] = old_cx
                current_shape["cy"] = old_cy
                current_shape["r"] = old_r
            else:
                plotter.sprint_distance = actual_dist

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
        plotter = self.plotter
        cx, cy = self.shape_artist.get_center()  # type: ignore
        new_r = int(round(((xdata - cx) ** 2 + (ydata - cy) ** 2) ** 0.5))
        current_shape = plotter.shapes[self.entry_id]
        new_sp_r = None

        if (
            plotter.saved_mouse_wheel
            and current_shape["scancode"] == MOUSE_WHEEL_SIMULATOR_CODE
        ):
            new_r = min(
                new_r,
                int(
                    round(
                        DEFAULT_SPEC_MAX_RATIO
                        * ((plotter.img_width + plotter.img_height) / 2)
                    )
                ),
            )

            if plotter.saved_sprint_distance:
                if plotter.sprint_distance > DEFAULT_MIN_CIRCLE_R:
                    new_r = min(new_r, int(plotter.sprint_distance) - 1)

                if plotter.sprint_artist_id is not None:
                    sprint_shape_artist = plotter.shapes_artists.get(
                        plotter.sprint_artist_id
                    )
                    if isinstance(sprint_shape_artist, Circle):
                        if new_r < sprint_shape_artist.get_radius():
                            new_sp_r = new_r

        if (
            plotter.saved_sprint_distance
            and current_shape["scancode"] == SPRINT_DISTANCE_CODE
        ):
            new_r = min(new_r, plotter.mouse_wheel_radius)

        if new_r >= DEFAULT_MIN_CIRCLE_R:
            self.shape_artist.set_radius(new_r)
            current_shape["r"] = new_r
            if new_sp_r is not None and plotter.sprint_artist_id is not None:
                sprint_shape_artist = plotter.shapes_artists.get(
                    plotter.sprint_artist_id
                )
                sprint_shape = plotter.shapes.get(plotter.sprint_artist_id)
                if isinstance(sprint_shape_artist, Circle) and sprint_shape:
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
        self._circle_transform_helper(old_cx, old_cy, old_r, new_cx, new_cy, False)
        self.plotter.mark_dirty()
        self.canvas.draw()
        self.plotter.captured = False


class _DraggableRectangle(_DraggableShape):
    def __init__(self, entry_id: int, plotter_ref: LayoutsPlotterWidget):
        super().__init__(entry_id, plotter_ref)
        if not isinstance(self.shape_artist, Rectangle):
            return
        x, y = self.shape_artist.get_xy()
        self._update_rectangle_safe(
            x, y, self.shape_artist.get_width(), self.shape_artist.get_height()
        )

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
        self.plotter.mark_dirty()
        self.canvas.draw()
        self.plotter.captured = False


class _MouseWheelDragManager:
    """Click target for one of the four wheel direction indicators. The plotter dispatches presses here AFTER all zone managers, so this can reliably cancel any zone drag that started underneath the indicator."""

    def __init__(self, entry_id: int, plotter_ref: LayoutsPlotterWidget):
        self.entry_id = entry_id
        self.plotter = plotter_ref

    def _on_press(self, event):
        if (
            self.plotter.is_fatal_state
            or self.plotter.state is not PlotterState.IDLE
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

        self.plotter.state = PlotterState.WAITING_FOR_WHEEL_INDICATOR
        indicators.current_mouse_wheel_indicator = self.entry_id
        self.plotter.mouse_wheel_indicators.highlight_mouse_wheel_indicator(
            self.entry_id
        )
        self.plotter.update_title(
            "Press KEY to bind or click anywhere outside the indicator to cancel."
        )


class MouseWheelIndicators:
    def __init__(self, plotter_ref: LayoutsPlotterWidget) -> None:
        self.mouse_wheel_indicators_map: dict[int, int] = {}
        self.mouse_wheel_shapes_artists: dict[int, Circle] = {}
        self.mouse_wheel_labels_artists: dict[int, Text] = {}
        self.mouse_wheel_labels_drag_managers: dict[int, _MouseWheelDragManager] = {}
        self.current_mouse_wheel_indicator: int | None = None
        self.plotter = plotter_ref
        self.canvas = self.plotter.canvas
        self.mouse_wheel_indicators_captured = False

    def _calculate_translations(self) -> dict[int, tuple[float, float]]:
        cx = self.plotter.mouse_wheel_cx
        cy = self.plotter.mouse_wheel_cy
        r = self.plotter.mouse_wheel_radius
        # 0: Up (cy - r), 1: Left (cx - r), 2: Down (cy + r), 3: Right (cx + r)
        return {0: (cx, cy - r), 1: (cx - r, cy), 2: (cx, cy + r), 3: (cx + r, cy)}

    def _sprint_shape_artist(self) -> Optional[Circle]:
        sid = self.plotter.sprint_artist_id
        if sid is None or not self.plotter.saved_sprint_distance:
            return None
        art = self.plotter.shapes_artists.get(sid)
        return art if isinstance(art, Circle) else None

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

    def update_mouse_wheel_indicator_from_key(self, key_name: Optional[str]):
        current_indicator = self.current_mouse_wheel_indicator

        if current_indicator is not None:
            if not key_name:
                msg = "Key could not be identified."
                self.plotter.send_message.emit("Key Error", msg)
                return

            scancode = get_scancode_from_key(key_name)

            if not scancode:
                msg = f"Key '{key_name}' not mapped."
                self.plotter.send_message.emit("Key Error", msg)
                print(msg)
                return

            if scancode == MOUSE_WHEEL_SIMULATOR_CODE:
                msg = f"Key '{key_name}' with scancode '{scancode}' cannot be bound to the indicator as it is the mouse wheel code."
                self.plotter.send_message.emit("Key Error", msg)
                print(msg)
                return

            elif scancode == SPRINT_DISTANCE_CODE:
                msg = f"Key '{key_name}' with scancode '{scancode}' cannot be bound to the indicator as it is the sprint code."
                self.plotter.send_message.emit("Key Error", msg)
                print(msg)
                return

            for idx, bound in self.mouse_wheel_indicators_map.items():
                if idx != current_indicator and bound == scancode:
                    msg = (
                        f"Key '{key_name}' is already bound to another wheel direction."
                    )
                    self.plotter.send_message.emit("Key Error", msg)
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
            self.plotter.send_message.emit("Key Error", msg)
            print(msg)
            return

        self.mouse_wheel_indicators_map[current_indicator] = scancode

        if current_indicator in self.mouse_wheel_labels_artists:
            self.mouse_wheel_labels_artists[current_indicator].set_text(
                scancode_key_name.upper()
            )

        self.current_mouse_wheel_indicator = None
        self.unhighlight_mouse_wheel_indicator(current_indicator)
        self.plotter.mark_dirty()
        self.plotter.reset_state()

    def delete_mouse_wheel_indicators(self):
        for uid in list(self.mouse_wheel_labels_artists.keys()):
            label_artist = self.mouse_wheel_labels_artists[uid]
            if label_artist.axes is not None:
                label_artist.remove()
        self.mouse_wheel_labels_artists = {}

        for uid in list(self.mouse_wheel_shapes_artists.keys()):
            shape_artist = self.mouse_wheel_shapes_artists[uid]
            if shape_artist.axes is not None:
                shape_artist.remove()
        self.mouse_wheel_shapes_artists = {}

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

    def move_mouse_wheel_indicators(self, is_blitting: bool):
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

            if is_blitting and label_artist.axes is not None:
                label_artist.axes.draw_artist(label_artist)

            if is_blitting and shape_artist.axes is not None:
                shape_artist.axes.draw_artist(shape_artist)

        # The sprint circle is animated during a wheel drag (see _capture_*), so it must be
        # redrawn every frame or it disappears / ghosts at its old position.
        if is_blitting and self.mouse_wheel_indicators_captured:
            sprint_art = self._sprint_shape_artist()
            if sprint_art is not None and sprint_art.axes is not None:
                sprint_art.axes.draw_artist(sprint_art)

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

    def _capture_mouse_wheel_background(self):
        for i in range(4):
            if (
                i not in self.mouse_wheel_labels_artists
                or i not in self.mouse_wheel_shapes_artists
            ):
                continue

            label_artist = self.mouse_wheel_labels_artists[i]
            shape_artist = self.mouse_wheel_shapes_artists[i]

            if (label_bbox := label_artist.get_bbox_patch()) is not None:
                label_bbox.set_edgecolor(ACTIVE_EDGE_COLOR)
                label_bbox.set_linewidth(DEFAULT_LARGE_LINE_WIDTH)
            label_artist.set_animated(True)

            shape_artist.set_edgecolor(ACTIVE_EDGE_COLOR)
            shape_artist.set_linewidth(DEFAULT_LARGE_LINE_WIDTH)
            shape_artist.set_animated(True)

        sprint_art = self._sprint_shape_artist()
        if sprint_art is not None:
            sprint_art.set_animated(True)

        self.canvas.draw()
        self.plotter.bg_cache = self.canvas.copy_from_bbox(self.plotter.ax.bbox)
        self.mouse_wheel_indicators_captured = True

    def _on_release_mouse_wheel(self):
        if self.mouse_wheel_indicators_captured:
            for i in range(4):
                if (
                    i not in self.mouse_wheel_labels_artists
                    or i not in self.mouse_wheel_shapes_artists
                ):
                    continue

                label_artist = self.mouse_wheel_labels_artists[i]
                shape_artist = self.mouse_wheel_shapes_artists[i]

                if (label_bbox := label_artist.get_bbox_patch()) is not None:
                    label_bbox.set_edgecolor("black")
                    label_bbox.set_linewidth(DEFAULT_SMALL_LINE_WIDTH)
                label_artist.set_animated(False)

                shape_artist.set_edgecolor(DEFAULT_EDGE_COLOR)
                shape_artist.set_linewidth(DEFAULT_MEDIUM_LINE_WIDTH)
                shape_artist.set_animated(False)

            sprint_art = self._sprint_shape_artist()
            if sprint_art is not None:
                sprint_art.set_animated(False)

            self.mouse_wheel_indicators_captured = False


class LayoutsPlotterWidget(QWidget):
    layout_saved = Signal(str, int)
    zone_selected = Signal(int)
    status_updated = Signal(str)
    send_message = Signal(str, str)
    dirty_changed = Signal(bool)
    save_requested = Signal()

    def __init__(self, parent: QWidget | None = None, standalone: bool = False):
        super().__init__(parent)
        self.standalone = standalone
        self.is_fatal_state = False
        self.loaded_layout_id: int | None = None
        self.selected_entry_id: int | None = None
        self.top_bezel_id: int | None = None
        self.bottom_bezel_id: int | None = None
        self.top_bezel_dp: int = BEZEL_DP_THICKNESS
        self.bottom_bezel_dp: int = BEZEL_DP_THICKNESS
        self._dirty = False
        self.show_overlays = True

        self.fig = Figure()
        self.fig.subplots_adjust(left=0, right=1, top=1, bottom=0)

        self.canvas = FigureCanvasQTAgg(self.fig)
        self.canvas.setMinimumSize(1, 1)
        self.canvas.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

        self.ax = self.fig.add_subplot(1, 1, 1)
        self._reset_axes()

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

        self.top_bezel_label_artist = Text()
        self.top_bezel_shape_artist = Rectangle((0, 0), 0, 0)
        self.bottom_bezel_label_artist = Text()
        self.bottom_bezel_shape_artist = Rectangle((0, 0), 0, 0)

        self.mouse_wheel_indicators = MouseWheelIndicators(self)

        # Every attribute that handlers read must exist BEFORE the first (possibly failing)
        # reload, otherwise _render_empty_state -> update_title raises AttributeError.
        self._init_params_helper()

        # One connection per event; managers are dispatched from here (no N-fold handlers).
        self.canvas.mpl_connect("motion_notify_event", self._on_mouse_move)
        self.canvas.mpl_connect("button_press_event", self._on_click)
        if self.canvas.supports_blit:
            self.canvas.mpl_connect("motion_notify_event", self._on_motion_all)
            self.canvas.mpl_connect("button_press_event", self._on_press_all)
            self.canvas.mpl_connect("button_release_event", self._on_release_all)
        self.canvas.mpl_connect("key_press_event", self._on_key_press)
        self.canvas.mpl_connect("resize_event", self.on_resize)
        self.canvas.mpl_connect("draw_event", self._on_draw)
        self.canvas.mpl_connect("axes_leave_event", self._on_mouse_leave)
        self.canvas.mpl_connect("figure_leave_event", self._on_mouse_leave)

        self.reload_active_layout()

    # ------------------------------------------------------------------
    # State / dirty tracking
    # ------------------------------------------------------------------
    @property
    def is_dirty(self) -> bool:
        return self._dirty

    def mark_dirty(self) -> None:
        self._set_dirty(True)

    def _set_dirty(self, value: bool) -> None:
        if self._dirty != value:
            self._dirty = value
            self.dirty_changed.emit(value)

    def _reset_axes(self) -> None:
        self.ax.set_axis_off()
        self.ax.set_position((0, 0, 1, 1))

    def _init_params_helper(self):
        self.points = []
        self.point_artists = []
        self.mode = None
        self.state = PlotterState.IDLE
        self.input_buffer = ""
        
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
        self.img_width: int = 0
        self.img_height: int = 0
        self.img_dpi: float = 0
        self.bg_cache = None
        self.top_bezel_id = None
        self.bottom_bezel_id = None
        self.top_bezel_dp = BEZEL_DP_THICKNESS
        self.bottom_bezel_dp = BEZEL_DP_THICKNESS
        self.selected_entry_id = None

        for uid in list(self.labels_artists.keys()):
            label_artist = self.labels_artists[uid]
            if label_artist.axes is not None:
                label_artist.remove()
        self.labels_artists = {}

        for uid in list(self.shapes_artists.keys()):
            shape_artist = self.shapes_artists[uid]
            if shape_artist.axes is not None:
                shape_artist.remove()
        self.shapes_artists = {}

        self.labels_drag_managers = {}
        self.shapes_drag_managers = {}

        self.last_artist_id: str | None = None
        self.ignore_current_draggable_id_n = 0
        self.current_draggable_id = None
        self.current_draggable: _DraggableLabel | _DraggableShape | None = None
        self.draggables_ids = []
        self.captured = False
        self.current_move_distance = 0.0
        self.iter_count = 0
        self.fire_on_motion = False
        self.mouse_wheel_indicators.mouse_wheel_indicators_captured = False

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
        image_params: Optional[tuple[int, int, int]] = None,
    ) -> bool:
        self.active_layout = store.get_active_layout()
        self.loaded_layout_id = self.active_layout.id if self.active_layout else None

        if not self.active_layout:
            return self._render_empty_state(
                "No active layout set. Please select or create a layout first."
            )

        if not self.active_layout.image_path:
            return self._render_empty_state(
                f"Layout '{self.active_layout.name}' has no assigned HUD image."
            )

        img_path = Path(self.active_layout.image_path)
        if not img_path.is_absolute():
            img_path = Path(IMAGES_FOLDER) / img_path

        if not img_path.exists():
            return self._render_empty_state(
                f"Image '{img_path.as_posix()}' does not exist on disk."
            )

        # Try to get the layout's image with its parameters if it wasn't provided
        if img is None or image_params is None:
            try:
                img, image_params = self.get_image_params(self.active_layout)
            except Exception as exc:
                logger.exception("Failed to read/store image parameters")
                return self._render_empty_state(f"Could not read image: {exc}")

        if img is None:
            return self._render_empty_state("Could not load image file.")

        if image_params is None:
            return self._render_empty_state("Could not get image parameters")

        # get_image_params() may have changed width/height/dpi/image_path in the DB.
        # Re-read so bezel dpi, copy-saves, etc. never use a stale snapshot.
        refreshed = store.layouts.get(self.active_layout.id)
        if refreshed is not None:
            self.active_layout = refreshed

        prev_overlays = self.show_overlays
        self.is_fatal_state = False
        self.ax.clear()
        self._reset_axes()
        self._init_params_helper()
        self.show_overlays = prev_overlays
        self._init_crosshairs()

        self._update_image_params(*image_params)
        self.ax.imshow(img, aspect="equal")
        self.ax.set_xlim(-0.5, img.width - 0.5)
        self.ax.set_ylim(img.height - 0.5, -0.5)

        self._load_active_layout_zones()
        self._render_bezels_notch()

        self.mouse_wheel_indicators.delete_mouse_wheel_indicators()
        self.mouse_wheel_indicators.create_mouse_wheel_indicators()

        self._set_dirty(False)
        self.zone_selected.emit(-1)
        self.update_title(f"OVERLAYS: {'VISIBLE' if self.show_overlays else 'HIDDEN'}")
        self.canvas.draw_idle()

        return True

    def _bezel_kwargs(self, is_top: bool):
        dp = self.top_bezel_dp if is_top else self.bottom_bezel_dp
        dpi = int(self.img_dpi) if self.img_dpi > 0 else BASELINE_DPI
        thickness_px = float(dp_to_px(dp, dpi))
        label_y = (
            (thickness_px / 2.0) if is_top else (self.img_height - thickness_px / 2.0)
        )
        y = 0.0 if is_top else self.img_height - thickness_px
        label = "Top Bezel Notch" if is_top else "Bottom Bezel Notch"

        return (
            {
                "x": self.img_width / 2.0,
                "y": label_y,
                "text": f"{label} ({thickness_px:.0f}px)",
                "color": "white",
                "fontsize": self._get_scaled_font_size(),
                "ha": "center",
                "va": "center",
                "zorder": 9,
                "alpha": 0.8,
            },
            {
                "xy": (0.0, y),
                "width": float(self.img_width),
                "height": thickness_px,
                "fill": True,
                "facecolor": (1.0, 0.2, 0.2, 0.25),
                "edgecolor": (1.0, 0.4, 0.4, 0.7),
                "linewidth": 1.0,
                "linestyle": "--",
                "zorder": 8,
            },
        )

    def _render_bezels_notch(self):
        if self.img_width <= 0 or self.img_height <= 0:
            return

        for is_top, lbl, shp in (
            (True, self.top_bezel_label_artist, self.top_bezel_shape_artist),
            (False, self.bottom_bezel_label_artist, self.bottom_bezel_shape_artist),
        ):
            label_kwargs, shape_kwargs = self._bezel_kwargs(is_top)
            lbl.set(**label_kwargs)
            shp.set(**shape_kwargs)
            lbl.set_visible(self.show_overlays)
            shp.set_visible(self.show_overlays)
            if lbl.axes is None:
                self.ax.add_artist(lbl)
            if shp.axes is None:
                self.ax.add_patch(shp)

    def set_bezel_dp(self, is_top: bool, dp: float) -> None:
        """Edits a bezel thickness in memory (saved with the layout, like every other edit)."""
        if self.is_fatal_state:
            return
        value = clamp(int(round(dp)), MIN_BEZEL_DP, MAX_BEZEL_DP)
        current = self.top_bezel_dp if is_top else self.bottom_bezel_dp
        if value == current:
            return
        if is_top:
            self.top_bezel_dp = value
        else:
            self.bottom_bezel_dp = value
        self._render_bezels_notch()
        self.mark_dirty()
        self.canvas.draw_idle()

    def _render_empty_state(self, message: str) -> bool:
        self.ax.clear()
        self._reset_axes()
        self._init_params_helper()  # drop every stale shape/id so nothing can be saved
        self.is_fatal_state = True
        self.ax.text(
            0.5,
            0.5,
            message,
            transform=self.ax.transAxes,
            ha="center",
            va="center",
            wrap=True,
            color="gray",
        )
        self._set_dirty(False)
        self.zone_selected.emit(-1)
        self.update_title(f"ERROR: {message}")
        self.canvas.draw_idle()
        return False

    def _load_image(self, path: Optional[Path] = None) -> Optional[Image.Image]:
        target_path = path
        if target_path is None:
            return

        try:
            # Copy into memory and close the file handle right away (Windows file locks).
            with Image.open(target_path) as raw:
                img = raw.copy()

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
    ) -> tuple[Optional[Image.Image], Optional[tuple[int, int, int]]]:
        """Loads the image and atomically stores its width/height/dpi/path on the layout. If the resolution changed, the DB layer rescales all zones in the same transaction, so the stored zones and the stored canvas size can never disagree."""
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
            img_dpi = int(round(dpi_meta[0])) if dpi_meta else BASELINE_DPI
        else:
            img_dpi = int(round(dpi_meta)) if dpi_meta else BASELINE_DPI
        if img_dpi <= 0:
            img_dpi = BASELINE_DPI

        # Store clean filename if placed in data/images/ for cross-machine portability
        saved_img_ref = (
            img_path.name
            if img_path.parent.resolve() == IMAGES_FOLDER.resolve()
            else str(img_path.resolve())
        )

        store.layouts.apply_image_params(
            active_layout.id, img_width, img_height, img_dpi, saved_img_ref
        )

        return img, (img_width, img_height, img_dpi)

    def _update_image_params(self, width: int, height: int, dpi: int) -> None:
        """Sets canvas dimensions"""
        self.img_width = width
        self.img_height = height
        self.img_dpi = dpi

    def update_title(self, text: str, idle_override: bool = False):
        self.status_updated.emit(text)
        self.cursor_manager.set_state_cursor(self.state)

        if idle_override:
            self.fig.canvas.draw_idle()
        else:
            self.fig.canvas.draw()

    def _overlay_title(self, idle_override: bool = True):
        self.update_title(
            f"OVERLAYS: {'VISIBLE' if self.show_overlays else 'HIDDEN'}", idle_override
        )

    def _clear_visuals(self):
        for artist in self.point_artists:
            if artist.axes is not None:
                artist.remove()
        self.point_artists = []
        self.fig.canvas.draw()

    def reset_state(self):
        if self.is_fatal_state:
            return

        self._clear_visuals()
        self.state, self.mode, self.points = PlotterState.IDLE, None, []
        self.input_buffer, self.buffer_default = "", True
        self._overlay_title(False)
        if self.ax.bbox.width > 0 and self.ax.bbox.height > 0:
            self.bg_cache = self.canvas.copy_from_bbox(self.ax.bbox)

    def start_mode(self, mode: str, num_points: int):
        if self.is_fatal_state or self.state is not PlotterState.IDLE:
            return

        self.reset_state()
        self.mode, self.artists_points, self.state = mode, num_points, PlotterState.COLLECTING
        self.update_title(f"MODE: {mode}. Click {num_points} points on the image.")

    def _load_active_layout_zones(self) -> None:
        if not self.active_layout:
            return

        zones = store.zones.list_for_layout(self.active_layout.id)
        self.reset_state()

        # Wheel first, then sprint, then everything else: the sprint is only valid relative
        # to an existing wheel, and list_for_layout() orders by id (import/duplicate can
        # put the sprint before the wheel).
        def load_order(z):
            if z.scancode == MOUSE_WHEEL_SIMULATOR_CODE:
                return (0, z.id)
            if z.scancode == SPRINT_DISTANCE_CODE:
                return (1, z.id)
            return (2, z.id)

        for zone in zones:
            if zone.zone_type == BEZEL:
                zone.set_parsed_config_from_json()
                _, _, dp, _ = zone.CONFIG_HELPER.get_region_config()
                dp = clamp(int(round(dp)), MIN_BEZEL_DP, MAX_BEZEL_DP)
                if zone.scancode == TOP_BEZEL_ID:
                    self.top_bezel_id = zone.id
                    self.top_bezel_dp = dp
                elif zone.scancode == BOTTOM_BEZEL_ID:
                    self.bottom_bezel_id = zone.id
                    self.bottom_bezel_dp = dp

        for zone in sorted((z for z in zones if z.zone_type != BEZEL), key=load_order):
            if zone.zone_type not in (CIRCLE, RECTANGLE):
                continue

            self.mode = zone.zone_type
            cx = int(round(zone.cx or 0.0))
            cy = int(round(zone.cy or 0.0))

            r, bb = None, None
            if zone.zone_type == CIRCLE:
                r = int(round(zone.r or 0.0))
            else:
                bb = (
                    (int(round(zone.x1 or 0.0)), int(round(zone.y1 or 0.0))),
                    (int(round(zone.x2 or 0.0)), int(round(zone.y2 or 0.0))),
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
                strict=False,
            )

        # The zones are authoritative when they exist; fall back to the stored layout values
        # only when there is no wheel / sprint zone.
        if not self.saved_mouse_wheel:
            self.mouse_wheel_radius = float(self.active_layout.mouse_wheel_radius)
        if not self.saved_sprint_distance:
            self.sprint_distance = float(self.active_layout.sprint_distance)
        self.reset_state()

    def toggle_visibility(self):
        if self.is_fatal_state:
            return
        if self.state is not PlotterState.IDLE:
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

        self._overlay_title(False)

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
        """Captures a fresh background cache immediately after every full render. Because crosshairs use animated=True, this snapshot is always clean and matches the exact post-resize ax.bbox dimensions."""
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
            self.state is PlotterState.IDLE
            and not self.captured
            and self.current_draggable_id is not None
        ):
            self._partial_release_all()
            self._overlay_title(True)

    def on_resize(self, event=None) -> None:
        """Keeps overlays and blit caches dynamically aligned to the canvas viewport on resize. Invalidates stale blit caches on resize so _on_draw rebuilds them cleanly."""
        if self.is_fatal_state:
            return

        # Invalidate stale blit cache from previous viewport dimensions
        self.bg_cache = None
        self.captured = False
        self.mouse_wheel_indicators.mouse_wheel_indicators_captured = False
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

        if self.state is PlotterState.COLLECTING and event.inaxes == self.ax:
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
            self.state is PlotterState.IDLE
            and not self.captured
            and event.button is None
            and event.inaxes == self.ax
        ):
            if self.ignore_current_draggable_id_n > 0:
                return

            hovering = None
            for uid, mgr in self.labels_drag_managers.items():
                if (
                    mgr.label_artist.get_visible()
                    and mgr.label_artist.contains(event)[0]
                ):
                    hovering = (uid, mgr, "label")
                    break
            if not hovering:
                for uid, mgr in self.shapes_drag_managers.items():
                    if (
                        mgr.shape_artist
                        and mgr.shape_artist.get_visible()
                        and mgr.shape_artist.contains(event)[0]
                    ):
                        hovering = (uid, mgr, "shape")
                        break

            if hovering:
                uid, mgr, m_type = hovering
                if (curr_id := m_type + "_" + str(uid)) != self.current_draggable_id:
                    self._partial_release_all()
                    mgr._on_press_helper(event)
                    self.current_draggable_id = curr_id
                    self._indicate_current_draggable_id()
                    self.fire_on_motion = False
            else:
                self._partial_release_all()
                self._overlay_title(True)

    def _partial_release_all(self):
        """Clears hover state. Does not touch the sticky inspector selection."""
        for mgr in self._iter_drag_managers():
            mgr._reset_edge()
        self.current_draggable_id = None
        self.draggables_ids = []
        self.fig.canvas.draw_idle()

    # ------------------------------------------------------------------
    # Central drag dispatch (replaces one mpl connection per manager)
    # ------------------------------------------------------------------
    def _iter_drag_managers(self) -> list[_Draggable]:
        out: list[_Draggable] = []
        for uid in sorted(
            set(self.labels_drag_managers) | set(self.shapes_drag_managers)
        ):
            if uid in self.labels_drag_managers:
                out.append(self.labels_drag_managers[uid])
            if uid in self.shapes_drag_managers:
                out.append(self.shapes_drag_managers[uid])
        return out

    def _on_press_all(self, event):
        if self.is_fatal_state or self.state is not PlotterState.IDLE:
            return
        for mgr in self._iter_drag_managers():
            mgr._on_press(event)
        # Wheel indicators run LAST so they can always veto a zone drag underneath them.
        for ind in list(
            self.mouse_wheel_indicators.mouse_wheel_labels_drag_managers.values()
        ):
            ind._on_press(event)

    def _on_motion_all(self, event):
        if self.is_fatal_state:
            return
        for mgr in self._iter_drag_managers():
            mgr._on_motion(event)

    def _on_release_all(self, event=None):
        if self.is_fatal_state or self.state is not PlotterState.IDLE:
            return

        managers = self._iter_drag_managers()
        for mgr in managers:
            mgr._reset_edge()

        if self.ignore_current_draggable_id_n <= 0:
            self._overlay_title(True)

        if self.current_draggable_id is None and self.draggables_ids:
            self.current_draggable_id = self._select_current_draggable_id()
            self._indicate_current_draggable_id()

        chosen = None
        if self.current_draggable_id is not None:
            chosen = next(
                (m for m in managers if m.artist_id == self.current_draggable_id), None
            )

        if chosen is not None:
            chosen._finish_release()
            self._finish_drag_cycle()
        elif (
            not self.draggables_ids
            and event is not None
            and getattr(event, "inaxes", None) == self.ax
        ):
            # Clicked empty canvas: drop the inspector selection.
            self._select_entry(None)

        self.mouse_wheel_indicators._on_release_mouse_wheel()
        self.canvas.draw_idle()

    def _select_current_draggable_id(self):
        if not self.draggables_ids:
            self.iter_count = 0
            return None
        if self.last_artist_id is None:
            self.iter_count = 0
            return self.draggables_ids[0]

        if self.last_artist_id in self.draggables_ids:
            if self.iter_count >= 2:
                idx = self.draggables_ids.index(self.last_artist_id)
                self.iter_count = 0
                return self.draggables_ids[(idx + 1) % len(self.draggables_ids)]
            else:
                return self.last_artist_id
        else:
            self.iter_count = 0
            return self.draggables_ids[0]

    def _indicate_current_draggable_id(self):
        """Highlights the current artist and updates the status text. The entry is parsed from the id itself (the caller may be another artist's manager)."""
        curr_id = self.current_draggable_id
        if curr_id is None:
            return
        entry_id = _parse_artist_id(curr_id)
        if entry_id is None or entry_id not in self.shapes:
            return

        current_shape = self.shapes[entry_id]
        priority = current_shape.get("priority", 0)
        pointer_info = (
            "Pointer Enabled"
            if current_shape.get("pointer", False)
            else "Pointer Disabled"
        )

        if curr_id.startswith("label_"):
            mgr = self.labels_drag_managers.get(entry_id)
            if mgr is not None:
                if (label_bbox := mgr.label_artist.get_bbox_patch()) is not None:
                    label_bbox.set_edgecolor(INDICATED_EDGE_COLOR)
                    label_bbox.set_linewidth(DEFAULT_MEDIUM_LINE_WIDTH)
                self.update_title(
                    f"Current Artist: {curr_id} (ID: {entry_id}, Prio: {priority}) | Drag/Nudge | {pointer_info}",
                    True,
                )
            self.current_draggable = mgr

        elif curr_id.startswith("shape_"):
            mgr = self.shapes_drag_managers.get(entry_id)
            if mgr is not None:
                mgr.shape_artist.set_edgecolor(INDICATED_EDGE_COLOR)
                mgr.shape_artist.set_linewidth(DEFAULT_LARGE_LINE_WIDTH)
                self.update_title(
                    f"Current Artist: {curr_id} (ID: {entry_id}, Prio: {priority}) | Drag/Resize/Nudge | {pointer_info}",
                    True,
                )
            self.current_draggable = mgr

        self.cursor_manager.set_custom_cursor(Qt.CursorShape.SizeAllCursor)

    def _finish_drag_cycle(self):
        self._indicate_current_draggable_id()
        entry_id = _parse_artist_id(self.current_draggable_id)

        if self.current_move_distance <= DEFAULT_MIN_MOVE_DIST:
            self.iter_count += 1
        else:
            self.iter_count = 0

        self.captured = False
        self.last_artist_id = self.current_draggable_id
        self.current_draggable_id = None
        self.current_move_distance = 0.0
        self.draggables_ids = []

        if entry_id is not None:
            self._select_entry(entry_id)

    def _select_entry(self, entry_id: Optional[int]) -> None:
        """Sticky inspector selection (set by click/drag, cleared by empty click / Esc / delete)."""
        self.selected_entry_id = entry_id
        self.zone_selected.emit(-1 if entry_id is None else entry_id)

    def _on_click(self, event):
        if self.is_fatal_state:
            return

        if self.state is PlotterState.IDLE:
            self.ignore_current_draggable_id_n = 0
        if self.state is PlotterState.WAITING_FOR_KEY:
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

        if self.state is PlotterState.WAITING_FOR_WHEEL_INDICATOR:
            current_indicator = (
                self.mouse_wheel_indicators.current_mouse_wheel_indicator
            )
            self.mouse_wheel_indicators.current_mouse_wheel_indicator = None
            self.mouse_wheel_indicators.unhighlight_mouse_wheel_indicator(
                current_indicator
            )
            self.reset_state()
            return

        if (
            self.state is not PlotterState.COLLECTING
            or event.button != 1
            or event.xdata is None
            or event.ydata is None
        ):
            return

        self.points.append((int(round(event.xdata)), int(round(event.ydata))))
        (dot,) = self.ax.plot(event.xdata, event.ydata, "ro")
        self.point_artists.append(dot)
        self.fig.canvas.draw()
        self.bg_cache = None

        if (rem := self.artists_points - len(self.points)) > 0:
            self.update_title(
                f"MODE: {self.mode}. {rem} points remaining (Esc to Cancel)."
            )
        else:
            self.state = PlotterState.WAITING_FOR_KEY
            self.update_title("Shape Defined! Press KEY or CLICK MOUSE to bind.")

    def _on_key_press(self, event):
        if self.is_fatal_state:
            return

        key = event.key
        if key is None:
            return

        if self.state is PlotterState.DELETING:
            self._handle_deleting_input(key)
            return

        if self.state is PlotterState.CONFIRM_DELETE_ALL:
            if key == "enter":
                self._delete_all_shapes()
            else:
                self.reset_state()
            return
        if self.state is PlotterState.CONFIRM_EXIT or self.state is PlotterState.COLLECTING:
            if key == "escape":
                self.reset_state()
            return
        if self.state is PlotterState.WAITING_FOR_KEY:
            self.calculate_shape(get_specific_mt_key(event))
            return
        if self.state is PlotterState.WAITING_FOR_WHEEL_INDICATOR:
            self.mouse_wheel_indicators.update_mouse_wheel_indicator_from_key(
                get_specific_mt_key(event)
            )
            return

        if self.state is PlotterState.IDLE:
            if key == "f1":
                self.reset_state()
            elif key == "f2":
                if not self.shapes:
                    self.update_title("List empty. Nothing to delete.")
                    return
                self.state = PlotterState.CONFIRM_DELETE_ALL
                self.update_title(
                    "[DELETE ALL?] Press ENTER to Confirm or Any other key to Cancel."
                )
            elif key == "f4":
                self.toggle_visibility()
            elif key == "f6":
                self.start_mode(CIRCLE, 3)
            elif key == "f7":
                self.start_mode(RECTANGLE, 4)
            elif key == "f9":
                self._print_data()
            elif key == "f12":
                self.save_requested.emit()
            elif key == "delete":
                self._enter_deleting_mode()
            elif key == "escape":
                self.reset_state()
                self._select_entry(None)
            elif key in ("p", "o") and self.current_draggable:
                eid = self.current_draggable.entry_id
                if eid in self.shapes:
                    delta = 1 if key == "p" else -1
                    self.shapes[eid]["priority"] = clamp(self.shapes[eid]["priority"] + delta, MIN_PRIORITY, MAX_PRIORITY)
                    self.mark_dirty()
                    self.update_title(
                        f"Priority {'increased' if key == 'p' else 'decreased'}: {self.shapes[eid]['priority']} (ID: {eid})",
                        True,
                    )
                    self._select_entry(eid)
            else:
                step = 5 if key.startswith("shift+") else 1
                clean_key = key.replace("shift+", "")
                dirs = {
                    "left": (-step, 0),
                    "right": (step, 0),
                    "up": (0, -step),
                    "down": (0, step),
                }
                if clean_key in dirs and self.current_draggable:
                    self.current_draggable._move(*dirs[clean_key])

    def _enter_deleting_mode(self):
        if self.state is not PlotterState.IDLE:
            return

        if not self.shapes:
            self.update_title("List empty. Nothing to delete")
            return
        self.state, self.input_buffer = PlotterState.DELETING, ""
        self.update_title("DELETE MODE: Type ID... (Enter to Confirm | Esc to Cancel)")

    def _delete_all_shapes(self):
        # Always leave CONFIRM_DELETE_ALL first (it used to stay stuck when the list was empty).
        had_shapes = bool(self.shapes)
        for uid in list(self.shapes.keys()):
            self._delete_entry(uid)
        self.count = 0
        self.reset_state()
        self._select_entry(None)
        if not had_shapes:
            self.update_title("List empty. Nothing to delete.")

    def _handle_deleting_input(self, key):
        if key == "escape":
            self.reset_state()
            return
        if key == "enter":
            if self.input_buffer:
                try:
                    if (uid := int(self.input_buffer)) in self.shapes:
                        self._delete_entry(uid)
                        self.reset_state()
                        self.update_title(f"Deleted ID {uid}.", True)
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

    def _discard_artists(self, uid: int) -> None:
        """Removes an entry's data, artists and managers, and every reference to them."""
        self.shapes.pop(uid, None)

        for d in (self.labels_artists, self.shapes_artists):
            art = d.pop(uid, None)
            if art is not None and art.axes is not None:
                art.remove()
        self.labels_drag_managers.pop(uid, None)
        self.shapes_drag_managers.pop(uid, None)

        ids = (f"shape_{uid}", f"label_{uid}")
        if self.current_draggable_id in ids:
            self.current_draggable_id = None
        if (
            self.current_draggable is not None
            and self.current_draggable.entry_id == uid
        ):
            self.current_draggable = None
        if self.last_artist_id in ids:
            self.last_artist_id = None
        self.draggables_ids = [i for i in self.draggables_ids if i not in ids]
        if self.selected_entry_id == uid:
            self._select_entry(None)

    def _delete_entry(self, uid):
        if uid not in self.shapes:
            return

        entry_scancode = int(self.shapes[uid]["scancode"])

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
            self.mouse_wheel_indicators.set_indicators_visible(False)

        elif entry_scancode == SPRINT_DISTANCE_CODE:
            self.saved_sprint_distance = False
            self.sprint_artist_id = None
            self.sprint_distance = 0.0

        self._discard_artists(uid)
        self.mark_dirty()

    def calculate_shape(self, key_name: Optional[str]):
        if not key_name:
            self.send_message.emit("Key Error", "Key could not be identified.")
            return

        scancode = get_scancode_from_key(key_name)
        if not scancode:
            msg = f"Key '{key_name}' not mapped."
            self.send_message.emit("Key Error", msg)
            print(msg)
            return

        scancode_key_name = get_key_from_scancode(scancode)
        if not scancode_key_name:
            msg = f"Key '{key_name}' with scancode '{scancode}' has no equivalent key name."
            self.send_message.emit("Key Error", msg)
            print(msg)
            return

        cx, cy, r, bb = None, None, None, None
        if self.mode == CIRCLE:
            cx, cy, r, bb = self._calculate_circle()
        elif self.mode == RECTANGLE:
            cx, cy, r, bb = self._calculate_rectangle()

        if self._finalize_shape(
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
        ):
            self.mark_dirty()
        self.reset_state()

    def _finalize_shape(
        self,
        cy: Optional[int],
        cx: Optional[int],
        r: Optional[int],
        bb: Optional[tuple[tuple[float, float], tuple[float, float]]],
        key_name: str,
        scancode: int,
        pointer: bool,
        priority: int,
        pipeline_json: str,
        ignore_app_settings: bool,
        strict: bool = True,
    ) -> bool:
        """Creates the data entry and its artists. Returns True if a shape was added. `strict=False` is used while loading saved zones (no destructive validation)."""
        if cx is None or cy is None:
            return False

        # Validate geometry BEFORE touching any state, so no artist-less entry can be saved.
        if self.mode == CIRCLE:
            if r is None:
                return False
            r = max(int(r), DEFAULT_MIN_CIRCLE_R)
            if scancode == MOUSE_WHEEL_SIMULATOR_CODE:
                max_r = int(
                    round(
                        DEFAULT_SPEC_MAX_RATIO
                        * ((self.img_width + self.img_height) / 2)
                    )
                )
                r = clamp(max_r, DEFAULT_MIN_CIRCLE_R, r)
            elif scancode == SPRINT_DISTANCE_CODE and self.saved_mouse_wheel:
                r = clamp(r, DEFAULT_MIN_CIRCLE_R, int(self.mouse_wheel_radius))
        elif self.mode == RECTANGLE:
            if bb is None:
                return False
            (x1, y1), (x2, y2) = bb
            x2 = max(x2, x1 + DEFAULT_MIN_RECTANGLE_DIST)
            y2 = max(y2, y1 + DEFAULT_MIN_RECTANGLE_DIST)
            cx, cy, _, bb = calculate_raw_rectangle(((x1, y1), (x2, y2)))
        else:
            return False

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
            strict,
        )
        if not saved:
            return False

        label = (
            "MOUSE\nWHEEL"
            if scancode == MOUSE_WHEEL_SIMULATOR_CODE
            else (
                "SPRINT\nDISTANCE"
                if scancode == SPRINT_DISTANCE_CODE
                else key_name.upper()
            )
        )

        if self.mode == CIRCLE:
            if r is None:
                msg = f"{self.mode.capitalize()} shape with key name '{key_name}' and scancode '{scancode}' has no defined radius (r)."
                self._reject_entry("Shape Error", msg, strict)
                return False

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
                self.mouse_wheel_indicators.move_mouse_wheel_indicators(False)
                self.mouse_wheel_indicators.set_indicators_visible(True)

        else:
            if bb is None:
                msg = f"{self.mode.capitalize()} shape with key name '{key_name}' and scancode '{scancode}' has no defined bounding box (bb)."
                self._reject_entry("Shape Error", msg, strict)
                return False

            fc = get_vibrant_random_color(DEFAULT_FACE_COLOR_ALPHA)
            (x1, y1), (x2, y2) = bb

            lbl = self._create_label(cx, cy, label, fc)
            art = self._create_rectangle(x1, y1, x2, y2, fc)

            self.labels_artists[entry_id] = lbl
            self.shapes_artists[entry_id] = art
            self.labels_drag_managers[entry_id] = _DraggableLabel(entry_id, self)
            self.shapes_drag_managers[entry_id] = _DraggableRectangle(entry_id, self)

        lbl.set_visible(self.show_overlays)
        self.ax.add_artist(lbl)

        art.set_visible(self.show_overlays)
        self.ax.add_patch(art)

        if pointer:
            self.labels_drag_managers[entry_id].dull_face_color()
            self.shapes_drag_managers[entry_id].dull_face_color()

        return True

    def on_pointer_marked(self, uid):
        if uid not in self.shapes or uid not in self.labels_drag_managers:
            return
        if self.shapes[uid]["pointer"]:
            self.labels_drag_managers[uid].dull_face_color()
            self.shapes_drag_managers[uid].dull_face_color()
        else:
            self.labels_drag_managers[uid].restore_face_color()
            self.shapes_drag_managers[uid].restore_face_color()
        self.mark_dirty()
        self.canvas.draw_idle()

    def _build_zone_rows(self) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        for _, data in self.shapes.items():
            entry_scancode = int(data["scancode"])
            p_cfg = PipelineConfig()
            p_cfg.set_pipeline_config_from_json(
                pipeline_json=data.get("pipeline_json", "{}")
            )

            row: dict[str, Any] = {
                "scancode": entry_scancode,
                "name": data["key_name"],
                "zone_type": data["type"],
                "cx": float(data["cx"]),
                "cy": float(data["cy"]),
                "r": None,
                "x1": None,
                "y1": None,
                "x2": None,
                "y2": None,
                "ignore_app_settings": bool(data.get("ignore_app_settings", False)),
            }

            if data["type"] == CIRCLE:
                region_idx = 1
                row["r"] = float(data["r"])
            else:
                region_idx = 2
                (x_min, y_min), (x_max, y_max) = data["bb"]
                row["x1"], row["y1"] = float(x_min), float(y_min)
                row["x2"], row["y2"] = float(x_max), float(y_max)

            if entry_scancode == MOUSE_WHEEL_SIMULATOR_CODE:
                indicators_map = self.mouse_wheel_indicators.mouse_wheel_indicators_map
                p_cfg.pipeline_config["up"] = indicators_map[0]
                p_cfg.pipeline_config["left"] = indicators_map[1]
                p_cfg.pipeline_config["down"] = indicators_map[2]
                p_cfg.pipeline_config["right"] = indicators_map[3]

            # VERIFY (needs pipeline.py): these re-assert the idx of every stage on each save.
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
            row["pipeline_json"] = p_cfg.get_pipeline_json_from_config()
            rows.append(row)
        return rows

    def save_to_database(self, user_name: str, as_copy: bool = False) -> bool:
        """Atomically saves the canvas. Returns True on success. as_copy=False: saves in place; if `user_name` differs from the current name the layout is RENAMED (never forked). as_copy=True : saves everything as a brand-new layout called `user_name`."""
        if self.is_fatal_state or self.active_layout is None:
            self.send_message.emit(
                "Cannot Save", "There is no loaded layout image to save."
            )
            return False

        user_name = (user_name or "").strip() or self.active_layout.name

        try:
            zone_rows = self._build_zone_rows()
            layout_fields: dict[str, Any] = {
                "width": self.img_width,
                "height": self.img_height,
                "dpi": int(self.img_dpi),
                "mouse_wheel_radius": float(self.mouse_wheel_radius),
                "sprint_distance": float(self.sprint_distance),
            }

            if as_copy:
                if store.layouts.name_exists(user_name):
                    raise DuplicateNameError("A layout with that name already exists.")
                layout_fields["name"] = user_name
                layout_fields["image_path"] = self.active_layout.image_path
                target_id = None
            else:
                if user_name != self.active_layout.name:
                    if store.layouts.name_exists(user_name, self.active_layout.id):
                        raise DuplicateNameError(
                            "A layout with that name already exists."
                        )
                    layout_fields["name"] = user_name
                target_id = self.active_layout.id

            saved_layout = store.layouts.save_with_zones(
                target_id,
                layout_fields,
                self.top_bezel_dp,
                self.bottom_bezel_dp,
                zone_rows,
            )
            store.set_active_layout(saved_layout.id)
        except DuplicateNameError:
            self.send_message.emit(
                "Name Conflict", f"A layout named '{user_name}' already exists."
            )
            return False
        except Exception as exc:
            logger.exception("Failed to save layout '%s'", user_name)
            self.send_message.emit("Save Error", f"Could not save layout:\n{exc}")
            return False

        self.active_layout = store.layouts.get(saved_layout.id)
        self.loaded_layout_id = saved_layout.id

        # Zone rows were recreated, so refresh the bezel row ids.
        for zone in store.zones.list_for_layout(saved_layout.id, auto_heal=False):
            if zone.zone_type == BEZEL:
                if zone.scancode == TOP_BEZEL_ID:
                    self.top_bezel_id = zone.id
                elif zone.scancode == BOTTOM_BEZEL_ID:
                    self.bottom_bezel_id = zone.id

        self._set_dirty(False)
        self.layout_saved.emit(saved_layout.name, saved_layout.id)
        self.update_title(
            f"SAVED COPY: {saved_layout.name}"
            if as_copy
            else f"SAVED: {saved_layout.name}"
        )
        return True

    def _discard_special_entry(self, scancode: int) -> Optional[int]:
        """Removes the single existing wheel/sprint entry (for replacement); returns its uid."""
        for k, v in list(self.shapes.items()):
            if v["scancode"] == scancode:
                self._discard_artists(k)
                return k
        return None

    def _reject_entry(self, title: str, msg: str, strict: bool) -> None:
        """User-facing error when creating a shape; silent (log only) while loading saved zones."""
        if strict:
            self.send_message.emit(title, msg)
            print(msg)
        else:
            logger.warning("%s: %s", title, msg)

    def _save_entry(
        self,
        key_name: str,
        scancode: int,
        cx: int,
        cy: int,
        r: Optional[int],
        bb: Optional[tuple[tuple[float, float], tuple[float, float]]],
        pointer: bool,
        priority: int,
        pipeline_json: str,
        ignore_app_settings: bool,
        strict: bool = True,
    ):
        uid, inc_count = self.count, True
        replace_scancode: Optional[int] = None

        # ---- 1. Validate everything first; mutate nothing until it all passes ----
        if scancode == MOUSE_WHEEL_SIMULATOR_CODE:
            if self.mode == RECTANGLE or r is None:
                msg = "Mouse wheel cannot be a rectangle."
                self._reject_entry("Mouse Wheel Error", msg, strict)
                return False, uid

            if (
                strict
                and self.saved_sprint_distance
                and self.sprint_artist_id in self.shapes
            ):
                sp = self.shapes[self.sprint_artist_id]
                if self._euclidean_distance(sp["cx"], sp["cy"], cx, cy) <= r:
                    msg = "The existing sprint would end up inside the new mouse wheel. Delete or move the sprint first."
                    self._reject_entry("Mouse Wheel Error", msg, strict)
                    return False, uid

            if self.saved_mouse_wheel:
                replace_scancode = MOUSE_WHEEL_SIMULATOR_CODE

        elif scancode == SPRINT_DISTANCE_CODE:
            if self.mode == RECTANGLE:
                msg = "Sprint cannot be a rectangle."
                self._reject_entry("Sprint Error", msg, strict)
                return False, uid

            if not self.saved_mouse_wheel:
                msg = "No mouse wheel found, create one first before attempting to create sprint."
                self._reject_entry("Sprint Error", msg, strict)
                return False, uid

            actual_dist = self._euclidean_distance(
                cx, cy, self.mouse_wheel_cx, self.mouse_wheel_cy
            )
            if strict and actual_dist <= self.mouse_wheel_radius:
                msg = "Sprint is too close to mouse wheel."
                self._reject_entry("Sprint Error", msg, strict)
                return False, uid

            if self.saved_sprint_distance:
                replace_scancode = SPRINT_DISTANCE_CODE

        # ---- 2. Commit ----
        if replace_scancode is not None:
            old_uid = self._discard_special_entry(replace_scancode)
            if old_uid is not None:
                uid, inc_count = old_uid, False

        if scancode == MOUSE_WHEEL_SIMULATOR_CODE:
            self.mouse_wheel_radius = r  # type: ignore[assignment]
            self.mouse_wheel_cx = cx
            self.mouse_wheel_cy = cy
            self.saved_mouse_wheel = True

            # A surviving sprint is now measured against the NEW wheel position.
            if self.saved_sprint_distance and self.sprint_artist_id in self.shapes:
                sp = self.shapes[self.sprint_artist_id]
                self.sprint_distance = self._euclidean_distance(
                    sp["cx"], sp["cy"], cx, cy
                )

        elif scancode == SPRINT_DISTANCE_CODE:
            self.sprint_distance = self._euclidean_distance(
                cx, cy, self.mouse_wheel_cx, self.mouse_wheel_cy
            )
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
            self.count = max(self.count, uid) + 1
        return True, uid

    def _print_data(self):
        if self.state is not PlotterState.IDLE:
            return

        if not self.shapes:
            self.update_title("List empty. Nothing to print.")
            return

        bound = sorted(
            {
                (
                    "MOUSE WHEEL"
                    if int(v["scancode"]) == MOUSE_WHEEL_SIMULATOR_CODE
                    else (
                        "SPRINT DISTANCE"
                        if int(v["scancode"]) == SPRINT_DISTANCE_CODE
                        else str(v["key_name"]).upper()
                    )
                )
                for v in self.shapes.values()
            }
        )
        print("\nCurrently bound: " + ", ".join(bound))
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
            self.send_message.emit("Shape Error", "The three points are collinear.")
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
        # Same center rule as every later edit (bbox center, not the mean of the 4 clicks).
        return calculate_raw_rectangle(((min(xs), min(ys)), (max(xs), max(ys))))

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
            return clamp(cx, x_min, x_max), clamp(cy, y_min, y_max)
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
