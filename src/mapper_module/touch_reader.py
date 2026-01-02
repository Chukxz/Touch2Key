import time
import threading
import subprocess
import re
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
        # Convert Hz to seconds (e.g., 250Hz -> 0.004s)
        self.move_interval = 1.0 / adb_rate_cap if adb_rate_cap > 0 else 0
        self.last_dispatch_time = 0

        # 1. Physical Device Specs
        res = get_screen_size(self.device)
        if res is None: raise RuntimeError("Detected resolution invalid.")
        self.width, self.height = res
        physical_dpi = get_dpi(self.device)

        # 2. Configured Specs
        json_res = config.get('system', {}).get('json_dev_res', [self.width, self.height])
        json_dpi = config.get('system', {}).get('json_dev_dpi', physical_dpi)

        # 3. Validation
        if self.width != json_res[0] or self.height != json_res[1]:
            raise RuntimeError(f"Resolution Mismatch! Physical: {self.width}x{self.height}")
        
        self.res_dpi = [json_res[0], json_res[1], json_dpi]       
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
        print(f"[INFO] TouchReader starting @ {adb_rate_cap}Hz Cap...")
        self.process = None
        threading.Thread(target=self.update_rotation, daemon=True).start()
        threading.Thread(target=self.get_touches, daemon=True).start()

    # (Methods: find_touch_device_event, get_max_slots, parse_hex_signed, rotate_coordinates remain same)

    def get_touches(self):
        current_slot = 0
        while True:
            self.process = subprocess.Popen(
                ["adb", "-s", self.device, "shell", "getevent", "-l", self.device_touch_event],
                stdout=subprocess.PIPE, text=True, bufsize=0 
            )

            try:
                for line in self.process.stdout:
                    line = line.strip()
                    if not line: continue

                    if "ABS_MT_SLOT" in line:
                        current_slot = int(line.split()[-1], 16)
                        self.ensure_slot(current_slot)

                    elif "ABS_MT_TRACKING_ID" in line:
                        tracking_id = self.parse_hex_signed(line.split()[-1])
                        self.ensure_slot(current_slot)
                        prev_id = self.slots[current_slot]['tracking_id']
                        self.slots[current_slot]['tracking_id'] = tracking_id
                        
                        if tracking_id >= 0 and prev_id == -1:
                            self.slots[current_slot]['state'] = 'DOWN'
                            # We reset the start_info to ensure fresh coordinates for is_mouse check
                            self.start_slots[current_slot] = {'x': None, 'y': None, 'timestamp': time.monotonic_ns()}
                            self.active_touches += 1
                        elif tracking_id == -1 and prev_id >= 0: 
                            self.slots[current_slot]['state'] = 'UP'
                            self.active_touches -= 1

                    elif "ABS_MT_POSITION_X" in line:
                        val = int(line.split()[-1], 16)
                        self.ensure_slot(current_slot)
                        self.slots[current_slot]['x'] = val
                        if current_slot in self.start_slots and self.start_slots[current_slot]['x'] is None:
                             self.start_slots[current_slot]['x'] = val

                    elif "ABS_MT_POSITION_Y" in line:
                        val = int(line.split()[-1], 16)
                        self.ensure_slot(current_slot)
                        self.slots[current_slot]['y'] = val
                        if current_slot in self.start_slots and self.start_slots[current_slot]['y'] is None:
                             self.start_slots[current_slot]['y'] = val

                    elif "SYN_REPORT" in line:
                        self.handle_sync(current_slot)

            except Exception as e:
                print(f"[ERROR] ADB Stream Error: {e}")
            
            time.sleep(1.0)

    def handle_sync(self, current_slot):
        """Processes the synchronized touch data with rate limiting."""
        now = time.perf_counter()
        
        # Identify mouse/wasd fingers based on where they first touched
        self.update_mouse_finger()
        self.update_wasd_finger()

        for slot, info in self.slots.items():
            start_info = self.start_slots.get(slot)
            if info['tracking_id'] < 0 or info['x'] is None or info['y'] is None or not start_info:
                continue

            state = info['state']
            
            # --- RATE LIMITING ---
            # We ALWAYS allow DOWN and UP. We cap PRESSED (movement).
            if state == 'PRESSED':
                if (now - self.last_dispatch_time) < self.move_interval:
                    continue
                self.last_dispatch_time = now

            with self.lock:
                rx, ry = self.rotate_coordinates(info['x'], info['y'], self.width, self.height, self.rotation)
                srx, sry = self.rotate_coordinates(start_info['x'], start_info['y'], self.width, self.height, self.rotation)

            touch_event = TouchMapperEvent(
                slot=slot, tracking_id=info['tracking_id'],
                x=rx, y=ry, sx=srx, sy=sry,
                is_mouse=(slot == self.mouse_slot),
                is_wasd=(slot == self.wasd_slot)
            )

            self.mapper_event_dispatcher.dispatch(MapperEvent(action=state, touch=touch_event))

            # State Transition
            if state == 'DOWN':
                self.slots[slot]['state'] = 'PRESSED'
            elif state == 'UP':
                self.slots[slot] = {'timestamp': None, 'x': None, 'y': None, 'tracking_id': -1, 'state': 'IDLE'}
                self.start_slots.pop(slot, None)

    # (Remaining helper methods: update_mouse_finger, update_wasd_finger, stop, etc.)
