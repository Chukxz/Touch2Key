import time
import ctypes
from ctypes import wintypes
import threading
from .utils import DEF_DPI, WINDOW_FIND_RETRIES, WINDOW_FIND_DELAY

MAX_CLASS_NAME = 256

# EnumWindows callback type definition
EnumWindowsProc = ctypes.WINFUNCTYPE(ctypes.c_bool, wintypes.HWND, wintypes.LPARAM)

# RECT structure for Windows API
class RECT(ctypes.Structure):
    _fields_ = [
        ("left", ctypes.c_long),
        ("top", ctypes.c_long),
        ("right", ctypes.c_long),
        ("bottom", ctypes.c_long)
    ]

# POINT structure for ClientToScreen
class POINT(ctypes.Structure):
    _fields_ = [
        ("x", ctypes.c_long), 
        ("y", ctypes.c_long)
    ]

class Mapper():
    def __init__(self, json_loader, res_dpi, interception_bridge, window_title="Gameloop(64beta)"):
        # 1. Setup Dependencies
        self.json_loader = json_loader
        self.config = self.json_loader.config
        self.mapper_event_dispatcher = self.json_loader.mapper_event_dispatcher
        self.interception_bridge = interception_bridge
        
        # 2. Window Tracking Setup
        self.lock = threading.Lock()
        self.window_title_target = window_title 
        
        # Constants applied implicitly via default arguments here
        self.game_window_class_name = self.get_game_window_class_name(window_title)
        
        self.game_window_info = self.get_game_window_info()
        self._window_update_interval = 0.05 
        
        # 3. Initialize Resolution & DPI
        self.device_width = res_dpi[0]
        self.device_height = res_dpi[1]
        self.device_dpi = res_dpi[2]
        
        # 4. Config & State
        self.wasd_block = 0
        self.update_config() 
        
        self.mapper_event_dispatcher.register_callback("ON_CONFIG_RELOAD", self.update_config)
        
        # 5. Start the window tracking thread
        self.running = True
        self.window_lost = False
        self.window_thread = threading.Thread(target=self.update_game_window_info, daemon=True)
        self.window_thread.start()
    
    def update_config(self):
        with self.lock:
            self.device_width = self.json_loader.width
            self.device_height = self.json_loader.height
            self.dpi = self.json_loader.dpi
            print(f"[INFO] Mapper synced to Resolution: {self.device_width}x{self.device_height}, DPI: {self.dpi}")
            
    # --- Window Management ---
    
    def get_window_class_name(self, hwnd):
        buffer = ctypes.create_unicode_buffer(MAX_CLASS_NAME)
        ctypes.windll.user32.GetClassNameW(hwnd, buffer, MAX_CLASS_NAME)
        return buffer.value

    def get_game_window_class_name(self, window_title, retries=WINDOW_FIND_RETRIES, delay=WINDOW_FIND_DELAY):
        """Waits for the game window to appear on startup."""
        if window_title is None:
            raise RuntimeError("Window_title must be provided")
            
        print(f"[INFO] Waiting for window: '{window_title}'...")
        for i in range(retries):
            hwnd = ctypes.windll.user32.FindWindowW(None, window_title)
            if hwnd != 0:
                class_name = self.get_window_class_name(hwnd)
                print(f"[INFO] Found window '{window_title}' (Class: {class_name})")
                return class_name
            time.sleep(delay)
        
        _str = f"Window '{window_title}' not found after {retries} retries, lasting for {retries * delay} seconds."
        raise RuntimeError(_str)

    def enum_windows_callback(self, hwnd, lParam):
        target_class = ctypes.cast(lParam, ctypes.POINTER(ctypes.py_object)).contents.value['class_name']
        results = ctypes.cast(lParam, ctypes.POINTER(ctypes.py_object)).contents.value['results']
        
        buffer = ctypes.create_unicode_buffer(256)
        ctypes.windll.user32.GetClassNameW(hwnd, buffer, 256)
        if buffer.value == target_class:
            results.append(hwnd)
        return True

    def find_hwnds_by_class(self, class_name):
        results = []
        data = ctypes.py_object({'class_name': class_name, 'results': results})
        ctypes.windll.user32.EnumWindows(EnumWindowsProc(self.enum_windows_callback), ctypes.byref(data))
        return results

    def get_window_info(self, hwnd):
        # 1. Get the Client Area (The pure game content size)
        client_rect = RECT()
        ctypes.windll.user32.GetClientRect(hwnd, ctypes.byref(client_rect))
        width = client_rect.right - client_rect.left
        height = client_rect.bottom - client_rect.top
        
        # 2. Find where top-left (0,0) of the Client Area is on the Screen
        pt = POINT()
        pt.x = 0
        pt.y = 0
        ctypes.windll.user32.ClientToScreen(hwnd, ctypes.byref(pt))
        
        return {
            'hwnd': hwnd,
            'left': pt.x,    
            'top': pt.y,     
            'width': width,  
            'height': height 
        }
        
    def update_game_window_info(self):
        """Background thread to track window movement and handle restarts."""
        while self.running:
            try:
                # 1. Check if current handle is still valid
                if self.game_window_info and ctypes.windll.user32.IsWindow(self.game_window_info['hwnd']):
                    # Window exists, update its position
                    info = self.get_window_info(self.game_window_info['hwnd'])
                    with self.lock:
                        self.game_window_info = info
                    
                    if self.window_lost:
                        print(f"[INFO] Re-acquired game window!")
                        self.window_lost = False

                else:
                    # 2. Window Handle Invalid (Closed/Crashed)
                    if not self.window_lost:
                        print("[WARNING] Game window handle lost! Scanning for new window...")
                        self.window_lost = True
                    
                    try:
                        # Attempt to find a new window
                        new_info = self.get_game_window_info()
                        with self.lock:
                            self.game_window_info = new_info
                    except RuntimeError:
                        # Still not found, keep looping
                        pass

            except Exception as e:
                print(f"[ERROR] Window tracking error: {e}")
            
            # 3. Dynamic Sleep: Fast if found, Slow if lost (using Constant)
            sleep_time = WINDOW_FIND_DELAY if self.window_lost else self._window_update_interval
            time.sleep(sleep_time) 
       
    def get_game_window_info(self):
        hwnds = self.find_hwnds_by_class(self.game_window_class_name)
        target_info = None
        max_diag = 0

        for hwnd in hwnds:
            if ctypes.windll.user32.IsWindowVisible(hwnd) == 0:
                continue

            info = self.get_window_info(hwnd)
            w, h = info['width'], info['height']
            diag = (w*w + h*h) ** 0.5

            if diag > max_diag:
                max_diag = diag
                target_info = info
        
        if target_info is None:
            _str = f"No visible window found for class '{self.game_window_class_name}'."
            raise RuntimeError(_str)
        return target_info

    # --- Coordinate Mapping ---

    def device_to_game_rel(self, dx, dy):
        with self.lock:
            if self.window_lost:
                return 0, 0
                
            game_w = self.game_window_info['width']
            game_h = self.game_window_info['height']
                        
        converted_x = (dx / self.device_width) * game_w
        converted_y = (dy / self.device_height) * game_h

        return converted_x, converted_y
    
    def device_to_game_abs(self, x, y):
        converted_x, converted_y = self.device_to_game_rel(x, y)
        
        with self.lock:
            if self.window_lost:
                return 0, 0
                
            game_left = self.game_window_info['left']
            game_top = self.game_window_info['top']
            
        final_x = game_left + converted_x
        final_y = game_top  + converted_y

        return final_x, final_y
    
    def dp_to_px(self, dp):
        return dp * (self.dpi / DEF_DPI)

    def px_to_dp(self, px):
        return px * (DEF_DPI / self.dpi)
