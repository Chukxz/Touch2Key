import time
import ctypes
from ctypes import wintypes
import threading
from bridge import InterceptionBridge
from utils import DEF_DPI

MAX_CLASS_NAME = 256

# EnumWindows callback
EnumWindowsProc = ctypes.WINFUNCTYPE(ctypes.c_bool, wintypes.HWND, wintypes.LPARAM)

# RECT structure
class RECT(ctypes.Structure):
    _fields_ = [
        ("left", ctypes.c_long),
        ("top", ctypes.c_long),
        ("right", ctypes.c_long),
        ("bottom", ctypes.c_long)
    ]

class Mapper():
    def __init__(self, csv_loader, window_title="Gameloop(64beta)"):
        super().__init__()
        self.game_window_class_name = self.get_game_window_class_name(window_title)
        self.game_window_info = self.get_game_window_info()
        self._last_window_update = 0.0
        self._window_update_interval = 0.016  # seconds
        self.lock = threading.Lock()
        self.csv_loader = csv_loader
        self.config = self.csv_loader.config
        self.mapper_event_dispatcher = self.csv_loader.mapper_event_dispatcher
        self.wasd_block = False
        self.interception_bridge = InterceptionBridge(self.dpi)
        self.update_config()
        
        self.mapper_event_dispatcher.register_callback("ON_CONFIG_RELOAD", self.update_config)
    
    def update_config(self):
        self.device_width = self.csv_loader.width
        self.device_height = self.csv_loader.height
        self.dpi = self.csv_loader.dpi

        print(f"[INFO] Using resolution: {self.width}x{self.height}")
        print(f"[INFO] Using DPI: {self.dpi}")
              
    # Get the class name of a window
    def get_window_class_name(self, hwnd):
        buffer = ctypes.create_unicode_buffer(MAX_CLASS_NAME)
        ctypes.windll.user32.GetClassNameW(hwnd, buffer, MAX_CLASS_NAME)
        return buffer.value

    def get_game_window_class_name(self, window_title, retries=100, delay=1):
        if window_title is None:
            raise RuntimeError("window_title must be provided or pass class name directly")
        for _ in range(retries):
            hwnd = ctypes.windll.user32.FindWindowW(None, window_title)
            if hwnd != 0:
                return self.get_window_class_name(hwnd)
            time.sleep(delay)
        raise RuntimeError(f"No window with title '{window_title}' found after {retries} tries.")
        
    # EnumWindows callback
    def enum_windows_callback(self, hwnd, lParam):
        target_class = ctypes.cast(lParam, ctypes.POINTER(ctypes.py_object)).contents.value['class_name']
        results = ctypes.cast(lParam, ctypes.POINTER(ctypes.py_object)).contents.value['results']
        # Get class name
        buffer = ctypes.create_unicode_buffer(256)
        ctypes.windll.user32.GetClassNameW(hwnd, buffer, 256)
        if buffer.value == target_class:
            results.append(hwnd)
        return True

    # Find HWNDs by class name
    def find_hwnds_by_class(self, class_name):
        results = []
        data = ctypes.py_object({'class_name': class_name, 'results': results})
        ctypes.windll.user32.EnumWindows(EnumWindowsProc(self.enum_windows_callback), ctypes.byref(data))
        return results

    # Get window rect info
    def get_window_info(self, hwnd):
        rect = RECT()
        ctypes.windll.user32.GetWindowRect(hwnd, ctypes.byref(rect))
        
        left = rect.left
        top = rect.top
        width = rect.right - rect.left
        height = rect.bottom - rect.top
        
        return {
            'hwnd': hwnd,
            'left': left,
            'top': top,
            'width': width,
            'height': height
        }
        
    def update_game_window_info(self):
        while True:
            try:
                if ctypes.windll.user32.IsWindow(self.game_window_info['hwnd']):
                    info = self.get_window_info(self.game_window_info['hwnd'])
                    with self.lock:
                        self.game_window_info = info

            except Exception as e:
                raise RuntimeError(f"Error updating window info: {e}")
            
            time.sleep(self._window_update_interval) 
       
    def get_game_window_info(self):
        hwnds = self.find_hwnds_by_class(self.game_window_class_name)
        target_info = None
        
        if not hwnds:
            raise RuntimeError(f"No windows found with class '{self.game_window_class_name}'")
        else:
            max_diag = 0

            for hwnd in hwnds:
                # Filter invisible or zero-size windows
                if ctypes.windll.user32.IsWindowVisible(hwnd) == 0:
                    continue

                info = self.get_window_info(hwnd)
                w, h = info['width'], info['height']
                diag = (w*w + h*h) ** 0.5

                if diag > max_diag:
                    max_diag = diag
                    target_info = info
        
        if target_info is None:
            raise RuntimeError(f"No appropiate window info found for class '{self.game_window_class_name}'")    
        return target_info

    def device_to_game_rel(self, dx, dy):
        game_w = int(self.game_window_info['width'])
        game_h = int(self.game_window_info['height'])
                       
        converted_x = (dx / self.device_width) * game_w
        converted_y = (dy / self.device_height) * game_h

        return converted_x, converted_y
    
    def device_to_game_abs(self, x, y):
        converted_x, converted_y = self.device_to_game_rel(x, y)
        game_left = self.game_window_info['left']
        game_top = self.game_window_info['top']
        final_x = game_left + converted_x
        final_y = game_top  + converted_y

        return final_x, final_y
    
    def dp_to_px(self, dp):
        """Convert dependent pixels (dp) to pixels (px)."""
        return dp * (self.dpi / DEF_DPI)

    def px_to_dp(self, px):
        """Convert pixels (px) to dependent pixels (dp)."""
        return px * (DEF_DPI / self.dpi)

    def accept_touch_mouse_event(self, event, button_type="LEFT"):
        """
        Handles absolute clicks. 
        Moves the cursor to the exact mapped coordinates and clicks.
        """
        game_x, game_y = self.device_to_game_abs(event.x, event.y)

        # State Machine
        if event.action == "DOWN":
            # CRITICAL: Move the mouse FIRST, then click.
            # If you click before moving, you click the wrong spot.
            self.interception_bridge.mouse_move_abs(game_x, game_y)
            if button_type == "LEFT":
                self.interception_bridge.left_click_down()
            elif button_type == "RIGHT":
                self.interception_bridge.right_click_down()

        elif event.action == "PRESSED":
            # If holding and dragging (e.g., dragging an inventory item)
            # We update position but keep the button held down.
            self.interception_bridge.mouse_move_abs(game_x, game_y)

        elif event.action == "UP":
            # Release the button
            if button_type == "LEFT":
                self.interception_bridge.left_click_up()
            elif button_type == "RIGHT":
                self.interception_bridge.right_click_up()
    
    def send_mouse_move(self, dx, dy):
        self.interception_bridge.mouse_move_rel(dx, dy)
    
    def send_key_down(self, key_code):
        self.interception_bridge.key_down(key_code)
    
    def send_key_up(self, key_code):
        self.interception_bridge.key_up(key_code)