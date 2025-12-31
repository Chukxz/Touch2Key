import subprocess
import os
import tomlkit
from utils import IMAGES_FOLDER_NAME, get_adb_device, get_screen_size, get_dpi, TOML_PATH
from default_toml_helper import create_default_toml

def capture_android_screen(save_path: str) -> None:
    """
    Captures the screen of the connected Android device via ADB and saves it to the specified path.

    :param save_path: Path where the captured screenshot will be saved.
    """
    
    device = get_adb_device()
    res = get_screen_size(device)
    if res is None:
        raise RuntimeError("Invalid screen resolution.")
    dpi = get_dpi(device)
    
    base_dir = os.path.join("..", "resources", IMAGES_FOLDER_NAME)
    os.makedirs(base_dir, exist_ok=True)
    save_path = os.path.join(base_dir, save_path)
    
    try:
        subprocess.run(['adb', '-s', device, 'shell', 'screencap', '-p', '/data/local/tmp/screenshot.png'], check=True)
        subprocess.run(['adb', '-s', device, 'pull', '/data/local/tmp/screenshot.png', save_path], check=True)
        subprocess.run(['adb', '-s', device, 'shell', 'rm', '/data/local/tmp/screenshot.png'], check=True)
        print(f"[INFO] Screenshot saved to {save_path} with resolution {res[0]}x{res[1]} and DPI {dpi}.")
        
    except subprocess.CalledProcessError as e:
        print(f"An error occurred while capturing the screen: {e}")
        return

    try:
        with open(TOML_PATH, "r", encoding="utf-8") as f:
            doc = tomlkit.load(f)

        if "system" not in doc: doc.add("system", tomlkit.table())
        if "key" not in doc: doc.add("key", tomlkit.table())

        doc["system"]["json_dev_res"] = [res[0], res[1]]
        doc["system"]["json_dev_dpi"] = dpi
        doc["system"]["hud_image_path"] = save_path

        with open(TOML_PATH, "w", encoding="utf-8") as f:
            tomlkit.dump(doc, f)

    except (KeyError, Exception) as e:
        # Fallback if the file was totally corrupt or structure was wrong
        create_default_toml()
        raise RuntimeError(f"Config corrupted. Resetting to defaults. Error: {e}")