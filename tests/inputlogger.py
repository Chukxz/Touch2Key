import tkinter as tk
from pynput import mouse, keyboard
import pandas as pd
import seaborn as sns
import matplotlib.pyplot as plt
import time

class InputDiagnosticLab:
    def __init__(self):
        self.root = tk.Tk()
        self.root.title("Diagnostic Input Lab")
        self.root.attributes("-fullscreen", True)
        self.root.configure(bg="black")
        
        # Data storage for heatmap
        self.data = []
        
        # Canvas for drawing
        self.canvas = tk.Canvas(self.root, bg="black", highlightthickness=0)
        self.canvas.pack(fill="both", expand=True)

        # The "Active Key" Label (Overwrites every time)
        self.active_key_text = self.canvas.create_text(0, 0, text="", fill="lime", 
                                                      font=("Courier", 16, "bold"))

        # Instructions
        self.canvas.create_text(self.root.winfo_screenwidth()//2, 30, 
                                text="DIAGNOSTIC MODE: Press ESC to exit and view Heatmap", 
                                fill="#444444", font=("Arial", 10))

        # Mouse & Keyboard Listeners
        self.m_listener = mouse.Listener(on_click=self.on_click, on_move=self.on_move)
        self.k_listener = keyboard.Listener(on_press=self.on_press)
        
        self.m_listener.start()
        self.k_listener.start()

        # Exit Bind
        self.root.bind("<Escape>", lambda e: self.finish())

    def on_move(self, x, y):
        # Draw a faint path (trailing effect)
        self.canvas.create_rectangle(x, y, x+1, y+1, outline="#1a1a1a")
        # Move the active key label to follow the mouse cursor
        self.canvas.coords(self.active_key_text, x + 20, y - 20)

    def on_click(self, x, y, button, pressed):
        if pressed:
            # Map button names
            btn_name = str(button).replace('Button.', '').capitalize()
            color = "cyan" if "Left" in btn_name else "magenta" if "Right" in btn_name else "yellow"
            
            self.data.append({'x': x, 'y': y, 'type': f'{btn_name} Click', 'time': time.time()})
            
            # Draw visual "Ripple"
            ring = self.canvas.create_oval(x-15, y-15, x+15, y+15, outline=color, width=2)
            label = self.canvas.create_text(x, y+25, text=f"{btn_name}", fill=color, font=("Arial", 8))
            
            # Fade out the click indicator after 1 second
            self.root.after(1000, lambda: self.canvas.delete(ring))
            self.root.after(1000, lambda: self.canvas.delete(label))

    def on_press(self, key):
        # Overwrite the previous key label
        try:
            k = key.char if key.char else str(key)
        except:
            k = str(key)
        
        k_clean = k.replace('Key.', '').upper()
        
        # Capture current mouse pos for heatmap data
        mx, my = self.root.winfo_pointerxy()
        self.data.append({'x': mx, 'y': my, 'type': f'Key: {k_clean}', 'time': time.time()})
        
        # Update the single active key label on screen
        self.canvas.itemconfig(self.active_key_text, text=f"[{k_clean}]")

    def finish(self):
        self.m_listener.stop()
        self.k_listener.stop()
        self.root.destroy()
        self.playback_and_heatmap()

    def playback_and_heatmap(self):
        if not self.data: return
        df = pd.DataFrame(self.data)
        
        # 1. Show Static Heatmap Summary
        plt.figure(figsize=(12, 7), facecolor='black')
        ax = plt.gca()
        ax.set_facecolor('black')
        
        sns.kdeplot(data=df, x="x", y="y", fill=True, thresh=0.01, 
                    levels=40, cmap="icefire", alpha=0.7)
        
        sns.scatterplot(data=df, x="x", y="y", hue="type", s=20, palette="pastel")
        
        plt.title("Session Analysis (Click/Key Density)", color="white")
        plt.axis('off')
        plt.gca().invert_yaxis()
        plt.show()

if __name__ == "__main__":
    app = InputDiagnosticLab()
    app.root.mainloop()