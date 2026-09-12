from __future__ import annotations
from typing import TYPE_CHECKING

import queue
import threading
from time import sleep as _sleep, perf_counter_ns as _perf_counter_ns
from random import uniform as _uniform

from mapper_module.utils import KEY_PING, BUTTON_PING, CONSTANT_DWELL

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
    from mapper_module.utils import (
        PACK_KEY,
        MIN_KEY_DWELL,
        MAX_KEY_DWELL,
        INITIAL_DELAY_NS,
        REPEAT_RATE,
        NON_SPAMMING_KEYS,
    )

    cap = {ecodes.EV_KEY: list(range(1, 256))}
    ui_device = UInput(cap, name="Touch2Key-Keyboard")

    # Maps Windows/DOS Scancodes to Linux evdev ecodes
    LINUX_KEY_MAP = {
        0x01: ecodes.KEY_ESC,
        0x02: ecodes.KEY_1,
        0x03: ecodes.KEY_2,
        0x04: ecodes.KEY_3,
        0x05: ecodes.KEY_4,
        0x06: ecodes.KEY_5,
        0x07: ecodes.KEY_6,
        0x08: ecodes.KEY_7,
        0x09: ecodes.KEY_8,
        0x0A: ecodes.KEY_9,
        0x0B: ecodes.KEY_0,
        0x0C: ecodes.KEY_MINUS,
        0x0D: ecodes.KEY_EQUAL,
        0x0E: ecodes.KEY_BACKSPACE,
        0x0F: ecodes.KEY_TAB,
        0x10: ecodes.KEY_Q,
        0x11: ecodes.KEY_W,
        0x12: ecodes.KEY_E,
        0x13: ecodes.KEY_R,
        0x14: ecodes.KEY_T,
        0x15: ecodes.KEY_Y,
        0x16: ecodes.KEY_U,
        0x17: ecodes.KEY_I,
        0x18: ecodes.KEY_O,
        0x19: ecodes.KEY_P,
        0x1A: ecodes.KEY_LEFTBRACE,  # LEFT_BRACKET
        0x1B: ecodes.KEY_RIGHTBRACE,  # RIGHT_BRACKET
        0x1C: ecodes.KEY_ENTER,
        0x1D: ecodes.KEY_LEFTCTRL,
        0x1E: ecodes.KEY_A,
        0x1F: ecodes.KEY_S,
        0x20: ecodes.KEY_D,
        0x21: ecodes.KEY_F,
        0x22: ecodes.KEY_G,
        0x23: ecodes.KEY_H,
        0x24: ecodes.KEY_J,
        0x25: ecodes.KEY_K,
        0x26: ecodes.KEY_L,
        0x27: ecodes.KEY_SEMICOLON,
        0x28: ecodes.KEY_APOSTROPHE,
        0x29: ecodes.KEY_GRAVE,
        0x2A: ecodes.KEY_LEFTSHIFT,
        0x2B: ecodes.KEY_BACKSLASH,
        0x2C: ecodes.KEY_Z,
        0x2D: ecodes.KEY_X,
        0x2E: ecodes.KEY_C,
        0x2F: ecodes.KEY_V,
        0x30: ecodes.KEY_B,
        0x31: ecodes.KEY_N,
        0x32: ecodes.KEY_M,
        0x33: ecodes.KEY_COMMA,
        0x34: ecodes.KEY_DOT,
        0x35: ecodes.KEY_SLASH,
        0x36: ecodes.KEY_RIGHTSHIFT,
        0x37: ecodes.KEY_KPASTERISK,  # NUM_MULTIPLY
        0x38: ecodes.KEY_LEFTALT,
        0x39: ecodes.KEY_SPACE,
        0x3A: ecodes.KEY_CAPSLOCK,
        0x3B: ecodes.KEY_F1,
        0x3C: ecodes.KEY_F2,
        0x3D: ecodes.KEY_F3,
        0x3E: ecodes.KEY_F4,
        0x3F: ecodes.KEY_F5,
        0x40: ecodes.KEY_F6,
        0x41: ecodes.KEY_F7,
        0x42: ecodes.KEY_F8,
        0x43: ecodes.KEY_F9,
        0x44: ecodes.KEY_F10,
        0x45: ecodes.KEY_NUMLOCK,
        0x46: ecodes.KEY_SCROLLLOCK,
        0x47: ecodes.KEY_KP7,
        0x48: ecodes.KEY_KP8,
        0x49: ecodes.KEY_KP9,
        0x4A: ecodes.KEY_KPMINUS,
        0x4B: ecodes.KEY_KP4,
        0x4C: ecodes.KEY_KP5,
        0x4D: ecodes.KEY_KP6,
        0x4E: ecodes.KEY_KPPLUS,
        0x4F: ecodes.KEY_KP1,
        0x50: ecodes.KEY_KP2,
        0x51: ecodes.KEY_KP3,
        0x52: ecodes.KEY_KP0,
        0x53: ecodes.KEY_KPDOT,
        0x57: ecodes.KEY_F11,
        0x58: ecodes.KEY_F12,
        # Extended keys (0xE0XX series)
        0xE047: ecodes.KEY_HOME,
        0xE048: ecodes.KEY_UP,
        0xE049: ecodes.KEY_PAGEUP,
        0xE051: ecodes.KEY_PAGEDOWN,
        0xE04B: ecodes.KEY_LEFT,
        0xE04D: ecodes.KEY_RIGHT,
        0xE04F: ecodes.KEY_END,
        0xE050: ecodes.KEY_DOWN,
        0xE052: ecodes.KEY_INSERT,
        0xE053: ecodes.KEY_DELETE,
        0xE01D: ecodes.KEY_RIGHTCTRL,
        0xE038: ecodes.KEY_RIGHTALT,
        0xE01C: ecodes.KEY_KPENTER,  # Numpad Enter
        0xE035: ecodes.KEY_KPSLASH,  # Numpad Slash
    }

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

    from evdev import UInput, ecodes, AbsInfo
    from mapper_module.utils import (
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

    cap = {
        ecodes.EV_KEY: [ecodes.BTN_LEFT, ecodes.BTN_RIGHT, ecodes.BTN_MIDDLE],
        ecodes.EV_REL: [ecodes.REL_X, ecodes.REL_Y, ecodes.REL_WHEEL],
        ecodes.EV_ABS: [
            (
                ecodes.ABS_X,
                AbsInfo(value=0, min=0, max=65535, fuzz=0, flat=0, resolution=0),
            ),
            (
                ecodes.ABS_Y,
                AbsInfo(value=0, min=0, max=65535, fuzz=0, flat=0, resolution=0),
            ),
        ],
    }
    ui_device = UInput(cap, name="Touch2Key-Mouse")

    BTN_MAP = {
        LEFT_BUTTON_DOWN: (ecodes.BTN_LEFT, 1),
        LEFT_BUTTON_UP: (ecodes.BTN_LEFT, 0),
        RIGHT_BUTTON_DOWN: (ecodes.BTN_RIGHT, 1),
        RIGHT_BUTTON_UP: (ecodes.BTN_RIGHT, 0),
        MIDDLE_BUTTON_DOWN: (ecodes.BTN_MIDDLE, 1),
        MIDDLE_BUTTON_UP: (ecodes.BTN_MIDDLE, 0),
    }

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
