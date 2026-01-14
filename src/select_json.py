import os
import tkinter as tk
from tkinter import filedialog
import json
import tomlkit
from mapper_module.utils import JSONS_FOLDER, TOML_PATH, configure_config
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

    # Update settings.toml
    try:
        if not os.path.exists(TOML_PATH):
            create_default_toml()

        with open(TOML_PATH, "r", encoding="utf-8") as f:
            doc = tomlkit.load(f)

        if "system" not in doc: doc.add("system", tomlkit.table())
        if "joystick" not in doc: doc.add("joystick", tomlkit.table())

        # Apply new path and clear HUD image
        doc["system"]["json_path"] = os.path.normpath(file_path)
        
        # Reset dynamic joystick values
        doc["joystick"]["mouse_wheel_radius"] = 0.0
        doc["joystick"]["sprint_distance"] = 0.0
        
        metadata      
        
        configure_config(w, h, dpi, "")

    root.destroy()

if __name__ == "__main__":
    select_json_profile()