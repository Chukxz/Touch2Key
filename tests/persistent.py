import tkinter as tk
from pynput import mouse, keyboard
import pandas as pd
import seaborn as sns
import matplotlib.pyplot as plt
import time
import threading
import sys

class PersistentLab:
    def __init__(self):
        self.root = tk.Tk()
        self.root.attributes("-fullscreen", True)

        # --- OPACITY SETTING ---
        # 1.0 = Solid, 0.0 = Invisible. 0.7 is a good "tinted" balance.
        self.opacity = 0.7 
        self.root.attributes("-alpha", self.opacity)
        
        self.root.configure(bg="black")
        
        self.data = [] 
        self.start_time = time.time()
        self.is_playing = False 
        
        self.last_esc_time = 0
        self.esc_threshold = 0.5 
        
        self.canvas = tk.Canvas(self.root, bg="black", highlightthickness=0)
        self.canvas.pack(fill="both", expand=True)

        # --- HUD INSTRUCTIONS ---
        self.hud_msg = self.canvas.create_text(
            self.root.winfo_screenwidth() // 2, 35,
            text="[RECORDING MODE] Double-Press ESC to Finish & Start Playback or Long-Press ESC to Force Exit",
            fill="#444444",
            font=("Arial", 12, "bold")
        )

        # Crosshair Lines
        self.cross_h = self.canvas.create_line(0, 0, 0, 0, fill="#222222", dash=(4, 4))
        self.cross_v = self.canvas.create_line(0, 0, 0, 0, fill="#222222", dash=(4, 4))

        # Floating Labels
        self.active_key_text = self.canvas.create_text(0, 0, text="", fill="lime", 
                                                      font=("Courier", 16, "bold"), anchor="nw")
        self.coord_text = self.canvas.create_text(0, 0, text="X:0, Y:0", fill="white", 
                                                 font=("Courier", 10), anchor="nw")

        # Start listeners
        self.m_listener = mouse.Listener(on_click=self.on_click, on_move=self.on_move)
        self.k_listener = keyboard.Listener(on_press=self.on_press)
        self.m_listener.start()
        self.k_listener.start()

        self.root.focus_force()
        
        # Start the flashing effect
        self.flash_hud(count=6)

    def flash_hud(self, count):
        """Alternates HUD color to grab attention"""
        if count > 0:
            current_color = self.canvas.itemcget(self.hud_msg, "fill")
            next_color = "white" if current_color == "#444444" else "#444444"
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
            self.canvas.create_rectangle(x, y, x+1, y+1, outline="#1a1a1a")
            self.update_visuals(x, y)

    def on_click(self, x, y, button, pressed):
        if pressed and not self.is_playing:
            btn = str(button).split('.')[-1]
            color = "cyan" if btn == "left" else "magenta" if btn == "right" else "yellow"
            self.data.append({'t': time.time() - self.start_time, 'x': x, 'y': y, 'type': 'click', 'val': btn})
            
            self.canvas.create_oval(x-10, y-10, x+10, y+10, outline=color, width=2)
            label_y_offset = 25 if y < (self.root.winfo_screenheight() - 50) else -25
            self.canvas.create_text(x, y + label_y_offset, text=f"{btn.upper()} ({int(x)},{int(y)})", 
                                  fill=color, font=("Arial", 9), anchor="n" if label_y_offset > 0 else "s")

    def on_press(self, key):
        current_time = time.time()
        
        if key == keyboard.Key.esc:
            if (current_time - self.last_esc_time) < self.esc_threshold:
                self.root.after(0, self.finish_recording)
                return 
            else:
                # Flash HUD yellow to indicate one ESC was registered
                self.canvas.itemconfig(self.hud_msg, fill="yellow")
                self.root.after(200, lambda: self.canvas.itemconfig(self.hud_msg, fill="#444444"))
            self.last_esc_time = current_time

        if not self.is_playing:
            try: k = key.char if key.char else str(key)
            except: k = str(key)
            k = k.replace('Key.', '').upper()
            mx, my = self.root.winfo_pointerxy()
            self.data.append({'t': time.time() - self.start_time, 'x': mx, 'y': my, 'type': 'key', 'val': k})
            self.canvas.itemconfig(self.active_key_text, text=f"KEY: {k}")

    def handle_playback_esc(self, event):
        self.root.destroy()
        sys.exit()

    def finish_recording(self):
        self.is_playing = True
        self.m_listener.stop()
        self.k_listener.stop()
        
        self.root.bind("<Escape>", self.handle_playback_esc)
        self.canvas.delete("all")
        
        # Reset visual assets for playback
        self.cross_h = self.canvas.create_line(0, 0, 0, 0, fill="#333333", dash=(2, 2))
        self.cross_v = self.canvas.create_line(0, 0, 0, 0, fill="#333333", dash=(2, 2))
        self.active_key_text = self.canvas.create_text(0, 0, text="", fill="lime", font=("Courier", 16, "bold"), anchor="nw")
        self.coord_text = self.canvas.create_text(0, 0, text="", fill="white", font=("Courier", 10), anchor="nw")
        
        # --- NEW: PLAYBACK STATUS ---
        self.hud_msg = self.canvas.create_text(
            self.root.winfo_screenwidth() // 2, 50,
            text="[PLAYBACK MODE] Press ESC once to Force Exit",
            fill="#444444",  # Subtle grey to avoid distraction
            font=("Arial", 12, "bold"),
        )
        threading.Thread(target=self.playback_loop, daemon=True).start()
        
        # Start the flashing effect
        self.flash_hud(count=6)

    def playback_loop(self):
        start_playback = time.time()
        for event in self.data:
            if not self.root.winfo_exists(): return
            current_elapsed = time.time() - start_playback
            wait = event['t'] - current_elapsed
            if wait > 0: time.sleep(wait)
            
            x, y = event['x'], event['y']
            if event['type'] == 'move':
                self.canvas.create_rectangle(x, y, x+1, y+1, outline="#333333")
                self.update_visuals(x, y)
            elif event['type'] == 'click':
                color = "cyan" if event['val'] == "left" else "magenta"
                self.canvas.create_oval(x-12, y-12, x+12, y+12, outline=color, width=3)
            elif event['type'] == 'key':
                self.canvas.itemconfig(self.active_key_text, text=f"REPLAY KEY: {event['val']}")

        time.sleep(1)
        if self.root.winfo_exists():
            self.root.destroy()
            self.show_heatmap()

    def show_heatmap(self):
        if not self.data: return
        df = pd.DataFrame(self.data)
        df_filtered = df[df['type'] != 'move']
        plt.figure(figsize=(12, 7), facecolor='black')
        ax = plt.gca()
        ax.set_facecolor('black')
        if len(df_filtered) > 1:
            sns.kdeplot(data=df_filtered, x="x", y="y", fill=True, cmap="magma", levels=30, thresh=0.01)
        sns.scatterplot(data=df_filtered, x="x", y="y", hue="type", s=40, palette="pastel")
        plt.title("Session Summary", color="white")
        plt.axis('off')
        plt.gca().invert_yaxis()
        plt.show()

if __name__ == "__main__":
    app = PersistentLab()
    app.root.mainloop()