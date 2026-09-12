import subprocess
import datetime
from pathlib import Path
from PIL import Image

from modules.utils import (
    IMAGES_FOLDER,
    TOML_PATH,
    ADB,
    get_adb_device,
    get_screen_size,
    get_dpi,
    get_rotation,
    update_toml,
)


def _capture_android_screen(
    nickname=None, custom_img_folder_name=None, custom_img_name=None
):
    device_id = get_adb_device()
    res = get_screen_size(device_id)
    if res is None:
        raise RuntimeError("Invalid screen resolution.")

    dpi = get_dpi(device_id)
    timestamp = datetime.datetime.now().strftime("hud_%Y%m%d_%H%M%S")

    nick_clean = nickname.replace(" ", "_") if nickname else "Device"
    img_folder_clean = (
        custom_img_folder_name.replace(" ", "_") if custom_img_folder_name else "Image"
    )
    img_clean = custom_img_name.replace(" ", "_") + "_" if custom_img_name else ""

    img_rotation = get_rotation(device_id)
    base_dir = Path(IMAGES_FOLDER)

    relative_filename = (
        Path(nick_clean)
        / img_folder_clean
        / f"{img_clean}{timestamp}_r{img_rotation}.png"
    )
    full_save_path = base_dir / relative_filename
    full_save_path.parent.mkdir(parents=True, exist_ok=True)

    try:
        print(f"[PROCESS] Capturing {res[0]}x{res[1]} screen...")
        android_tmp = "/data/local/tmp/temp_cap.png"

        subprocess.run(
            [ADB, "-s", device_id, "shell", "screencap", "-p", android_tmp],
            check=True,
            timeout=30,
        )
        subprocess.run(
            [ADB, "-s", device_id, "pull", android_tmp, str(full_save_path)],
            check=True,
            timeout=20,
        )

    except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as e:
        print(f"[ERROR] ADB failure: {e}")
        return

    finally:
        # Wrap the cleanup in its own try/except so a disconnected device doesn't crash the script here
        try:
            # We don't strictly need check=True here since failure just means the file isn't deleted
            subprocess.run(
                [ADB, "-s", device_id, "shell", "rm", android_tmp],
                timeout=10,
                stderr=subprocess.DEVNULL,
            )
        except subprocess.TimeoutExpired:
            print("[WARNING] Cleanup timed out. Device likely disconnected.")
        except Exception as e:
            print(f"[WARNING] Cleanup failed: {e}")

    try:
        with Image.open(full_save_path) as img:
            img.save(full_save_path, dpi=(dpi, dpi))
            print(f"[INFO] DPI ({dpi}) embedded.")
    except Exception as e:
        print(f"[WARNING] DPI metadata failed: {e}")

    try:
        update_toml(image_path=str(relative_filename), strict=True)

        print(f"\n[SUCCESS]")
        print(f"File:   {full_save_path}")
        print(f"Config: {TOML_PATH} updated.")

    except Exception as e:
        print(f"[ERROR] Toml update failed: {e}")


def run():
    nickname = input(
        "Enter device nickname [Default 'Device', Blank for Default]: "
    ).strip()
    custom_img_folder_name = input(
        "Enter image folder name [Default 'Image', Blank for Default]: "
    ).strip()
    custom_img_name = input(
        "Enter image name prefix [Default '', Blank for Default]: "
    ).strip()

    _capture_android_screen(nickname, custom_img_folder_name, custom_img_name)


if __name__ == "__main__":
    run()
