import subprocess

DEF_DPI = 160

class TouchMapperEvent:
    def __init__(self, slot, tracking_id, x, y, sx, sy, is_mouse, is_wasd):
        self.slot = slot
        self.id = tracking_id
        self.x = x
        self.y = y
        self.sx = sx
        self.sy = sy
        self.is_mouse = is_mouse
        self.is_wasd = is_wasd

class MapperEvent:
    def __init__(self, action, touch: TouchMapperEvent | None = None):
        self.touch = touch
        self.action = action # UP, DOWN, PRESSED, CONFIG, CSV
        
class MapperEventDispatcher:
    def __init__(self):    
        # The Registry
        self.callback_registry = {
            "ON_TOUCH_DOWN": [],
            "ON_TOUCH_UP": [],
            "ON_TOUCH_PRESSED": [],
            "ON_CONFIG_RELOAD": [],
            "ON_CSV_RELOAD": []
        }

    def register_callback(self, event_type, func):
        self.callback_registry[event_type].append(func)
    
    def unregister_callback(self, event_type, func):
        self.callback_registry[event_type].remove(func)

    def dispatch(self, event_object: MapperEvent):
        if event_object.action == "DOWN":
            for func in self.callback_registry["ON_TOUCH_DOWN"]:
                func(event_object.touch) # Execute the callback
        elif event_object.action == "UP":
            for func in self.callback_registry["ON_TOUCH_UP"]:
                func(event_object.touch) # Execute the callback
        elif event_object.action == "PRESSED":
            for func in self.callback_registry["ON_TOUCH_PRESSED"]:
                func(event_object.touch) # Execute the callback
        elif event_object.action == "CONFIG":
            for func in self.callback_registry["ON_CONFIG_RELOAD"]:
                func() # Execute the callback
        elif event_object.action == "CSV":
            for func in self.callback_registry["ON_CSV_RELOAD"]:
                func() # Execute the callback

    def get_screen_size():
        """Detect screen resolution (portrait natural)."""
        result = subprocess.run(
            ["adb", "-s", self.device, "shell", "wm", "size"], capture_output=True, text=True
        )
        output = result.stdout.strip()
        if "Physical size" in output:
            w, h = map(int, output.split(":")[-1].strip().split("x"))
            return w, h

        return None
    
    def get_dpi(self):
        """Detect screen DPI, fallback to 160."""
        try:
            result = subprocess.run(["adb", "-s", self.device, "shell", "getprop", "ro.sf.lcd_density"],
                                    capture_output=True, text=True, timeout=1)
            val = result.stdout.strip()
            return int(val) if val else DEF_DPI
        except Exception:
            return DEF_DPI