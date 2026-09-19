from __future__ import annotations

import multiprocessing
import struct
import threading
from datetime import datetime as _datetime

from ..base import AbstractBridge
from .workers import keyboard_worker, mouse_worker

from modules.utils import (
    BUTTON_PING,
    KEEPALIVE_INTERVAL,
    KEY_CONFIG,
    KEY_PING,
    LEFT_BUTTON_DOWN,
    LEFT_BUTTON_UP,
    M_LEFT,
    M_MIDDLE,
    M_RIGHT,
    MIDDLE_BUTTON_DOWN,
    MIDDLE_BUTTON_UP,
    PACK_ABS,
    PACK_BUTTON,
    PACK_KEY,
    PACK_REL,
    PACK_TYPEMATIC_HEADER,
    RIGHT_BUTTON_DOWN,
    RIGHT_BUTTON_UP,
    SCANCODES,
    TASK_ABS,
    TASK_BUTTON,
    TASK_REL,
)


class InterceptionBridge(AbstractBridge):
    def __init__(self, window_manager, system_config):
        self.window_manager = window_manager
        self.system_config = system_config
        self.screen_w, self.screen_h = window_manager.get_screen_dimensions()
        self.bridge_lock = threading.RLock()

        self._mouse_left_down = False
        self._mouse_right_down = False
        self._mouse_middle_down = False
        self._pressed_keys = set()

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
        self.k_proc = None

        self.m_pipe_read, self.m_pipe_write = multiprocessing.Pipe(duplex=False)
        self.mb_pipe_read, self.mb_pipe_write = multiprocessing.Pipe(duplex=False)
        self.m_proc = None

        self._stop_heartbeat = threading.Event()
        self.heartbeat_thread = threading.Thread(
            target=self._heartbeat_loop, name="Keepalive", daemon=True
        )

        self._respawn_callback = None
        self.k_device_handle = None
        self.m_device_handle = None

    def set_respawn_callback(self, callback):
        self._respawn_callback = callback

    def update_typematic(
        self,
        enabled: bool,
        delay_ms: float,
        rate_hz: float,
        exclude_scancodes: set[int],
    ) -> None:
        """Pushes typematic timing and exclusion rules to the keyboard worker over IPC."""
        with self.bridge_lock:
            self._cached_typematic["enabled"] = enabled
            self._cached_typematic["delay_ms"] = delay_ms
            self._cached_typematic["rate_hz"] = rate_hz
            self._cached_typematic["exclude_scancodes"] = set(exclude_scancodes)

            delay_ns = int(delay_ms * 1_000_000)
            interval_sec = 1.0 / max(1.0, rate_hz)
            codes = list(exclude_scancodes)

            payload = bytearray(
                PACK_TYPEMATIC_HEADER.pack(
                    KEY_CONFIG, enabled, delay_ns, interval_sec, len(codes)
                )
            )
            for code in codes:
                payload.extend(struct.pack("<H", code))

            try:
                self.k_pipe_write.send_bytes(bytes(payload))
            except OSError:
                pass

    def start_worker_processes(self, k_device_handle, m_device_handle):
        with self.bridge_lock:
            self.k_device_handle = k_device_handle
            self.m_device_handle = m_device_handle

            self.k_proc = multiprocessing.Process(
                target=keyboard_worker,
                name="Keyboard Worker",
                args=(self.k_pipe_read, self.k_device_handle),
                daemon=True,
            )
            self.k_proc.start()
            self.system_config.set_high_priority(self.k_proc.pid, "Keyboard")

            self.m_proc = multiprocessing.Process(
                target=mouse_worker,
                name="Mouse Worker",
                args=(self.m_pipe_read, self.mb_pipe_read, self.m_device_handle),
                daemon=True,
            )
            self.m_proc.start()
            self.system_config.set_high_priority(self.m_proc.pid, "Mouse")

            # Push typematic profile configuration to revived worker
            self.update_typematic(
                self._cached_typematic["enabled"],
                self._cached_typematic["delay_ms"],
                self._cached_typematic["rate_hz"],
                self._cached_typematic["exclude_scancodes"],
            )

            if not self.heartbeat_thread.is_alive():
                self.heartbeat_thread.start()

            print(
                f"\n[BRIDGE] - Interception Dual Engine Started. K-PID: {self.k_proc.pid} | M-PID: {self.m_proc.pid}."
            )

    def reload_devices(
        self, new_k_handle: int | None, new_m_handle: int | None
    ) -> None:
        with self.bridge_lock:
            print(f"\n[BRIDGE] - Hot-Reloading Devices -> K:{new_k_handle}, M:{new_m_handle}")
            self.release_all()

            self.k_device_handle = new_k_handle
            self.m_device_handle = new_m_handle

            if self.k_proc is not None:
                try:
                    self.k_pipe_read.close()
                    self.k_pipe_write.close()
                except Exception:
                    pass
                if self.k_proc.is_alive():
                    self.k_proc.terminate()
                    self.k_proc.join(timeout=1.0)
                    if self.k_proc.is_alive():
                        self.k_proc.kill()

            self.k_pipe_read, self.k_pipe_write = multiprocessing.Pipe(duplex=False)
            self.k_proc = multiprocessing.Process(
                target=keyboard_worker,
                name="Keyboard Worker (Reloaded)",
                args=(self.k_pipe_read, self.k_device_handle),
                daemon=True,
            )
            self.k_proc.start()
            self.system_config.set_high_priority(self.k_proc.pid, "Keyboard")

            self.update_typematic(
                self._cached_typematic["enabled"],
                self._cached_typematic["delay_ms"],
                self._cached_typematic["rate_hz"],
                self._cached_typematic["exclude_scancodes"],
            )

            if self.m_proc is not None:
                try:
                    self.m_pipe_read.close()
                    self.m_pipe_write.close()
                    self.mb_pipe_read.close()
                    self.mb_pipe_write.close()
                except Exception:
                    pass
                if self.m_proc.is_alive():
                    self.m_proc.terminate()
                    self.m_proc.join(timeout=1.0)
                    if self.m_proc.is_alive():
                        self.m_proc.kill()

            self.m_pipe_read, self.m_pipe_write = multiprocessing.Pipe(duplex=False)
            self.mb_pipe_read, self.mb_pipe_write = multiprocessing.Pipe(duplex=False)
            self.m_proc = multiprocessing.Process(
                target=mouse_worker,
                name="Mouse Worker (Reloaded)",
                args=(self.m_pipe_read, self.mb_pipe_read, self.m_device_handle),
                daemon=True,
            )
            self.m_proc.start()
            self.system_config.set_high_priority(self.m_proc.pid, "Mouse")

            print(
                f"[BRIDGE] - Workers Reloaded. K-PID: {self.k_proc.pid} | M-PID: {self.m_proc.pid}"
            )

    def key_down(self, code):
        with self.bridge_lock:
            self._pressed_keys.add(code)
            try:
                self.k_pipe_write.send_bytes(PACK_KEY.pack(int(code), 0))
            except OSError:
                self.selective_release()

    def key_up(self, code):
        with self.bridge_lock:
            try:
                self.k_pipe_write.send_bytes(PACK_KEY.pack(int(code), 1))
            except OSError:
                self.selective_release()
            else:
                self._pressed_keys.discard(code)

    def mouse_move_rel(self, dx, dy):
        try:
            self.m_pipe_write.send_bytes(PACK_REL.pack(TASK_REL, int(dx), int(dy)))
        except OSError:
            self.selective_release()

    def mouse_move_abs(self, x, y):
        abs_x = max(0, min(65535, int((x / self.screen_w) * 65535)))
        abs_y = max(0, min(65535, int((y / self.screen_h) * 65535)))
        try:
            self.m_pipe_write.send_bytes(PACK_ABS.pack(TASK_ABS, int(abs_x), int(abs_y)))
        except OSError:
            self.selective_release()

    def left_click_down(self):
        with self.bridge_lock:
            try:
                self.mb_pipe_write.send_bytes(PACK_BUTTON.pack(TASK_BUTTON, LEFT_BUTTON_DOWN))
            except OSError:
                self.selective_release()
            else:
                self._mouse_left_down = True

    def left_click_up(self):
        with self.bridge_lock:
            try:
                self.mb_pipe_write.send_bytes(PACK_BUTTON.pack(TASK_BUTTON, LEFT_BUTTON_UP))
            except OSError:
                self.selective_release()
            else:
                self._mouse_left_down = False

    def right_click_down(self):
        with self.bridge_lock:
            try:
                self.mb_pipe_write.send_bytes(PACK_BUTTON.pack(TASK_BUTTON, RIGHT_BUTTON_DOWN))
            except OSError:
                self.selective_release()
            else:
                self._mouse_right_down = True

    def right_click_up(self):
        with self.bridge_lock:
            try:
                self.mb_pipe_write.send_bytes(PACK_BUTTON.pack(TASK_BUTTON, RIGHT_BUTTON_UP))
            except OSError:
                self.selective_release()
            else:
                self._mouse_right_down = False

    def middle_click_down(self):
        with self.bridge_lock:
            try:
                self.mb_pipe_write.send_bytes(PACK_BUTTON.pack(TASK_BUTTON, MIDDLE_BUTTON_DOWN))
            except OSError:
                self.selective_release()
            else:
                self._mouse_middle_down = True

    def middle_click_up(self):
        with self.bridge_lock:
            try:
                self.mb_pipe_write.send_bytes(PACK_BUTTON.pack(TASK_BUTTON, MIDDLE_BUTTON_UP))
            except OSError:
                self.selective_release()
            else:
                self._mouse_middle_down = False

    def _heartbeat_loop(self):
        while not self._stop_heartbeat.wait(KEEPALIVE_INTERVAL):
            self.health_check()
            with self.bridge_lock:
                for code in list(self._pressed_keys):
                    try:
                        self.k_pipe_write.send_bytes(PACK_KEY.pack(int(code), KEY_PING))
                    except OSError:
                        pass
                if (
                    self._mouse_left_down
                    or self._mouse_right_down
                    or self._mouse_middle_down
                ):
                    try:
                        self.mb_pipe_write.send_bytes(PACK_BUTTON.pack(TASK_BUTTON, BUTTON_PING))
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
            print(f"\n[BRIDGE] - Keyboard Worker Died: {_datetime.now().strftime('%H:%M:%S')}!")
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
                    args=(self.k_pipe_read, self.k_device_handle),
                    daemon=True,
                )
                self.k_proc.start()
                self.system_config.set_high_priority(self.k_proc.pid, "Revived Keyboard")
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
                    print(f"\n[BRIDGE] - Respawn callback (keyboard) failed: {e}.")
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
            print(f"\n[BRIDGE] - Mouse Worker Died: {_datetime.now().strftime('%H:%M:%S')}!")
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
                self.mb_pipe_read, self.mb_pipe_write = multiprocessing.Pipe(duplex=False)
                self.m_proc = multiprocessing.Process(
                    target=mouse_worker,
                    name="Mouse Worker",
                    args=(self.m_pipe_read, self.mb_pipe_read, self.m_device_handle),
                    daemon=True,
                )
                self.m_proc.start()
                self.system_config.set_high_priority(self.m_proc.pid, "Revived Mouse")

            if old_proc is not None:
                old_proc.join(timeout=1.0)

            if self._respawn_callback:
                try:
                    self._respawn_callback("mouse")
                except Exception as e:
                    print(f"\n[BRIDGE] - Respawn callback (mouse) failed: {e}.")
        finally:
            with self._m_respawn_lock:
                self._m_respawning = False

    def selective_release(self):
        with self.bridge_lock:
            self.health_check()
            if self._pressed_keys:
                for code in list(self._pressed_keys):
                    try:
                        self.k_pipe_write.send_bytes(PACK_KEY.pack(int(code), 1))
                    except OSError:
                        pass
                self._pressed_keys.clear()

            if self._mouse_left_down:
                try:
                    self.mb_pipe_write.send_bytes(PACK_BUTTON.pack(TASK_BUTTON, LEFT_BUTTON_UP))
                except OSError:
                    pass
            if self._mouse_right_down:
                try:
                    self.mb_pipe_write.send_bytes(PACK_BUTTON.pack(TASK_BUTTON, RIGHT_BUTTON_UP))
                except OSError:
                    pass
            if self._mouse_middle_down:
                try:
                    self.mb_pipe_write.send_bytes(PACK_BUTTON.pack(TASK_BUTTON, MIDDLE_BUTTON_UP))
                except OSError:
                    pass

            self._mouse_left_down = self._mouse_right_down = self._mouse_middle_down = False

    def release_all(self):
        print("\n[BRIDGE] - Emergency Release (Interception)...")
        with self.bridge_lock:
            self.health_check()
            internal_mouse_codes = {M_LEFT, M_RIGHT, M_MIDDLE}
            unique_codes = set(SCANCODES.values()) - internal_mouse_codes
            for code in unique_codes:
                try:
                    self.k_pipe_write.send_bytes(PACK_KEY.pack(int(code), 1))
                except OSError:
                    pass
            self._pressed_keys.clear()

            for btn_up in [LEFT_BUTTON_UP, RIGHT_BUTTON_UP, MIDDLE_BUTTON_UP]:
                try:
                    self.mb_pipe_write.send_bytes(PACK_BUTTON.pack(TASK_BUTTON, btn_up))
                except OSError:
                    pass
            self._mouse_left_down = self._mouse_right_down = self._mouse_middle_down = False
        print("[BRIDGE] - Release signals dispatched.")

    def shutdown(self):
        self._stop_heartbeat.set()
        self.release_all()