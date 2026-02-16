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

        # Pre-convert scancodes
        self.KEY_W = int(SCANCODES["w"], 16) if isinstance(SCANCODES["w"], str) else int(SCANCODES["w"])
        self.KEY_A = int(SCANCODES["a"], 16) if isinstance(SCANCODES["a"], str) else int(SCANCODES["a"])
        self.KEY_S = int(SCANCODES["s"], 16) if isinstance(SCANCODES["s"], str) else int(SCANCODES["s"])
        self.KEY_D = int(SCANCODES["d"], 16) if isinstance(SCANCODES["d"], str) else int(SCANCODES["d"])

        self.sector_to_state = {
            0: State.D,                      # 0: Right
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

        self.PI_8 = math.pi / 8
        self.INV_PI_4 = 1.0 / (math.pi / 4.0)
        self.sprinting = False
        self.current_mask = State.NONE
        self.center_x = 0.0
        self.center_y = 0.0
        self.last_sector = None

        # Radius Placeholders
        self.raw_inner_radius = 100.0
        self.raw_outer_radius = 150.0
        self.effective_inner_sq = 10000.0
        self.deadzone = 10
        self.deadzone_sq = 100.0
        self.sensitivity = 1.0

        # Init (Order matters: MouseWheel -> Config -> Recalc)
        self.updateMouseWheel() 
        self.update_config()

        self.mapper_event_dispatcher.register_callback("ON_CONFIG_RELOAD", self.update_config)
        self.mapper_event_dispatcher.register_callback("ON_JSON_RELOAD", self.updateMouseWheel)
        self.mapper_event_dispatcher.register_callback("ON_WASD_BLOCK", self.on_wasd_block)


    def update_config(self):
        print(f"[WASDMapper] Reloading config...")
        try:
            with self.config.config_lock:
                # Get Joystick Settings (Deadzone, Hysteresis)
                joystick_conf = self.config.config_data.get('joystick', {})
                self.deadzone = joystick_conf.get('deadzone', 0.1)
                self.hysteresis = math.radians(joystick_conf.get('hysteresis', 5.0))
                
                # Get Mouse Settings (Sensitivity)
                # We reuse the mouse sensitivity here!
                mouse_conf = self.config.config_data.get('mouse', {})
                self.sensitivity = mouse_conf.get('sensitivity', 1.0)
                
                # Recalculate Thresholds
                self.recalc_thresholds()
                
        except Exception as e:
            print(f"[Error] Joystick config error: {e}")

    def updateMouseWheel(self):
        with self.config.config_lock:
            print(f"[WASDMapper] Updating mousewheel radius...")
            self.raw_inner_radius, d_radius = self.json_loader.get_mouse_wheel_info()
            self.raw_outer_radius = self.raw_inner_radius + d_radius
            
            # Recalculate based on current sensitivity
            self.recalc_thresholds()

    def recalc_thresholds(self):
        """
        Applies Mouse Sensitivity to the raw JSON radii.
        Higher Sensitivity = Smaller mechanical radius = Less physical movement required.
        """
        # Protect against Zero Division or negative sens
        sens = self.sensitivity if self.sensitivity > 0.1 else 1.0

        # Scale down the required movement distance
        # e.g. Radius 200px / Sens 2.0 = Effective 100px activation
        effective_inner = self.raw_inner_radius / sens
        
        # Calculate Sprint Threshold (Squared)
        self.effective_inner_sq = effective_inner * effective_inner
        
        # Calculate Deadzone Threshold (Squared)
        # Deadzone is % of the EFFECTIVE radius.
        dz_px = effective_inner * self.deadzone
        self.deadzone_sq = dz_px * dz_px
        
        print(f"[WASD] Shared Sensitivity: {sens}x")
        print(f"       Walk Distance: {dz_px:.1f}px (was {self.raw_inner_radius * self.deadzone:.1f}px)")
        print(f"       Sprint Distance: {effective_inner:.1f}px (was {self.raw_inner_radius:.1f}px)")

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
        
        # Deadzone Check (Optimized)
        if dist_sq < self.deadzone_sq:
            # If we are inside deadzone, lift keys
            if self.current_mask != State.NONE:
                self.touch_up()
            return

        # Leash Logic (Floating Joystick center follow)
        # We use RAW outer radius for leashing so the joystick center visually 
        # follows your thumb naturally, even if sensitivity is high.
        outer_sq = self.raw_outer_radius * self.raw_outer_radius
        if dist_sq > outer_sq and outer_sq > 0:
            dist = dist_sq**0.5 
            scale = self.raw_outer_radius / dist
            self.center_x = touch_event.x - (vx * scale)
            self.center_y = touch_event.y - (vy * scale)
            vx = touch_event.x - self.center_x
            vy = touch_event.y - self.center_y
            
        # Angle Calculation
        angle_rad = math.atan2(vy, vx)
        if angle_rad < 0: angle_rad += 2 * math.pi  
        new_sector = int((angle_rad + self.PI_8) * self.INV_PI_4) % 8
                
        # Hysteresis Logic     
        if self.last_sector is not None:
            current_sector_center = self.last_sector * (math.pi / 4)
            angle_diff = (angle_rad - current_sector_center + math.pi) % (2 * math.pi) - math.pi
            if abs(angle_diff) < (self.PI_8 + self.hysteresis):
                new_sector = self.last_sector

        self.last_sector = new_sector

        # Sprint Check
        # Uses the SENSITIVITY-SCALED threshold
        sprint = False
        if self.sprint_key_code is not None:
            if dist_sq > self.effective_inner_sq:
                sprint = True

        self.apply_keys(new_sector, sprint)

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
        self.last_sector = None

    def apply_keys(self, sector, sprint):
        target_mask = self.sector_to_state[sector]
        to_release = self.current_mask & ~target_mask
        to_press = target_mask & ~self.current_mask

        for k in to_release: 
            if k.value > 0:
                self.interception_bridge.key_up(self.state_value_to_key[k.value])

        if self.sprint_key_code is not None:
            if self.sprinting and not sprint:
                self.interception_bridge.key_up(self.sprint_key_code)
                self.sprinting = False
            elif not self.sprinting and sprint:
                self.interception_bridge.key_down(self.sprint_key_code)
                self.sprinting = True

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
