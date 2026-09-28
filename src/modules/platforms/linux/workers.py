from __future__ import annotations

import queue
import struct
import threading
from random import uniform as _uniform
from time import perf_counter_ns as _perf_counter_ns, sleep as _sleep
from typing import TYPE_CHECKING

from modules.utils import (
    BUTTON_PING,
    CONSTANT_DWELL,
    DOWN_TUPLE,
    KEY_CONFIG,
    KEY_PING,
    LEFT_BUTTON_DOWN,
    LEFT_BUTTON_UP,
    MAX_BUTTON_DWELL,
    MAX_COALESCE,
    MAX_KEY_DWELL,
    MAX_MOUSE_DWELL,
    MIDDLE_BUTTON_DOWN,
    MIDDLE_BUTTON_UP,
    MIN_BUTTON_DWELL,
    MIN_KEY_DWELL,
    MIN_MOUSE_DWELL,
    PACK_ABS_STRUCT,
    PACK_BUTTON_STRUCT,
    PACK_KEY_STRUCT,
    PACK_REL_STRUCT,
    PACK_TYPEMATIC_STRUCT,
    RIGHT_BUTTON_DOWN,
    RIGHT_BUTTON_UP,
    TASK_ABS,
    TASK_REL,
)
from .ecodes_map import BTN_MAP, KEYBOARD_CAP, LINUX_KEY_MAP, MOUSE_CAP

if TYPE_CHECKING:
    from multiprocessing.connection import Connection


def _release_all_keys(ui_device, ecodes, keys_set, reason=""):
    print(f"\n[WORKER] - {reason}.")
    if keys_set:
        print(f"\n[WORKER] - Releasing {len(keys_set)} keys.")
        for linux_code in list(keys_set):
            ui_device.write(ecodes.EV_KEY, linux_code, 0)
        ui_device.syn()
        keys_set.clear()


def _release_all_buttons(
    ui_device, ecodes, left_down, right_down, middle_down, reason=""
):
    print(f"\n[WORKER] - {reason}.")
    buttons_set_sum = sum([left_down, right_down, middle_down])
    if buttons_set_sum > 0:
        print(f"\n[WORKER] - Releasing {buttons_set_sum} buttons.")
        if left_down:
            ui_device.write(ecodes.EV_KEY, ecodes.BTN_LEFT, 0)
        if right_down:
            ui_device.write(ecodes.EV_KEY, ecodes.BTN_RIGHT, 0)
        if middle_down:
            ui_device.write(ecodes.EV_KEY, ecodes.BTN_MIDDLE, 0)
        ui_device.syn()


def keyboard_worker(k_pipe_read: Connection):
    """Dedicated process for Linux evdev virtual keyboard with typematic engine."""
    from evdev import UInput, ecodes

    ui_device = UInput(KEYBOARD_CAP, name="Touch2Key-Keyboard")
    pressed_keys = set()
    state = {"running": True}

    # Typematic state: initialized empty and populated dynamically via KEY_CONFIG
    typematic_cfg = {
        "enabled": True,
        "delay_ns": 250_000_000,
        "repeat_rate": 0.0333,
        "non_spamming": set(),
    }

    key_queue = queue.Queue()

    def key_injection_loop():
        active_keys = set()
        repeat_key = None
        repeat_start_time = 0.0

        while state["running"]:
            while not key_queue.empty():
                try:
                    linux_code, k_state = key_queue.get_nowait()

                    if k_state == 1:  # KEY DOWN
                        if linux_code not in active_keys:
                            active_keys.add(linux_code)

                            if (
                                not typematic_cfg["enabled"]
                                or linux_code in typematic_cfg["non_spamming"]
                            ):
                                repeat_key = None
                            else:
                                repeat_key = linux_code

                            repeat_start_time = _perf_counter_ns()
                            ui_device.write(ecodes.EV_KEY, linux_code, 1)
                            ui_device.syn()
                            _sleep(_uniform(MIN_KEY_DWELL, MAX_KEY_DWELL))

                    elif k_state == 0:  # KEY UP
                        if linux_code in active_keys:
                            active_keys.discard(linux_code)
                            if repeat_key == linux_code:
                                repeat_key = None

                            ui_device.write(ecodes.EV_KEY, linux_code, 0)
                            ui_device.syn()
                            _sleep(CONSTANT_DWELL)

                    key_queue.task_done()
                except Exception as e:
                    print(f"\n[WORKER] - Key Injection Error (Queue): {e}.")

            if typematic_cfg["enabled"] and repeat_key is not None:
                if repeat_key not in typematic_cfg["non_spamming"]:
                    current_time = _perf_counter_ns()
                    if (current_time - repeat_start_time) >= typematic_cfg["delay_ns"]:
                        try:
                            ui_device.write(ecodes.EV_KEY, repeat_key, 1)
                            ui_device.syn()
                        except Exception:
                            pass

            _sleep(typematic_cfg["repeat_rate"])

    injector_thread = threading.Thread(
        target=key_injection_loop, name="Keyboard-Injection-Loop", daemon=True
    )
    injector_thread.start()

    while state["running"]:
        try:
            if k_pipe_read.poll(15.0):
                payload = k_pipe_read.recv_bytes()

                if len(payload) == 3:
                    win_code, k_state = PACK_KEY_STRUCT.unpack(payload)
                    if k_state == KEY_PING:
                        continue
                    linux_code = LINUX_KEY_MAP.get(win_code)
                    if linux_code is None:
                        continue

                    if k_state == 1:
                        pressed_keys.add(linux_code)
                    elif k_state == 0:
                        pressed_keys.discard(linux_code)

                    key_queue.put((linux_code, k_state))
                    continue

                if payload and payload[0] == KEY_CONFIG:
                    _, enabled, delay_ns, rate_sec, count = (
                        PACK_TYPEMATIC_STRUCT.unpack_from(payload, 0)
                    )
                    offset = PACK_TYPEMATIC_STRUCT.size
                    excludes = set()
                    for _ in range(count):
                        (sc,) = struct.unpack_from("<H", payload, offset)
                        l_code = LINUX_KEY_MAP.get(sc)
                        if l_code is not None:
                            excludes.add(l_code)
                        offset += 2

                    typematic_cfg["enabled"] = enabled
                    typematic_cfg["delay_ns"] = delay_ns
                    typematic_cfg["repeat_rate"] = rate_sec
                    typematic_cfg["non_spamming"] = excludes
                    continue

            else:
                _release_all_keys(ui_device, ecodes, pressed_keys, "Keyboard Timeout")
                pressed_keys.clear()
        except EOFError:
            state["running"] = False
        except Exception as e:
            print(f"\n[WORKER] - Keyboard Worker crashed: {e}.")
            state["running"] = False

    state["running"] = False
    injector_thread.join(timeout=2.0)
    ui_device.close()


def mouse_worker(m_pipe_read: Connection, mb_pipe_read: Connection):
    """Dedicated UInput worker for mouse movement and button emulation."""
    from evdev import UInput, ecodes

    ui_device = UInput(MOUSE_CAP, name="Touch2Key-Mouse")
    send_lock = threading.Lock()
    state = {"running": True}

    def button_loop():
        left_down = right_down = middle_down = False
        while state["running"]:
            try:
                if mb_pipe_read.poll(15.0):
                    payload = mb_pipe_read.recv_bytes()
                    _, data = PACK_BUTTON_STRUCT.unpack(payload)

                    if data == BUTTON_PING:
                        continue

                    if data == LEFT_BUTTON_DOWN:
                        left_down = True
                    elif data == LEFT_BUTTON_UP:
                        left_down = False
                    elif data == RIGHT_BUTTON_DOWN:
                        right_down = True
                    elif data == RIGHT_BUTTON_UP:
                        right_down = False
                    elif data == MIDDLE_BUTTON_DOWN:
                        middle_down = True
                    elif data == MIDDLE_BUTTON_UP:
                        middle_down = False

                    btn_code, btn_val = BTN_MAP[data]
                    with send_lock:
                        ui_device.write(ecodes.EV_KEY, btn_code, btn_val)
                        ui_device.syn()

                    if data in DOWN_TUPLE:
                        _sleep(_uniform(MIN_BUTTON_DWELL, MAX_BUTTON_DWELL))
                    else:
                        _sleep(CONSTANT_DWELL)

                else:
                    with send_lock:
                        _release_all_buttons(
                            ui_device,
                            ecodes,
                            left_down,
                            right_down,
                            middle_down,
                            "Mouse Button Timeout",
                        )
                    left_down = right_down = middle_down = False

            except EOFError:
                state["running"] = False
            except Exception as e:
                print(f"\n[WORKER] - Mouse Button Worker crashed: {e}.")
                state["running"] = False

    button_thread = threading.Thread(
        target=button_loop, name="Mouse-Button-Loop", daemon=True
    )
    button_thread.start()

    acc_dx, acc_dy = 0, 0
    pending_task = None

    while state["running"]:
        try:
            if pending_task:
                payload = pending_task
                task_id = pending_task[0]
                pending_task = None
            else:
                if m_pipe_read.poll(15.0):
                    payload = m_pipe_read.recv_bytes()
                    task_id = payload[0]
                else:
                    continue

            if task_id == TASK_REL:
                _, dx, dy = PACK_REL_STRUCT.unpack(payload)
                acc_dx += dx
                acc_dy += dy

                coalesce_count = 0
                while m_pipe_read.poll() and coalesce_count < MAX_COALESCE:
                    next_payload = m_pipe_read.recv_bytes()
                    next_task_id = next_payload[0]

                    if next_task_id == TASK_REL:
                        _, next_dx, next_dy = PACK_REL_STRUCT.unpack(next_payload)
                        acc_dx += next_dx
                        acc_dy += next_dy
                        coalesce_count += 1
                    else:
                        pending_task = next_payload
                        break

                if acc_dx != 0 or acc_dy != 0:
                    with send_lock:
                        ui_device.write(ecodes.EV_REL, ecodes.REL_X, acc_dx)
                        ui_device.write(ecodes.EV_REL, ecodes.REL_Y, acc_dy)
                        ui_device.syn()
                    acc_dx, acc_dy = 0, 0

                _sleep(_uniform(MIN_MOUSE_DWELL, MAX_MOUSE_DWELL))

            elif task_id == TASK_ABS:
                _, x, y = PACK_ABS_STRUCT.unpack(payload)
                with send_lock:
                    ui_device.write(ecodes.EV_ABS, ecodes.ABS_X, x)
                    ui_device.write(ecodes.EV_ABS, ecodes.ABS_Y, y)
                    ui_device.syn()
                _sleep(CONSTANT_DWELL)

        except EOFError:
            state["running"] = False
        except Exception as e:
            print(f"\n[WORKER] - Mouse Movement Worker crashed: {e}.")
            state["running"] = False

    state["running"] = False
    button_thread.join(timeout=16.0)
    ui_device.close()
