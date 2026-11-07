from __future__ import annotations

import ctypes
import queue
import struct
import threading
from random import uniform as _uniform
from time import monotonic as _monotonic, perf_counter_ns as _perf_counter_ns, sleep as _sleep
from typing import TYPE_CHECKING

from modules.scripts.utils import (
    BUTTON_4_DOWN,
    BUTTON_4_UP,
    BUTTON_5_DOWN,
    BUTTON_5_UP,
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
    MOUSE_HWHEEL,
    MOUSE_MOVE_ABSOLUTE,
    MOUSE_MOVE_RELATIVE,
    MOUSE_VIRTUAL_DESKTOP,
    MOUSE_WHEEL,
    NT_TIMER_RES,
    PACK_ABS_STRUCT,
    PACK_BUTTON_STRUCT,
    PACK_KEY_STRUCT,
    PACK_REL_STRUCT,
    PACK_TYPEMATIC_STRUCT,
    PACK_WHEEL_STRUCT,
    RIGHT_BUTTON_DOWN,
    RIGHT_BUTTON_UP,
    TASK_ABS,
    TASK_REL,
    TASK_WHEEL,
    WHEEL_DELTA,
)

if TYPE_CHECKING:
    from multiprocessing.connection import Connection
    from multiprocessing.queues import Queue

IDLE_RELEASE_S = 15.0
POLL_S = 1.0


def _release_all_buttons(
    log_queue: Queue,
    m_ctx,
    m_handle,
    M_Stroke,
    left_down: bool,
    right_down: bool,
    middle_down: bool,
    btn4_down: bool,
    btn5_down: bool,
    reason="",
):
    buttons_count = sum([left_down, right_down, middle_down, btn4_down, btn5_down])
    if buttons_count == 0:
        return

    log_queue.put(f"{reason}. Releasing {buttons_count} buttons.")
    if left_down:
        m_ctx.send(m_handle, M_Stroke(MOUSE_MOVE_RELATIVE, LEFT_BUTTON_UP, 0, 0, 0))
    if right_down:
        m_ctx.send(m_handle, M_Stroke(MOUSE_MOVE_RELATIVE, RIGHT_BUTTON_UP, 0, 0, 0))
    if middle_down:
        m_ctx.send(m_handle, M_Stroke(MOUSE_MOVE_RELATIVE, MIDDLE_BUTTON_UP, 0, 0, 0))
    if btn4_down:
        m_ctx.send(m_handle, M_Stroke(MOUSE_MOVE_RELATIVE, BUTTON_4_UP, 0, 0, 0))
    if btn5_down:
        m_ctx.send(m_handle, M_Stroke(MOUSE_MOVE_RELATIVE, BUTTON_5_UP, 0, 0, 0))


def keyboard_worker(
    k_pipe_read: Connection,
    log_queue: Queue,
    k_device_handle: int | None,
):
    if k_device_handle is None:
        log_queue.put("Keyboard worker has an invalid Interception keyboard handle.")
        return

    ctypes.windll.ntdll.NtSetTimerResolution(
        NT_TIMER_RES, 1, ctypes.byref(ctypes.c_ulong())
    )

    from interception.interception import Interception
    from interception.strokes import KeyStroke

    k_ctx = Interception()
    pressed_keys: set[int] = set()
    state = {"running": True}

    typematic_cfg = {
        "enabled": True,
        "delay_ns": 250_000_000,
        "repeat_rate": 0.0333,
        "ignore_typematic": False,
        "non_spamming": set(),
    }

    key_queue: queue.Queue = queue.Queue()

    def _stroke(code: int, up: bool):
        k_state = 1 if up else 0
        if code > 0xFF:
            k_state |= 2
        return KeyStroke(code & 0xFF, k_state)

    def key_injection_loop():
        active: set[int] = set()
        repeat_key: int | None = None
        next_repeat_ns = 0

        while state["running"]:
            try:
                if repeat_key is None:
                    wait = 0.1
                else:
                    wait = max(0.0, (next_repeat_ns - _perf_counter_ns()) / 1e9)

                try:
                    code, is_down = key_queue.get(timeout=wait)
                except queue.Empty:
                    code = None

                if code is not None:
                    if is_down:
                        if code not in active:
                            active.add(code)
                            if (
                                not typematic_cfg["ignore_typematic"]
                                and typematic_cfg["enabled"]
                                and (code & 0xFF) not in typematic_cfg["non_spamming"]
                            ):
                                repeat_key = code
                                next_repeat_ns = (
                                    _perf_counter_ns() + typematic_cfg["delay_ns"]
                                )
                            else:
                                repeat_key = None
                            k_ctx.send(k_device_handle, _stroke(code, False))
                            _sleep(_uniform(MIN_KEY_DWELL, MAX_KEY_DWELL))
                    elif is_down is False:
                        active.discard(code)
                        if repeat_key == code:
                            repeat_key = None
                        k_ctx.send(k_device_handle, _stroke(code, True))
                        _sleep(CONSTANT_DWELL)
                    continue

                if repeat_key is not None and _perf_counter_ns() >= next_repeat_ns:
                    k_ctx.send(k_device_handle, _stroke(repeat_key, False))
                    next_repeat_ns = _perf_counter_ns() + int(
                        typematic_cfg["repeat_rate"] * 1e9
                    )
            except Exception as e:
                log_queue.put(f"Keyboard: Key Injection Error: {e}.")
                _sleep(0.01)

    injector_thread = threading.Thread(
        target=key_injection_loop, name="Keyboard-Injection-Loop", daemon=True
    )
    injector_thread.start()

    last_rx = _monotonic()

    while state["running"]:
        try:
            if k_pipe_read.poll(POLL_S):
                last_rx = _monotonic()
                payload = k_pipe_read.recv_bytes()

                if len(payload) == 3:
                    win_code, k_state = PACK_KEY_STRUCT.unpack_from(payload, 0)
                    if k_state == KEY_PING:
                        continue
                    if k_state == 0:
                        pressed_keys.add(win_code)
                        key_queue.put((win_code, True))
                    elif k_state == 1:
                        pressed_keys.discard(win_code)
                        key_queue.put((win_code, False))
                    continue

                if payload and payload[0] == KEY_CONFIG:
                    _, enabled, delay_ns, rate_sec, ignore_typematic, count = (
                        PACK_TYPEMATIC_STRUCT.unpack_from(payload, 0)
                    )
                    offset = PACK_TYPEMATIC_STRUCT.size
                    excludes = set()
                    for _ in range(count):
                        (sc,) = struct.unpack_from("<H", payload, offset)
                        excludes.add(sc & 0xFF)
                        offset += 2

                    typematic_cfg["enabled"] = enabled
                    typematic_cfg["delay_ns"] = delay_ns
                    typematic_cfg["repeat_rate"] = rate_sec
                    typematic_cfg["ignore_typematic"] = ignore_typematic
                    typematic_cfg["non_spamming"] = excludes
                    continue

            elif pressed_keys and (_monotonic() - last_rx) >= IDLE_RELEASE_S:
                log_queue.put(
                    f"Keyboard Timeout: releasing {len(pressed_keys)} keys."
                )
                for code in list(pressed_keys):
                    key_queue.put((code, False))
                pressed_keys.clear()

        except EOFError:
            state["running"] = False
        except Exception as e:
            log_queue.put(f"Keyboard Worker crashed: {e}.")
            state["running"] = False

    state["running"] = False
    injector_thread.join(timeout=2.0)

    for code in list(pressed_keys):
        try:
            k_ctx.send(k_device_handle, _stroke(code, True))
        except Exception:
            pass


def mouse_worker(
    m_pipe_read: Connection,
    mb_pipe_read: Connection,
    log_queue: Queue,
    m_device_handle: int | None,
):
    if m_device_handle is None:
        log_queue.put("Mouse worker has an invalid Interception mouse handle.")
        return

    ctypes.windll.ntdll.NtSetTimerResolution(
        NT_TIMER_RES, 1, ctypes.byref(ctypes.c_ulong())
    )

    from interception.interception import Interception
    from interception.strokes import MouseStroke

    m_ctx = Interception()
    send_lock = threading.Lock()
    state = {"running": True}

    def _send_abs(x: int, y: int) -> None:
        with send_lock:
            m_ctx.send(
                m_device_handle,
                MouseStroke(
                    MOUSE_MOVE_ABSOLUTE | MOUSE_VIRTUAL_DESKTOP,
                    0,
                    0,
                    int(x),
                    int(y),
                ),
            )

    def button_loop():
        left_down = right_down = middle_down = btn4_down = btn5_down = False
        last_rx = _monotonic()

        while state["running"]:
            try:
                if mb_pipe_read.poll(POLL_S):
                    last_rx = _monotonic()
                    payload = mb_pipe_read.recv_bytes()

                    if payload[0] == TASK_ABS:
                        _, x, y = PACK_ABS_STRUCT.unpack_from(payload, 0)
                        _send_abs(x, y)
                        _sleep(CONSTANT_DWELL)
                        continue

                    _, data = PACK_BUTTON_STRUCT.unpack_from(payload, 0)

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
                    elif data == BUTTON_4_DOWN:
                        btn4_down = True
                    elif data == BUTTON_4_UP:
                        btn4_down = False
                    elif data == BUTTON_5_DOWN:
                        btn5_down = True
                    elif data == BUTTON_5_UP:
                        btn5_down = False

                    with send_lock:
                        m_ctx.send(
                            m_device_handle,
                            MouseStroke(MOUSE_MOVE_RELATIVE, data, 0, 0, 0),
                        )

                    if data in DOWN_TUPLE:
                        _sleep(_uniform(MIN_BUTTON_DWELL, MAX_BUTTON_DWELL))
                    else:
                        _sleep(CONSTANT_DWELL)

                elif (
                    (left_down or right_down or middle_down or btn4_down or btn5_down)
                    and (_monotonic() - last_rx) >= IDLE_RELEASE_S
                ):
                    with send_lock:
                        _release_all_buttons(
                            log_queue,
                            m_ctx,
                            m_device_handle,
                            MouseStroke,
                            left_down,
                            right_down,
                            middle_down,
                            btn4_down,
                            btn5_down,
                            "Mouse Button Timeout",
                        )
                    left_down = right_down = middle_down = btn4_down = btn5_down = False

            except EOFError:
                state["running"] = False
            except Exception as e:
                log_queue.put(f"Mouse Button Worker error: {e}.")
                _sleep(0.05)

    button_thread = threading.Thread(
        target=button_loop, name="Mouse-Button-Loop", daemon=True
    )
    button_thread.start()

    acc_dx = 0
    acc_dy = 0
    acc_dw_x = 0
    acc_dw_y = 0
    pending_task = None

    while state["running"]:
        try:
            if not button_thread.is_alive():
                log_queue.put("Mouse Button thread exited; stopping mouse worker.")
                state["running"] = False
                break

            if pending_task:
                payload = pending_task
                task_id = pending_task[0]
                pending_task = None
            else:
                if m_pipe_read.poll(POLL_S):
                    payload = m_pipe_read.recv_bytes()
                    task_id = payload[0]
                else:
                    continue

            if task_id == TASK_REL:
                _, dx, dy = PACK_REL_STRUCT.unpack_from(payload, 0)
                acc_dx += dx
                acc_dy += dy

                coalesce_count = 0
                while m_pipe_read.poll() and coalesce_count < MAX_COALESCE:
                    next_payload = m_pipe_read.recv_bytes()
                    next_task_id = next_payload[0]

                    if next_task_id == TASK_REL:
                        _, next_dx, next_dy = PACK_REL_STRUCT.unpack_from(
                            next_payload, 0
                        )
                        acc_dx += next_dx
                        acc_dy += next_dy
                        coalesce_count += 1
                    else:
                        pending_task = next_payload
                        break

                if acc_dx != 0 or acc_dy != 0:
                    with send_lock:
                        m_ctx.send(
                            m_device_handle,
                            MouseStroke(
                                MOUSE_MOVE_RELATIVE, 0, 0, int(acc_dx), int(acc_dy)
                            ),
                        )
                    acc_dx = 0
                    acc_dy = 0

                _sleep(_uniform(MIN_MOUSE_DWELL, MAX_MOUSE_DWELL))

            elif task_id == TASK_ABS:
                _, x, y = PACK_ABS_STRUCT.unpack_from(payload, 0)
                _send_abs(x, y)
                _sleep(CONSTANT_DWELL)

            elif task_id == TASK_WHEEL:
                _, dw_x, dw_y = PACK_WHEEL_STRUCT.unpack_from(payload, 0)
                acc_dw_x += dw_x
                acc_dw_y += dw_y

                coalesce_count = 0
                while m_pipe_read.poll() and coalesce_count < MAX_COALESCE:
                    next_payload = m_pipe_read.recv_bytes()
                    next_task_id = next_payload[0]

                    if next_task_id == TASK_WHEEL:
                        _, next_wx, next_wy = PACK_WHEEL_STRUCT.unpack_from(
                            next_payload, 0
                        )
                        acc_dw_x += next_wx
                        acc_dw_y += next_wy
                        coalesce_count += 1
                    else:
                        pending_task = next_payload
                        break

                with send_lock:
                    if acc_dw_y != 0:
                        m_ctx.send(
                            m_device_handle,
                            MouseStroke(
                                MOUSE_MOVE_RELATIVE,
                                MOUSE_WHEEL,
                                int(acc_dw_y * WHEEL_DELTA),
                                0,
                                0,
                            ),
                        )

                    if acc_dw_x != 0:
                        m_ctx.send(
                            m_device_handle,
                            MouseStroke(
                                MOUSE_MOVE_RELATIVE,
                                MOUSE_HWHEEL,
                                int(acc_dw_x * WHEEL_DELTA),
                                0,
                                0,
                            ),
                        )

                    acc_dw_x = 0
                    acc_dw_y = 0

                _sleep(CONSTANT_DWELL)

        except EOFError:
            state["running"] = False
        except Exception as e:
            log_queue.put(f"Mouse Movement Worker crashed: {e}.")
            state["running"] = False

    state["running"] = False
    button_timer_join = button_thread.join(timeout=2.0)
