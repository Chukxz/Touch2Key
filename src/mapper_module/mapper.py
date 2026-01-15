import time
import ctypes
from ctypes import wintypes
import threading
import win32gui
from .utils import (
    DEF_DPI, WINDOW_FIND_DELAY,
    MapperEvent, set_dpi_awareness,
    set_high_priority
    )

MAX_CLASS_NAME = 256

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
    # EnumWindows callback type definition
    EnumWindowsProc = ctypes.WINFUNCTYPE(ctypes.c_bool, wintypes.HWND, wintypes.LPARAM)

    def __init__(self, json_loader, interception_bridge, pps, window_title="Gameloop(64beta)"):
        set_dpi_awareness()
        self.enumWindowsProc = Mapper.EnumWindowsProc

        # Setup Dependencies
        self.json_loader = json_loader
        self.config = self.json_loader.config
        self.mapper_event_dispatcher = self.json_loader.mapper_event_dispatcher
        self.interception_bridge = interception_bridge

        self.pps = pps
        self.event_count = 0
        self.last_pulse_time = time.perf_counter()
        
        # Window Tracking Setup
        self.screen_w = ctypes.windll.user32.GetSystemMetrics(0)
        self.screen_h = ctypes.windll.user32.GetSystemMetrics(1)
        self.lock = threading.Lock()
        self.window_lost = False        
        self.window_title_target = window_title
        self.last_cursor_state = True # Cursor showing (Default)
        self.game_window_class_name = None
        self.game_window_info = None
        self.window_lost = True
        self.window_update_interval = 0.05 
        
        # Config & State
        self.wasd_block = 0
        self.update_config() 
        
        self.mapper_event_dispatcher.register_callback("ON_CONFIG_RELOAD", self.update_config)
        
        # Start the window tracking thread
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

    def get_game_window_class_name(self, window_title):
        """Gets the game window classname."""
        if window_title is None:
            raise ValueError("Window_title must be provided.")

        class_name = None            
        print(f"[INFO] Waiting for window: '{window_title}'...")
        hwnd = ctypes.windll.user32.FindWindowW(None, window_title)
        if hwnd != 0:
            class_name = self.get_window_class_name(hwnd)
            print(f"[INFO] Found window '{window_title}' (Class: {class_name}).")
        else:
            _str = f"[INFO] Window class name could not be gotten for window: '{window_title}'."
            raise RuntimeError(_str)            
        return class_name

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
        ctypes.windll.user32.EnumWindows(self.enumWindowsProc(self.enum_windows_callback), ctypes.byref(data))
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

        self.pulse_status()
        
        # Restart failed child processes
        self.maintain_bridge_health()
        
        # Check Cursor Visibility
        try:
            flags, hcursor, pos = win32gui.GetCursorInfo()
            # 0x00000001 is CURSOR_SHOWING
            is_visible = (flags & 1) 
            
            if not is_visible == self.last_cursor_state:
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
                        print(f"[INFO] Acquired game window!")
                                            
                    # 2. ATOMIC SWAP: Only hold lock to update the dict reference
                    with self.lock:
                        self.game_window_info = new_info
                        self.window_lost = False
                        
                else:
                    # 3. WINDOW IS LOST: Handle scanning
                    if not self.window_lost:
                        print("[WARNING] Game window lost! Scanning for new window...")
                        with self.lock:
                            self.window_lost = True
                    
                    try:
                        # Get window title class name if it doesn't exist
                        if not self.game_window_class_name:
                            self.game_window_class_name = self.get_game_window_class_name(self.window_title_target)

                        # Scan for the window
                        discovered_info = self.get_game_window_info()
                        
                        # If we found it, swap it in
                        with self.lock:
                            self.game_window_info = discovered_info
                            self.window_lost = False
                        print("[INFO] New window handle bound.")
                            
                    except RuntimeError:
                        # Game isn't open yet, just keep waiting
                        pass
                    
            except Exception as e:
                print(f"[ERROR] Window tracking error: {e}")
            
            # Dynamic Sleep: Constant from utils
            sleep_time = WINDOW_FIND_DELAY if self.window_lost else self.window_update_interval
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
            _str = f"No visible window found for class: '{self.game_window_class_name}'."
            raise RuntimeError(_str)
        
        return target_info

    def device_to_game_rel(self, dx, dy):
        """Thread-safe relative mapping."""
        with self.lock:
            if self.window_lost: 
                w = self.screen_w
                h = self.screen_h
            else:
                w = self.game_window_info['width']
                h = self.game_window_info['height']

        return (dx / self.device_width) * w, (dy / self.device_height) * h
    
    def device_to_game_abs(self, x, y):
        """Thread-safe absolute mapping."""
        with self.lock:
            if self.window_lost:
                w = self.screen_w
                h = self.screen_h
                l = 0
                t = 0
            else:
                w = self.game_window_info['width']
                h = self.game_window_info['height']
                l = self.game_window_info['left']
                t = self.game_window_info['top']
            
        return l + (x / self.device_width) * w, t + (y / self.device_height) * h
    
    def dp_to_px(self, dp):
        return dp * (self.dpi / DEF_DPI)

    def px_to_dp(self, px):
        return px * (DEF_DPI / self.dpi)

    def maintain_bridge_health(self):
        """
        Checks if workers are alive; restarts and re-prioritizes if dead.
        """
        bridge = self.interception_bridge
    
        # 1. Check Keyboard Worker
        if not bridge.k_proc.is_alive():
            print(f"\n[CRITICAL] {datetime.now().strftime('%H:%M:%S')} - Keyboard Worker Died!")
            bridge.k_proc = multiprocessing.Process(target=keyboard_worker, args=(bridge.k_queue,), daemon=True)
            bridge.k_proc.start()
            # Re-apply High Priority to the new PID
            set_high_priority(bridge.k_proc.pid, "RE-REVived Keyboard")
            # Safety: Clear the queue to prevent a backlog of old 'stuck' keys firing at once
            while not bridge.k_queue.empty():
                try: 
                    bridge.k_queue.get_nowait()
                except: 
                    break

        # 2. Check Mouse Worker
        if not bridge.m_proc.is_alive():
            print(f"\n[CRITICAL] {datetime.now().strftime('%H:%M:%S')} - Mouse Worker Died!")
            bridge.m_proc = multiprocessing.Process(target=mouse_worker, args=(bridge.m_queue,), daemon=True)
            bridge.m_proc.start()
            set_high_priority(bridge.m_proc.pid, "RE-REVived Mouse")
            # Safety: Clear the queue to prevent a backlog of old 'stuck' mouse movements firing at once
            while not bridge.m_queue.empty():
                try: 
                    bridge.m_queue.get_nowait()
                except: 
                    break

    def pulse_status(self):
        now = time.perf_counter()
        elapsed = now - self.last_pulse_time
    
        if elapsed >= 5.0: # Every 5 seconds
            pps = self.event_count / elapsed # Packets Per Second
        
            # Check if we are lagging
        status = "HEALTHY" if pps > 60 else "LOW RATE"
            if pps == 0: status = "IDLE/DISCONNECTED"

            print(f"[Monitor] Rate: {pps:.1f} Hz | Status: {status} | WASD Block: {self.wasd_block}")
        
            # Reset
            self.event_count = 0
            self.last_pulse_time = now


