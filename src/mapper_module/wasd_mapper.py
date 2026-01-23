from __future__ import annotations
from typing import TYPE_CHECKING

from enum import IntFlag
class State(IntFlag):
    NONE = 0
    W = 1 << 0
    A = 1 << 1
    S = 1 << 2
    D = 1 << 3

    
import math
from .utils import (
    SCANCODES, UP, DOWN, PRESSED
)

if TYPE_CHECKING:
    from .mapper import Mapper
    from .utils import TouchEvent


class WASDMapper():
    def __init__(self, mapper:Mapper):
        self.mapper = mapper
        self.interception_bridge = mapper.interception_bridge
        self.json_loader = mapper.json_loader
        self.config = mapper.config
        self.mapper_event_dispatcher = self.mapper.mapper_event_dispatcher
        sprint_key = mapper.emulator['sprint_key']
        self.sprint_key_code = None

        if sprint_key is not None:
            try:
                self.sprint_key_code = int(SCANCODES[sprint_key], 16) if isinstance(SCANCODES[sprint_key], str) else int(SCANCODES[sprint_key])
            except:
                self.sprint_key_code = None

        # Pre-convert scancodes to Integers once for faster Bridge interaction
        self.KEY_W = int(SCANCODES["w"], 16) if isinstance(SCANCODES["w"], str) else int(SCANCODES["w"])
        self.KEY_A = int(SCANCODES["a"], 16) if isinstance(SCANCODES["a"], str) else int(SCANCODES["a"])
        self.KEY_S = int(SCANCODES["s"], 16) if isinstance(SCANCODES["s"], str) else int(SCANCODES["s"])
        self.KEY_D = int(SCANCODES["d"], 16) if isinstance(SCANCODES["d"], str) else int(SCANCODES["d"])
        
        self.sector_to_state = {
            0: State.D,                      # 0: Right (-22.5° to 22.5°)
            1: State.S | State.D,            # 1: Down-Right
            2: State.S,                      # 2: Down
            3: State.S | State.A,            # 3: Down-Left
            4: State.A,                      # 4: Left
            5: State.W | State.A,            # 5: Up-Left
            6: State.W,                      # 6: Up
            7: State.W | State.D             # 7: Up-Right
        }
                
        self.state_value_to_key = {
            1: self.KEY_W,
            2: self.KEY_A,
            4: self.KEY_S,
            8: self.KEY_D       
        }
        
        # Math.PI fractional constants
        self.PI_8 = math.pi / 8
        self.INV_PI_4 = 1.0 / (math.pi / 4.0)
        self.sprinting = False
        self.current_mask = State.NONE
        self.center_x = 0.0
        self.center_y = 0.0
        
        self.update_config()
        self.updateMouseWheel()

        # Register Callbacks
        self.mapper_event_dispatcher.register_callback("ON_CONFIG_RELOAD", self.update_config)
        self.mapper_event_dispatcher.register_callback("ON_JSON_RELOAD", self.updateMouseWheel)
        self.mapper_event_dispatcher.register_callback("ON_WASD_BLOCK", self.on_wasd_block)
        

    def update_config(self):
        print(f"[WASDMapper] Reloading config...")
        try:
            with self.config.config_lock:
                conf = self.config.config_data.get('joystick', {})
                self.DEADZONE = conf.get('deadzone', 0.1)
                self.HYSTERESIS = conf.get('hysteresis', 5.0)
        except Exception as e:
            _str = f"Error loading joystick config: {e}"
            raise RuntimeError(_str)

    def updateMouseWheel(self):
        with self.config.config_lock:
            print(f"[WASDMapper] Updating mousewheel...")
            self.inner_radius, d_radius = self.json_loader.get_mouse_wheel_info()
            self.outer_radius = self.inner_radius + d_radius

    def on_wasd_block(self):
        if self.mapper.wasd_block > 0:
            self.touch_up()
            
    def touch_down(self, touch_event:TouchEvent, is_visible:bool):
        if self.mapper.wasd_block == 0 and not is_visible:
            self.center_x = touch_event.x
            self.center_y = touch_event.y

    def touch_pressed(self, touch_event:TouchEvent, is_visible:bool):
        if self.mapper.wasd_block > 0 or is_visible:
            self.touch_up()
            return

        vx = touch_event.x - self.center_x
        vy = touch_event.y - self.center_y
        dist_sq = vx*vx + vy*vy

        # Optimization: Deadzone check using squared distance
        dz_px = self.inner_radius * self.DEADZONE
        if dist_sq < (dz_px * dz_px):
            self.touch_up()
            return

        # Leash Logic (Floating Joystick center follow)
        outer_sq = self.outer_radius * self.outer_radius
        if dist_sq > outer_sq and outer_sq > 0:
            dist = dist_sq**0.5 # Only calculate sqrt if we are actually leashing
            scale = self.outer_radius / dist
            self.center_x = touch_event.x - (vx * scale)
            self.center_y = touch_event.y - (vy * scale)
            vx = touch_event.x - self.center_x
            vy = touch_event.y - self.center_y
            # dist is now effectively self.outer_radius

        # FAST ANGLE TO SECTOR INDEX
        # atan2 gives -pi to pi; we shift to 0 to 2pi and offset by pi/8 (22.5°)
        angle_rad = math.atan2(vy, vx)
        if angle_rad < 0: angle_rad += 2 * math.pi

        # Divide circle into 8 segments of 45°
        sector = int((angle_rad + self.PI_8) * self.INV_PI_4) % 8

        # Sprint Check
        sprint = False
        if self.sprint_key_code is not None:
            inner_sq = self.inner_radius * self.inner_radius
            if dist_sq > inner_sq:
                sprint = True
                
        # Apply the keys
        self.apply_keys(sector, sprint)

    def touch_up(self):        
        for k in self.current_mask:
            if k.value > 0:
                self.interception_bridge.key_up(self.state_value_to_key[k.value])
        if self.sprint_key_code is not None and self.sprinting:
            self.interception_bridge.key_up(self.sprint_key_code)

        self.sprinting = False
        self.current_mask = State.NONE
        self.center_x = 0.0
        self.center_y = 0.0
        
    def apply_keys(self, sector, sprint):
        # Bitmask-style diffing to minimize Interception Bridge overhead
        target_mask = self.sector_to_state[sector]
        to_release = self.current_mask & ~target_mask
        to_press = target_mask & ~self.current_mask
        
        for k in to_release: 
            if k.value > 0:
                self.interception_bridge.key_up(self.state_value_to_key[k.value])

        if self.sprint_key_code is not None and self.sprinting and not sprint:
        self.interception_bridge.key_up(self.sprint_key_code)
        self.sprinting = sprint
        
        if self.sprint_key_code is not None and not self.sprinting and sprint:          
            self.interception_bridge.key_down(self.sprint_key_code)
        self.sprinting = sprint
            
        for k in to_press:
            if k.value > 0:
                self.interception_bridge.key_down(self.state_value_to_key[k.value])
        
        self.current_mask = target_mask

    def process_touch(self, action, touch_event:TouchEvent, is_visible:bool):
        if action == PRESSED:
            self.touch_pressed(touch_event, is_visible)

        elif action == DOWN:
            self.touch_down(touch_event, is_visible)

        elif action == UP:
            self.touch_up()

