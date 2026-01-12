import time
import ctypes
from ctypes import wintypes
import threading
import win32gui
from .utils import (
    DEF_DPI, WINDOW_FIND_RETRIES, WINDOW_FIND_DELAY,
    MapperEvent
    )

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
        
        # We create a local 'cache' of window info to avoid locking during math
        self.cached_window_info = {'left': 0, 'top': 0, 'width': 1, 'height': 1}
        self.window_lost = False        
        self.window_title_target = window_title
        self.last_cursor_state = True # Cursor showing (Default)
        
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
            print(f"[INFO] Mapping from Device synced to Resolution: {self.device_width}x{self.device_height}, DPI: {self.dpi}")
            
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
        

        # Check Cursor Visibility
        try:
            flags, hcursor, pos = win32gui.GetCursorInfo()
            # 0x00000001 is CURSOR_SHOWING
            is_visible = (flags & 1) 
            
            if is_visible != self.last_cursor_state:
                self.last_cursor_state = is_visible
                # Signal the rest of the app to switch modes
                self.mapper_event_dispatcher.dispatch(MapperEvent(action="MENU_MODE_TOGGLE", is_visible=is_visible))
        except Exception:
            print("Could not check cursor visibility.")
                
        return {
            'hwnd': hwnd,
            'left': pt.x,    
            'top': pt.y,     
            'width': width,  
            'height': height 
        }

    def update_game_window_info(self):
        """Background thread - optimized to minimize lock hold time."""
        while self.running:
            try:
                # Check if current handle is still valid
                current_hwnd = None
                with self.lock:
                    if self.game_window_info:
                        current_hwnd = self.game_window_info.get('hwnd')

                if current_hwnd and ctypes.windll.user32.IsWindow(current_hwnd):
                    # 1. WINDOW IS ACTIVE: Get fresh coordinates
                    new_info = self.get_window_info(current_hwnd)
                    
                    if self.window_lost:
                        print(f"[INFO] Re-acquired game window!")
                                            
                    # 2. ATOMIC SWAP: Only hold lock to update the dict reference
                    with self.lock:
                        self.game_window_info = new_info
                        self.cached_window_info = new_info 
                        self.window_lost = False
                        
                else:
                    # 3. WINDOW IS LOST: Handle scanning
                    if not self.window_lost:
                        print("[WARNING] Game window lost! Scanning for new window...")
                        with self.lock:
                            self.window_lost = True
                    
                    try:
                        # Scan for the window (CPU intensive, done outside lock)
                        discovered_info = self.get_game_window_info()
                        
                        # If we found it, swap it in
                        with self.lock:
                            self.game_window_info = discovered_info
                            self.cached_window_info = discovered_info # FIX: Use discovered_info, not 'info'
                            self.window_lost = False
                            print("[INFO] New window handle bound.")
                            
                    except RuntimeError:
                        # Game isn't open yet, just keep waiting
                        pass
                    
            except Exception as e:
                print(f"[ERROR] Window tracking error: {e}")
            
            # Dynamic Sleep: Constant from utils
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

    def device_to_game_rel(self, dx, dy):
        """Math is now outside the lock."""
        # Check window_lost once without a full block if possible, 
        # but for safety, we grab the current dimensions quickly.
        with self.lock:
            if self.window_lost: return 0, 0
            w = self.cached_window_info['width']
            h = self.cached_window_info['height']

        # Math happens here - NO LOCK HELD
        # This allows other threads (Keyboard) to get the lock immediately
        return (dx / self.device_width) * w, (dy / self.device_height) * h
    
    def device_to_game_abs(self, x, y):
        """Thread-safe absolute mapping."""
        with self.lock:
            if self.window_lost: return 0, 0
            w = self.cached_window_info['width']
            h = self.cached_window_info['height']
            l = self.cached_window_info['left']
            t = self.cached_window_info['top']
            
        return l + (x / self.device_width) * w, t + (y / self.device_height) * h
    
    def dp_to_px(self, dp):
        return dp * (self.dpi / DEF_DPI)

    def px_to_dp(self, px):
        return px * (DEF_DPI / self.dpi)
