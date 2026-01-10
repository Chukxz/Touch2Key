import ctypes
import threading
import tkinter as tk
import pandas as pd
import seaborn as sns
import matplotlib.pyplot as plt
import pyautogui
from pynput import mouse, keyboard

# --- Windows High-DPI Fix (Prevents heatmap 'drift') ---
try:
    ctypes.windll.shcore.SetProcessDpiAwareness(1)
except Exception:
    ctypes.windll.user32.SetProcessDPIAware()

# Global Data Store
input_data = []
data_lock = threading.Lock()

def on_click(x, y, button, pressed):
    if pressed:
        with data_lock:
            input_data.append({'x': x, 'y': y, 'type': 'Click'})

def on_press(key):
    # Capture mouse position at the moment of keypress for mapping
    mx, my = pyautogui.position()
    try:
        k_name = key.char if key.char else str(key)
    except:
        k_name = str(key)
    with data_lock:
        input_data.append({'x': mx, 'y': my, 'type': f'Key: {k_name}'})

# Background Listener
def start_listeners():
    with mouse.Listener(on_click=on_click) as ml, \
         keyboard.Listener(on_press=on_press) as kl:
        ml.join()
        kl.join()

threading.Thread(target=start_listeners, daemon=True).start()

class GeneralVisualizer:
    def __init__(self, root):
        self.root = root
        self.root.title("Input Heatmapper")
        self.root.geometry("280x140")
        self.root.attributes("-topmost", True)
        self.root.configure(padx=20, pady=10)

        tk.Label(root, text="System-wide Recording Active", fg="#34495e", font=("Arial", 10, "bold")).pack(pady=5)
        
        self.btn_show = tk.Button(root, text="Display Heat Map", command=self.prepare_heatmap, 
                                  bg="#2ecc71", fg="white", font=("Arial", 9, "bold"), height=2, width=25)
        self.btn_show.pack(pady=5)
        
        tk.Button(root, text="Clear Data", command=self.clear, 
                  bg="#e74c3c", fg="white", width=25).pack(pady=5)

    def clear(self):
        with data_lock:
            input_data.clear()
        print("Session data cleared.")

    def prepare_heatmap(self):
        if not input_data:
            print("No data recorded yet.")
            return
        # Hide the control window so it doesn't appear in the screenshot
        self.root.withdraw() 
        self.root.after(500, self.render_overlay)

    def render_overlay(self):
        with data_lock:
            df = pd.DataFrame(input_data)
        
        screen_bg = pyautogui.screenshot()
        plt.figure(figsize=(16, 9))
        plt.imshow(screen_bg)
        
        # Check if we have enough variety in data to draw a heatmap
        if len(df) > 1 and df['x'].nunique() > 1 and df['y'].nunique() > 1:
            try:
                sns.kdeplot(data=df, x="x", y="y", fill=True, thresh=0.05, 
                            levels=30, cmap="rocket", alpha=0.5)
            except Exception as e:
                print(f"Could not draw heatmap cloud: {e}")
        else:
            print("Not enough spread in data for a heatmap cloud, showing individual points only.")

        # Always draw the dots (this will never fail even with 1 click)
        sns.scatterplot(data=df, x="x", y="y", hue="type", s=60, 
                        palette="viridis", edgecolor="white", alpha=0.9)

        plt.axis('off')
        plt.title("Input Activity Map")
        self.root.deiconify()
        plt.show()

if __name__ == "__main__":
    root = tk.Tk()
    app = GeneralVisualizer(root)
    root.mainloop()
    


      