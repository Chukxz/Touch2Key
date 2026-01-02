import time
import threading
import subprocess
import re
import os
from .utils import (
    TouchMapperEvent, MapperEvent, get_adb_device, 
    get_screen_size, get_dpi, DEFAULT_ADB_RATE_CAP
)

class TouchReader():
    def __init__(self, config, dispatcher, adb_rate_cap=DEFAULT_ADB_RATE_CAP):
        self.device = get_adb_device()
        self.device_touch_event = self.find_touch_device_event()

        if self.device_touch_event is None:
            raise RuntimeError("No touchscreen device found via ADB.")

        print(f"[INFO] Using touchscreen device: {self.device_touch_event}")
        self.config = config
        self.mapper_event_dispatcher = dispatcher

        # --- PERFORMANCE TUNING ---
        self.move_interval = 1.0 / adb_rate_cap if adb_rate_cap > 0 else 0
        self.last_dispatch_time = 0

        # 1. Physical Device Specs
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

        self.res_dpi = [json_res[0], json_res[1], json_dpi]       
        self.mapper_event_dispatcher.register_callback("ON_CONFIG_RELOAD", self.update_config)

        # State Tracking
        self.slots = {}
        self.active_touches = 0
        self.max_slots = self.get_max_slots()
        self.rotation = 0
        self.rotation_poll_interval = 0.5 
        self.lock = threading.Lock()
        self.side_limit = self.width // 2
        self.running = True

        # --- SELF STARTING THREADS ---
        print(f"[INFO] TouchReader running at {adb_rate_cap}Hz Cap. Side Limit: {self.side_limit}px")
        self.process = None
        threading.Thread(target=self.update_rotation, daemon=True).start()
        threading.Thread(target=self.get_touches, daemon=True).start()

    def find_touch_device_event(self):
        """Finds the correct /dev/input/event node for the touchscreen."""
        try:
            result = subprocess.run(
                ["adb", "-s", self.device, "shell", "getevent", "-lp"],
                capture_output=True, text=True, timeout=2
            )
            lines = result.stdout.splitlines()
            current_device, block, devices = None, [], {}
            for line in lines:
                if line.startswith("add device"):
                    if current_device: devices[current_device] = "\n".join(block)
                    block = []
                    current_device = line.split(":")[1].strip()
                else: block.append(line)
            if current_device: devices[current_device] = "\n".join(block)

            for dev, txt in devices.items():
                if "ABS_MT_POSITION_X" in txt and "INPUT_PROP_DIRECT" in txt: return dev
            for dev, txt in devices.items():
                if "ABS_MT_POSITION_X" in txt: return dev
        except: pass
        return None

    def get_max_slots(self):
        """Detects the maximum number of multi-touch fingers supported."""
        try:
            result = subprocess.run(["adb", "-s", self.device, "shell", "getevent", "-p", self.device_touch_event], capture_output=True, text=True)
            for line in result.stdout.splitlines():
                if "ABS_MT_SLOT" in line and "max" in line:
                    return int(line.split("max")[1].strip().split(',')[0]) + 1
        except: pass
        return 10 

    def update_config(self, *args):
        """Hot-reloads settings from TOML."""
        try:
            json_res = self.config.get('system', {}).get('json_dev_res', [self.width, self.height])
            json_dpi = self.config.get('system', {}).get('json_dev_dpi', 160)
            self.side_limit = json_res[0] // 2
            self.res_dpi[:] = [json_res[0], json_res[1], json_dpi]
        except Exception as e:
            print(f"[ERROR] Config update failed: {e}")

    def update_rotation(self):
        """Monitors Android orientation changes."""
        patterns = [r"mCurrentRotation=(\d+)", r"rotation=(\d+)", r"mCurrentOrientation=(\d+)"]
        while self.running:
            try:
                result = subprocess.run(["adb", "-s", self.device, "shell", "dumpsys", "display"], capture_output=True, text=True, timeout=1)
                for pat in patterns:
                    m = re.search(pat, result.stdout)
                    if m:
                        with self.lock: self.rotation = int(m.group(1)) % 4
                        break
            except: pass
            time.sleep(self.rotation_poll_interval)

    def rotate_coordinates(self, x, y):
        """Adjusts raw coordinates based on device rotation."""
        if self.rotation == 1: return y, self.width - x
        elif self.rotation == 2: return self.width - x, self.height - y
        elif self.rotation == 3: return self.height - y, x
        return x, y

    def _ensure_slot(self, slot):
        if slot not in self.slots:
            self.slots[slot] = {'x': 0, 'y': 0, 'start_x': None, 'start_y': None, 
                                'tid': -1, 'state': 'IDLE', 'is_mouse': False, 'is_wasd': False}

    def parse_hex_signed(self, value_hex):
        val = int(value_hex, 16)
        return val if val < 0x80000000 else val - 0x100000000

    def get_touches(self):
        """The main ADB event streaming loop."""
        current_slot = 0
        while self.running:
            self.process = subprocess.Popen(
                ["adb", "-s", self.device, "shell", "getevent", "-l", self.device_touch_event],
                stdout=subprocess.PIPE, text=True, bufsize=0 
            )

            try:
                for line in self.process.stdout:
                    if not self.running: break
                    parts = line.strip().split()
                    if len(parts) < 3: continue

                    code, val_str = parts[1], parts[2]

                    if "ABS_MT_SLOT" == code:
                        current_slot = int(val_str, 16)
                        self._ensure_slot(current_slot)
                    elif "ABS_MT_TRACKING_ID" == code:
                        tid = self.parse_hex_signed(val_str)
                        self._ensure_slot(current_slot)
                        prev_id = self.slots[current_slot]['tid']
                        self.slots[current_slot]['tid'] = tid
                        if tid >= 0 and prev_id == -1:
                            self.slots[current_slot].update({'state': 'DOWN', 'start_x': None})
                        elif tid == -1:
                            self.slots[current_slot]['state'] = 'UP'
                    elif "ABS_MT_POSITION_X" == code:
                        self.slots[current_slot]['x'] = int(val_str, 16)
                    elif "ABS_MT_POSITION_Y" == code:
                        self.slots[current_slot]['y'] = int(val_str, 16)
                    elif "SYN_REPORT" == code:
                        self.handle_sync()
            except Exception: pass
            if self.running:
                self.stop_process()
                time.sleep(1.0)

    def handle_sync(self):
        """Processes and dispatches synchronized events with the rate cap."""
        now = time.perf_counter()
        
        for slot, data in list(self.slots.items()):
            if data['state'] == 'IDLE': continue

            # Initial Identification
            if data['state'] == 'DOWN':
                if data['x'] is None or data['y'] is None: continue
                data['start_x'], data['start_y'] = data['x'], data['y']
                data['is_mouse'] = (data['x'] >= self.side_limit)
                data['is_wasd'] = not data['is_mouse']

            # Rate Limit for movement
            if data['state'] == 'PRESSED':
                if (now - self.last_dispatch_time) < self.move_interval:
                    continue
                self.last_dispatch_time = now

            with self.lock:
                rx, ry = self.rotate_coordinates(data['x'], data['y'])
                sx, sy = self.rotate_coordinates(data['start_x'], data['start_y'])

            event = MapperEvent(
                action=data['state'],
                touch=TouchMapperEvent(
                    slot=slot, tracking_id=data['tid'], x=rx, y=ry, sx=sx, sy=sy,
                    is_mouse=data['is_mouse'], is_wasd=data['is_wasd']
                )
            )
            self.mapper_event_dispatcher.dispatch(event)

            if data['state'] == 'DOWN': data['state'] = 'PRESSED'
            elif data['state'] == 'UP': self.reset_slot(slot)

    def reset_slot(self, slot):
        self.slots[slot] = {'x': 0, 'y': 0, 'start_x': None, 'start_y': None, 
                            'tid': -1, 'state': 'IDLE', 'is_mouse': False, 'is_wasd': False}

    def stop_process(self):
        """Kills the active ADB subprocess."""
        if self.process:
            try:
                self.process.terminate()
                self.process.wait(timeout=2)
            except:
                self.process.kill()

    def stop(self):
        """Stops all threads and cleanup."""
        self.running = False
        self.stop_process()
