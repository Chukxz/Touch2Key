import time
import ctypes
from ctypes import wintypes
import mouse_mapper
import key_mapper
import threading
from bridge import InterceptionBridge

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

class TouchMapperEvent:
    def __init__(self, slot, tracking_id, x, y, sx, sy, action, is_mouse, is_wasd):
        self.slot = slot
        self.id = tracking_id
        self.x = x
        self.y = y
        self.sx = sx
        self.sy = sy
        self.is_mouse = is_mouse
        self.is_wasd = is_wasd
        self.action = action # UP, DOWN, PRESSED
        
class TouchMapperEventDispatcher:
    def __init__(self):    
        # The Registry
        self.callback_registry = {
            "ON_TOUCH_DOWN": [],
            "ON_TOUCH_UP": [],
            "ON_TOUCH_PRESSED": []
        }

    def register_callback(self, event_type, func):
        self.callback_registry[event_type].append(func)
    
    def unregister_callback(self, event_type, func):
        self.callback_registry[event_type].remove(func)

    def dispatch(self, event_object):
        if event_object.action == "DOWN":
            for func in self.callback_registry["ON_TOUCH_DOWN"]:
                func(event_object) # Execute the callback
        elif event_object.action == "UP":
            for func in self.callback_registry["ON_TOUCH_UP"]:
                func(event_object) # Execute the callback
        elif event_object.action == "PRESSED":
            for func in self.callback_registry["ON_TOUCH_PRESSED"]:
                func(event_object) # Execute the callback

class Mapper(TouchMapperEventDispatcher):
    def __init__(self, width, height, dpi, window_title="Gameloop(64beta)"):
        super().__init__()
        self.game_window_class_name = self.get_game_window_class_name(window_title)
        self.game_window_info = self.get_game_window_info()
        self._last_window_update = 0.0
        self._window_update_interval = 0.016  # seconds
        self.device_width = width
        self.device_height = height
        self.dpi = dpi
        self.lock = threading.Lock()
        self.interception_bridge = InterceptionBridge(self.dpi)
        self.mouse_mapper = mouse_mapper.MouseMapper(self.interception_bridge)
        self.key_mapper = key_mapper.KeyMapper(self.interception_bridge)

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
    
    def accept_touch_event(self, slot, tracking_id, x, y, sx, sy, action, is_mouse=False, is_wasd=False):
        event = TouchMapperEvent(slot, tracking_id, x, y, sx, sy, action, is_mouse, is_wasd)
        if is_mouse:
            self.mouse_mapper.accept_touch_event(event)
        else:
            self.key_mapper.accept_touch_event(event)