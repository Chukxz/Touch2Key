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

def capture_android_screen(nickname: str, custom_img_name: str) -> None:
    """
    Captures screen and saves as: {nickname}_{custom_img_name}_{timestamp}.png
    Saves hardware info and nickname to settings.toml.
    """
    device_id = get_adb_device()
    res = get_screen_size(device_id)
    if res is None:
        raise RuntimeError("Invalid screen resolution.")

    dpi = get_dpi(device_id)

    # --- NAMING LOGIC ---
    timestamp = int(time.time())
    nick_clean = nickname.replace(" ", "_")
    img_clean = custom_img_name.strip().replace(" ", "_")

    # Pattern: {nickname}_{image_name}_{timestamp}.png 
    # If img_clean is empty, result is: {nickname}_{timestamp}.png
    if img_clean:
        filename = f"{nick_clean}_{img_clean}_{timestamp}.png"
    else:
        filename = f"{nick_clean}_{timestamp}.png"

    # Setup Paths
    base_dir = os.path.normpath(os.path.join("..", "resources", IMAGES_FOLDER))
    os.makedirs(base_dir, exist_ok=True)
    full_save_path = os.path.join(base_dir, filename)

    try:
        print(f"[PROCESS] Capturing {res[0]}x{res[1]} screen via ADB...")
        android_tmp = '/data/local/tmp/temp_cap.png'
        
        # ADB Capture sequence (-p forces PNG)
        subprocess.run(['adb', '-s', device_id, 'shell', 'screencap', '-p', android_tmp], check=True)
        subprocess.run(['adb', '-s', device_id, 'pull', android_tmp, full_save_path], check=True)
        subprocess.run(['adb', '-s', device_id, 'shell', 'rm', android_tmp], check=True)
        
    except subprocess.CalledProcessError as e:
        print(f"[ERROR] ADB failure: {e}")
        return

    try:
        if not os.path.exists(TOML_PATH):
            create_default_toml()

        with open(TOML_PATH, "r", encoding="utf-8") as f:
            doc = tomlkit.load(f)

        if "system" not in doc: 
            doc.add("system", tomlkit.table())

        # Update TOML settings
        doc["system"]["json_dev_res"] = [res[0], res[1]]
        doc["system"]["json_dev_dpi"] = dpi
        doc["system"]["hud_image_path"] = full_save_path
        doc["system"]["json_dev_name"] = nickname  # As requested

        with open(TOML_PATH, "w", encoding="utf-8") as f:
            tomlkit.dump(doc, f)

        print(f"\n[SUCCESS]")
        print(f"File:   {filename}")
        print(f"Device: {nickname}")
        print(f"Config: {TOML_PATH} updated.")

    except Exception as e:
        print(f"[ERROR] Config update failed: {e}")

if __name__ == "__main__":
    # 1. Nickname (Default: Device)
    nick_in = input("Enter device nickname (default 'Device'): ").strip()
    nickname = nick_in if nick_in else "Device"

    # 2. Image Name (Default: empty, results in nickname_timestamp)
    img_in = input("Enter optional image name (e.g. cod_low): ").strip()
    
    capture_android_screen(nickname, img_in)