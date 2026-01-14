import time
import threading
import subprocess
import re
from .utils import (
    TouchEvent, MapperEvent, get_adb_device,
    get_screen_size, get_dpi, DOWN, UP, PRESSED
    )

class TouchReader():
    def __init__(self, config, dispatcher, rate_cap, latency):
        self.config = config
        self.mapper_event_dispatcher = dispatcher
           
        self.mapper_event_dispatcher.register_callback("ON_CONFIG_RELOAD", self.update_config)
        # self.mapper_event_dispatcher.register_callback("ON_NETWORK_LAG", self.log_lag)

        # State Tracking
        self.slots = {}
        self.active_touches = 0
        self.max_slots = self.get_max_slots()
        self.rotation = 0
        self.rotation_poll_interval = 0.5 
        self.lock = threading.Lock()
        self.running = True

        # Identity tracking
        self.side_limit = 0
        self.mouse_slot = None
        self.wasd_slot = None
        self.scale_x = 1
        self.scale_y = 1
        
        init_time = 0

        # --- PERFORMANCE TUNING ---
        self.adb_rate_cap = rate_cap
        self.move_interval = 1.0 / self.adb_rate_cap if self.adb_rate_cap > 0 else 0
        self.last_dispatch_times = []
        for _ in range(self.max_slots):
            self.last_dispatch_times.append(init_time)
        
        # --- LATENCY MONITORING ---
        self.packet_time_acc = 0.0
        self.packet_time_n = 0
        self.last_packet_time = init_time
        self.latency_threshold = latency
        
        self.touch_event_processor = None

        # --- SELF STARTING THREADS ---
        print(f"[INFO] Reading pressed touches at {self.adb_rate_cap}Hz Cap.")
        self.process = None
        threading.Thread(target=self.update_rotation, daemon=True).start()
        threading.Thread(target=self.get_touches, daemon=True).start()

    # --- FINGER IDENTITY LOGIC ---

    def update_finger_identities(self):
        """
        Implements 'Upside' logic: Identify the oldest finger on each side
        to assign as the dedicated Mouse or WASD finger.
        """
        eligible_mouse = []
        eligible_wasd = []

        for slot, data in list(self.slots.items()):
            if data['tid'] != -1 and data['start_x'] is not None:
                # Check which side the finger started on
                if data['start_x'] >= self.side_limit:
                    eligible_mouse.append((slot, data['timestamp']))
                else:
                    eligible_wasd.append((slot, data['timestamp']))
        

        # Use the finger with the earliest timestamp (oldest) for each role
        self.mouse_slot = min(eligible_mouse, key=lambda x: x[1])[0] if eligible_mouse else None
        self.wasd_slot = min(eligible_wasd, key=lambda x: x[1])[0] if eligible_wasd else None

    # --- CONFIG & SPECS ---

    def find_touch_device_event(self):
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
        try:
            result = subprocess.run(["adb", "-s", self.device, "shell", "getevent", "-p", self.device_touch_event], capture_output=True, text=True)
            for line in result.stdout.splitlines():
                if "ABS_MT_SLOT" in line and "max" in line:
                    return int(line.split("max")[1].strip().split(',')[0]) + 1
        except: pass
        return 10

    def update_config(self):
        try:
            json_res = self.config.get('system', {}).get('json_dev_res', [self.width, self.height])
            json_dpi = self.config.get('system', {}).get('json_dev_dpi', 160)
            self.res_dpi[:] = [json_res[0], json_res[1], json_dpi]
        except Exception as e:
            print(f"[ERROR] Config update failed: {e}")            

    def update_rotation(self):
        patterns = [r"mCurrentRotation=(\d+)", r"rotation=(\d+)", r"mCurrentOrientation=(\d+)", r"mUserRotation=(\d+)"]
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

    def rotate_norm_coordinates(self, x, y):
        if x is None or y is None:
            return x, y
        
        # Normalize physical pixels back to "JSON Space"
        # If phone is 2000px and JSON was 1000px, we divide by 2.
        logic_x = x / self.scale_x
        logic_y = y / self.scale_y

        if 
            self.config.config_lock.acquire(blocking=False):
            try:
                with self.lock:
                    if self.rotation == 1: # 90 deg
                        self.side_limit = self.json_height // 2
                        return logic_y, self.json_width - logic_x
                    elif self.rotation == 2: # 180 deg
                        self.side_limit = self.json_width // 2
                        return self.json_width - logic_x, self.json_height - logic_y
                    elif self.rotation == 3: # 270 deg
                        self.side_limit = self.json_height // 2
                        return self.json_height - logic_y, logic_x
                    else: # 0 deg
                        self.side_limit = self.json_width // 2
                        return logic_x, logic_y
            finally:
                self.config.config_lock.release()


    def ensure_slot(self, slot):
        if slot not in self.slots:
            self.reset_slot(slot)
            
    def reset_slot(self, slot):
        self.slots[slot] = {
            'x': None, 'y': None, 'start_x': None, 'start_y': None, 
            'tid': -1, 'state': 'IDLE', 'timestamp': 0
        }

    def parse_hex_signed(self, value_hex):
        val = int(value_hex, 16)
        return val if val < 0x80000000 else val - 0x100000000


    def configure_device(self):
        try:
            self.device = get_adb_device() # Raises runtime error is no eligible adb device is found
            self.device_touch_event = self.find_touch_device_event()
            if self.device_touch_event is None:
                raise RuntimeError("No touchscreen device found via ADB.")
            print(f"[INFO] Using touchscreen device: {self.device_touch_event}")
            
            # 1. Physical Device Specs
            res = get_screen_size(self.device)
            if res is None:
                raise RuntimeError("Detected resolution invalid.")
            
            self.width, self.height = res
            physical_dpi = get_dpi(self.device)
            
            # 2. Get Configured Specs
            json_res = self.config.get('system', {}).get('json_dev_res', [self.width, self.height])
            json_dpi = self.config.get('system', {}).get('json_dev_dpi', physical_dpi)
            
            self.json_width, self.json_height = json_res
            self.scale_x = self.width / self.json_width
            self.scale_y = self.height / self.json_height
            
            print(f"[INFO] Auto-Scaling Active: X={self.scale_x:.2f}, Y={self.scale_y:.2f}")
            self.res_dpi = [json_res[0], json_res[1], json_dpi]
            
            return self.width, self.height, physical_dpi
            
        except RuntimeError:
            return None

    def get_touches(self):
        current_slot = 0

        while self.running:
            configure_device = self.configure_device()
            if not configure_device:
                print("[Warning] ADB Device disconnected. Retrying in 2s...")
                time.sleep(2.0)
                continue            

            self.mapper_event_dispatcher.dispatch(MapperEvent(action="CONFIGURE_DEVICE", res_dpi=configure_device))

            self.process = subprocess.Popen(
                ["adb", "-s", self.device, "shell", "getevent", "-l", self.device_touch_event],
                stdout=subprocess.PIPE, text=True, bufsize=0 
            )

            try:
                for line in self.process.stdout:                    
                    if not self.running: break
                    
                    # self.get_latency()
                    
                    parts = line.strip().split()
                    if len(parts) < 3: continue

                    code, val_str = parts[1], parts[2]
                    
                    if "ABS_MT_SLOT" == code:
                        current_slot = int(val_str, 16)
                        self.ensure_slot(current_slot)
                        
                    elif "ABS_MT_TRACKING_ID" == code:
                        tid = self.parse_hex_signed(val_str)
                        self.ensure_slot(current_slot)
                        prev_id = self.slots[current_slot]['tid']
                        self.slots[current_slot]['tid'] = tid
                        
                        if tid >= 0 and prev_id == -1:
                            self.slots[current_slot].update({
                                'state': DOWN, 
                                'start_x': None, 'start_y': None,
                                'timestamp': time.monotonic_ns()
                            })
                        elif tid == -1:
                            self.slots[current_slot]['state'] = UP
                            
                    elif "ABS_MT_POSITION_X" == code:
                        val = int(val_str, 16)
                        self.slots[current_slot]['x'] = val                        
                        if self.slots[current_slot]['start_x'] is None:
                            tmp = self.rotate_norm_coordinates(val, self.slots[current_slot]['start_y'])
                            self.slots[current_slot]['start_x'], self.slots[current_slot]['start_y'] = tmp
                            
                    elif "ABS_MT_POSITION_Y" == code:
                        val = int(val_str, 16)
                        self.slots[current_slot]['y'] = val                        
                        if self.slots[current_slot]['start_y'] is None:
                            tmp = self.rotate_norm_coordinates(self.slots[current_slot]['start_x'], val)
                            self.slots[current_slot]['start_x'], self.slots[current_slot]['start_y'] = tmp

                    elif "SYN_REPORT" == code:
                        self.handle_sync()
                        
            except Exception as e:
                print(f"[Error] ADB Stream interrupted: {e}")
                with self.lock:
                    for slot in self.slots:
                        self.reset_slot(slot) # Clear all touches on disconnect
                        
            if self.running:
                self.stop_process()
                time.sleep(1.0)

    def handle_sync(self):
        now = time.perf_counter()
        
        # Only update identities if a slot state changed from DOWN or UP
        needs_identity_update = any(s['state'] in [DOWN, UP] for s in self.slots.values())
        if needs_identity_update:
            self.update_finger_identities()
                
        for slot, data in list(self.slots.items()):
            if data['state'] == 'IDLE': continue

            # Rate Limit for movement (PRESSED state) only
            if data['state'] == PRESSED:
                if (now - self.last_dispatch_times[slot]) < self.move_interval:
                    continue
                self.last_dispatch_times[slot] = now
            
            rx, ry = self.rotate_norm_coordinates(data['x'], data['y'])

            if self.touch_event_processor:
                try:
                    action = data['state']
                    
                    touch_event = TouchEvent(
                        slot=slot, 
                        id=data['tid'], 
                        x=rx, y=ry,
                        sx=data['start_x'], sy=data['start_y'],
                        is_mouse=(slot == self.mouse_slot), 
                        is_wasd=(slot == self.wasd_slot),
                    )
                    
                   if self.config.config_lock.acquire(blocking=False):
                       try:
                           self.touch_event_processor(action, touch_event)
                       finally:
                           self.config.config_lock.release()
 
               except:
                   print(f"[INFO] Event with action: {action} could not be processed")

            if data['state'] == DOWN: 
                data['state'] = PRESSED
            elif data['state'] == UP: 
                self.reset_slot(slot)

    def stop_process(self):
        if self.process:
            try:
                self.process.terminate()
                # Wait up to 2 seconds for clean exit
                self.process.wait(timeout=2)
            except Exception:
                # Force kill if it hangs
                if self.process:
                    self.process.kill()

    def stop(self):
        self.running = False
        self.stop_process()

    def get_latency(self):
        current_time = time.perf_counter()
        time_since_last = current_time - self.last_packet_time                                                            
        self.packet_time_n += 1
        self.packet_time_acc += time_since_last
        self.last_packet_time = current_time
        
        if self.packet_time_acc >= 1.0:
            avg_t = self.packet_time_acc / self.packet_time_n
            if avg_t > self.latency_threshold:
                self.mapper_event_dispatcher.dispatch(MapperEvent(action="NETWORK", pac_n=self.packet_time_n, pac_t=avg_t))
                
            self.packet_time_acc = 0.0
            self.packet_time_n = 0

    def log_lag(self, pac_n, pac_t):
        print(f"[Network] Jitter detected, {pac_n} packets captured in approx. 1s with an average latency of {pac_t * 1000:.2f}ms")
    
    
    def bind_touch_event(self, touch_event_processor):
        self.touch_event_processor = touch_event_processor
