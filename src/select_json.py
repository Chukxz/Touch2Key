import os
import tkinter as tk
from tkinter import filedialog
import json
import tomlkit
from mapper_module.utils import JSONS_FOLDER, TOML_PATH, update_toml
from mapper_module.default_toml_helper import create_default_toml

def select_json_profile():
    # Initialize Tkinter and hide the root window
    root = tk.Tk()
    root.withdraw()
    root.attributes('-topmost', True) 

    os.makedirs(JSONS_FOLDER, exist_ok=True)
    
    # Open File Dialog
    file_path = filedialog.askopenfilename(
        initialdir=JSONS_FOLDER,
        title="Select JSON Mapping Profile",
        filetypes=(("JSON files", "*.json"), ("All files", "*.*"))
    )

    if not file_path:
        print("[!] Selection cancelled.")
        root.destroy()
        return

    root.destroy()
        
    if not os.path.exists(file_path):
        print(_str = f"Error: File '{file_path}' not found.")
        return

    with open(file_path, mode='r', encoding='utf-8') as f:
        try:
            json.load(f)
        except json.JSONDecodeError as e:
            print(f"Invalid JSON syntax in '{file_path}': {e}")
            return

    update_toml(image_path="", json_path=file_path)

if __name__ == "__main__":
    select_json_profile()