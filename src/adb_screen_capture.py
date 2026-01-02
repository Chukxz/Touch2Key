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
    Handles 4 scenarios: 
    1. Only image name -> Device_imgname_ts
    2. Only nickname -> Nickname_ts
    3. Both -> Nickname_imgname_ts
    4. Neither -> Device_ts
    """
    device_id = get_adb_device()
    res = get_screen_size(device_id)
    if res is None:
        raise RuntimeError("Invalid screen resolution.")

    dpi = get_dpi(device_id)

    # --- ROBUST NAMING LOGIC ---
    timestamp = int(time.time())
    
    # Clean and fallback for nickname
    nick_clean = nickname.strip().replace(" ", "_") if nickname.strip() else "Device"
    # Clean image name
    img_clean = custom_img_name.strip().replace(" ", "_")

    # Construct filename based on presence of custom image name
    if img_clean:
        filename = f"{nick_clean}_{img_clean}_{timestamp}.png"
    else:
        filename = f"{nick_clean}_{timestamp}.png"

    # Setup Paths (Ensures cross-platform compatibility)
    base_dir = os.path.normpath(os.path.join("..", "resources", IMAGES_FOLDER))
    os.makedirs(base_dir, exist_ok=True)
    full_save_path = os.path.join(base_dir, filename)

    try:
        print(f"[PROCESS] Capturing {res[0]}x{res[1]} screen from {device_id}...")
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
        doc["system"]["json_dev_name"] = nick_clean  # Uses the cleaned nickname

        with open(TOML_PATH, "w", encoding="utf-8") as f:
            tomlkit.dump(doc, f)

        print(f"\n[SUCCESS]")
        print(f"File:   {filename}")
        print(f"Device: {nick_clean}")
        print(f"Config: {TOML_PATH} updated.")

    except Exception as e:
        print(f"[ERROR] Config update failed: {e}")

if __name__ == "__main__":
    # Get inputs from user
    nick_in = input("Enter device nickname (optional, default 'Device'): ").strip()
    img_in = input("Enter optional image name (e.g. cod_low): ").strip()

    # The function now handles the empty/whitespace logic internally
    capture_android_screen(nick_in, img_in)
