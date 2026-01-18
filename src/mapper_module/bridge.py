import ctypes
import multiprocessing
from .utils import (
    SCANCODES, M_LEFT, M_RIGHT, M_MIDDLE,
    MOUSE_MOVE_ABSOLUTE, MOUSE_VIRTUAL_DESKTOP,
    LEFT_BUTTON_DOWN, LEFT_BUTTON_UP,
    RIGHT_BUTTON_DOWN, RIGHT_BUTTON_UP,
    MIDDLE_BUTTON_DOWN, MIDDLE_BUTTON_UP,
    mouse_worker, keyboard_worker,
    )


class InterceptionBridge:
    def __init__(self):
        self.screen_w = ctypes.windll.user32.GetSystemMetrics(0)
        self.screen_h = ctypes.windll.user32.GetSystemMetrics(1)

        # 1. Setup Keyboard Channel (Infinite queue - never drop keys)
        self.k_queue = multiprocessing.Queue()
        self.k_proc = multiprocessing.Process(
            target=keyboard_worker, name="Keyboard Worker", args=(self.k_queue,), daemon=True
        )
        
        # 2. Setup Mouse Channel (Capped queue - drop frames if lagging)
        self.m_queue = multiprocessing.Queue(maxsize=64)
        self.m_proc = multiprocessing.Process(
            target=mouse_worker, name="Mouse Worker", args=(self.m_queue,), daemon=True
        )

        # Start both engines
        self.k_proc.start()
        self.m_proc.start()
        
        print(f"[Bridge] Dual Engine Started. K-PID: {self.k_proc.pid} | M-PID: {self.m_proc.pid}")

    # --- Keyboard API ---
    def key_down(self, code): self.k_queue.put((code, 0))
    def key_up(self, code): self.k_queue.put((code, 1))

    # --- Mouse API ---
    def mouse_move_rel(self, dx, dy):
        try:
            self.m_queue.put_nowait(("move_rel", (dx, dy)))
        except: pass # Drop move if flooded

    def mouse_move_abs(self, x, y):
        abs_x = int((x * 65535) / self.screen_w)
        abs_y = int((y * 65535) / self.screen_h)
        flags = MOUSE_MOVE_ABSOLUTE | MOUSE_VIRTUAL_DESKTOP
        self.m_queue.put(("move_abs", (abs_x, abs_y, flags)))

    def left_click_down(self): self.m_queue.put(("button", LEFT_BUTTON_DOWN))
    def left_click_up(self): self.m_queue.put(("button", LEFT_BUTTON_UP))
    def right_click_down(self): self.m_queue.put(("button", RIGHT_BUTTON_DOWN))
    def right_click_up(self): self.m_queue.put(("button", RIGHT_BUTTON_UP))
    def middle_click_down(self): self.m_queue.put(("button", MIDDLE_BUTTON_DOWN))
    def middle_click_up(self): self.m_queue.put(("button", MIDDLE_BUTTON_UP))

    def release_all(self):
        """Sends 'UP' signals for all critical keys and mouse buttons."""
        print("[Bridge] Emergency Release: Clearing all input states...")
        
        # Clear Mouse buttons
        for btn_up in [LEFT_BUTTON_UP, RIGHT_BUTTON_UP, MIDDLE_BUTTON_UP]:
            try:
                self.m_queue.put(("button", btn_up))
            except: pass

        internal_mouse_codes = {M_LEFT, M_RIGHT, M_MIDDLE}
        
        for code in SCANCODES.values():
            if code not in internal_mouse_codes:
                try:
                    self.k_queue.put((code, 1))
                except: pass
            
        print("[Bridge] Release signals dispatched.")