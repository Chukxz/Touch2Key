from __future__ import annotations
from typing import TYPE_CHECKING

import time
import threading
import subprocess
import re

from mapper_module.utils import (
    TouchEvent,
    ADB,
    DOWN,
    UP,
    PRESSED,
    IDLE,
    ROTATION_POLL_INTERVAL,
    SHORT_DELAY,
    LONG_DELAY,
    get_adb_device,
    is_device_online,
    get_screen_size,
    wireless_connect,
)

if TYPE_CHECKING:
    from .config import AppConfig
    from mapper_module.utils import MapperEventDispatcher


class TouchReader:
    def __init__(
        self, config: AppConfig, dispatcher: MapperEventDispatcher, rate_cap: float
    ):
        self.config = config
        self.mapper_event_dispatcher = dispatcher

        # State Tracking
        self.device = None
        self.device_touch_event = None
        self.slots = {}
        self.active_touches = 0
        self.max_slots = self._get_max_slots()
        self.rotation = 0
        self.rotation_poll_interval = ROTATION_POLL_INTERVAL
        self.rotation_lock = threading.Lock()
        self.finger_lock = threading.Lock()
        self.running = True
        self.is_visible = True
        self.touch_lost = False

        # Identity tracking
        self.side_limit = 0
        self.last_mouse_slot = None
        self.mouse_slot = None
        self.last_wasd_slot = None
        self.wasd_slot = None
        self.width = 1080
        self.height = 1920
        self.json_width = self.width
        self.json_height = self.height
        self.scale_x = 1
        self.scale_y = 1
        self.matrix = (0, 0, 0, 0, 0, 0)

        self._update_config()

        # PERFORMANCE TUNING
        self.adb_rate_cap = rate_cap
        self.move_interval = (
            1.0 / self.adb_rate_cap if self.adb_rate_cap > 0 else 0.0001
        )
        self.last_dispatch_times = []
        for _ in range(self.max_slots):
            self.last_dispatch_times.append(0)

        self.touch_event_processor = None

        self.mapper_event_dispatcher.register_callback(
            "ON_CONFIG_RELOAD", self._update_config
        )
        self.mapper_event_dispatcher.register_callback(
            "ON_MENU_MODE_TOGGLE", self._set_is_visible
        )

        # SELF STARTING THREADS
        self.process = None
        threading.Thread(target=self._update_rotation, daemon=True).start()
        threading.Thread(target=self._get_touches, daemon=True).start()
        self.wireless_thread = threading.Thread(
            target=self._connect_wirelessly, daemon=True
        )
        self.wireless_thread.start()

    # FINGER IDENTITY LOGIC
    def _update_finger_identities(self):
        """Identify the oldest finger on each side to assign as the dedicated Mouse or WASD finger."""

        if self.is_visible:
            eligible_finger = []
            for slot, data in list(self.slots.items()):
                if (
                    data["tid"] != -1
                    and data["start_x"] is not None
                    and data["start_y"] is not None
                ):
                    eligible_finger.append((slot, data["timestamp"]))

            self.last_mouse_slot = self.mouse_slot
            self.mouse_slot = (
                min(eligible_finger, key=lambda x: x[1])[0] if eligible_finger else None
            )
            self.last_wasd_slot = self.wasd_slot
            self.wasd_slot = None
            return

        eligible_mouse = []
        eligible_wasd = []

        is_left_handed = self.config.get("system").get("left_handed", False)

        for slot, data in list(self.slots.items()):
            if (
                data["tid"] != -1
                and data["start_x"] is not None
                and data["start_y"] is not None
            ):
                # Determine if the finger is on the 'Primary' or 'Secondary' side
                is_on_left = data["start_x"] < self.side_limit

                if is_on_left == is_left_handed:
                    eligible_mouse.append((slot, data["timestamp"]))
                else:
                    eligible_wasd.append((slot, data["timestamp"]))

        # Use the finger with the earliest timestamp (oldest) for each role
        self.last_mouse_slot = self.mouse_slot
        self.mouse_slot = (
            min(eligible_mouse, key=lambda x: x[1])[0] if eligible_mouse else None
        )
        self.last_wasd_slot = self.wasd_slot
        self.wasd_slot = (
            min(eligible_wasd, key=lambda x: x[1])[0] if eligible_wasd else None
        )

    # CONFIG & SPECS
    def _connect_wirelessly(self):
        connecting = True
        while self.running and connecting:
            with self.config.config_lock:
                device = self.device

            ret = wireless_connect(device, False)
            if ret:
                success, dev = ret

                if success:
                    connecting = False
                    try:
                        with self.config.config_lock:
                            self.device = dev
                            self._configure_device()
                    except Exception:
                        with self.config.config_lock:
                            self.device = None
                    else:
                        with self.rotation_lock:
                            self._update_matrix()

                else:
                    time.sleep(LONG_DELAY)
                    continue

    def _find_touch_device_event(self):
        if not ADB is None and not self.device is None:
            try:
                result = subprocess.run(
                    [ADB, "-s", self.device, "shell", "getevent", "-lp"],
                    capture_output=True,
                    text=True,
                    timeout=2,
                )

                lines = result.stdout.splitlines()
                current_device, block, devices = None, [], {}
                for line in lines:
                    if line.startswith("add device"):
                        if current_device:
                            devices[current_device] = "\n".join(block)
                        block = []
                        current_device = line.split(":")[1].strip()
                    else:
                        block.append(line)
                if current_device:
                    devices[current_device] = "\n".join(block)

                for dev, txt in devices.items():
                    if "ABS_MT_POSITION_X" in txt and "INPUT_PROP_DIRECT" in txt:
                        return dev
                for dev, txt in devices.items():
                    if "ABS_MT_POSITION_X" in txt:
                        return dev
            except Exception:
                pass

        else:
            print(
                f"\n[TOUCHREADER] - ADB not configured properly. Check ADB path and device connection."
            )

        return None

    def _get_max_slots(self):
        if (
            not ADB is None
            and not self.device is None
            and not self.device_touch_event is None
        ):
            try:
                result = subprocess.run(
                    [
                        ADB,
                        "-s",
                        self.device,
                        "shell",
                        "getevent",
                        "-p",
                        self.device_touch_event,
                    ],
                    capture_output=True,
                    text=True,
                    timeout=2,
                )
                for line in result.stdout.splitlines():
                    if "ABS_MT_SLOT" in line and "max" in line:
                        return int(line.split("max")[1].strip().split(",")[0]) + 1
            except Exception:
                pass

        else:
            print(
                f"\n[TOUCHREADER] - ADB not configured properly. Check ADB path and device connection."
            )

        return 10

    def _update_config(self):
        with self.config.config_lock:
            try:
                json_res = self.config.get("system", {}).get(
                    "json_dev_res", [self.width, self.height]
                )

                self.json_width, self.json_height = json_res
                self.scale_x = self.width / self.json_width
                self.scale_y = self.height / self.json_height

                print(
                    f"\n[TOUCHREADER] - Auto-Scaling Active: X={self.scale_x:.2f}, Y={self.scale_y:.2f}."
                )

            except Exception as e:
                print(f"\n[TOUCHREADER] - Config update failed: {e}.")
                return

        with self.rotation_lock:
            self._update_matrix()

    def _update_rotation(self):
        patterns = [
            r"mCurrentRotation=(\d+)",
            r"rotation=(\d+)",
            r"mCurrentOrientation=(\d+)",
            r"mUserRotation=(\d+)",
        ]
        while self.running:
            if not self.device:
                time.sleep(SHORT_DELAY)
                continue

            try:
                result = subprocess.run(
                    [ADB, "-s", self.device, "shell", "dumpsys", "display"],
                    capture_output=True,
                    text=True,
                    timeout=2,
                )
                for pat in patterns:
                    m = re.search(pat, result.stdout)
                    if m:
                        with self.rotation_lock:
                            self.rotation = int(m.group(1)) % 4
                            self._update_matrix()
                        break
            except Exception:
                pass
            time.sleep(self.rotation_poll_interval)

    def _update_matrix(self):
        sx = 1 / self.scale_x
        sy = 1 / self.scale_y
        w = self.json_width
        h = self.json_height

        if self.rotation == 0:  # 0°
            self.matrix = (sx, 0, 0, 0, sy, 0)
            self.side_limit = w // 2
        elif self.rotation == 1:  # 90° CW
            self.matrix = (0, sy, 0, -sx, 0, w)
            self.side_limit = h // 2
        elif self.rotation == 2:  # 180°
            self.matrix = (-sx, 0, w, 0, -sy, h)
            self.side_limit = w // 2
        elif self.rotation == 3:  # 270° CW
            self.matrix = (0, -sy, h, sx, 0, 0)
            self.side_limit = h // 2

    def _rotate_norm_coordinates(self, x, y):
        with self.rotation_lock:
            matrix_snapshot = self.matrix
        return self._rotate_norm_coordinates_local(x, y, matrix_snapshot)

    def _rotate_norm_coordinates_local(self, x, y, matrix):
        if x is None or y is None:
            return x, y

        a, b, c, d, e, f = matrix
        # Standard affine transformation formula
        res_x = a * x + b * y + c
        res_y = d * x + e * y + f

        return res_x, res_y

    def get_rotation(self):
        with self.rotation_lock:
            return self.rotation

    def _ensure_slot(self, slot):
        if slot not in self.slots:
            self._reset_slot(slot)

    def _reset_slot(self, slot):
        self.slots[slot] = {
            "x": None,
            "y": None,
            "start_x": None,
            "start_y": None,
            "tid": -1,
            "state": IDLE,
            "timestamp": 0,
        }

    def _parse_hex_signed(self, value_hex):
        val = int(value_hex, 16)
        return val if val < 0x80000000 else val - 0x100000000

    def _configure_device(self):
        if self.device is None:
            self.device = (
                get_adb_device()
            )  # Raises runtime error if no eligible adb device is found
        if not is_device_online(self.device):
            raise RuntimeError(f"\n[TOUCHREADER] - {self.device} is not online.")
        self.device_touch_event = self._find_touch_device_event()
        if self.device_touch_event is None:
            raise RuntimeError("\n[TOUCHREADER] - No touchscreen device found via ADB.")
        print(f"\n[TOUCHREADER] - Using touchscreen device: {self.device_touch_event}.")

        real_slots = self._get_max_slots()
        if real_slots > len(self.last_dispatch_times):
            # Extend to cover new slots
            while len(self.last_dispatch_times) < real_slots:
                self.last_dispatch_times.append(0)
            self.max_slots = real_slots

        # Physical Device Specs
        res = get_screen_size(self.device)
        if res is None:
            raise RuntimeError("\n[TOUCHREADER] - Detected resolution invalid.")
        self.width, self.height = res

        # Get Configured Specs
        json_res = self.config.get("system", {}).get(
            "json_dev_res", [self.width, self.height]
        )
        self.json_width, self.json_height = json_res
        self.scale_x = self.width / self.json_width
        self.scale_y = self.height / self.json_height

        print(
            f"\n[TOUCHREADER] - Auto-Scaling Active: X={self.scale_x:.2f}, Y={self.scale_y:.2f}. Max slots: {self.max_slots}."
        )

    def _get_touches(self):
        current_slot = 0

        while self.running:
            try:
                with self.config.config_lock:
                    self._configure_device()

            except RuntimeError as e:
                with self.config.config_lock:
                    self.device = None
                if not self.touch_lost:
                    self.touch_lost = True
                    print(
                        f"{e}\n[TOUCHREADER] - Error: ADB Device disconnected. Attempting to connect..."
                    )

                time.sleep(LONG_DELAY)
                continue

            else:
                with self.rotation_lock:
                    self._update_matrix()

            self.touch_lost = False

            if (
                ADB is not None
                and self.device is not None
                and self.device_touch_event is not None
            ):
                self.process = subprocess.Popen(
                    [
                        ADB,
                        "-s",
                        self.device,
                        "shell",
                        "getevent",
                        "-l",
                        self.device_touch_event,
                    ],
                    stdout=subprocess.PIPE,
                    text=True,
                    bufsize=0,
                )

                if self.process.stdout is None:
                    print(f"\n[TOUCHREADER] - Failed to read from ADB process stdout.")
                    self.process = None
                    time.sleep(LONG_DELAY)
                    continue

                try:
                    for line in self.process.stdout:
                        if not self.running:
                            break

                        if "ABS_MT" not in line and "SYN_REPORT" not in line:
                            continue

                        parts = line.split()
                        code, val_str = parts[-2], parts[-1]

                        if "ABS_MT_SLOT" == code:
                            current_slot = int(val_str, 16)
                            self._ensure_slot(current_slot)

                        elif "ABS_MT_TRACKING_ID" == code:
                            tid = self._parse_hex_signed(val_str)
                            self._ensure_slot(current_slot)
                            prev_id = self.slots[current_slot]["tid"]
                            self.slots[current_slot]["tid"] = tid

                            if tid >= 0 and prev_id == -1:
                                self.slots[current_slot].update(
                                    {
                                        "state": DOWN,
                                        "start_x": None,
                                        "start_y": None,
                                        "timestamp": time.perf_counter_ns(),
                                    }
                                )
                                self.active_touches += 1
                            elif tid == -1 and prev_id != -1:
                                self.slots[current_slot]["state"] = UP
                                self.active_touches -= 1

                        elif "ABS_MT_POSITION_X" == code:
                            val = int(val_str, 16)
                            self.slots[current_slot]["x"] = val
                            if self.slots[current_slot]["start_x"] is None:
                                tmp = self._rotate_norm_coordinates(
                                    val, self.slots[current_slot]["start_y"]
                                )
                                (
                                    self.slots[current_slot]["start_x"],
                                    self.slots[current_slot]["start_y"],
                                ) = tmp

                        elif "ABS_MT_POSITION_Y" == code:
                            val = int(val_str, 16)
                            self.slots[current_slot]["y"] = val
                            if self.slots[current_slot]["start_y"] is None:
                                tmp = self._rotate_norm_coordinates(
                                    self.slots[current_slot]["start_x"], val
                                )
                                (
                                    self.slots[current_slot]["start_x"],
                                    self.slots[current_slot]["start_y"],
                                ) = tmp

                        elif "SYN_REPORT" == code:
                            self._handle_sync()

                except Exception as e:
                    print(
                        f"\n[TOUCHREADER] - ADB Stream interrupted: {e}. Restarting..."
                    )
                    self._handle_sync(True)
                    self.mouse_slot = None
                    self.wasd_slot = None

            else:
                print(
                    f"\n[TOUCHREADER] - ADB not configured properly. Check ADB path and device connection."
                )
                time.sleep(LONG_DELAY)

            self._stop_process()

            if self.running:
                time.sleep(SHORT_DELAY)
                if not self.wireless_thread.is_alive():
                    self.wireless_thread = threading.Thread(
                        target=self._connect_wirelessly, daemon=True
                    )
                    self.wireless_thread.start()

    def _handle_sync(self, lift_up=False):
        now = time.perf_counter()
        # Grab a local snapshot of the matrix once per sync
        with self.rotation_lock:
            matrix_snapshot = self.matrix

        # Only update identities if a slot state changed from DOWN or UP
        with self.finger_lock:
            needs_identity_update = any(
                s["state"] in [DOWN, UP] for s in self.slots.values()
            )
            if needs_identity_update:
                self._update_finger_identities()

        for slot, data in list(self.slots.items()):
            if lift_up:
                data["state"] = UP
            if data["state"] == IDLE:
                continue

            # Rate Limit for movement (PRESSED state) only
            if data["state"] == PRESSED:
                if (now - self.last_dispatch_times[slot]) < self.move_interval:
                    continue
                self.last_dispatch_times[slot] = now

            rx, ry = self._rotate_norm_coordinates_local(
                data["x"], data["y"], matrix_snapshot
            )
            m_s = self.mouse_slot
            w_s = self.wasd_slot

            if data["state"] == UP:
                m_s = self.last_mouse_slot
                w_s = self.last_wasd_slot

            if rx is not None and ry is not None and self.touch_event_processor:
                with self.config.config_lock:
                    try:
                        action = data["state"]
                        touch_event = TouchEvent(
                            slot=slot,
                            id=data["tid"],
                            x=rx,
                            y=ry,
                            sx=data["start_x"],
                            sy=data["start_y"],
                            timestamp=data["timestamp"],
                            is_mouse=(slot == m_s),
                            is_wasd=(slot == w_s),
                        )
                        self.touch_event_processor(action, touch_event)
                    except Exception:
                        pass

            if data["state"] == DOWN:
                data["state"] = PRESSED
            elif data["state"] == UP:
                self._reset_slot(slot)

        if lift_up:
            self.active_touches = 0

    def _stop_process(self):
        with self.config.config_lock:
            self.device = None

        if self.process:
            try:
                self.process.terminate()
                self.process.wait(timeout=2)
            except Exception:
                if self.process:
                    self.process.kill()

    def _set_is_visible(self, _is_visible):
        with self.config.config_lock:
            self.is_visible = _is_visible
        with self.finger_lock:
            self._update_finger_identities()

    def stop(self):
        self.running = False
        self._stop_process()

    def bind_touch_event(self, touch_event_processor):
        self.touch_event_processor = touch_event_processor
