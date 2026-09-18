from __future__ import annotations
from typing import TYPE_CHECKING

import queue
import threading
from time import sleep as _sleep, perf_counter_ns as _perf_counter_ns
from random import uniform as _uniform

from modules.utils import KEY_PING, BUTTON_PING, CONSTANT_DWELL
from .ecodes_map import LINUX_KEY_MAP, KEYBOARD_CAP, MOUSE_CAP, BTN_MAP

if TYPE_CHECKING:
    from multiprocessing.connection import Connection


def _release_all_keys(ui_device, ecodes, keys_set, reason=""):
    print(f"\n[WORKER] - {reason}.")
    if keys_set:
        print(f"\n[WORKER] - Releasing {len(keys_set)} keys.")
        for linux_code in list(keys_set):
            ui_device.write(ecodes.EV_KEY, linux_code, 0)  # KEY UP
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
    """Dedicated process for Linux evdev virtual keyboard."""

    from evdev import UInput, ecodes
    from modules.utils import (
        PACK_KEY,
        MIN_KEY_DWELL,
        MAX_KEY_DWELL,
        INITIAL_DELAY_NS,
        REPEAT_RATE,
        NON_SPAMMING_KEYS,
    )

    ui_device = UInput(KEYBOARD_CAP, name="Touch2Key-Keyboard")

    pressed_keys = set()
    state = {"running": True}

    # Thread-safe queue to pass keys from the pipe reader to the injector
    key_queue = queue.Queue()

    def key_injection_loop():
        """
        Dedicated thread for executing keystrokes with strict Typematic auto-repeat.
        - Supports True Diagonal WASD movement (no artificial KEY_UPs).
        - Correctly filters Modifier and Lock keys (no spamming).
        - Accurately steals typematic focus on new key presses.
        """

        LINUX_NON_SPAMMING_KEYS = {LINUX_KEY_MAP[x] for x in NON_SPAMMING_KEYS}
        active_keys = set()

        # Typematic state tracking
        repeat_key = None
        repeat_start_time = 0.0

        while state["running"]:
            # Process all immediate state changes (Physical down/up from the bridge)
            while not key_queue.empty():
                try:
                    linux_code, k_state = key_queue.get_nowait()

                    if k_state == 1:  # KEY DOWN
                        if linux_code not in active_keys:
                            active_keys.add(linux_code)

                            # TRUE HARDWARE LOGIC: Normal keys steal focus WITHOUT sending KEY_UP to the old key.
                            # This allows WASD diagonal movement to function flawlessly.
                            if linux_code in LINUX_NON_SPAMMING_KEYS:
                                repeat_key = None
                            else:
                                repeat_key = linux_code

                            repeat_start_time = _perf_counter_ns()
                            # Send the actual physical press to the OS (UInput)
                            ui_device.write(ecodes.EV_KEY, linux_code, 1)
                            ui_device.syn()
                            _sleep(_uniform(MIN_KEY_DWELL, MAX_KEY_DWELL))

                    elif k_state == 0:  # KEY UP
                        if linux_code in active_keys:
                            active_keys.discard(linux_code)

                            # If the currently repeating key is released, clear focus
                            if repeat_key == linux_code:
                                repeat_key = None

                            # Send the actual physical release to the OS (UInput)
                            ui_device.write(ecodes.EV_KEY, linux_code, 0)
                            ui_device.syn()
                            _sleep(CONSTANT_DWELL)

                    key_queue.task_done()
                except Exception as e:
                    print(f"\n[WORKER] - Key Injection Error (Queue): {e}.")

            # Process Auto-Repeat for the SINGLE active repeat key
            if repeat_key is not None:
                # Double-check it's not a modifier/lock key just to be absolutely safe
                if repeat_key not in LINUX_NON_SPAMMING_KEYS:
                    current_time = _perf_counter_ns()
                    if (current_time - repeat_start_time) >= INITIAL_DELAY_NS:
                        try:
                            ui_device.write(ecodes.EV_KEY, repeat_key, 1)  # KEY DOWN
                            ui_device.syn()
                        except Exception:
                            pass

            # Sleep at the repeat rate to prevent overwhelming the CPU and pipe
            _sleep(REPEAT_RATE)

    # Start the injection thread
    injector_thread = threading.Thread(
        target=key_injection_loop, name="Keyboard-Injection-Loop", daemon=True
    )
    injector_thread.start()

    while state["running"]:
        try:
            if k_pipe_read.poll(15.0):
                payload = k_pipe_read.recv_bytes()
                win_code, k_state = PACK_KEY.unpack(payload)

                if k_state == KEY_PING:
                    continue  # keepalive only: resets poll() timer, no device write

                # Translate Windows scancode to Linux ecode
                linux_code = LINUX_KEY_MAP.get(win_code)

                # If the key isn't in our dictionary, ignore it to prevent crashes
                if linux_code is None:
                    continue

                # Linux logic sends state=1 for down, state=0 for up.
                if k_state == 1:
                    pressed_keys.add(linux_code)
                elif k_state == 0:
                    pressed_keys.discard(linux_code)

                # Instantly offload the event to the injection thread
                key_queue.put((linux_code, k_state))

            else:
                _release_all_keys(ui_device, ecodes, pressed_keys, "Keyboard Timeout")
                pressed_keys.clear()
                continue

        except EOFError:
            print("\n[WORKER] - Keyboard Pipe closed by parent.")
            state["running"] = False

        except Exception as e:
            print(f"\n[WORKER] - Keyboard Worker crashed: {e}.")
            state["running"] = False

    # Cleanup
    state["running"] = False
    injector_thread.join(timeout=2.0)
    ui_device.close()


def mouse_worker(m_pipe_read: Connection, mb_pipe_read: Connection):
    """Movement (REL/ABS) runs on this function's main loop. Buttons run on
    a separate thread with their own pipe, so a button's dwell sleep can
    never block camera-movement delivery. Both share one UInput device
    behind `send_lock`, which wraps only write()/syn(), not sleeps."""

    from evdev import UInput, ecodes
    from modules.utils import (
        TASK_REL,
        TASK_ABS,
        PACK_BUTTON,
        PACK_REL,
        PACK_ABS,
        LEFT_BUTTON_DOWN,
        LEFT_BUTTON_UP,
        RIGHT_BUTTON_DOWN,
        RIGHT_BUTTON_UP,
        MIDDLE_BUTTON_DOWN,
        MIDDLE_BUTTON_UP,
        MAX_COALESCE,
        DOWN_TUPLE,
        MIN_BUTTON_DWELL,
        MAX_BUTTON_DWELL,
        MIN_MOUSE_DWELL,
        MAX_MOUSE_DWELL,
    )

    ui_device = UInput(MOUSE_CAP, name="Touch2Key-Mouse")

    send_lock = threading.Lock()
    state = {"running": True}

    def button_loop():
        left_down = right_down = middle_down = False
        while state["running"]:
            try:
                if mb_pipe_read.poll(15.0):
                    payload = mb_pipe_read.recv_bytes()
                    _, data = PACK_BUTTON.unpack(payload)

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
                print("\n[WORKER] - Mouse Button Pipe closed by parent.")
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
                _, dx, dy = PACK_REL.unpack(payload)
                acc_dx += dx
                acc_dy += dy

                coalesce_count = 0
                while m_pipe_read.poll() and coalesce_count < MAX_COALESCE:
                    next_payload = m_pipe_read.recv_bytes()
                    next_task_id = next_payload[0]

                    if next_task_id == TASK_REL:
                        _, next_dx, next_dy = PACK_REL.unpack(next_payload)
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
                _, x, y = PACK_ABS.unpack(payload)
                with send_lock:
                    ui_device.write(ecodes.EV_ABS, ecodes.ABS_X, x)
                    ui_device.write(ecodes.EV_ABS, ecodes.ABS_Y, y)
                    ui_device.syn()
                _sleep(CONSTANT_DWELL)

        except EOFError:
            print("\n[WORKER] - Mouse Movement Pipe closed by parent.")
            state["running"] = False

        except Exception as e:
            print(f"\n[WORKER] - Mouse Movement Worker crashed: {e}.")
            state["running"] = False

    state["running"] = False  # no-op if already False; covers normal loop exit too
    button_thread.join(timeout=16.0)
    ui_device.close()
