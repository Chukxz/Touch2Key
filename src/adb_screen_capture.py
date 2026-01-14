import subprocess
import os
import tomlkit
import time
from PIL import Image

from mapper_module.utils import (
    IMAGES_FOLDER,
    get_adb_device, 
    get_screen_size, 
    get_dpi, 
    TOML_PATH
)
from mapper_module.default_toml_helper import create_default_toml

    def get_rotation(device):
        rotation = 0
        patterns = [r"mCurrentRotation=(\d+)", r"rotation=(\d+)", r"mCurrentOrientation=(\d+)", r"mUserRotation=(\d+)"]
        while self.running:
            try:
                result = subprocess.run(["adb", "-s", device, "shell", "dumpsys", "display"], capture_output=True, text=True, timeout=1)
                for pat in patterns:
                    m = re.search(pat, result.stdout)
                    if m:
                        rotation = int(m.group(1)) % 4
                        break
            except: pass

        return rotation
    

    def rotate_coordinates(self, device, x, y):
        if x is None or y is None:
            return x, y

        # Initialize result with current values as a fallback
        res_x, res_y = x, y 

        rotation = get_rotation(device)
        if rotation == 1:
            res_x, res_y = logic_y, self.json_width - logic_x
                    elif self.rotation == 2:
                        self.side_limit = self.json_width // 2
                        res_x, res_y = self.json_width - logic_x, self.json_height - logic_y
                    elif self.rotation == 3:
                        self.side_limit = self.json_height // 2
                        res_x, res_y = self.json_height - logic_y, logic_x
                    else:
                        self.side_limit = self.json_width // 2
                        res_x, res_y = logic_x, logic_y
            finally:
                self.config.config_lock.release()

        # Always returns a tuple, even if the lock was busy
        return res_x, res_y 

def capture_android_screen():
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

    # Get inputs from user
    nickname = input("Enter device nickname (optional, default 'Device'): ").strip()
    custom_img_name = input("Enter optional image name (e.g. cod_low): ").strip()
    
    # Clean and fallback for nickname
    nick_clean = nickname.strip().replace(" ", "_") if nickname.strip() else "Device"
    # Clean image name
    img_clean = custom_img_name.strip().replace(" ", "_")

    # Construct filename based on presence of custom image name
    if img_clean:
        filename = f"{nick_clean}_{img_clean}_{timestamp}.png"
    else:
        filename = f"{nick_clean}_{timestamp}.png"

    os.makedirs(IMAGES_FOLDER, exist_ok=True)
    full_save_path = os.path.join(IMAGES_FOLDER, filename)

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
        doc["system"]["hud_image_path"] = os.path.normpath(full_save_path)

        with open(TOML_PATH, "w", encoding="utf-8") as f:
            tomlkit.dump(doc, f)

        print(f"\n[SUCCESS]")
        print(f"File:   {filename}")
        print(f"Device: {nick_clean}")
        print(f"Config: {TOML_PATH} updated.")

    except Exception as e:
        print(f"[ERROR] Config update failed: {e}")

    try:
        with Image.open(full_save_path) as img:
        # PNG stores DPI as a tuple (horizontal, vertical)
        # We re-save the image with the 'dpi' parameter
            img.save(full_save_path, dpi=(dpi, dpi))
        print(f"[INFO] DPI ({dpi}) embedded into PNG metadata.")

    except Exception as e:
        print(f"[WARNING] Could not embed DPI into image: {e}")

if __name__ == "__main__":
    capture_android_screen()
