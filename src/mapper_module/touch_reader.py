import time
import threading
import subprocess
import re
from utils import TouchMapperEvent, MapperEvent, get_adb_device, get_screen_size, get_dpi


class TouchReader():
    def __init__(self, config):
        self.device = get_adb_device()
        self.device_touch_event = self.find_touch_device_event()
        if self.device_touch_event is None:
            raise RuntimeError("No touchscreen device found via ADB.")
        print(f"[INFO] Using touchscreen device: {self.device_touch_event}")
        self.config = config
        
        res = get_screen_size(self.device)
        if res is None:
            raise RuntimeError("Detected resolution invalid.")
        else:
            w, h = res
            tmp_w = config.config_data['system']['json_dev_res'][0]
            tmp_h = config.config_data['system']['json_dev_res'][1]
            if w != tmp_w or h != tmp_h:
                raise RuntimeError("Detected resolution doesn't match JSON resolution.")
        
        dpi = config.config_data['system']['json_dev_dpi']
        tmp_dpi = get_dpi(self.device)        
        if dpi != tmp_dpi:
            raise RuntimeError("Detected DPI doesn't match JSON DPI.")
        
        self.res_dpi = [tmp_w, tmp_h, tmp_dpi]       
        self.mapper_event_dispatcher = config.mapper_event_dispatcher
        self.slots = {}
        self.start_slots = {}
        self.active_touches = 0
        self.max_slots = self.get_max_slots()
        self.rotation = 0
        self.rotation_poll_interval = 0.1 # seconds
        self.lock = threading.Lock()
        self.side_limit = self.width // 2
        self.mouse_slot = None
        self.wasd_slot = None  

    def get_max_slots(self):
        result = subprocess.run(
            ["adb", "-s", self.device, "shell", "getevent", "-p", self.device_touch_event],
            capture_output=True, text=True
        )

        for line in result.stdout.splitlines():
            if "ABS_MT_SLOT" in line and "max" in line:
                parts = line.split()
                for i, part in enumerate(parts):
                    if part == "max":
                        max_slot = int(parts[i+1].strip(','))
                        return max_slot + 1  # total slots
        return 10  # default fallback

    def find_touch_device_event(self):
        result = subprocess.run(
            ["adb", "-s", self.device, "shell", "getevent", "-lp"],
            capture_output=True, text=True
        )

        lines = result.stdout.splitlines()
        current_device = None
        block = []
        devices = {}

        # Collect device blocks
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

        print("[INFO] Candidate devices found:")
        for dev, txt in devices.items():
            print(f"- {dev}")
            if ("ABS_MT_POSITION_X" in txt and
                "ABS_MT_POSITION_Y" in txt and
                "INPUT_PROP_DIRECT" in txt):
                print(f"  -> Looks like a touchscreen!")
            elif "ABS_MT_POSITION_X" in txt and "ABS_MT_POSITION_Y" in txt:
                print(f"  -> Might be a touchscreen (fallback)")

        # First, try strict match
        for dev, txt in devices.items():
            if ("ABS_MT_POSITION_X" in txt and
                "ABS_MT_POSITION_Y" in txt and
                "INPUT_PROP_DIRECT" in txt):
                return dev

        # Fallback: looser match
        for dev, txt in devices.items():
            if "ABS_MT_POSITION_X" in txt and "ABS_MT_POSITION_Y" in txt:
                return dev

        # None found
        return None

    def parse_hex_signed(self, value_hex: str) -> int:
        """Convert hex string from getevent to signed integer."""
        val = int(value_hex, 16)
        return val if val < 0x80000000 else val - 0x100000000

    def rotate_coordinates(self, x, y, width, height, rotation_code):
        """Rotate coordinates based on rotation code (0-3)."""
        if rotation_code == 0:  # Portrait
            return x, y
        elif rotation_code == 1:  # Landscape right (screen rotated clockwise)
            return y, width - x
        elif rotation_code == 2:  # Portrait upside-down
            return width - x, height - y
        elif rotation_code == 3:  # Landscape left (screen rotated counter-clockwise)
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
                        try:
                            with self.lock:
                                self.rotation = int(m.group(1)) % 4
                        except Exception:
                            pass
                        break
            except subprocess.TimeoutExpired:
                pass
            except Exception:
                pass
            time.sleep(self.rotation_poll_interval) 

    def ensure_slot(self, current_slot):
        if current_slot not in self.slots and current_slot < self.max_slots:
            self.slots[current_slot] = {'timestamp': None, 'x': None, 'y': None, 'tracking_id': -1, 'state': 'IDLE'}

    def update_mouse_finger(self):
        # earliest-started finger on right side (slot is int)
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
        # earliest-started finger on right side (slot is int)
        
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

        proc = subprocess.Popen(
            ["adb", "-s", self.device, "shell", "getevent", "-l", self.device_touch_event],
            stdout=subprocess.PIPE,
            text=True,
            bufsize=0
        )

        try:
            for line in proc.stdout:
                line = line.strip()
                if not line:
                    continue

                # Switch to slot
                if "ABS_MT_SLOT" in line:
                    new_slot = int(line.split()[-1], 16)
                    current_slot = new_slot
                    self.ensure_slot(current_slot)

                # Finger down/up
                elif "ABS_MT_TRACKING_ID" in line:
                    tracking_id = self.parse_hex_signed(line.split()[-1])
                    self.ensure_slot(current_slot)
                    prev_id = self.slots[current_slot]['tracking_id']
                    self.slots[current_slot]['tracking_id'] = tracking_id
                    self.slots[current_slot]['timestamp'] = time.monotonic_ns()
                    
                    # Finger Up
                    if tracking_id >= 0 and prev_id == -1:
                        self.slots[current_slot]['state'] = 'DOWN'
                        self.start_slots[current_slot] = self.slots[current_slot]
                        self.active_touches += 1
                        self.start_slots[current_slot]['active_touches'] = self.active_touches
                            
                    # Finger Down
                    elif tracking_id == -1 and prev_id >= 0: 
                        self.slots[current_slot]['state'] = 'UP'
                        self.active_touches -= 1
                                        
                # Position X                    
                elif "ABS_MT_POSITION_X" in line:
                    val = int(line.split()[-1], 16)
                    self.ensure_slot(current_slot)
                    self.slots[current_slot]['x'] = val
                    self.slots[current_slot]['timestamp'] = time.monotonic_ns()
                    
                    try:
                        res = self.start_slots.pop(current_slot)
                        if res['x'] is None:
                            res['x'] = val
                        self.start_slots[current_slot] = res
                    except Exception:
                        pass
                    
                # Position Y
                elif "ABS_MT_POSITION_Y" in line:
                    val = int(line.split()[-1], 16)
                    self.ensure_slot(current_slot)
                    self.slots[current_slot]['y'] = val
                    self.slots[current_slot]['timestamp'] = time.monotonic_ns()

                    try:
                        res = self.start_slots.pop(current_slot)
                        if res['y'] is None:
                            res['y'] = val
                        self.start_slots[current_slot] = res
                    except Exception:
                        pass

                # SYN_REPORT - process current touches
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
                                slot,
                                info['tracking_id'],
                                rx,
                                ry,
                                srx,
                                sry,
                                is_mouse = (slot == self.mouse_slot),
                                is_wasd = (slot == self.wasd_slot)
                            )
                            
                            mapper_event = MapperEvent(
                                info['state'],
                                touch_event
                            )
                            
                            self.mapper_event_dispatcher.dispatch(mapper_event)
                            
                            if info['state'] != 'UP':
                                self.slots[slot]['state'] = 'PRESSED'
                            
                            if info['state'] == 'UP':
                                # Reset slot info after UP
                                self.slots[slot] = {'timestamp': None, 'x': None, 'y': None, 'tracking_id': -1, 'state': 'IDLE'}
                                try:
                                    self.start_slots.pop(slot)
                                except Exception:
                                    pass                    

                # allow clean exit if process terminates
                if proc.poll() is not None:
                    break
        except Exception:
            # on error, make sure proc is killed, then restart after short sleep
            try:
                proc.kill()
            except Exception:
                pass
        time.sleep(0.1)  # small backoff before restarting adb getevent