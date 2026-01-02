import time
import threading
import subprocess
import re
from .utils import TouchMapperEvent, MapperEvent, get_adb_device, get_screen_size, get_dpi

class TouchReader():
    def __init__(self, config):
        self.device = get_adb_device()
        self.device_touch_event = self.find_touch_device_event()
        
        if self.device_touch_event is None:
            raise RuntimeError("No touchscreen device found via ADB.")
        
        print(f"[INFO] Using touchscreen device: {self.device_touch_event}")
        self.config = config
        
        # 1. Get Physical Device Specs
        res = get_screen_size(self.device)
        if res is None:
            raise RuntimeError("Detected resolution invalid.")
        
        self.width, self.height = res
        physical_dpi = get_dpi(self.device)

        # 2. Get Configured Specs
        json_res = config.get('system', {}).get('json_dev_res', [self.width, self.height])
        json_dpi = config.get('system', {}).get('json_dev_dpi', physical_dpi)
        
        # 3. Strict Validation
        if self.width != json_res[0] or self.height != json_res[1]:
            raise RuntimeError(f"Resolution Mismatch! Physical: {self.width}x{self.height} vs Config: {json_res[0]}x{json_res[1]}")
            
        if physical_dpi != json_dpi:
            raise RuntimeError(f"DPI Mismatch! Physical: {physical_dpi} vs Config: {json_dpi}")

        self.res_dpi = [json_res[0], json_res[1], json_dpi]       
        self.mapper_event_dispatcher = config.mapper_event_dispatcher
        
        self.mapper_event_dispatcher.register_callback("ON_CONFIG_RELOAD", self.update_config)
        
        # State Tracking
        self.slots = {}
        self.start_slots = {}
        self.active_touches = 0
        self.max_slots = self.get_max_slots()
        self.rotation = 0
        self.rotation_poll_interval = 0.5 
        self.lock = threading.Lock()
        self.side_limit = self.width // 2
        self.mouse_slot = None
        self.wasd_slot = None  

        # --- SELF STARTING THREADS ---
        print("[INFO] TouchReader starting background threads...")
        self.process = None
        threading.Thread(target=self.update_rotation, daemon=True).start()
        threading.Thread(target=self.get_touches, daemon=True).start()

    # ... (Rest of the methods: update_config, get_touches, etc. remain exactly as before) ...
    def update_config(self):
        """Updates internal state when settings.toml changes."""
        try:
            json_res = self.config.get('system', {}).get('json_dev_res', [self.width, self.height])
            json_dpi = self.config.get('system', {}).get('json_dev_dpi', 160)
            current_device_dpi = self.res_dpi[2]
            
            if json_res[0] != self.width or json_res[1] != self.height:
                print(f"[ERROR] CONFIG REJECTED: JSON Res {json_res} != Physical Res {self.width}x{self.height}")
                return 
            
            if json_dpi != current_device_dpi:
                print(f"[ERROR] CONFIG REJECTED: JSON DPI {json_dpi} != Physical DPI {current_device_dpi}")
                return 

            # In-Place Update so Mapper sees it immediately
            self.res_dpi[:] = [json_res[0], json_res[1], json_dpi]
            print(f"[INFO] TouchReader configuration updated: {self.res_dpi}")
            
        except Exception as e:
            print(f"[ERROR] Failed to update TouchReader config: {e}")

    def get_max_slots(self):
        try:
            result = subprocess.run(
                ["adb", "-s", self.device, "shell", "getevent", "-p", self.device_touch_event],
                capture_output=True, text=True, timeout=2
            )
            for line in result.stdout.splitlines():
                if "ABS_MT_SLOT" in line and "max" in line:
                    parts = line.split()
                    for i, part in enumerate(parts):
                        if part == "max":
                            max_slot = int(parts[i+1].strip(','))
                            return max_slot + 1
        except Exception:
            pass
        return 10 

    def find_touch_device_event(self):
        try:
            result = subprocess.run(
                ["adb", "-s", self.device, "shell", "getevent", "-lp"],
                capture_output=True, text=True, timeout=2
            )
        except Exception:
            return None

        lines = result.stdout.splitlines()
        current_device = None
        block = []
        devices = {}

        for line in lines:
            line = line.rstrip()
            if line.startswith("add device"):
                if current_device and block:
                    devices[current_device] = "\n".join(block)
                block = []
                current_device = line.split(":")[1].strip()
            else:
                block.append(line)
        if current_device and block:
            devices[current_device] = "\n".join(block)

        # Priority 1: Direct Input Touchscreens
        for dev, txt in devices.items():
            if ("ABS_MT_POSITION_X" in txt and "ABS_MT_POSITION_Y" in txt and "INPUT_PROP_DIRECT" in txt):
                return dev
        
        # Priority 2: Any Touchscreen
        for dev, txt in devices.items():
            if "ABS_MT_POSITION_X" in txt and "ABS_MT_POSITION_Y" in txt:
                return dev

        return None

    def parse_hex_signed(self, value_hex: str) -> int:
        val = int(value_hex, 16)
        return val if val < 0x80000000 else val - 0x100000000

    def rotate_coordinates(self, x, y, width, height, rotation_code):
        if rotation_code == 0:   # Portrait
            return x, y
        elif rotation_code == 1: # Landscape (90 deg CW)
            return y, width - x
        elif rotation_code == 2: # Upside Down
            return width - x, height - y
        elif rotation_code == 3: # Landscape (90 deg CCW)
            return height - y, x
        return x, y

    def update_rotation(self):
        patterns = [r"mCurrentRotation=(\d+)", r"rotation=(\d+)", r"mCurrentOrientation=(\d+)"]
        while True:
            try:
                result = subprocess.run(
                    ["adb", "-s", self.device, "shell", "dumpsys", "display"],
                    capture_output=True, text=True, timeout=1
                )
                out = result.stdout
                for pat in patterns:
                    m = re.search(pat, out)
                    if m:
                        with self.lock:
                            self.rotation = int(m.group(1)) % 4
                        break
            except Exception:
                pass
            time.sleep(self.rotation_poll_interval) 

    def ensure_slot(self, current_slot):
        if current_slot not in self.slots and current_slot < self.max_slots:
            self.slots[current_slot] = {'timestamp': None, 'x': None, 'y': None, 'tracking_id': -1, 'state': 'IDLE'}

    def update_mouse_finger(self):
        eligible = [
            (slot, info['timestamp'])
            for slot, info in self.start_slots.items()
            if info and info['timestamp'] is not None and info['x'] >= self.side_limit
        ]
        if eligible:
            self.mouse_slot = min(eligible, key=lambda x: x[1])[0]
        else:
            self.mouse_slot = None

    def update_wasd_finger(self):
        eligible = [
            (slot, info['timestamp'])
            for slot, info in self.start_slots.items()
            if info and info['timestamp'] is not None and info['x'] < self.side_limit
        ]
        if eligible:
            self.wasd_slot = min(eligible, key=lambda x: x[1])[0]
        else:
            self.wasd_slot = None
            
    def get_touches(self):
        current_slot = 0
        while True:
            print("[INFO] Starting ADB event stream...")
            self.process = subprocess.Popen(
                ["adb", "-s", self.device, "shell", "getevent", "-l", self.device_touch_event],
                stdout=subprocess.PIPE,
                text=True,
                bufsize=0 
            )

            try:
                for line in self.process.stdout:
                    line = line.strip()
                    if not line: continue

                    if "ABS_MT_SLOT" in line:
                        new_slot = int(line.split()[-1], 16)
                        current_slot = new_slot
                        self.ensure_slot(current_slot)

                    elif "ABS_MT_TRACKING_ID" in line:
                        tracking_id = self.parse_hex_signed(line.split()[-1])
                        self.ensure_slot(current_slot)
                        prev_id = self.slots[current_slot]['tracking_id']
                        self.slots[current_slot]['tracking_id'] = tracking_id
                        self.slots[current_slot]['timestamp'] = time.monotonic_ns()
                        
                        if tracking_id >= 0 and prev_id == -1:
                            self.slots[current_slot]['state'] = 'DOWN'
                            self.start_slots[current_slot] = self.slots[current_slot].copy()
                            self.active_touches += 1
                        elif tracking_id == -1 and prev_id >= 0: 
                            self.slots[current_slot]['state'] = 'UP'
                            self.active_touches -= 1
                                            
                    elif "ABS_MT_POSITION_X" in line:
                        val = int(line.split()[-1], 16)
                        self.ensure_slot(current_slot)
                        self.slots[current_slot]['x'] = val
                        self.slots[current_slot]['timestamp'] = time.monotonic_ns()
                        if current_slot in self.start_slots and self.start_slots[current_slot]['x'] is None:
                             self.start_slots[current_slot]['x'] = val
                    
                    elif "ABS_MT_POSITION_Y" in line:
                        val = int(line.split()[-1], 16)
                        self.ensure_slot(current_slot)
                        self.slots[current_slot]['y'] = val
                        self.slots[current_slot]['timestamp'] = time.monotonic_ns()
                        if current_slot in self.start_slots and self.start_slots[current_slot]['y'] is None:
                             self.start_slots[current_slot]['y'] = val

                    elif "SYN_REPORT" in line:
                        self.update_mouse_finger()
                        self.update_wasd_finger()
                        
                        for slot, info in self.slots.items():
                            start_info = self.start_slots.get(slot, None)
                            
                            if info['tracking_id'] >= 0 and info['x'] is not None and info['y'] is not None and start_info is not None:
                                with self.lock:
                                    rx, ry = self.rotate_coordinates(
                                        info['x'], info['y'], self.width, self.height, self.rotation
                                    )
                                    srx, sry = self.rotate_coordinates(
                                        start_info['x'], start_info['y'], self.width, self.height, self.rotation
                                    )
                                
                                touch_event = TouchMapperEvent(
                                    slot=slot,
                                    tracking_id=info['tracking_id'],
                                    x=rx, y=ry,
                                    sx=srx, sy=sry,
                                    is_mouse=(slot == self.mouse_slot),
                                    is_wasd=(slot == self.wasd_slot)
                                )
                                
                                mapper_event = MapperEvent(
                                    action=info['state'],
                                    touch=touch_event
                                )
                                
                                self.mapper_event_dispatcher.dispatch(mapper_event)
                                
                                if info['state'] == 'DOWN':
                                    self.slots[slot]['state'] = 'PRESSED'
                                
                                elif info['state'] == 'UP':
                                    self.slots[slot] = {'timestamp': None, 'x': None, 'y': None, 'tracking_id': -1, 'state': 'IDLE'}
                                    self.start_slots.pop(slot, None)

            except Exception as e:
                print(f"[ERROR] ADB Stream Error: {e}")
            
            if self.process:
                try:
                    self.process.kill()
                    self.process.wait()
                except:
                    pass
            
            print("[INFO] Restarting ADB touch listener in 1 second...")
            time.sleep(1.0)
    
    def stop(self):
        """Kills the ADB process and stops the stream."""
        if self.process:
            self.process.terminate()
            self.process.wait()
            print("[TouchReader] ADB Stream terminated.")