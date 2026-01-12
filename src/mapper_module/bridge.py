import ctypes
import multiprocessing
from interception import Interception, KeyStroke, MouseStroke
from .utils import SCANCODES, M_LEFT, M_RIGHT, M_MIDDLE

# --- Mouse Constants ---
MOUSE_MOVE_RELATIVE = 0x00
MOUSE_MOVE_ABSOLUTE = 0x01
MOUSE_VIRTUAL_DESKTOP = 0x02

LEFT_BUTTON_DOWN, LEFT_BUTTON_UP = 0x0001, 0x0002
RIGHT_BUTTON_DOWN, RIGHT_BUTTON_UP = 0x0004, 0x0008
MIDDLE_BUTTON_DOWN, MIDDLE_BUTTON_UP = 0x0010, 0x0020

# --- Worker: Keyboard (Isolated) ---
def keyboard_worker(k_queue):
    """ Dedicated process for Keyboard events only. """
    import time
    import random

    k_ctx = Interception()
    k_handle = k_ctx.keyboard
    _sleep = time.sleep
    _random = random.random
    
    while True:
        code, state = k_queue.get() # Blocks until key event
        k_ctx.send(k_handle, KeyStroke(code, state))

# --- Worker: Mouse (Isolated with Coalescing) ---
def mouse_worker(m_queue):
    """ Dedicated process for Mouse events with movement coalescing. """
    m_ctx = Interception()
    m_handle = m_ctx.mouse
    
    acc_dx, acc_dy = 0, 0

    while True:
        task, data = m_queue.get()

        if task == "move_rel":
            acc_dx += data[0]
            acc_dy += data[1]

            # Coalesce pending moves
            while not m_queue.empty():
                try:
                    next_task, next_data = m_queue.get_nowait()
                    if next_task == "move_rel":
                        acc_dx += next_data[0]
                        acc_dy += next_data[1]
                    else:
                        # If a button/absolute move is next, break to process it
                        break 
                except: break

            if acc_dx != 0 or acc_dy != 0:
                m_ctx.send(m_handle, MouseStroke(0, MOUSE_MOVE_RELATIVE, 0, int(acc_dx), int(acc_dy)))
                acc_dx, acc_dy = 0, 0
            
            _sleep(0.0008 + _random() * 0.0004) # Fast Randomized Pacing (approx. 1000Hz)

        elif task == "move_abs":
            x, y, flags = data
            m_ctx.send(m_handle, MouseStroke(MOUSE_MOVE_ABSOLUTE, flags, 0, x, y))

        elif task == "button":
            # Data is the button state flag
            m_ctx.send(m_handle, MouseStroke(data, MOUSE_MOVE_RELATIVE, 0, 0, 0))

class InterceptionBridge:
    def __init__(self):
        import ctypes
        # Set timer resolution to 1ms (10,000 units of 100ns)
        ctypes.windll.ntdll.NtSetTimerResolution(10000, 1, ctypes.byref(ctypes.c_ulong()))

self.screen_w = ctypes.windll.user32.GetSystemMetrics(0)
self.screen_h = ctypes.windll.user32.GetSystemMetrics(1)

        # 1. Setup Keyboard Channel (Infinite queue - never drop keys)
        self.k_queue = multiprocessing.Queue()
        self.k_proc = multiprocessing.Process(
            target=keyboard_worker, args=(self.k_queue,), daemon=True
        )
        
        # 2. Setup Mouse Channel (Capped queue - drop frames if lagging)
        self.m_queue = multiprocessing.Queue(maxsize=64)
        self.m_proc = multiprocessing.Process(
            target=mouse_worker, args=(self.m_queue,), daemon=True
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