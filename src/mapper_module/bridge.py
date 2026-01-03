from interception import Interception, KeyStroke, MouseStroke
import ctypes
from .utils import SCANCODES, M_LEFT, M_RIGHT, M_MIDDLE

# Mouse event flags
MOUSE_MOVE_RELATIVE = 0x00
MOUSE_MOVE_ABSOLUTE = 0x01
MOUSE_VIRTUAL_DESKTOP = 0x02
MOUSE_ATTRIBUTES_CHANGED = 0x04
MOUSE_MOVE_NOCOALESCE = 0x08

LEFT_BUTTON_DOWN = 0x0001
LEFT_BUTTON_UP = 0x0002
RIGHT_BUTTON_DOWN = 0x0004
RIGHT_BUTTON_UP = 0x0008
MIDDLE_BUTTON_DOWN = 0x0010
MIDDLE_BUTTON_UP = 0x0020
X_BUTTON_DOWN = 0x0040
X_BUTTON_UP = 0x0080
X_BUTTON_2_DOWN = 0x0100
X_BUTTON_2_UP = 0x0200
MOUSE_V_WHEEL = 0x0400
MOUSE_HWHEEL = 0x0800
MOUSE_WHEEL_NEGATIVE = 0x1000

class InterceptionBridge:
    def __init__(self):
        self.ctx = Interception()
        # Access context properties directly
        self.mouse = self.ctx.mouse
        self.keyboard = self.ctx.keyboard

    def key_down(self, key_code):
        # KeyStroke(code, flags)
        ks = KeyStroke(key_code, 0) 
        self.ctx.send(self.keyboard, ks)
    
    def key_up(self, key_code):
        # KeyStroke(code, flags)
        ks = KeyStroke(key_code, 1)
        self.ctx.send(self.keyboard, ks)
        
    def hotkey_down(self, key_codes):
        for key_code in key_codes:
            self.key_down(key_code)
    
    def hotkey_up(self, key_codes):
        for key_code in reversed(key_codes):
            self.key_up(key_code)

    def mouse_move_rel(self, dx, dy):
        dx = int(dx)
        dy = int(dy)
        # MouseStroke(state, flags, rolling, x, y)
        ms = MouseStroke(0, MOUSE_MOVE_RELATIVE, 0, dx, dy)
        self.ctx.send(self.mouse, ms)

    def mouse_move_abs(self, x, y):
        screen_w = ctypes.windll.user32.GetSystemMetrics(0)
        screen_h = ctypes.windll.user32.GetSystemMetrics(1)

        abs_x = int((x * 65535) / screen_w)
        abs_y = int((y * 65535) / screen_h)
        
        flags = MOUSE_MOVE_ABSOLUTE | MOUSE_VIRTUAL_DESKTOP
        # FORCE MOUSE_MOVE_ABSOLUTE as state (Arg 1)
        ms = MouseStroke(MOUSE_MOVE_ABSOLUTE, flags, 0, abs_x, abs_y)
        self.ctx.send(self.mouse, ms)
        
    def left_click_down(self):
        ms = MouseStroke(LEFT_BUTTON_DOWN, MOUSE_MOVE_RELATIVE, 0, 0, 0)
        self.ctx.send(self.mouse, ms)

    def left_click_up(self):
        ms = MouseStroke(LEFT_BUTTON_UP, MOUSE_MOVE_RELATIVE, 0, 0, 0)
        self.ctx.send(self.mouse, ms)

    def right_click_down(self):
        ms = MouseStroke(RIGHT_BUTTON_DOWN, MOUSE_MOVE_RELATIVE, 0, 0, 0)
        self.ctx.send(self.mouse, ms)
        
    def right_click_up(self):
        ms = MouseStroke(RIGHT_BUTTON_UP, MOUSE_MOVE_RELATIVE, 0, 0, 0)
        self.ctx.send(self.mouse, ms)

    def middle_click_down(self):
        ms = MouseStroke(MIDDLE_BUTTON_DOWN, MOUSE_MOVE_RELATIVE, 0, 0, 0)
        self.ctx.send(self.mouse, ms)
        
    def middle_click_up(self):
        ms = MouseStroke(MIDDLE_BUTTON_UP, MOUSE_MOVE_RELATIVE, 0, 0, 0)
        self.ctx.send(self.mouse, ms)
        
    def release_all(self):
        """Releases every key defined in SCANCODES and all mouse buttons."""
        print("[Bridge] Emergency Release: Clearing all inputs...")
        
        # 1. Release all defined Keyboard keys
        # We iterate through the values of your SCANCODES dictionary
        for scancode in SCANCODES.values():
            # Skip mouse codes if they are in your SCANCODES dict (handled below)
            if scancode in [M_LEFT, M_RIGHT, M_MIDDLE]:
                continue
            self.key_up(scancode)

        # 2. Release Mouse Buttons (Static calls for safety)
        self.left_click_up()
        self.right_click_up()
        self.middle_click_up
        
        print("[Bridge] All inputs cleared.")
