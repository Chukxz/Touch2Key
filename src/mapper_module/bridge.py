import ctypes
import multiprocessing
import time
from interception import Interception, KeyStroke, MouseStroke

# --- Mouse Constants ---
MOUSE_MOVE_RELATIVE = 0x00
MOUSE_MOVE_ABSOLUTE = 0x01
MOUSE_VIRTUAL_DESKTOP = 0x02

LEFT_BUTTON_DOWN, LEFT_BUTTON_UP = 0x0001, 0x0002
RIGHT_BUTTON_DOWN, RIGHT_BUTTON_UP = 0x0004, 0x0008
MIDDLE_BUTTON_DOWN, MIDDLE_BUTTON_UP = 0x0010, 0x0020

def bridge_worker(cmd_queue):
    """
    Runs in a dedicated OS process. 
    Contexts must be created inside the process they are used in.
    """
    k_ctx = Interception()
    m_ctx = Interception()
    
    # Cache handles for speed
    k_handle = k_ctx.keyboard
    m_handle = m_ctx.mouse
    
    acc_dx, acc_dy = 0, 0

    while True:
        # Blocks here until a command arrives
        task, data = cmd_queue.get()

        if task == "K":  # Keyboard: (code, state)
            k_ctx.send(k_handle, KeyStroke(data[0], data[1]))

        elif task == "move_rel":
            acc_dx += data[0]
            acc_dy += data[1]

            # Coalesce: Merge all waiting moves into one packet
            while not cmd_queue.empty():
                try:
                    # peek next item without removing
                    next_task, next_data = cmd_queue.get_nowait()
                    if next_task == "move_rel":
                        acc_dx += next_data[0]
                        acc_dy += next_data[1]
                    else:
                        # It's a key/button; we must stop coalescing 
                        # and process the sum immediately.
                        # Put it back in the queue or handle manually:
                        # To keep order perfect, we handle the move, then the next item.
                        # For simplicity, we process it in the next loop iteration.
                        break 
                except: break

            if acc_dx != 0 or acc_dy != 0:
                ms = MouseStroke(0, MOUSE_MOVE_RELATIVE, 0, int(acc_dx), int(acc_dy))
                m_ctx.send(m_handle, ms)
                acc_dx, acc_dy = 0, 0
            
            # Pacing to keep Windows Input Stack happy (~1000Hz)
            time.sleep(0.001)

        elif task == "move_abs":
            x, y, flags = data
            ms = MouseStroke(MOUSE_MOVE_ABSOLUTE, flags, 0, x, y)
            m_ctx.send(m_handle, ms)

        elif task == "button":
            ms = MouseStroke(data, MOUSE_MOVE_RELATIVE, 0, 0, 0)
            m_ctx.send(m_handle, ms)

class InterceptionBridge:
    def __init__(self):
        # maxsize prevents queue from growing infinitely if driver lags
        self.cmd_queue = multiprocessing.Queue(maxsize=128)
        
        # Start the worker process
        self.process = multiprocessing.Process(
            target=bridge_worker, 
            args=(self.cmd_queue,),
            daemon=True
        )
        self.process.start()
        
        print(f"[Bridge] Multiprocessing Engine Started (PID: {self.process.pid})")

    # --- Keyboard API ---
    def key_down(self, code): self.cmd_queue.put(("K", (code, 0)))
    def key_up(self, code): self.cmd_queue.put(("K", (code, 1)))

    # --- Mouse API ---
    def mouse_move_rel(self, dx, dy):
        try:
            # Drop frames if bridge is overwhelmed (prevents lag)
            self.cmd_queue.put_nowait(("move_rel", (dx, dy)))
        except: pass 

    def mouse_move_abs(self, x, y):
        # Interception requires 0-65535 scaling
        screen_w = ctypes.windll.user32.GetSystemMetrics(0)
        screen_h = ctypes.windll.user32.GetSystemMetrics(1)
        abs_x = int((x * 65535) / screen_w)
        abs_y = int((y * 65535) / screen_h)
        flags = MOUSE_MOVE_ABSOLUTE | MOUSE_VIRTUAL_DESKTOP
        self.cmd_queue.put(("move_abs", (abs_x, abs_y, flags)))

    def left_click_down(self): self.cmd_queue.put(("button", LEFT_BUTTON_DOWN))
    def left_click_up(self): self.cmd_queue.put(("button", LEFT_BUTTON_UP))
    def right_click_down(self): self.cmd_queue.put(("button", RIGHT_BUTTON_DOWN))
    def right_click_up(self): self.cmd_queue.put(("button", RIGHT_BUTTON_UP))