import subprocess
import datetime
from pathlib import Path
from PIL import Image

from mapper_module.utils import (
    IMAGES_FOLDER, TOML_PATH, get_adb_device,
    get_screen_size, get_dpi, get_rotation, update_toml
)

def capture_android_screen():
    device_id = get_adb_device()
    res = get_screen_size(device_id)
    if res is None:
        raise RuntimeError("Invalid screen resolution.")

    dpi = get_dpi(device_id)
    timestamp = datetime.datetime.now().strftime("hud_%Y%m%d_%H%M%S")

    nickname = input("Enter device nickname (optional): ").strip()
    custom_img_name = input("Enter optional image name: ").strip()

    nick_clean = nickname.replace(" ", "_") if nickname else "Device"
    img_clean = custom_img_name.replace(" ", "_") if custom_img_name else "Image"
    
    img_rotation = get_rotation(device_id)
    base_dir = Path(IMAGES_FOLDER)
    
    relative_filename = Path(nick_clean) / img_clean / f"{timestamp}_r{img_rotation}.png"
    full_save_path = base_dir / relative_filename
    full_save_path.parent.mkdir(parents=True, exist_ok=True)

    try:
        print(f"[PROCESS] Capturing {res[0]}x{res[1]} screen...")
        android_tmp = '/data/local/tmp/temp_cap.png'

        subprocess.run(['adb', '-s', device_id, 'shell', 'screencap', '-p', android_tmp], check=True)
        subprocess.run(['adb', '-s', device_id, 'pull', android_tmp, str(full_save_path)], check=True)
        subprocess.run(['adb', '-s', device_id, 'shell', 'rm', android_tmp], check=True)

    except subprocess.CalledProcessError as e:
        print(f"[ERROR] ADB failure: {e}")
        return
    
    try:
        with Image.open(full_save_path) as img:
            img.save(full_save_path, dpi=(dpi, dpi))
            print(f"[INFO] DPI ({dpi}) embedded.")
    except Exception as e:
        print(f"[WARNING] DPI metadata failed: {e}")

    try:
        update_toml(image_path=str(relative_filename), strict=True)

        print(f"\n[SUCCESS]")
        print(f"File:   {relative_filename}")
        print(f"Config: {TOML_PATH} updated.")

    except Exception as e:
        print(f"[ERROR] Toml update failed: {e}")

if __name__ == "__main__":
    capture_android_screen()