from interception import Interception, KeyStroke, MouseStroke
import ctypes

# Mouse event flags
MOUSE_MOVE_RELATIVE = 0x00
MOUSE_MOVE_ABSOLUTE = 0x01
MOUSE_VIRTUAL_DESKTOP = 0x02
MOUSE_ATTRIBUTES_CHANGED = 0x04
MOUSE_MOVE_NOCOALESCE = 0x08
LEFT_BUTTON_DOWN = 0x0001	
LEFT_BUTTON_UP = 0x0002	
RIGHT_BUTTON_DOWN = 0x0004	
RIGHT_BUTTON_UP = 	0x0008	
MIDDLE_DOWN = 0x0010
MIDDLE_UP = 0x0020
X_BUTTON_DOWN =	0x0040
X_BUTTON_UP = 0x0080
X_BUTTON_2_DOWN = 0x0100
X_BUTTON_2_UP =	0x0200
MOUSE_V_WHEEL = 0x0400
MOUSE_HWHEEL = 0x0800
MOUSE_WHEEL_NEGATIVE = 0x1000

class InterceptionBridge:
    def __init__(self, dpi):
        self.ctx = Interception()
        self.mouse = self.ctx.mouse()
        self.keyboard = self.ctx.keyboard()

    def key_down(self, key_code):
        ks_down = KeyStroke(key_code, flags=0)
        self.ctx.send(self.keyboard, ks_down)
    
    def key_up(self, key_code):
        ks_up = KeyStroke(key_code, flags=1)
        self.ctx.send(self.keyboard, ks_up)
        
    def press_hotkey(self, key_codes):
        for key_code in key_codes:
            self.key_down(key_code)        
        for key_code in reversed(key_codes):
            self.key_up(key_code)

    def mouse_move_rel(self, dx, dy):
        dx = int(dx)
        dy = int(dy)
        ms = MouseStroke(MOUSE_MOVE_RELATIVE, 0, 0, dx, dy)
        ms.x = dx
        ms.y = dy
        self.ctx.send(self.mouse, ms)

    def mouse_move_abs(self, x, y):
        screen_w = ctypes.windll.user32.GetSystemMetrics(0)
        screen_h = ctypes.windll.user32.GetSystemMetrics(1)

        abs_x = int((x * 65535) / screen_w)
        abs_y = int((y * 65535) / screen_h)
        ms = MouseStroke(MOUSE_MOVE_ABSOLUTE | MOUSE_VIRTUAL_DESKTOP, 0, 0, abs_x, abs_y)
        self.ctx.send(self.mouse, ms)
        
    def left_click_down(self):
        ms_down = MouseStroke(MOUSE_MOVE_RELATIVE, LEFT_BUTTON_DOWN, 0, 0, 0)
        self.ctx.send(self.mouse, ms_down)

    def left_click_up(self):
        ms_up = MouseStroke(MOUSE_MOVE_RELATIVE, LEFT_BUTTON_UP, 0, 0, 0)
        self.ctx.send(self.mouse, ms_up)

    def right_click_down(self):
        ms_down = MouseStroke(MOUSE_MOVE_RELATIVE, RIGHT_BUTTON_DOWN, 0, 0, 0)
        self.ctx.send(self.mouse, ms_down)
        
    def right_click_up(self):
        ms_down = MouseStroke(MOUSE_MOVE_RELATIVE, RIGHT_BUTTON_UP, 0, 0, 0)
        self.ctx.send(self.mouse, ms_down)