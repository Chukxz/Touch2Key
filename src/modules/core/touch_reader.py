from __future__ import annotations

import logging
import re
import subprocess
import threading
import time
from typing import TYPE_CHECKING, Any

from modules.utils import (
    ADB,
    DEFAULT_ADB_RATE_CAP,
    LONG_DELAY,
    ROTATION_POLL_INTERVAL,
    SHORT_DELAY,
    Point,
    TouchEvent,
    TouchPhase,
    get_adb_device,
    get_screen_size,
    is_device_online,
    wireless_connect,
)

if TYPE_CHECKING:
    from .config import AppConfig
    from modules.utils import MapperEventDispatcher

logger = logging.getLogger("modules.core.touch_reader")


class TouchReader:
    def __init__(
        self,
        config: AppConfig,
        dispatcher: MapperEventDispatcher,
        rate_cap: float = DEFAULT_ADB_RATE_CAP,
    ):
        self.config = config
        self.mapper_event_dispatcher = dispatcher

        self.device: str | None = None
        self.device_touch_event: str | None = None
        self.slots: dict[int, dict] = {}
        self.active_touches = 0
        self.max_slots = 10
        self.rotation = 0
        self.rotation_poll_interval = ROTATION_POLL_INTERVAL
        self.rotation_lock = threading.Lock()
        self.running = True

        self.width = 1080
        self.height = 1920
        self.matrix = (1.0, 0.0, 0.0, 0.0, 1.0, 0.0)

        self.adb_rate_cap = rate_cap
        self.move_interval = 1.0 / self.adb_rate_cap if self.adb_rate_cap > 0 else 0.0001
        self.last_dispatch_times = [0.0] * self.max_slots

        self.touch_event_processor: Any = None
        self.process: subprocess.Popen | None = None

        self.mapper_event_dispatcher.register_callback("ON_CONFIG_RELOAD", self._on_config_reload)

        threading.Thread(target=self._update_rotation, daemon=True).start()
        threading.Thread(target=self._get_touches, daemon=True).start()
        self.wireless_thread = threading.Thread(target=self._connect_wirelessly, daemon=True)
        self.wireless_thread.start()

    def _on_config_reload(self) -> None:
        """Dynamically updates rate-limiting intervals and matrix transforms."""
        with self.config.config_lock:
            new_cap = getattr(self.config.settings, "adb_rate_cap", self.adb_rate_cap)
            if new_cap > 0 and new_cap != self.adb_rate_cap:
                self.adb_rate_cap = float(new_cap)
                self.move_interval = 1.0 / self.adb_rate_cap
                logger.info(
                    "TouchReader pacing updated on the fly: %.1f Hz (%.4fs interval)",
                    self.adb_rate_cap,
                    self.move_interval,
                )

        with self.rotation_lock:
            self._update_matrix()

    def _connect_wirelessly(self) -> None:
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

                        if self.process is not None:
                            try:
                                self.process.terminate()
                            except Exception:
                                pass
                    except Exception:
                        with self.config.config_lock:
                            self.device = None
                    else:
                        with self.rotation_lock:
                            self._update_matrix()
                else:
                    time.sleep(LONG_DELAY)
            else:
                time.sleep(LONG_DELAY)

    def _find_touch_device_event(self) -> str | None:
        if ADB is not None and self.device is not None:
            try:
                result = subprocess.run(
                    [ADB, "-s", self.device, "shell", "getevent", "-lp"],
                    capture_output=True,
                    text=True,
                    timeout=2,
                )
                current_device, block, devices = None, [], {}
                for line in result.stdout.splitlines():
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
                    if "ABS_MT_POSITION_X" in txt:
                        return dev
            except Exception:
                pass
        return None

    def _get_max_slots(self) -> int:
        if ADB is not None and self.device is not None and self.device_touch_event is not None:
            try:
                result = subprocess.run(
                    [ADB, "-s", self.device, "shell", "getevent", "-p", self.device_touch_event],
                    capture_output=True,
                    text=True,
                    timeout=2,
                )
                for line in result.stdout.splitlines():
                    if "ABS_MT_SLOT" in line and "max" in line:
                        return int(line.split("max")[1].strip().split(",")[0]) + 1
            except Exception:
                pass
        return 10

    def _update_rotation(self) -> None:
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

    def _update_matrix(self) -> None:
        w = float(self.width)
        h = float(self.height)
        if self.rotation == 0:
            self.matrix = (1.0, 0.0, 0.0, 0.0, 1.0, 0.0)
        elif self.rotation == 1:
            self.matrix = (0.0, 1.0, 0.0, -1.0, 0.0, w)
        elif self.rotation == 2:
            self.matrix = (-1.0, 0.0, w, 0.0, -1.0, h)
        elif self.rotation == 3:
            self.matrix = (0.0, -1.0, h, 1.0, 0.0, 0.0)

    def _rotate_coordinates(
        self, x: float | None, y: float | None, matrix: tuple[float, ...]
    ) -> tuple[float, float]:
        if x is None or y is None:
            return 0.0, 0.0
        a, b, c, d, e, f = matrix
        return a * x + b * y + c, d * x + e * y + f

    def get_rotation(self) -> int:
        with self.rotation_lock:
            return self.rotation

    def _ensure_slot(self, slot: int) -> None:
        if slot not in self.slots:
            self.slots[slot] = {
                "x": None,
                "y": None,
                "tid": -1,
                "phase": None,
                "timestamp": 0.0,
            }

    @staticmethod
    def _parse_hex_signed(value_hex: str) -> int:
        val = int(value_hex, 16)
        return val if val < 0x80000000 else val - 0x100000000

    def _configure_device(self) -> None:
        if self.device is None:
            self.device = get_adb_device()
        if not is_device_online(self.device):
            raise RuntimeError(f"Device {self.device} is not online.")

        self.device_touch_event = self._find_touch_device_event()
        if self.device_touch_event is None:
            raise RuntimeError("No touchscreen event device found.")

        real_slots = self._get_max_slots()
        if real_slots > len(self.last_dispatch_times):
            while len(self.last_dispatch_times) < real_slots:
                self.last_dispatch_times.append(0.0)
            self.max_slots = real_slots

        res = get_screen_size(self.device)
        if res:
            self.width, self.height = res
        self._update_matrix()

    def _get_touches(self) -> None:
        current_slot = 0
        while self.running:
            try:
                with self.config.config_lock:
                    self._configure_device()
            except RuntimeError:
                with self.config.config_lock:
                    self.device = None
                time.sleep(LONG_DELAY)
                continue

            if ADB is not None and self.device is not None and self.device_touch_event is not None:
                self.process = subprocess.Popen(
                    [ADB, "-s", self.device, "shell", "getevent", "-l", self.device_touch_event],
                    stdout=subprocess.PIPE,
                    text=True,
                    bufsize=0,
                )
                if self.process.stdout is None:
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

                        if code == "ABS_MT_SLOT":
                            current_slot = int(val_str, 16)
                            self._ensure_slot(current_slot)
                        elif code == "ABS_MT_TRACKING_ID":
                            tid = self._parse_hex_signed(val_str)
                            self._ensure_slot(current_slot)
                            prev_id = self.slots[current_slot]["tid"]
                            self.slots[current_slot]["tid"] = tid

                            if tid >= 0 and prev_id == -1:
                                self.slots[current_slot].update(
                                    {
                                        "phase": TouchPhase.DOWN,
                                        "timestamp": time.perf_counter(),
                                    }
                                )
                                self.active_touches += 1
                            elif tid == -1 and prev_id != -1:
                                self.slots[current_slot]["phase"] = TouchPhase.UP
                                self.active_touches -= 1
                        elif code == "ABS_MT_POSITION_X":
                            self._ensure_slot(current_slot)
                            self.slots[current_slot]["x"] = int(val_str, 16)
                        elif code == "ABS_MT_POSITION_Y":
                            self._ensure_slot(current_slot)
                            self.slots[current_slot]["y"] = int(val_str, 16)
                        elif code == "SYN_REPORT":
                            self._handle_sync()
                except Exception:
                    self._handle_sync(lift_up=True)

            self._stop_process()
            if self.running:
                time.sleep(SHORT_DELAY)

    def _handle_sync(self, lift_up: bool = False) -> None:
        now = time.perf_counter()
        with self.rotation_lock:
            matrix = self.matrix

        for slot, data in list(self.slots.items()):
            if lift_up:
                data["phase"] = TouchPhase.UP
            if data["phase"] is None:
                continue

            if data["phase"] is TouchPhase.MOVE:
                if (now - self.last_dispatch_times[slot]) < self.move_interval:
                    continue
                self.last_dispatch_times[slot] = now

            rx, ry = self._rotate_coordinates(data["x"], data["y"], matrix)

            if data["x"] is not None and data["y"] is not None and self.touch_event_processor:
                try:
                    event = TouchEvent(
                        contact_id=slot,
                        phase=data["phase"],
                        position=Point(rx, ry),
                        timestamp=data["timestamp"],
                    )
                    self.touch_event_processor(event)
                except Exception as e:
                    logger.debug("Error processing touch event: %s", e)

            if data["phase"] is TouchPhase.DOWN:
                data["phase"] = TouchPhase.MOVE
            elif data["phase"] is TouchPhase.UP:
                self.slots[slot] = {
                    "x": None,
                    "y": None,
                    "tid": -1,
                    "phase": None,
                    "timestamp": 0.0,
                }

        if lift_up:
            self.active_touches = 0

    def _stop_process(self) -> None:
        with self.config.config_lock:
            self.device = None
        if self.process:
            try:
                self.process.terminate()
                self.process.wait(timeout=2)
            except Exception:
                if self.process:
                    self.process.kill()

    def stop(self) -> None:
        self.running = False
        self._stop_process()

    def bind_touch_event(self, processor: Any) -> None:
        self.touch_event_processor = processor
