import tkinter as tk
from pynput import mouse, keyboard
import pandas as pd
import seaborn as sns
import matplotlib.pyplot as plt
import threading

class InputLoggerApp:
    def __init__(self):
        self.root = tk.Tk()
        self.root.title("Input Diagnostic Lab")
        self.root.attributes("-fullscreen", True)
        self.root.configure(bg="black")
        
        # Data storage
        self.data = []
        self.recording = True

        # Canvas for real-time visualization
        self.canvas = tk.Canvas(self.root, bg="black", highlightthickness=0)
        self.canvas.pack(fill="both", expand=True)

        # Instructions Overlay
        self.label = tk.Label(self.root, text="LAB MODE: ESC to Finish & View Heatmap", 
                              fg="#555555", bg="black", font=("Courier", 12))
        self.label.place(relx=0.5, rely=0.05, anchor="center")

        # Listeners
        self.m_listener = mouse.Listener(on_click=self.on_click, on_move=self.on_move)
        self.k_listener = keyboard.Listener(on_press=self.on_press)
        
        self.m_listener.start()
        self.k_listener.start()

        # Exit Bind
        self.root.bind("<Escape>", lambda e: self.finish())

    def on_move(self, x, y):
        # Optional: Log movements (very high volume data)
        self.canvas.create_oval(x-1, y-1, x+1, y+1, fill="#1a1a1a", outline="")

    def on_click(self, x, y, button, pressed):
        if pressed:
            self.data.append({'x': x, 'y': y, 'type': 'Click'})
            # Draw real-time "touch" indicator
            self.canvas.create_oval(x-10, y-10, x+10, y+10, outline="cyan", width=2)
            self.canvas.create_text(x, y+20, text="CLICK", fill="cyan", font=("Arial", 8))

    def on_press(self, key):
        # Get mouse pos to anchor the keypress visually
        x, y = self.root.winfo_pointerxy()
        try:
            k = key.char if key.char else str(key)
        except:
            k = str(key)
            
        self.data.append({'x': x, 'y': y, 'type': f'Key: {k}'})
        # Draw real-time "key" indicator
        self.canvas.create_rectangle(x-15, y-15, x+15, y+15, outline="lime", width=2)
        self.canvas.create_text(x, y, text=k, fill="white", font=("Arial", 10, "bold"))

    def finish(self):
        self.recording = False
        self.m_listener.stop()
        self.k_listener.stop()
        self.root.destroy()
        self.show_final_analysis()

    def show_final_analysis(self):
        if not self.data: return
        df = pd.DataFrame(self.data)
        
        plt.figure(figsize=(12, 8), facecolor='black')
        ax = plt.gca()
        ax.set_facecolor('black')
        
        # Heatmap on black background
        sns.kdeplot(data=df, x="x", y="y", fill=True, thresh=0.01, 
                    levels=50, cmap="inferno", alpha=0.8)
        
        # Clean up plot aesthetics
        plt.title("Diagnostic Input Heatmap", color="white")
        plt.axis('off')
        plt.gca().invert_yaxis()
        plt.show()

if __name__ == "__main__":
    app = InputLoggerApp()
    app.root.mainloop()