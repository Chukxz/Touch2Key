import subprocess
import os
import tomlkit
import time

from mapper_module.utils import (
    IMAGES_FOLDER,
    get_adb_device, 
    get_screen_size, 
    get_dpi, 
    TOML_PATH
)
from mapper_module.default_toml_helper import create_default_toml

def capture_android_screen(save_path: str, device_nickname: str) -> None:
    """
    Captures screen and saves hardware info + a personal nickname to config.
    """
    device_id = get_adb_device()
    res = get_screen_size(device_id)
    if res is None:
        raise RuntimeError("Invalid screen resolution.")
    
    dpi = get_dpi(device_id)
    
    # Setup Paths
    base_dir = os.path.join("..", "resources", IMAGES_FOLDER)
    os.makedirs(base_dir, exist_ok=True)
    full_save_path = os.path.join(base_dir, save_path)
    
    try:
        # ADB Capture sequence
        subprocess.run(['adb', '-s', device_id, 'shell', 'screencap', '-p', '/data/local/tmp/screenshot.png'], check=True)
        subprocess.run(['adb', '-s', device_id, 'pull', '/data/local/tmp/screenshot.png', full_save_path], check=True)
        subprocess.run(['adb', '-s', device_id, 'shell', 'rm', '/data/local/tmp/screenshot.png'], check=True)
        print(f"[INFO] Screenshot saved to {full_save_path}")
        
    except subprocess.CalledProcessError as e:
        print(f"An error occurred while capturing the screen: {e}")
        return

    try:
        if not os.path.exists(TOML_PATH):
            create_default_toml()

        with open(TOML_PATH, "r", encoding="utf-8") as f:
            doc = tomlkit.load(f)

        if "system" not in doc: 
            doc.add("system", tomlkit.table())

        # Update TOML with hardware info and the personal nickname
        doc["system"]["json_dev_res"] = [res[0], res[1]]
        doc["system"]["json_dev_dpi"] = dpi
        doc["system"]["hud_image_path"] = full_save_path
        doc["system"]["device_nickname"] = device_nickname # <--- Your personal label

        with open(TOML_PATH, "w", encoding="utf-8") as f:
            tomlkit.dump(doc, f)
            
        print(f"[SUCCESS] Config updated for: {device_nickname} ({res[0]}x{res[1]})")

    except Exception as e:
        create_default_toml()
        raise RuntimeError(f"Config corrupted. Resetting to defaults. Error: {e}")

if __name__ == "__main__":
    # 1. Ask for Nickname
    nickname = input("Enter a nickname for this device (e.g., MyPhone, Tablet-V2): ").strip()
    if not nickname:
        nickname = "Default_Device"

    # 2. Ask for Filename
    image_name = input(f"Enter filename for {nickname} (default: auto-timestamp): ").strip()
    if not image_name:
        image_name = f"{nickname}_{int(time.time())}.png"
    if not image_name.endswith(('.png', '.jpg', '.jpeg')):
        image_name += ".png"
        
    capture_android_screen(image_name, nickname)