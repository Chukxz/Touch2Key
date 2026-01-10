import tkinter as tk
from pynput import mouse, keyboard
import pandas as pd
import seaborn as sns
import matplotlib.pyplot as plt
import time
import threading
import sys
import ctypes  # Added for Click-Through logic

class ClickThroughLab:
    def __init__(self):
        self.root = tk.Tk()
        self.root.attributes("-fullscreen", True)
        self.root.attributes("-topmost", True)  # Keep the lab on top of all windows

        # --- OPACITY SETTING ---
        self.opacity = 0.5  # Lowered for better visibility of background apps
        self.root.attributes("-alpha", self.opacity)
        self.root.configure(bg="black")
        
        # --- CLICK-THROUGH LOGIC (Windows Only) ---
        if sys.platform == "win32":
            self.enable_click_through()

        self.data = [] 
        self.start_time = time.time()
        self.is_playing = False 
        
        self.last_esc_time = 0
        self.esc_threshold = 0.5 
        
        self.canvas = tk.Canvas(self.root, bg="black", highlightthickness=0)
        self.canvas.pack(fill="both", expand=True)

        # HUD Instructions
        self.hud_msg = self.canvas.create_text(
            self.root.winfo_screenwidth() // 2, 35,
            text="[GLOBAL RECORDING] Click-Through Active | Double-ESC to Playback | Long-ESC to Exit",
            fill="#888888",
            font=("Arial", 12, "bold")
        )

        self.cross_h = self.canvas.create_line(0, 0, 0, 0, fill="#444444", dash=(4, 4))
        self.cross_v = self.canvas.create_line(0, 0, 0, 0, fill="#444444", dash=(4, 4))

        self.active_key_text = self.canvas.create_text(0, 0, text="", fill="lime", 
                                                      font=("Courier", 16, "bold"), anchor="nw")
        self.coord_text = self.canvas.create_text(0, 0, text="X:0, Y:0", fill="white", 
                                                 font=("Courier", 10), anchor="nw")

        # Listeners
        self.m_listener = mouse.Listener(on_click=self.on_click, on_move=self.on_move)
        self.k_listener = keyboard.Listener(on_press=self.on_press)
        self.m_listener.start()
        self.k_listener.start()

        self.root.focus_force()
        self.flash_hud(count=6)

    def enable_click_through(self):
        """Allows mouse events to pass through the window to apps below."""
        GWL_EXSTYLE = -20
        WS_EX_LAYERED = 0x00080000
        WS_EX_TRANSPARENT = 0x00000020
        hwnd = self.root.winfo_id()
        style = ctypes.windll.user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
        style |= WS_EX_LAYERED | WS_EX_TRANSPARENT
        ctypes.windll.user32.SetWindowLongW(hwnd, GWL_EXSTYLE, style)

    def disable_click_through(self):
        """Restores normal window interaction."""
        GWL_EXSTYLE = -20
        hwnd = self.root.winfo_id()
        ctypes.windll.user32.SetWindowLongW(hwnd, GWL_EXSTYLE, 0)

    def flash_hud(self, count):
        if count > 0:
            current_color = self.canvas.itemcget(self.hud_msg, "fill")
            next_color = "white" if current_color == "#888888" else "#888888"
            self.canvas.itemconfig(self.hud_msg, fill=next_color)
            self.root.after(250, lambda: self.flash_hud(count - 1))

    def update_visuals(self, x, y):
        screen_w = self.root.winfo_screenwidth()
        screen_h = self.root.winfo_screenheight()
        self.canvas.coords(self.cross_h, 0, y, screen_w, y)
        self.canvas.coords(self.cross_v, x, 0, x, screen_h)
        
        offset_x = 40 if x < (screen_w - 250) else -220
        offset_y = 20 if y < (screen_h - 100) else -80
        
        self.canvas.coords(self.active_key_text, x + offset_x, y + offset_y)
        self.canvas.coords(self.coord_text, x + offset_x, y + offset_y + 30)
        self.canvas.itemconfig(self.coord_text, text=f"X:{int(x)}, Y:{int(y)}")

    def on_move(self, x, y):
        if not self.is_playing:
            self.data.append({'t': time.time() - self.start_time, 'x': x, 'y': y, 'type': 'move', 'val': None})
            self.canvas.create_rectangle(x, y, x+1, y+1, outline="#333333")
            self.update_visuals(x, y)

    def on_click(self, x, y, button, pressed):
        if pressed and not self.is_playing:
            btn = str(button).split('.')[-1]
            color = "cyan" if btn == "left" else "magenta"
            self.data.append({'t': time.time() - self.start_time, 'x': x, 'y': y, 'type': 'click', 'val': btn})
            self.canvas.create_oval(x-10, y-10, x+10, y+10, outline=color, width=2)

    def on_press(self, key):
        current_time = time.time()
        if key == keyboard.Key.esc:
            if (current_time - self.last_esc_time) < self.esc_threshold:
                self.root.after(0, self.finish_recording)
                return 
            self.last_esc_time = current_time

        if not self.is_playing:
            try: k = key.char if key.char else str(key)
            except: k = str(key)
            mx, my = self.root.winfo_pointerxy()
            self.data.append({'t': time.time() - self.start_time, 'x': mx, 'y': my, 'type': 'key', 'val': k})

    def finish_recording(self):
        self.is_playing = True
        self.m_listener.stop()
        self.k_listener.stop()
        
        # Restore click focus so we can exit later
        if sys.platform == "win32":
            self.disable_click_through()
        
        self.root.bind("<Escape>", lambda e: self.root.destroy())
        self.canvas.delete("all")
        
        self.hud_msg = self.canvas.create_text(
            self.root.winfo_screenwidth() // 2, 50,
            text="[PLAYBACK MODE] Click-Through Disabled | Press ESC to Exit",
            fill="white", font=("Arial", 12, "bold")
        )
        threading.Thread(target=self.playback_loop, daemon=True).start()

    def playback_loop(self):
        start_playback = time.time()
        for event in self.data:
            if not self.root.winfo_exists(): return
            current_elapsed = time.time() - start_playback
            wait = event['t'] - current_elapsed
            if wait > 0: time.sleep(wait)
            
            x, y = event['x'], event['y']
            if event['type'] == 'move':
                self.canvas.create_rectangle(x, y, x+1, y+1, outline="#444444")
                self.update_visuals(x, y)
            elif event['type'] == 'click':
                color = "cyan" if event['val'] == "left" else "magenta"
                self.canvas.create_oval(x-12, y-12, x+12, y+12, outline=color, width=3)

        time.sleep(1)
        if self.root.winfo_exists():
            self.root.destroy()
            self.show_heatmap()

    def show_heatmap(self):
        df = pd.DataFrame(self.data)
        df_filtered = df[df['type'] != 'move']
        plt.figure(figsize=(12, 7), facecolor='black')
        ax = plt.gca()
        ax.set_facecolor('black')
        if not df_filtered.empty:
            sns.kdeplot(data=df_filtered, x="x", y="y", fill=True, cmap="magma", levels=30, thresh=0.01)
        plt.title("Global Interaction Pattern", color="white")
        plt.axis('off')
        plt.gca().invert_yaxis()
        plt.show()

if __name__ == "__main__":
    app = ClickThroughLab()
    app.root.mainloop()