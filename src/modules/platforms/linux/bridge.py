from __future__ import annotations

import logging
import multiprocessing
import struct
import threading
from datetime import datetime as _datetime

from modules.utils import (
    BUTTON_4_DOWN,
    BUTTON_4_UP,
    BUTTON_5_DOWN,
    BUTTON_5_UP,
    BUTTON_PING,
    KEEPALIVE_INTERVAL,
    KEY_CONFIG,
    KEY_PING,
    LEFT_BUTTON_DOWN,
    LEFT_BUTTON_UP,
    MIDDLE_BUTTON_DOWN,
    MIDDLE_BUTTON_UP,
    MOUSE_SCANCODES,
    PACK_ABS_STRUCT,
    PACK_BUTTON_STRUCT,
    PACK_KEY_STRUCT,
    PACK_REL_STRUCT,
    PACK_TYPEMATIC_STRUCT,
    PACK_WHEEL_STRUCT,
    RIGHT_BUTTON_DOWN,
    RIGHT_BUTTON_UP,
    SCANCODES,
    TASK_ABS,
    TASK_BUTTON,
    TASK_REL,
    TASK_WHEEL,
)
from ..base import AbstractBridge
from .workers import keyboard_worker, mouse_worker

logger = logging.getLogger("modules.platforms.linux.bridge")


class UInputBridge(AbstractBridge):
    def __init__(self, window_manager, system_config):
        self.window_manager = window_manager
        self.system_config = system_config
        self.screen_w, self.screen_h = window_manager.get_screen_dimensions()
        self.bridge_lock = threading.RLock()

        self._mouse_left_down = False
        self._mouse_right_down = False
        self._mouse_middle_down = False
        self._mouse_button4_down = False
        self._mouse_button5_down = False
        self._pressed_keys: set[int] = set()

        self._cached_typematic = {
            "enabled": True,
            "delay_ms": 250.0,
            "rate_hz": 30.0,
            "exclude_scancodes": set(),
        }

        self._k_respawn_lock = threading.Lock()
        self._m_respawn_lock = threading.Lock()
        self._k_respawning = False
        self._m_respawning = False

        self.k_pipe_read, self.k_pipe_write = multiprocessing.Pipe(duplex=False)
        self.k_proc: multiprocessing.Process | None = None

        self.m_pipe_read, self.m_pipe_write = multiprocessing.Pipe(duplex=False)
        self.mb_pipe_read, self.mb_pipe_write = multiprocessing.Pipe(duplex=False)
        self.m_proc: multiprocessing.Process | None = None

        self._stop_heartbeat = threading.Event()
        self.heartbeat_thread = threading.Thread(
            target=self._heartbeat_loop, name="Keepalive", daemon=True
        )

        self._respawn_callback = None
        self.k_device_handle = None
        self.m_device_handle = None

        self.log_queue = multiprocessing.Queue()
        self._log_consumer_thread: threading.Thread | None = None
        self._stop_log_event = threading.Event()

    def set_respawn_callback(self, callback):
        self._respawn_callback = callback

    def update_typematic(
        self,
        enabled: bool,
        delay_ms: float,
        rate_hz: float,
        exclude_scancodes: set[int],
    ) -> None:
        with self.bridge_lock:
            self._cached_typematic["enabled"] = enabled
            self._cached_typematic["delay_ms"] = delay_ms
            self._cached_typematic["rate_hz"] = rate_hz
            self._cached_typematic["exclude_scancodes"] = set(exclude_scancodes)

            delay_ns = int(delay_ms * 1_000_000)
            interval_sec = 1.0 / max(1.0, rate_hz)
            codes = list(exclude_scancodes)

            payload = bytearray(
                PACK_TYPEMATIC_STRUCT.pack(
                    KEY_CONFIG, enabled, delay_ns, interval_sec, len(codes)
                )
            )
            for code in codes:
                payload.extend(struct.pack("<H", code))

            try:
                self.k_pipe_write.send_bytes(bytes(payload))
            except OSError:
                pass

    def _consume_worker_logs(self) -> None:
        """Background thread in the engine process that reads from the queue and logs."""
        while not self._stop_log_event.is_set():
            try:
                msg = self.log_queue.get(timeout=0.1)
                if msg:
                    logger.info("[Worker] %s", msg)
            except Exception:
                continue

    def start_worker_processes(self, k_device_handle=None, m_device_handle=None):
        self._stop_log_event.clear()
        self._log_consumer_thread = threading.Thread(
            target=self._consume_worker_logs, daemon=True
        )
        self._log_consumer_thread.start()

        with self.bridge_lock:
            self.k_device_handle = k_device_handle
            self.m_device_handle = m_device_handle

            self.k_proc = multiprocessing.Process(
                target=keyboard_worker,
                name="Keyboard Worker",
                args=(self.k_pipe_read, self.log_queue),
                daemon=True,
            )
            self.k_proc.start()
            self.system_config.set_high_priority(self.k_proc.pid, "Keyboard")
            self.k_pipe_read.close()

            self.m_proc = multiprocessing.Process(
                target=mouse_worker,
                name="Mouse Worker",
                args=(self.m_pipe_read, self.mb_pipe_read, self.log_queue),
                daemon=True,
            )
            self.m_proc.start()
            self.system_config.set_high_priority(self.m_proc.pid, "Mouse")
            self.mb_pipe_read.close()
            self.m_pipe_read.close()

            self.update_typematic(
                self._cached_typematic["enabled"],
                self._cached_typematic["delay_ms"],
                self._cached_typematic["rate_hz"],
                self._cached_typematic["exclude_scancodes"],
            )

            if not self.heartbeat_thread.is_alive():
                self.heartbeat_thread.start()

            logger.info(
                f"[BRIDGE] - UInput Dual Engine Started. K-PID: {self.k_proc.pid} | M-PID: {self.m_proc.pid}."
            )

    def reload_devices(
        self, new_k_handle: int | None, new_m_handle: int | None
    ) -> None:
        pass

    def key_down(self, code: int) -> None:
        with self.bridge_lock:
            self._pressed_keys.add(code)
            try:
                self.k_pipe_write.send_bytes(PACK_KEY_STRUCT.pack(int(code), 1))
            except OSError:
                self.selective_release()

    def key_up(self, code: int) -> None:
        with self.bridge_lock:
            try:
                self.k_pipe_write.send_bytes(PACK_KEY_STRUCT.pack(int(code), 0))
            except OSError:
                self.selective_release()
            else:
                self._pressed_keys.discard(code)

    def mouse_move_rel(self, dx: int, dy: int) -> None:
        try:
            self.m_pipe_write.send_bytes(
                PACK_REL_STRUCT.pack(TASK_REL, int(dx), int(dy))
            )
        except OSError:
            pass

    def mouse_move_abs(self, x: int, y: int) -> None:
        abs_x = max(0, min(65535, int((x / self.screen_w) * 65535)))
        abs_y = max(0, min(65535, int((y / self.screen_h) * 65535)))
        try:
            self.m_pipe_write.send_bytes(
                PACK_ABS_STRUCT.pack(TASK_ABS, int(abs_x), int(abs_y))
            )
        except OSError:
            pass

    def wheel(self, dx: float, dy: float) -> None:
        """Dispatches wheel motion deltas to the motion pipe where TASK_WHEEL is handled."""
        with self.bridge_lock:
            try:
                self.m_pipe_write.send_bytes(
                    PACK_WHEEL_STRUCT.pack(TASK_WHEEL, int(round(dx)), int(round(dy)))
                )
            except OSError:
                pass

    def left_click_down(self) -> None:
        with self.bridge_lock:
            try:
                self.mb_pipe_write.send_bytes(
                    PACK_BUTTON_STRUCT.pack(TASK_BUTTON, LEFT_BUTTON_DOWN)
                )
            except OSError:
                self.selective_release()
            else:
                self._mouse_left_down = True

    def left_click_up(self) -> None:
        with self.bridge_lock:
            try:
                self.mb_pipe_write.send_bytes(
                    PACK_BUTTON_STRUCT.pack(TASK_BUTTON, LEFT_BUTTON_UP)
                )
            except OSError:
                self.selective_release()
            else:
                self._mouse_left_down = False

    def right_click_down(self) -> None:
        with self.bridge_lock:
            try:
                self.mb_pipe_write.send_bytes(
                    PACK_BUTTON_STRUCT.pack(TASK_BUTTON, RIGHT_BUTTON_DOWN)
                )
            except OSError:
                self.selective_release()
            else:
                self._mouse_right_down = True

    def right_click_up(self) -> None:
        with self.bridge_lock:
            try:
                self.mb_pipe_write.send_bytes(
                    PACK_BUTTON_STRUCT.pack(TASK_BUTTON, RIGHT_BUTTON_UP)
                )
            except OSError:
                self.selective_release()
            else:
                self._mouse_right_down = False

    def middle_click_down(self) -> None:
        with self.bridge_lock:
            try:
                self.mb_pipe_write.send_bytes(
                    PACK_BUTTON_STRUCT.pack(TASK_BUTTON, MIDDLE_BUTTON_DOWN)
                )
            except OSError:
                self.selective_release()
            else:
                self._mouse_middle_down = True

    def middle_click_up(self) -> None:
        with self.bridge_lock:
            try:
                self.mb_pipe_write.send_bytes(
                    PACK_BUTTON_STRUCT.pack(TASK_BUTTON, MIDDLE_BUTTON_UP)
                )
            except OSError:
                self.selective_release()
            else:
                self._mouse_middle_down = False

    def button4_down(self) -> None:
        """Dispatches Mouse 4 (BTN_SIDE / Back) press."""
        with self.bridge_lock:
            try:
                self.mb_pipe_write.send_bytes(
                    PACK_BUTTON_STRUCT.pack(TASK_BUTTON, BUTTON_4_DOWN)
                )
            except OSError:
                self.selective_release()
            else:
                self._mouse_button4_down = True

    def button4_up(self) -> None:
        """Dispatches Mouse 4 (BTN_SIDE / Back) release."""
        with self.bridge_lock:
            try:
                self.mb_pipe_write.send_bytes(
                    PACK_BUTTON_STRUCT.pack(TASK_BUTTON, BUTTON_4_UP)
                )
            except OSError:
                self.selective_release()
            else:
                self._mouse_button4_down = False

    def button5_down(self) -> None:
        """Dispatches Mouse 5 (BTN_EXTRA / Forward) press."""
        with self.bridge_lock:
            try:
                self.mb_pipe_write.send_bytes(
                    PACK_BUTTON_STRUCT.pack(TASK_BUTTON, BUTTON_5_DOWN)
                )
            except OSError:
                self.selective_release()
            else:
                self._mouse_button5_down = True

    def button5_up(self) -> None:
        """Dispatches Mouse 5 (BTN_EXTRA / Forward) release."""
        with self.bridge_lock:
            try:
                self.mb_pipe_write.send_bytes(
                    PACK_BUTTON_STRUCT.pack(TASK_BUTTON, BUTTON_5_UP)
                )
            except OSError:
                self.selective_release()
            else:
                self._mouse_button5_down = False

    # Aliases for abstract base and output sink compatibility
    mouse4_down = button4_down
    mouse4_up = button4_up
    mouse5_down = button5_down
    mouse5_up = button5_up

    def _heartbeat_loop(self):
        while not self._stop_heartbeat.wait(KEEPALIVE_INTERVAL):
            self.health_check()
            with self.bridge_lock:
                for code in list(self._pressed_keys):
                    try:
                        self.k_pipe_write.send_bytes(
                            PACK_KEY_STRUCT.pack(int(code), KEY_PING)
                        )
                    except OSError:
                        pass
                if (
                    self._mouse_left_down
                    or self._mouse_right_down
                    or self._mouse_middle_down
                    or self._mouse_button4_down
                    or self._mouse_button5_down
                ):
                    try:
                        self.mb_pipe_write.send_bytes(
                            PACK_BUTTON_STRUCT.pack(TASK_BUTTON, BUTTON_PING)
                        )
                    except OSError:
                        pass

    def health_check(self):
        if self.k_proc is not None and not self.k_proc.is_alive():
            self._trigger_respawn_keyboard()
        if self.m_proc is not None and not self.m_proc.is_alive():
            self._trigger_respawn_mouse()

    def _trigger_respawn_keyboard(self):
        with self._k_respawn_lock:
            if self._k_respawning:
                return
            self._k_respawning = True
        threading.Thread(
            target=self._respawn_keyboard, name="Keyboard-Respawn", daemon=True
        ).start()

    def _respawn_keyboard(self):
        try:
            logger.info(
                f"[BRIDGE] - Keyboard Worker Died: {_datetime.now().strftime('%H:%M:%S')}!"
            )
            with self.bridge_lock:
                old_proc = self.k_proc
                try:
                    self.k_pipe_read.close()
                    self.k_pipe_write.close()
                except Exception:
                    pass
                self.k_pipe_read, self.k_pipe_write = multiprocessing.Pipe(duplex=False)
                self.k_proc = multiprocessing.Process(
                    target=keyboard_worker,
                    args=(self.k_pipe_read, self.log_queue),
                    daemon=True,
                )
                self.k_proc.start()
                self.system_config.set_high_priority(
                    self.k_proc.pid, "Revived Keyboard"
                )
                self.k_pipe_read.close()

                self.update_typematic(
                    self._cached_typematic["enabled"],
                    self._cached_typematic["delay_ms"],
                    self._cached_typematic["rate_hz"],
                    self._cached_typematic["exclude_scancodes"],
                )

            if old_proc is not None:
                old_proc.join(timeout=1.0)

            if self._respawn_callback:
                try:
                    self._respawn_callback("keyboard")
                except Exception as e:
                    logger.info(
                        f"[BRIDGE] - Respawn callback (keyboard) failed: {e}."
                    )
        finally:
            with self._k_respawn_lock:
                self._k_respawning = False

    def _trigger_respawn_mouse(self):
        with self._m_respawn_lock:
            if self._m_respawning:
                return
            self._m_respawning = True
        threading.Thread(
            target=self._respawn_mouse, name="Mouse-Respawn", daemon=True
        ).start()

    def _respawn_mouse(self):
        try:
            logger.info(
                f"[BRIDGE] - Mouse Worker Died: {_datetime.now().strftime('%H:%M:%S')}!"
            )
            with self.bridge_lock:
                old_proc = self.m_proc
                try:
                    self.m_pipe_read.close()
                    self.m_pipe_write.close()
                    self.mb_pipe_read.close()
                    self.mb_pipe_write.close()
                except Exception:
                    pass
                self.m_pipe_read, self.m_pipe_write = multiprocessing.Pipe(duplex=False)
                self.mb_pipe_read, self.mb_pipe_write = multiprocessing.Pipe(
                    duplex=False
                )
                self.m_proc = multiprocessing.Process(
                    target=mouse_worker,
                    name="Mouse Worker",
                    args=(self.m_pipe_read, self.mb_pipe_read, self.log_queue),
                    daemon=True,
                )
                self.m_proc.start()
                self.system_config.set_high_priority(self.m_proc.pid, "Revived Mouse")
                self.m_pipe_read.close()
                self.mb_pipe_read.close()

            if old_proc is not None:
                old_proc.join(timeout=1.0)

            if self._respawn_callback:
                try:
                    self._respawn_callback("mouse")
                except Exception as e:
                    logger.info(f"[BRIDGE] - Respawn callback (mouse) failed: {e}.")
        finally:
            with self._m_respawn_lock:
                self._m_respawning = False

    def selective_release(self):
        with self.bridge_lock:
            self.health_check()
            if self._pressed_keys:
                for code in list(self._pressed_keys):
                    try:
                        self.k_pipe_write.send_bytes(PACK_KEY_STRUCT.pack(int(code), 0))
                    except OSError:
                        pass
                self._pressed_keys.clear()

            button_releases = [
                (self._mouse_left_down, LEFT_BUTTON_UP),
                (self._mouse_right_down, RIGHT_BUTTON_UP),
                (self._mouse_middle_down, MIDDLE_BUTTON_UP),
                (self._mouse_button4_down, BUTTON_4_UP),
                (self._mouse_button5_down, BUTTON_5_UP),
            ]
            for is_down, release_flag in button_releases:
                if is_down:
                    try:
                        self.mb_pipe_write.send_bytes(
                            PACK_BUTTON_STRUCT.pack(TASK_BUTTON, release_flag)
                        )
                    except OSError:
                        pass

            self._mouse_left_down = False
            self._mouse_right_down = False
            self._mouse_middle_down = False
            self._mouse_button4_down = False
            self._mouse_button5_down = False

    def release_all(self):
        logger.info("[BRIDGE] - Emergency Release (UInput)...")
        with self.bridge_lock:
            self.health_check()
            unique_codes = set(SCANCODES.values()) - set(MOUSE_SCANCODES)
            for code in unique_codes:
                try:
                    self.k_pipe_write.send_bytes(PACK_KEY_STRUCT.pack(int(code), 0))
                except OSError:
                    pass
            self._pressed_keys.clear()

            all_buttons = [
                LEFT_BUTTON_UP,
                RIGHT_BUTTON_UP,
                MIDDLE_BUTTON_UP,
                BUTTON_4_UP,
                BUTTON_5_UP,
            ]
            for btn_up in all_buttons:
                try:
                    self.mb_pipe_write.send_bytes(
                        PACK_BUTTON_STRUCT.pack(TASK_BUTTON, btn_up)
                    )
                except OSError:
                    pass

            self._mouse_left_down = False
            self._mouse_right_down = False
            self._mouse_middle_down = False
            self._mouse_button4_down = False
            self._mouse_button5_down = False
        logger.info("[BRIDGE] - Release signals dispatched.")

    def shutdown(self):
        self._stop_log_event.set()
        if self._log_consumer_thread and self._log_consumer_thread.is_alive():
            self._log_consumer_thread.join(timeout=1.0)
        self._stop_heartbeat.set()
        self.release_all()

        for proc in (self.k_proc, self.m_proc):
            if proc is not None and proc.is_alive():
                proc.terminate()
                proc.join(timeout=1.0)
                if proc.is_alive():
                    proc.kill()
