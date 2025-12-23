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

SCANCODES = {
    "ESC": 0x01,
    "1": 0x02,
    "2": 0x03,
    "3": 0x04,
    "4": 0x05,
    "5": 0x06,
    "6": 0x07,
    "7": 0x08,
    "8": 0x09,
    "9": 0x0A,
    "0": 0x0B,
    "MINUS": 0x0C,
    "EQUAL": 0x0D,
    "BACKSPACE": 0x0E,
    "TAB": 0x0F,

    "q": 0x10,
    "w": 0x11,
    "e": 0x12,
    "r": 0x13,
    "t": 0x14,
    "y": 0x15,
    "u": 0x16,
    "i": 0x17,
    "o": 0x18,
    "p": 0x19,
    "LEFT_BRACKET": 0x1A,
    "RIGHT_BRACKET": 0x1B,
    "ENTER": 0x1C,
    "LCTRL": 0x1D,

    "a": 0x1E,
    "s": 0x1F,
    "d": 0x20,
    "f": 0x21,
    "g": 0x22,
    "h": 0x23,
    "j": 0x24,
    "k": 0x25,
    "l": 0x26,
    "SEMICOLON": 0x27,
    "APOSTROPHE": 0x28,
    "GRAVE": 0x29,

    "LSHIFT": 0x2A,
    "BACKSLASH": 0x2B,

    "z": 0x2C,
    "x": 0x2D,
    "c": 0x2E,
    "v": 0x2F,
    "b": 0x30,
    "n": 0x31,
    "m": 0x32,
    "COMMA": 0x33,
    "DOT": 0x34,
    "SLASH": 0x35,

    "RSHIFT": 0x36,
    "NUM_MULTIPLY": 0x37,
    "LALT": 0x38,
    "SPACE": 0x39,
    "CAPSLOCK": 0x3A,

    "F1": 0x3B,
    "F2": 0x3C,
    "F3": 0x3D,
    "F4": 0x3E,
    "F5": 0x3F,
    "F6": 0x40,
    "F7": 0x41,
    "F8": 0x42,
    "F9": 0x43,
    "F10": 0x44,

    "NUMLOCK": 0x45,
    "SCROLLLOCK": 0x46,

    "NUM_7": 0x47,
    "NUM_8": 0x48,
    "NUM_9": 0x49,
    "NUM_MINUS": 0x4A,
    "NUM_4": 0x4B,
    "NUM_5": 0x4C,
    "NUM_6": 0x4D,
    "NUM_PLUS": 0x4E,
    "NUM_1": 0x4F,
    "NUM_2": 0x50,
    "NUM_3": 0x51,
    "NUM_0": 0x52,
    "NUM_DOT": 0x53,

    # Extended (E0 prefixed)
    "F11": 0x57,
    "F12": 0x58,

    "E0_HOME": 0xE047,
    "E0_UP": 0xE048,
    "E0_PAGEUP": 0xE049,
    "E0_PAGEDOWN": 0xE051,
    "E0_LEFT": 0xE04B,
    "E0_RIGHT": 0xE04D,
    "E0_END": 0xE04F,
    "E0_DOWN": 0xE050,
    "E0_INSERT": 0xE052,
    "E0_DELETE": 0xE053,

    "RCTRL": 0xE01D,
    "RALT": 0xE038,
    "E0_ENTER": 0xE01C,
    "E0_SLASH": 0xE035,
    "E0_NUM_ENTER": 0xE01C,
}


class InterceptionBridge:
    def __init__(self):
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
        ms.x = abs_x
        ms.y = abs_y
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