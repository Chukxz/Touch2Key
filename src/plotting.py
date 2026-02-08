from __future__ import annotations

import matplotlib.pyplot as plt
from PIL import Image
import tomlkit
import math
import os
import tkinter as tk
from tkinter import filedialog
import json
import datetime
from pathlib import Path
import time
from mapper_module.utils import (
    CIRCLE, RECT, SCANCODES, DEF_DPI, IMAGES_FOLDER, JSONS_FOLDER,
    TOML_PATH, MOUSE_WHEEL_CODE, SPRINT_DISTANCE_CODE, select_image_file,
    set_dpi_awareness, rotate_resolution, update_toml, get_vibrant_random_color
)

# Constants
IDLE = "IDLE"
COLLECTING = "COLLECTING"
WAITING_FOR_KEY = "WAITING_FOR_KEY"
DELETING = "DELETING"
CONFIRM_DELETE_ALL = "CONFIRM_DELETE_ALL"
CONFIRM_EXIT = "CONFIRM_EXIT"
NAMING = "NAMING"
HELP_STR = "F1(Help)"
DEF_STR = \
    "MODE: IDLE | F2(Delete All)\n\
    F3(Load JSON) | F4(Toggle Shapes Visibility) | F5(Change Image)\n\
    F6(Circle) | F7(Rect) | F8(Cancel) | F9(List) | F10(Save)\n\
    F11(Sprint Threshold) | F12(Mouse Wheel) | Delete(Delete) | Esc(Exit)\n\
    Double click to iterate between artists under the mouse"

SPECIAL_MAP = {
    "escape": "ESC", "enter": "ENTER", "backspace": "BACKSPACE", "tab": "TAB",
    "f1": "F1", "f2": "F2", "f3": "F3", "f4": "F4", "f5": "F5", "f6": "F6", 
    "f7": "F7", "f8": "F8", "f9": "F9", "f10": "F10", "f11": "F11", "f12": "F12",
    "=": "EQUAL", "-": "MINUS",
    "[": "LEFT_BRACKET", "]": "RIGHT_BRACKET",
    ";": "SEMICOLON", "'": "APOSTROPHE", "`": "GRAVE", "\\": "BACKSLASH",
    ",": "COMMA", ".": "DOT", "/": "SLASH",
    "shift": "LSHIFT", "alt": "LALT", "control": "LCTRL", " ": "SPACE",
    "caps_lock": "CAPSLOCK", "num_lock": "NUMLOCK", "scroll_lock": "SCROLLLOCK",
    "*": "NUM_MULTIPLY",
    "up": "E0_UP", "left": "E0_LEFT", "right": "E0_RIGHT", "down": "E0_DOWN",
    "insert": "E0_INSERT", "delete": "E0_DELETE",
}

class Draggable:
    def __init__(self, entry_id:int, is_shape:bool, plotter_ref: Plotter):
        self.entry_id = entry_id
        self.plotter = plotter_ref
        self.min_move_distance = 3
        if is_shape:
            self.artist_id = "shape_" + str(entry_id)
        else:
            self.artist_id = "label_" + str(entry_id)
            
    def populate_artist_list(self):
            self.plotter.artists_ids.append(self.artist_id)

    def indicate_current_artist_id(self):
        if self.plotter.current_artist_id is not None:
            if self.plotter.current_artist_id.startswith('label_'):
                for artist in self.plotter.label_drag_managers.values():
                    if artist.artist_id == self.plotter.current_artist_id:
                        label_bbox = artist.label_artist.get_bbox_patch()
                        if label_bbox:
                            label_bbox.set_edgecolor((0.85, 0.88, 0.92))
                            label_bbox.set_linewidth(2)
                        break
            
            elif self.plotter.current_artist_id.startswith('shape_'):
                for artist in self.plotter.shape_drag_managers.values():
                    if artist.artist_id == self.plotter.current_artist_id:
                        artist.shape_artist.set_edgecolor((0.85, 0.88, 0.92))
                        artist.shape_artist.set_linewidth(3)
                        break
    
    def select_current_artist_id(self):
        current_artist_id = None        
        if not self.plotter.artists_ids:
            self.plotter.iter_count = 0
            return None
                
        if self.plotter.last_artist_id is None:
            self.plotter.iter_count = 0
            return self.plotter.artists_ids[0]
        
        if self.plotter.last_artist_id in self.plotter.artists_ids:
            if self.plotter.iter_count >= 2:
                l = len(self.plotter.artists_ids)
                i = self.plotter.artists_ids.index(self.plotter.last_artist_id)
                n = (i + 1) % l
                self.plotter.iter_count = 0
                current_artist_id = self.plotter.artists_ids[n]
            else:
                current_artist_id = self.plotter.last_artist_id
                
        else:
            self.plotter.iter_count = 0
            current_artist_id = self.plotter.artists_ids[0]
        
        return current_artist_id

    
    def clean_up_current_artist_id(self):        
        self.indicate_current_artist_id()

        if self.plotter.current_move_distance <= self.min_move_distance:
            self.plotter.iter_count += 1
        else:
            self.plotter.iter_count = 0

        self.plotter.drawn = False
        self.plotter.last_artist_id = self.plotter.current_artist_id
        self.plotter.current_artist_id = None
        self.plotter.current_move_distance = 0.0
        self.plotter.artists_ids = []

class DraggableLabel(Draggable):
    def __init__(self, entry_id:int, plotter_ref:Plotter):
        super().__init__(entry_id, False, plotter_ref)        
        self.label_artist = self.plotter.labels_artists[entry_id]
        self.shape_artist = self.plotter.shapes_artists[entry_id]
        self.canvas = self.label_artist.figure.canvas
        self.press = None
        self.drag_bg = None
        
        # Store IDs so we can kill them later
        self.cids = [
            self.canvas.mpl_connect('button_press_event', self.on_press),
            self.canvas.mpl_connect('motion_notify_event', self.on_motion),
            self.canvas.mpl_connect('button_release_event', self.on_release),
        ]

    def on_press(self, event):
        if event.inaxes != self.shape_artist.axes: return
        
        contains, _ = self.label_artist.contains(event)
        if not contains: return
        
        x0, y0 = self.label_artist.get_position()
        self.press = x0, y0, event.xdata, event.ydata, event.x, event.y

        label_bbox = self.label_artist.get_bbox_patch()
        if label_bbox:
            label_bbox.set_edgecolor('black')
        
        if self.label_artist.get_visible():
            self.shape_artist.set_visible(True)
            self.populate_artist_list()
        
        self.canvas.draw_idle()
            
    def on_motion(self, event):
        if self.press is None or event.inaxes != self.label_artist.axes:
            return
        
        if self.plotter.current_artist_id is None and self.plotter.iter_count == 0:
            self.plotter.current_artist_id = self.select_current_artist_id()
            self.indicate_current_artist_id()
            
        if not self.plotter.current_artist_id == self.artist_id:
            return
        
        if not self.plotter.drawn:
            # Prepare Background for Blitting
            label_bbox = self.label_artist.get_bbox_patch()
            if label_bbox:
                label_bbox.set_edgecolor((0.7, 0.7, 0.7, 0.8))
                label_bbox.set_linewidth(3)
            self.label_artist.set_visible(False)
            
            self.shape_artist.set_edgecolor((0.7, 0.7, 0.7, 0.8))
            self.shape_artist.set_linewidth(3)
            
            self.canvas.draw()
            self.drag_bg = self.canvas.copy_from_bbox(self.label_artist.axes.bbox)
            self.label_artist.set_visible(True)
            self.plotter.drawn = True
        
        x0, y0, xdata_press, ydata_press, xpx_press, ypx_press = self.press
        dx = event.xdata - xdata_press
        dy = event.ydata - ydata_press   
        dx_press = event.x - xpx_press
        dy_press = event.y - ypx_press
        dist_px = ((dx_press**2) + (dy_press**2))**0.5
        self.plotter.current_move_distance = dist_px

        # Blitting Loop
        self.canvas.restore_region(self.drag_bg)
        self.label_artist.set_position((x0 + dx, y0 + dy))
        self.label_artist.axes.draw_artist(self.label_artist)
        self.canvas.blit(self.label_artist.axes.bbox)

    def on_release(self, event):
        self.press = None
        self.drag_bg = None

        label_bbox = self.label_artist.get_bbox_patch()
        if label_bbox:
            label_bbox.set_edgecolor('black')
            label_bbox.set_linewidth(1.5)
        
        if self.plotter.current_artist_id is None and self.plotter.artists_ids:
            self.plotter.current_artist_id = self.select_current_artist_id()
            self.indicate_current_artist_id()
        
        if self.artist_id == self.plotter.current_artist_id:
            if self.plotter.drawn:
                # Reset blitted background                    
                self.shape_artist.set_edgecolor((0.3, 0.3, 0.3, 0.8))
                self.shape_artist.set_linewidth(2)
            
            self.clean_up_current_artist_id()
            self.label_artist.remove()
            self.plotter.ax.add_artist(self.label_artist)
            
        self.canvas.draw_idle()

    def disconnect(self):
        for cid in self.cids:
            self.canvas.mpl_disconnect(cid)
        print(f"[System] Event listeners for {self.label_artist} disconnected.")


class DraggableShape(Draggable):
    def __init__(self, entry_id:int, plotter_ref:Plotter, shape_type:str):
        super().__init__(entry_id, True, plotter_ref)
        self.shape_type = shape_type
        self.label_artist = self.plotter.labels_artists[entry_id]
        self.shape_artist = self.plotter.shapes_artists[entry_id]
        self.canvas = self.shape_artist.figure.canvas
        self.press = None
        self.drag_bg = None
        self.radial_tolerance = 5 # Pixel coordinates
        self.edge_tolerance = 5 # Pixel coordinates
        self.vertex_tolerance = 10 # Pixel coordinates
        self.min_rect_dist = 50 # Data coordinates
        self.min_circ_dist = 30 # Data coordinates
        self.shape_mode = None
        self.spec_max_ratio = 0.3 # max ratio for joystick and sprint distance relative to image size
        
        if self.shape_type == CIRCLE:
            r = self.shape_artist.get_radius()
            new_r = max(r, self.min_circ_dist)
            self.shape_artist.set_radius(new_r)
            self.plotter.shapes[self.entry_id]['r'] = new_r            
            
        elif self.shape_type == RECT:
            x, y = self.shape_artist.get_xy()
            w = self.shape_artist.get_width()
            h = self.shape_artist.get_height()
            self.update_rect_safe(x, y, w, h)
        
        # Store IDs so we can kill them later
        self.cids = [
            self.canvas.mpl_connect('button_press_event', self.on_press),
            self.canvas.mpl_connect('motion_notify_event', self.on_motion),
            self.canvas.mpl_connect('button_release_event', self.on_release),
        ]
        
    def on_press(self, event):        
        if event.inaxes != self.shape_artist.axes: return
            
        contains, _ = self.shape_artist.contains(event,)
        if not contains: return
        
        if self.shape_type == CIRCLE:
            cx, cy = self.shape_artist.get_center()
            self.shape_mode = self.get_circumference(event, cx, cy)
            self.press = cx, cy, event.xdata, event.ydata, event.x, event.y
        elif self.shape_type == RECT:
            x, y = self.shape_artist.get_xy()
            self.shape_mode = self.get_corner_under_mouse(event)
            if self.shape_mode is None:
                self.shape_mode = self.get_edge_under_mouse(event)
            self.press = x, y, event.xdata, event.ydata, event.x, event.y
        
        self.shape_artist.set_edgecolor((0.3, 0.3, 0.3, 0.8))
        
        if self.shape_artist.get_visible():
            self.label_artist.set_visible(True)
            self.populate_artist_list()
            
        self.canvas.draw_idle()
        
    def on_motion(self, event):
        if self.press is None or event.inaxes != self.shape_artist.axes:
            return

        if self.plotter.current_artist_id is None:
            self.plotter.current_artist_id = self.select_current_artist_id()
            self.indicate_current_artist_id()
            
        if not self.plotter.current_artist_id == self.artist_id:
            return
                
        if not self.plotter.drawn:
            # Prepare Background for Blitting
            self.shape_artist.set_edgecolor((0.7, 0.7, 0.7, 0.8))
            self.shape_artist.set_linewidth(3)
            self.shape_artist.set_visible(False)
            
            label_bbox = self.label_artist.get_bbox_patch()
            if label_bbox:
                label_bbox.set_edgecolor((0.7, 0.7, 0.7, 0.8))
                label_bbox.set_linewidth(3)
                
            self.canvas.draw() 
            self.drag_bg = self.canvas.copy_from_bbox(self.shape_artist.axes.bbox)
            self.shape_artist.set_visible(True)
            self.plotter.drawn = True
        
        _, _, _, _, xpx_press, ypx_press = self.press
        dx_press = event.x - xpx_press
        dy_press = event.y - ypx_press
        dist_px = ((dx_press**2) + (dy_press**2))**0.5
        self.plotter.current_move_distance = dist_px

        # Blitting Loop
        self.canvas.restore_region(self.drag_bg)
        if self.shape_type == CIRCLE:
            self.circle_transform(event)
        elif self.shape_type == RECT:
            self.rect_transform(event)        
        self.shape_artist.axes.draw_artist(self.shape_artist)
        self.canvas.blit(self.shape_artist.axes.bbox)
                    
    def get_display_point(self, xdata, ydata):
        """
        Convert data pints to pixel coordinates
        """
        return self.shape_artist.axes.transData.transform((xdata, ydata))
    
    def circle_transform(self, event):
        if self.press is None:
            return
        xdata = event.xdata
        ydata = event.ydata
        
        old_cx, old_cy = self.shape_artist.get_center()
        old_r = self.shape_artist.get_radius()
        new_cx, new_cy = old_cx, old_cy
        current_shape = self.plotter.shapes[self.entry_id]

        if self.shape_mode == 'resize':
            self.update_radius(xdata, ydata)

        elif self.shape_mode == 'drag':
            x0, y0, xdata_press, ydata_press, _, _ = self.press
            dx = xdata - xdata_press
            dy = ydata - ydata_press
            new_cx = int(round(x0 + dx))
            new_cy = int(round(y0 + dy))
            self.shape_artist.set_center((new_cx, new_cy))
            current_shape['cx'] = new_cx
            current_shape['cy'] = new_cy
                        
        if self.plotter.saved_mouse_wheel and current_shape['key_name'] == MOUSE_WHEEL_CODE:
            self.plotter.mouse_wheel_cx = new_cx
            self.plotter.mouse_wheel_cy = new_cy
            self.plotter.mouse_wheel_radius = current_shape['r']
            
            if self.plotter.saved_sprint_distance and self.plotter.sprint_artist_id is not None:
                sprint_artist = self.plotter.shape_drag_managers[self.plotter.sprint_artist_id]
                sprint_shape = self.plotter.shapes[self.plotter.sprint_artist_id]
                cx, cy = sprint_artist.shape_artist.get_center()
                actual_dist = self.plotter.euclidean_distance(cx, cy, new_cx, new_cy)
                
                # STRICT CHECK: Ensure Sprint is actually outside the Joystick
                if actual_dist <= self.plotter.mouse_wheel_radius:                    
                    r = self.plotter.mouse_wheel_radius
                    screen_rect = ((0, 0), (self.plotter.width, self.plotter.height))
                    sp_x, sp_y = self.plotter.constrain_point_to_rect_radial(new_cx, new_cy-r-1, new_cx, new_cy, screen_rect)
                    sp_x, sp_y = int(round(sp_x)), int(round(sp_y))
                    
                    sprint_artist.shape_artist.set_center((sp_x, sp_y))
                    sprint_shape['cx'] = sp_x
                    sprint_shape['cy'] = sp_y

                    sp_actual_dist = self.plotter.euclidean_distance(sp_x, sp_y, new_cx, new_cy)
                    self.plotter.sprint_distance = sp_actual_dist
                else:
                    self.plotter.sprint_distance = actual_dist
            
        if self.plotter.saved_sprint_distance and current_shape['key_name'] == SPRINT_DISTANCE_CODE:
            actual_dist = self.plotter.euclidean_distance(new_cx, new_cy, self.plotter.mouse_wheel_cx, self.plotter.mouse_wheel_cy)
            
            # STRICT CHECK: Ensure Sprint is actually outside the Joystick
            if actual_dist <= self.plotter.mouse_wheel_radius:                
                self.shape_artist.set_center((old_cx, old_cy))
                self.shape_artist.set_radius(old_r)
                current_shape['cx'] = old_cx
                current_shape['cy'] = old_cy
                current_shape['r'] = old_r             
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
        if self.shape_mode == 'drag':
            x0, y0, xdata_press, ydata_press, _, _ = self.press
            dx = xdata - xdata_press
            dy = ydata - ydata_press
            new_x = int(round(x0 + dx))
            new_y = int(round(y0 + dy))
            w = self.shape_artist.get_width()
            h = self.shape_artist.get_height()
            self.update_rect_safe(new_x, new_y, w, h)

    def get_circumference(self, event, cx, cy):
        # Get circle data
        r = self.shape_artist.get_radius()
        # Convert center to pixels
        cx_px, cy_px = self.shape_artist.axes.transData.transform((cx, cy))
        # Calculate radius in pixels
        rim_x_px, _ = self.shape_artist.axes.transData.transform((cx + r, cy))
        r_px = abs(rim_x_px - cx_px)
        # Calculate distance from mouse to center
        dist_px = ((event.x - cx_px)**2 + (event.y - cy_px)**2)**0.5
        # Check if distance is within tolerance of radius, if not check if it is inside the circle
        diff_px = abs(dist_px - r_px)
        if diff_px <= self.radial_tolerance:
            return 'resize'
        if dist_px <= r_px:
            return 'drag'
        return None

    def update_radius(self, xdata, ydata):
        # Get the fixed center
        cx, cy = self.shape_artist.get_center()
        # Calculate distance from center to mouse
        new_r = int(round(((xdata - cx)**2 + (ydata - cy)**2)**0.5))
        current_shape = self.plotter.shapes[self.entry_id]
        new_sp_r = None
        
        if self.plotter.saved_mouse_wheel and current_shape['key_name'] == MOUSE_WHEEL_CODE:
            new_r = min(new_r, int(round((self.spec_max_ratio * ((self.plotter.width + self.plotter.height) / 2)))))
            
            if self.plotter.saved_sprint_distance and self.plotter.sprint_artist_id is not None:
                sprint_artist = self.plotter.shape_drag_managers[self.plotter.sprint_artist_id]
                sp_r = sprint_artist.shape_artist.get_radius()
                if new_r < sp_r:
                    new_sp_r = new_r
                
        if self.plotter.saved_sprint_distance and current_shape['key_name'] == SPRINT_DISTANCE_CODE:
            new_r = min(new_r, self.plotter.mouse_wheel_radius)

        if new_r >= self.min_circ_dist:
            self.shape_artist.set_radius(new_r)
            current_shape['r'] = new_r
            
            if new_sp_r is not None:
                sprint_artist = self.plotter.shape_drag_managers[self.plotter.sprint_artist_id]
                sprint_shape = self.plotter.shapes[self.plotter.sprint_artist_id]
                sprint_artist.shape_artist.set_radius(new_sp_r)
                sprint_shape['r'] = new_sp_r
    
    def get_corner_under_mouse(self, event):
        x, y = self.shape_artist.get_xy()
        w, h = self.shape_artist.get_width(), self.shape_artist.get_height()
        
        # VISUAL CORNERS (Adjusted for imshow Y-inversion)
        # (x, y) is visually TOP-LEFT
        # (x, y+h) is visually BOTTOM-LEFT
        corners = {
            'top_left':     (x, y),
            'top_right':    (x + w, y),
            'bottom_left':  (x, y + h),
            'bottom_right': (x + w, y + h)
        }

        # Check pixel distance for each corner
        for name, (cx, cy) in corners.items():
            cx_px, cy_px = self.shape_artist.axes.transData.transform((cx, cy))
            dist_px = ((event.x - cx_px)**2 + (event.y - cy_px)**2)**0.5
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
            return 'left'
        if abs(mx - bbox.x1) <= self.edge_tolerance and is_within_vertical:
            return 'right'
        
        # Visual TOP edge is mathematically the 'min y' (y0 in data, but y1 in pixels typically)
        # Let's trust the pixel bbox: y1 is usually visually Top in MPL GUI, y0 is Bottom
        if abs(my - bbox.y1) <= self.edge_tolerance and is_within_horizontal:
            return 'top'
        if abs(my - bbox.y0) <= self.edge_tolerance and is_within_horizontal:
            return 'bottom'

        if is_within_horizontal and is_within_vertical:
            return 'drag'
        return None
    
    def update_corner(self, corner, xdata, ydata):
        if corner is None:
            return False

        xdata, ydata = int(round(xdata)), int(round(ydata))

        # Get current RAW bounds (un-normalized)
        x, y = self.shape_artist.get_xy()
        w = self.shape_artist.get_width()
        h = self.shape_artist.get_height()

        # Identify fixed anchor points based on the corner being dragged
        # Note: We use the VISUAL names we defined in get_corner_under_mouse
        if corner == 'bottom_right':
            # Fixed Anchor is Top-Left (x, y)
            new_w = xdata - x
            new_h = ydata - y
            self.update_rect_safe(x, y, new_w, new_h)
            return True

        if corner == 'top_left':
            # Fixed Anchor is Bottom-Right (x+w, y+h)
            # New x is mouse_x, New y is mouse_y
            # Width changes by (old_right - mouse_x)
            new_w = (x + w) - xdata
            new_h = (y + h) - ydata
            self.update_rect_safe(xdata, ydata, new_w, new_h)
            return True

        if corner == 'top_right':
            # Fixed Anchor is Bottom-Left (x, y+h)
            # x is unchanged (visually left), y becomes mouse_y (visually top)
            new_w = xdata - x
            new_h = (y + h) - ydata
            self.update_rect_safe(x, ydata, new_w, new_h)
            return True

        if corner == 'bottom_left':
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
        x, y = self.shape_artist.get_xy()
        w = self.shape_artist.get_width()
        h = self.shape_artist.get_height()

        # Determine limits based on the visual edge being dragged
        #    We calculate the new proposed dimensions, then Normalize.

        if edge == 'right':
            # Anchor: Left Edge (x) stays fixed.
            # New Width = Mouse X - Left Edge
            new_w = xdata - x
            # Height and Y unchanged
            self.update_rect_safe(x, y, new_w, h)
            return True

        if edge == 'left':
            # Anchor: Right Edge (x + w) stays fixed.
            # New Width = Right Edge - Mouse X
            # New X = Mouse X
            right_edge = x + w
            new_w = right_edge - xdata
            # Height and Y unchanged
            self.update_rect_safe(xdata, y, new_w, h)
            return True

        if edge == 'bottom':
            # Visual Bottom means mathematically HIGHER Y in typical plots, 
            # BUT in imshow (y=0 at top), Bottom has a HIGHER pixel value.
            
            # Anchor: Top Edge (y) stays fixed.
            # New Height = Mouse Y - Top Edge
            new_h = ydata - y
            # Width and X unchanged
            self.update_rect_safe(x, y, w, new_h)
            return True

        if edge == 'top':
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
                
        if w < 0:
            return
        
        if h < 0:
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
                
        # Recalculate based on new visual shape
        raw_bb = (x, y), (x + w, y + h)
        cx, cy, _, bb = self.plotter.calculate_raw_rect(raw_bb)
        self.plotter.shapes[self.entry_id]['cx'] = cx
        self.plotter.shapes[self.entry_id]['cy'] = cy
        self.plotter.shapes[self.entry_id]['bb'] = bb

    def on_release(self, event):        
        self.press = None
        self.drag_bg = None
        self.shape_mode = None

        self.shape_artist.set_edgecolor((0.3, 0.3, 0.3, 0.8))
        self.shape_artist.set_linewidth(2)
        
        if self.plotter.current_artist_id is None and self.plotter.artists_ids:
            self.plotter.current_artist_id = self.select_current_artist_id()
            self.indicate_current_artist_id()

        if self.artist_id == self.plotter.current_artist_id:
            if self.plotter.drawn:
                # Reset blitted background
                label_bbox = self.label_artist.get_bbox_patch()
                if label_bbox:
                    label_bbox.set_edgecolor('black')
                    label_bbox.set_linewidth(1.5)
            
            self.clean_up_current_artist_id()
            self.shape_artist.remove()
            self.plotter.ax.add_patch(self.shape_artist)
            
        self.canvas.draw_idle()
                
    def disconnect(self):
        for cid in self.cids:
            self.canvas.mpl_disconnect(cid)
        print(f"[System] Event listeners for {self.shape_artist} disconnected.")

        
class Plotter:
    def __init__(self, image_path=None):
        # DPI Awareness MUST be first to ensure coordinates match the screen
        set_dpi_awareness()

        # SMART PATH DETECTION
        base_images_folder = Path(IMAGES_FOLDER)
        toml_file = Path(TOML_PATH)
        json_file_str = None

        if image_path is None:
            if toml_file.exists():
                try:
                    with open(toml_file, "r", encoding="utf-8") as f:
                        doc = tomlkit.load(f)
                    toml_img_str = doc.get("system", {}).get("hud_image_path", "")
                    json_file_str = doc.get("system", {}).get("json_path", "")
                    if toml_img_str:
                        potential_path = Path(toml_img_str)
                        if potential_path.exists():
                            image_path = potential_path
                            print(f"[System] Auto-loading last HUD: {image_path.as_posix()}")
                except Exception:
                    pass

            if image_path is None:
                base_images_folder.mkdir(parents=True, exist_ok=True)
                print(f"[System] No active HUD found in config. Opening selector...")
                selected = select_image_file(str(base_images_folder))
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
            if key.startswith('keymap.'):
                plt.rcParams[key] = []
        
        # Initiate Parameters
        self.fig, self.ax = plt.subplots()
        
        self.points = []          
        self.point_artists = []
        self.mode = None          
        self.state = IDLE         
        self.input_buffer = ""
        self.shapes_artists: dict[int, plt.Circle | plt.Rectangle] = {}
        self.labels_artists: dict[int, plt.Text] = {}
        self.label_drag_managers: dict[int, DraggableLabel] = {}
        self.shape_drag_managers: dict[int, DraggableShape] = {}
                       
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

        if json_file_str:
            json_path = Path(json_file_str)
            if json_path.exists():
                print(f"[System] Auto-loading last JSON: {json_path.as_posix()}")
                self.load_json_from_path(json_path)
                
        plt.show()
        

    # Visual & State Management
    def load_image(self):
        try:
            img = Image.open(self.image_path)
        except Exception as e:
            print(f"Error loading image: {e}")
            return None
        print(f"Image:{self.image_path.as_posix()} loaded successfully.")
        return img
        
    def update_image_params(self, img):
        self.width, self.height = img.size      
        try:
            # self.image_path.stem gets the filename without extension
            parts = self.image_path.stem.split("_")
            rotation_part = parts[-1] 
            if rotation_part.startswith("r"):
                rot = int(rotation_part[1:])
                self.width, self.height = rotate_resolution(self.width, self.height, rot)
        except Exception:
            pass
        self.dpi = int(round(img.info.get("dpi", DEF_DPI)[0]))

    def init_crosshairs(self):        
        # Create the "Shadow" (Black, thicker)
        self.crosshair_h_bg = self.ax.axhline(0, color='black', linewidth=1.5, alpha=0.8, visible=False, zorder=10, animated=True)
        self.crosshair_v_bg = self.ax.axvline(0, color='black', linewidth=1.5, alpha=0.8, visible=False, zorder=10, animated=True)
        
        # Create the "Core" (White, thinner)
        self.crosshair_h_fg = self.ax.axhline(0, color='white', linewidth=0.6, alpha=1.0, visible=False, zorder=11, animated=True)
        self.crosshair_v_fg = self.ax.axvline(0, color='white', linewidth=0.6, alpha=1.0, visible=False, zorder=11, animated=True)

    def init_params_helper(self):
        self.shapes = {}
        self.count = 0
        self.artists_points = 0
        self.saved_mouse_wheel = False
        self.saved_sprint_distance = False
        self.sprint_artist_id = None
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
        self.last_artist_id = None
        self.current_artist_id = None
        self.artists_ids = []
        self.drawn = False
        self.current_move_distance = 0.0
        self.iter_count = 0
        
    def update_title(self, text):
        self.ax.set_title(text)
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
        state_str = "VISIBLE" if self.show_overlays else "HIDDEN"
        self.update_title(f"OVERLAYS: {state_str} | {DEF_STR}")
        self.bg_cache = self.fig.canvas.copy_from_bbox(self.ax.bbox)
        
    def start_mode(self, mode, num_points):
        self.reset_state() 
        self.mode = mode
        self.artists_points = num_points
        self.state = COLLECTING
        self.update_title(f"MODE: {mode}. Click {num_points} points on the image (F8 to Cancel).")
    
    
    def load_json(self):
        # Initialize Tkinter and hide the root window
        root = tk.Tk()
        root.withdraw()
        root.attributes('-topmost', True) 

        os.makedirs(JSONS_FOLDER, exist_ok=True)
        
        # Open File Dialog
        file_path = filedialog.askopenfilename(
            initialdir=JSONS_FOLDER,
            title="Select JSON Mapping Profile",
            filetypes=(("JSON files", "*.json"), ("All files", "*.*"))
        )

        if not file_path:
            print("[!] Selection cancelled.")
            root.destroy()
            return

        root.destroy()
        
        self.load_json_from_path(file_path)
    
    def load_json_from_path(self, file_path):  
        if not os.path.exists(file_path):
            print(f"Error: File '{file_path}' not found.")
            return

        with open(file_path, mode='r', encoding='utf-8') as f:
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
        except:
            print(f"Error loading json file")
            return
        
        scale_x = self.width / screen_width
        scale_y = self.height / screen_height
        item_id = 0
        json_shapes:dict[int, dict] = {}

        for item in content:
            scancode = item.get("scancode")
            if scancode is None: 
                continue
                            
            zone_type = item.get("type", '')
            name = item.get('name', '')
                            
            try:
                cx = float(item['cx'])
                cy = float(item['cy'])
                val1 = float(item['val1'])
                val2 = float(item['val2'])
                val3 = float(item['val3'])
                val4 = float(item['val4'])

            except (ValueError, KeyError) as e:
                print(f"Skipping invalid item: {scancode} with name: {name}. Error: {e}")
                continue
            
            json_shape = {}
            key_name = self.get_event_key(scancode)
            _, interception_key = self.get_interception_code(key_name)
            json_shape['key_name'] = key_name
            json_shape['m_code'] = scancode
            json_shape['type'] = zone_type
            json_shape['cx'] = int(round(cx * scale_x))
            json_shape['cy'] = int(round(cy * scale_y))
            json_shape['interception_key'] = interception_key if interception_key is not None else ''
            
            if zone_type == CIRCLE:
                scale_r = (scale_x + scale_y) / 2
                json_shape['r'] = int(round(val1 * scale_r))
                json_shape['mode'] = CIRCLE

            elif zone_type == RECT:
                new_x1 = int(round(val1 * scale_x))
                new_y1 = int(round(val2 * scale_y))
                new_x2 = int(round(val3 * scale_x))
                new_y2 = int(round(val4 * scale_y))
                json_shape['bb'] = ((new_x1, new_y1), (new_x2, new_y2))
                json_shape['mode'] = RECT

            item_id += 1
            json_shapes[item_id] = json_shape

        if item_id > 0:
            w, h, dpi = self.width, self.height, self.dpi
            self.init_params_helper()
            self.width, self.height, self.dpi = w, h, dpi
            self.reset_state()
            print("Cleared previous shapes and artists, figure reset.")
            
            for shape in json_shapes.values():
                cx = shape['cx']
                cy = shape['cy']
                r = shape.get('r', None)
                bb = shape.get('bb', None)
                key_name = shape['key_name']
                interception_key = shape['interception_key']
                hex_code = shape['m_code']
                self.mode = shape['mode']
                                
                self.finalize_shape(cx, cy, r, bb, key_name, interception_key, hex_code)
            self.reset_state()
            print(f"Loaded JSON file: {Path(file_path).as_posix()}")

    def change_image(self):
        image_path = select_image_file(IMAGES_FOLDER)
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
            self.clear_visuals()
            self.ax.clear()
            self.ax.imshow(img)

            self.init_crosshairs()     
            self.reset_state()
            print("Cleared previous shapes and artists, figure reset.")
            print(f"Swapped HUD to: {self.image_path.as_posix()}")

    def toggle_visibility(self):
        self.show_overlays = not self.show_overlays
        state_str = "VISIBLE" if self.show_overlays else "HIDDEN"
        print(f"[*] Overlays are now {state_str}")
        
        for artist in self.shapes_artists.values():
            artist.set_visible(self.show_overlays)
        for artist in self.labels_artists.values():
            artist.set_visible(self.show_overlays)
        
        self.fig.canvas.draw()
        self.update_title(f"OVERLAYS: {state_str} | {DEF_STR}")


    def label(self, center_x, center_y, label, fc):
        # Get the height of the figure in inches and convert to points
        fig_height_pts = self.fig.get_size_inches()[1] * 72
        scaled_font = max(7, int(round(fig_height_pts * 0.03))) 

        return plt.Text(
            center_x, center_y, 
            label, 
            color='white',
            fontsize=scaled_font,
            fontweight='bold',
            ha='center',
            va='center',
            # This zorder keeps the label above the shape
            zorder=12, 
            bbox=dict(
                fc=fc,
                ec='black',
                lw=1.5,
                boxstyle='round,pad=0.3'
            )
        )

    # Event Handlers
    def on_mouse_move(self, event):
        if self.state == COLLECTING and event.inaxes == self.ax:
            # Round to integer for the "Snap to Pixel" feel
            x, y = int(round(event.xdata)), int(round(event.ydata))

            # Capture background if we don't have it yet
            # Note: We do this only when the mouse is actually inside to save memory
            if self.bg_cache is None:
                self.bg_cache = self.fig.canvas.copy_from_bbox(self.ax.bbox)

            # Restore the clean background (removes the crosshair from the previous frame)
            self.fig.canvas.restore_region(self.bg_cache)

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
                for line in [self.crosshair_h_bg, self.crosshair_h_fg, self.crosshair_v_bg, self.crosshair_v_fg]:
                    line.set_visible(False)
                self.fig.canvas.draw_idle()

    def on_click(self, event):
        # Handle Binding via Mouse Click
        if self.state == WAITING_FOR_KEY:
            # Matplotlib button codes: 1=Left, 2=Middle, 3=Right
            mouse_map = {
                1: "MOUSE_LEFT",
                2: "MOUSE_MIDDLE",
                3: "MOUSE_RIGHT"
            }
            
            button_name = mouse_map.get(event.button)
            
            if button_name:
                print(f"[-] Mouse Click Detected: {button_name}")
                self.calculate_shape(button_name)
            return

        # Handle Drawing Points
        if self.state != COLLECTING:
            return
        
        if event.xdata is None or event.ydata is None:
            return

        self.points.append((int(round(event.xdata)), int(round(event.ydata))))
        
        dot, = self.ax.plot(event.xdata, event.ydata, 'ro')
        self.point_artists.append(dot)
        self.fig.canvas.draw()
        self.bg_cache = None

        remaining = self.artists_points - len(self.points)
        if remaining > 0:
            self.update_title(f"MODE: {self.mode}. {remaining} points remaining (F8 to Cancel).")
        else:
            self.state = WAITING_FOR_KEY
            self.update_title(f"Shape Defined! Press KEY or CLICK MOUSE to bind.")

    def on_key_press(self, event):
        """Main Input Router."""
        
        if self.state == NAMING:
            self.handle_naming_input(event.key)
            return
        
        if self.state == DELETING:
            self.handle_delete_input(event.key)
            return
        
        if self.state == CONFIRM_DELETE_ALL:
            if event.key == 'enter':
                self.delete_all_shapes()
            else:
                self.reset_state()
            return

        if self.state == CONFIRM_EXIT:
            if event.key == 'enter':
                print("[-] Closing application.")
                plt.close()
            else:
                self.reset_state()
            return

        if self.state == COLLECTING:
            if event.key == 'f8':
                print("[-] Action Cancelled.")
                self.reset_state()
            
            else:
                print(f"[!] Blocked: Finish or Cancel (F8) current shape first.")
            return

        if self.state == WAITING_FOR_KEY:
            self.calculate_shape(event.key)
            return
            
        if self.state == IDLE:
            if event.key == 'f1':
                self.reset_state()
            if event.key == 'f2':
                self.state = CONFIRM_DELETE_ALL
                self.update_title("[DELETE ALL?] Press ENTER to Confirm or Any other key to Cancel.")
            if event.key == 'f3':
                self.load_json()
            if event.key == 'f4':
                self.toggle_visibility()
            if event.key == 'f5':
                self.change_image()
            if event.key == 'f6':
                self.start_mode(CIRCLE, 3)
            elif event.key == 'f7':
                self.start_mode(RECT, 4)
            elif event.key == 'f9':
                self.print_data()
            elif event.key == 'f10':
                self.enter_naming_mode()
            elif event.key == 'delete':
                self.enter_delete_mode()
            elif event.key == 'escape':
                self.state = CONFIRM_EXIT
                self.update_title("[EXIT?] Press ENTER to Quit or Any other key to Cancel.")

    # Delete Logic
    def enter_delete_mode(self):
        if not self.shapes:
            print("[!] No shapes to delete.")
            self.update_title(f"List empty. Nothing to delete | {HELP_STR}")
            return

        self.print_data()
        self.state = DELETING
        self.input_buffer = ""
        self.update_title("DELETE MODE: Type ID... (Enter to Confirm | Esc to Cancel)")
        
    def delete_all_shapes(self):
        if not self.shapes:
            print("[!] No shapes to delete.")
            self.update_title(f"List empty. Nothing to delete | {HELP_STR}")
            return
        
        for uid in list(self.shapes.keys()):
            self.delete_entry(uid)
        self.reset_state()
        print("[+] All shapes deleted.")
        
    def handle_delete_input(self, key):
        if key == 'escape':
            self.reset_state()
            return
        
        elif key == 'enter':
            if self.input_buffer:
                try:
                    uid = int(self.input_buffer)
                    
                    if uid in self.shapes:
                        # Cascade deletion check
                        deleted_key_name = self.shapes[uid]['key_name']
                        
                        if deleted_key_name == MOUSE_WHEEL_CODE:
                            # Search for the dependent Sprint point
                            sprint_uid = None
                            for k, v in self.shapes.items():
                                if v['key_name'] == SPRINT_DISTANCE_CODE:
                                    sprint_uid = k
                                    break
                            
                            if sprint_uid is not None:
                                print(f"[System] Auto-deleting Sprint Point (ID {sprint_uid}) because Joystick was deleted.")
                                self.delete_entry(sprint_uid)
                        
                        self.delete_entry(uid)
                        
                        # Check if specific special keys still exist
                        has_wheel = any(v['key_name'] == MOUSE_WHEEL_CODE for v in self.shapes.values())
                        has_sprint = any(v['key_name'] == SPRINT_DISTANCE_CODE for v in self.shapes.values())

                        if not has_wheel:
                            self.saved_mouse_wheel = False
                            self.mouse_wheel_radius = 0.0
                            self.mouse_wheel_cx = 0.0
                            self.mouse_wheel_cy = 0.0
                        
                        if not has_sprint:
                            self.saved_sprint_distance = False
                            self.sprint_artist_id = None
                            self.sprint_distance = 0.0
                        
                        if self.saved_mouse_wheel and any(v['key_name'] == MOUSE_WHEEL_CODE for v in self.shapes.values()) == False:
                            self.saved_mouse_wheel = False
                        if self.saved_sprint_distance and any(v['key_name'] == SPRINT_DISTANCE_CODE for v in self.shapes.values()) == False:
                            self.saved_sprint_distance = False
                            self.sprint_artist_id = None
                            
                        self.update_title(f"Deleted ID {uid}. Returning to IDLE...")
                        self.reset_state()
                    else:
                        print(f"[!] ID {uid} not found.")
                        self.update_title(f"Error: ID {uid} not found. Try again or Press ESC to Cancel.")
                        self.input_buffer = ""
                        
                except ValueError:
                    self.update_title("Error: Invalid Number. Try again or Press ESC to Cancel.")
                    self.input_buffer = ""
            return
        
        elif key.isdigit():
            self.input_buffer += key
            self.update_title(f"DELETE MODE: ID [{self.input_buffer}] (Enter to delete)")
        elif key == 'backspace':
            self.input_buffer = self.input_buffer[:-1]
            self.update_title(f"DELETE MODE: ID [{self.input_buffer}] (Enter to delete)")
        else:
            print("[!] Blocked: Exit Delete Mode (Esc) first.")

    def delete_entry(self, uid):
        """Removes a shape and all its associated resources (artists, labels, listeners)."""
        if uid not in self.shapes:
            return
        
        shape_type = self.shapes[uid]['type']
        interception_key = self.shapes[uid]['key_name']
        hex_code = self.shapes[uid]['m_code']
        
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

        if self.last_artist_id == f"shape_{uid}" or self.last_artist_id == f"label_{uid}":
            self.last_artist_id = None
            
        print(f"[+] Deleted Shape of type: {shape_type} with ID: {uid} and key: '{interception_key}' (hex: {hex_code})")

    # Shape Calculation & Finalization
    def calculate_shape(self, key_name):
        # 'key_name' might be a key string ('a', 'f1') OR a mouse string ('MOUSE_LEFT')
        hex_code, interception_key = self.get_interception_code(key_name)
        
        if hex_code is None:
            print(f"[!] Key '{key_name}' not mapped.")
            return

        cx, cy, r, bb = None, None, None, None
        if self.mode == CIRCLE:
            cx, cy, r, bb = self.calculate_circle()
        elif self.mode == RECT:
            cx, cy, r, bb = self.calculate_rect()
        
        self.finalize_shape(cx, cy, r, bb, key_name, interception_key, hex_code)
        self.reset_state()
    
    
    def finalize_shape(self, cx, cy, r, bb, key_name, interception_key, hex_code):
        if cx is not None:
            saved, entry_id = self.save_entry(interception_key, hex_code, cx, cy, r, bb)
            if saved:
                print(f"[+] Saved ID {self.count-1}: {self.mode} bound to key '{key_name}' with interception key: '{interception_key}'")
                if self.mode == CIRCLE and cx and cy and r:
                    if interception_key == MOUSE_WHEEL_CODE:
                        fc = (0.0, 0.8, 0.8, 0.4) # Bright Cyan/Teal
                    elif interception_key == SPRINT_DISTANCE_CODE:
                        fc = (1.0, 0.2, 0.2, 0.5) # Bright Red
                    else:
                        fc = get_vibrant_random_color(0.4)
                    # Add shape artist
                    shape_artist = plt.Circle((cx, cy), r, fill=True, lw=2, fc=fc, ec=(0.3, 0.3, 0.3, 0.8))
                    shape_artist.set_visible(self.show_overlays)
                    self.ax.add_patch(shape_artist)
                    self.shapes_artists[entry_id] = shape_artist
                    # Add label artist
                    label_artist = self.label(cx, cy, interception_key, fc)
                    label_artist.set_visible(self.show_overlays)
                    self.ax.add_artist(label_artist)
                    self.labels_artists[entry_id] = label_artist
                    # Make the label draggable
                    self.label_drag_managers[entry_id] = DraggableLabel(entry_id, self)
                    # Make the shape draggable
                    self.shape_drag_managers[entry_id] = DraggableShape(entry_id, self, CIRCLE)
                    
                elif self.mode == RECT and cx and cy and bb:
                    fc = get_vibrant_random_color(0.4)
                    (x1, y1), (x2, y2) = bb
                    # Add shape artist
                    shape_artist = plt.Rectangle((x1, y1), x2-x1, y2-y1, fill=True, lw=2, fc=fc, ec=(0.3, 0.3, 0.3, 0.8))
                    shape_artist.set_visible(self.show_overlays)
                    self.ax.add_patch(shape_artist)
                    self.shapes_artists[entry_id] = shape_artist
                    # Add label artist
                    label_artist = self.label(cx, cy, interception_key, fc)
                    label_artist.set_visible(self.show_overlays)
                    self.ax.add_artist(label_artist)
                    self.labels_artists[entry_id] = label_artist
                    # Make the label draggable
                    self.label_drag_managers[entry_id] = DraggableLabel(entry_id, self)
                    # Make the shape draggable
                    self.shape_drag_managers[entry_id] = DraggableShape(entry_id, self, RECT)                   

    # Naming / Saving Logic
    def enter_naming_mode(self):
        if not self.shapes:
            self.update_title(f"Nothing to save! | {HELP_STR}")
            return

        self.state = NAMING
        self.input_buffer = ""
        self.update_title("SAVE: Type Name... (Enter for Default | Esc to Cancel)")

    def handle_naming_input(self, key):
        if key == 'escape':
            self.reset_state()
            return
        elif key == 'enter':
            final_name = self.input_buffer.strip()
            self.export_data(final_name if final_name else None)
            self.reset_state()
            return
        elif key == 'backspace':
            self.input_buffer = self.input_buffer[:-1]
        elif len(key) == 1 and (key.isalnum() or key in ['_', '-']):
            self.input_buffer += key
        
        display_name = self.input_buffer if self.input_buffer else "[Default Timestamp]"
        self.update_title(f"SAVE: {display_name} (Enter to Save, Esc to Cancel, Default '')")

    def export_data(self, user_name):
        if not user_name:
            user_name = datetime.datetime.now().strftime("map_%Y%m%d_%H%M%S")
        else:
            user_name += datetime.datetime.now().strftime("_map_%Y%m%d_%H%M%S")
            
        relative_path_parent = self.image_path.relative_to(Path(IMAGES_FOLDER)).parent
        target_dir = Path(JSONS_FOLDER) / relative_path_parent
        file_path = target_dir / f"{user_name}.json"        
        target_dir.mkdir(parents=True, exist_ok=True)       
        output = []        

        for _, data in self.shapes.items():
            entry = {
                "name": data['key_name'], # Interception Key Name
                "scancode": data['m_code'], # Saved as hex string "0x..."
                "type": data['type'],
                "cx": data['cx'],
                "cy": data['cy'],
                # Initialize vals to 0/null
                "val1": 0, "val2": 0, "val3": 0, "val4": 0
            }
            
            if data['type'] == CIRCLE:
                entry["val1"] = data['r']
                # val 2, 3, 4 remain 0
                
            elif data['type'] == RECT:
                (x_min, y_min), (x_max, y_max) = data['bb']
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
                "sprint_distance": self.sprint_distance
                },
            "content": output
        }
        
        try:
            if (not self.saved_mouse_wheel) or (not self.saved_sprint_distance):
                print("[!] ERROR: Mouse wheel or sprint distance not configured.")
                self.update_title(f"Error saving: {file_path.name} | {HELP_STR}")
                return

            with file_path.open('w', encoding='utf-8') as f:
                json.dump(json_output, f, indent=4)
                
            print(f"[+] JSON file saved to: {file_path.as_posix()}")

            update_toml(
                self.width, self.height, self.dpi, 
                str(self.image_path), str(file_path), 
                self.mouse_wheel_radius, self.sprint_distance, True
            )

        except Exception as e:
            print(f"[!] Export Error: {e}")
            self.update_title(f"Error saving: {file_path.name} | {HELP_STR}")
            return
            
        self.update_title(f"SAVED: {file_path.name} | {HELP_STR}")
            
    # Helper Functions
    def get_interception_code(self, key):
        mapped_key = key
        val = SCANCODES.get(mapped_key)
        if val is None:
            mapped_key = SPECIAL_MAP.get(key)
            if mapped_key:
                val = SCANCODES.get(mapped_key)
        return hex(val) if val is not None else None, mapped_key if val is not None else None

    def get_event_key(self, scancode):
        mapped_scancode = scancode
        for key, val in SCANCODES.items():
            if hex(val) == mapped_scancode:
                for sp_key, sp_val in SPECIAL_MAP.items():
                    if sp_val == key:
                        return sp_key
                return key
        return ""
        

    def save_entry(self, interception_key, hex_code, cx, cy, r, bb):
        uid = self.count
        inc_count = True
        saved = False
        
        if interception_key == MOUSE_WHEEL_CODE:
            if self.mode == CIRCLE:
                if self.saved_mouse_wheel:
                    print(f"[!] Mouse Wheel already assigned. Overwriting previous assignment.")
                    for k, v in self.shapes.items():
                        if v['key_name'] == MOUSE_WHEEL_CODE:
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
                print(f"[!] ERROR: Mouse Wheel can only be assigned to '{CIRCLE}' not '{RECT} shapes.")
                return saved, uid
        
        elif interception_key == SPRINT_DISTANCE_CODE:
            if self.mode == CIRCLE:
                if not self.saved_mouse_wheel:
                    print(f"[!] ERROR: Mouse Wheel not assigned yet. Please assign it first.")
                    return saved, uid
                    
                if self.saved_sprint_distance:                    
                    print(f"[!] ERROR: Sprint Threshold already assigned. Overwriting previous assignment.")
                    for k, v in self.shapes.items():
                        if v['key_name'] == SPRINT_DISTANCE_CODE:
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
                            
                actual_dist = self.euclidean_distance(cx, cy, self.mouse_wheel_cx, self.mouse_wheel_cy)
                # STRICT CHECK: Ensure Sprint is actually outside the Joystick
                if actual_dist <= self.mouse_wheel_radius:
                    print(f"[!] ERROR: Sprint point must be OUTSIDE the joystick radius!")
                    return False, uid

                self.sprint_distance = actual_dist
                self.saved_sprint_distance = True
                self.sprint_artist_id = uid
                
            elif self.mode == RECT:
                print(f"[!] ERROR: Sprint Button can only be assigned to '{CIRCLE}' not '{RECT} shapes.")
                return saved, uid
        
        entry = {
            "key_name": interception_key,
            "m_code": hex_code,
            "type": self.mode,
            "cx": cx, "cy": cy, "r": r, "bb": bb
        }
        
        self.shapes[uid] = entry
        if inc_count:
            self.count += 1
        
        saved = True
        return saved, uid

    def print_data(self):
        if not self.shapes:
            print("[!] No shapes to print.")
            self.update_title(f"List empty. Nothing to print | {HELP_STR}")
            return
        
        print("\n")
        print("Current Shapes:")
        for k, v in self.shapes.items():
            print(k, v)
        print("\n")

    # Math
    def calculate_circle(self): # 3 Points
        x1, y1 = self.points[0]
        x2, y2 = self.points[1]
        x3, y3 = self.points[2]
        D = 2 * (x1 * (y2 - y3) + x2 * (y3 - y1) + x3 * (y1 - y2))
        if D == 0:
            self.update_title("Error: Points are collinear.")
            return None, None, None, None
        h = ((x1**2 + y1**2) * (y2 - y3) + (x2**2 + y2**2) * (y3 - y1) + (x3**2 + y3**2) * (y1 - y2)) / D
        k = ((x1**2 + y1**2) * (x3 - x2) + (x2**2 + y2**2) * (x1 - x3) + (x3**2 + y3**2) * (x2 - x1)) / D
        r = math.sqrt((x1 - h)**2 + (y1 - k)**2)
        return int(round(h)), int(round(k)), int(round(r)), None

    def calculate_rect(self): # 4 Points
        xs = [pt[0] for pt in self.points]
        ys = [pt[1] for pt in self.points]
        return int(round(sum(xs)/4)), int(round(sum(ys)/4)), None, ((min(xs), min(ys)), (max(xs), max(ys)))
        
    def calculate_raw_rect(self, values): # 2 Points
        xs = [v[0] for v in values]
        ys = [v[1] for v in values]
        return int(round(sum(xs)/2)), int(round(sum(ys)/2)), None, ((min(xs), min(ys)), (max(xs), max(ys)))


    def euclidean_distance(self, x1, y1, x2, y2):
        return ((x2 - x1)**2 + (y2 - y1)**2)**0.5

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
        radius = math.sqrt((cx - px)**2 + (cy - py)**2)
        if radius < 1e-9: return cx, cy # Pivot and point are identical

        current_angle = math.atan2(cy - py, cx - px)
        valid_intersections = []

        # Helper: Check if a point lies on a specific line segment
        def on_segment(x, y, x1, y1, x2, y2):
            # Use epsilon for float comparison stability
            epsilon = 1e-9
            return min(x1, x2) - epsilon <= x <= max(x1, x2) + epsilon and \
                min(y1, y2) - epsilon <= y <= max(y1, y2) + epsilon

        # Intersect Orbit Circle with all 4 Rectangle Edges
        # Edges defined as (x1, y1, x2, y2)
        edges = [
            (x_min, y_min, x_min, y_max), # Left
            (x_max, y_min, x_max, y_max), # Right
            (x_min, y_min, x_max, y_min), # Bottom
            (x_min, y_max, x_max, y_max)  # Top
        ]

        for (x1, y1, x2, y2) in edges:
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
            diff = math.atan2(math.sin(target_angle - current_angle), 
                            math.cos(target_angle - current_angle))
            
            candidates.append({
                'pt': (ix, iy),
                'diff': abs(diff),
                'y': iy
            })

        # SORTING LOGIC:
        # Primary: Angle Difference (Round to 5 decimals to force ties on float errors)
        # Secondary: Y Coordinate (Ascending = Top of Screen preference)
        candidates.sort(key=lambda c: (round(c['diff'], 5), c['y']))

        # Return the coordinate of the winner
        return candidates[0]['pt']

if __name__ == "__main__":
    Plotter()