import os
import tkinter as tk
from tkinter import filedialog, simpledialog
import tomlkit
from mapper_module.utils import JSONS_FOLDER, TOML_PATH
from mapper_module.default_toml_helper import create_default_toml

def select_json_profile():
    # Initialize Tkinter and hide the root window
    root = tk.Tk()
    root.withdraw()
    root.attributes('-topmost', True) 

    os.makedirs(JSONS_FOLDER, exist_ok=True)
    
    # 1. Open File Dialog
    file_path = filedialog.askopenfilename(
        initialdir=JSONS_FOLDER,
        title="Select JSON Mapping Profile",
        filetypes=(("JSON files", "*.json"), ("All files", "*.*"))
    )

    if not file_path:
        print("[!] Selection cancelled.")
        root.destroy()
        return

    # 2. Ask for Resolution and DPI (Optional but recommended)
    # These values must match the device that CREATED the JSON
    res_raw = simpledialog.askstring("Input", "Enter JSON native resolution (Width, Height):", initialvalue=None)
    dpi_raw = simpledialog.askinteger("Input", "Enter JSON native DPI:", initialvalue=None)

    # 3. Update settings.toml
    try:
        if not os.path.exists(TOML_PATH):
            create_default_toml()

        with open(TOML_PATH, "r", encoding="utf-8") as f:
            doc = tomlkit.load(f)

        if "system" not in doc: doc.add("system", tomlkit.table())
        if "joystick" not in doc: doc.add("joystick", tomlkit.table())

        # Apply new path and clear HUD image
        doc["system"]["json_path"] = os.path.normpath(file_path)
        doc["system"]["hud_image_path"] = "" 
        
        # Reset dynamic joystick values
        doc["joystick"]["mouse_wheel_radius"] = 0.0
        doc["joystick"]["sprint_distance"] = 0.0        
        
        # Apply new Resolution/DPI if provided
        if res_raw:
            try:
                w, h = map(int, res_raw.replace(" ", "").split(","))
                doc["system"]["json_dev_res"] = [w, h]
            except ValueError:
                print("[!] Invalid resolution format. Skipping update for resolution.")
        
        if dpi_raw:
            doc["system"]["json_dev_dpi"] = dpi_raw

        with open(TOML_PATH, "w", encoding="utf-8") as f:
            tomlkit.dump(doc, f)

        print(f"\n[SUCCESS] Profile changed!")
        print(f"New JSON: {os.path.basename(file_path)}")
        if res_raw: print(f"Native Res: {w}x{h}")
        if dpi_raw: print(f"Native DPI: {dpi_raw}")
        
    except Exception as e:
        print(f"[ERROR] Failed to update config: {e}")

    root.destroy()

if __name__ == "__main__":
    select_json_profile()