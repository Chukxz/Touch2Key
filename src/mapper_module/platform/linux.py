try:
    from pynput.keyboard import Controller as KeyboardController, Key
    from pynput.mouse import Controller as MouseController, Button
except ImportError:
    # Optional dependencies for Linux
    KeyboardController = None
    MouseController = None

from .base import InputBridge

class LinuxInputBridge(InputBridge):
    """
    A minimal Linux implementation using pynput.
    Note: pynput might require X11 or specific permissions on Linux.
    """
    def __init__(self):
        if KeyboardController is None:
            raise ImportError("pynput is required for Linux support. Install with 'pip install pynput'")
        
        self.keyboard = KeyboardController()
        self.mouse = MouseController()
        print("[Bridge] Started Linux (pynput) Engine.")

    def key_down(self, code):
        # Note: Scancode mapping might be needed for Linux
        # For now, we stub or use direct character mapping if possible
        # This is a minimal skeleton
        pass

    def key_up(self, code):
        pass

    def mouse_move_rel(self, dx, dy):
        self.mouse.move(dx, dy)

    def mouse_move_abs(self, x, y):
        self.mouse.position = (x, y)

    def left_click_down(self):
        self.mouse.press(Button.left)

    def left_click_up(self):
        self.mouse.release(Button.left)

    def right_click_down(self):
        self.mouse.press(Button.right)

    def right_click_up(self):
        self.mouse.release(Button.right)

    def middle_click_down(self):
        self.mouse.press(Button.middle)

    def middle_click_up(self):
        self.mouse.release(Button.middle)

    def release_all(self):
        # pynput doesn't have a simple 'release_all', would need to track state
        print("[Bridge] Linux release_all called (stub)")
        pass
