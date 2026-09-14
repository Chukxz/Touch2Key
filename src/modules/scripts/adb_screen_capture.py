import subprocess
import datetime
from pathlib import Path
from PIL import Image

from modules.utils import (
    IMAGES_FOLDER,
    ADB,
    get_adb_device,
    get_screen_size,
    get_dpi,
    get_rotation,
)
from modules.database.repositories import AppSettingsRepository, LayoutsRepository


def _capture_android_screen(custom_img_name=None):
    device_id = get_adb_device()
    res = get_screen_size(device_id)
    if res is None:
        raise RuntimeError("Invalid screen resolution.")

    dpi = get_dpi(device_id)
    timestamp = datetime.datetime.now().strftime("hud_%Y%m%d_%H%M%S")
    img_rotation = get_rotation(device_id)

    base_dir = Path(IMAGES_FOLDER)

    # Flattened path: resources/images/[prefix_]hud_YYYYMMDD_HHMMSS_rX.png
    prefix = custom_img_name.replace(" ", "_") + "_" if custom_img_name else ""
    relative_filename = f"{prefix}{timestamp}_r{img_rotation}.png"
    full_save_path = base_dir / relative_filename

    # Ensure the root images directory exists
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
        try:
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

    # Database Update
    try:
        settings_repo = AppSettingsRepository()
        layouts_repo = LayoutsRepository()

        settings = settings_repo.get()

        if settings.active_layout_id is not None:
            layouts_repo.update(
                settings.active_layout_id, image_path=str(relative_filename)
            )
            print(
                f"[INFO] Database updated: Image assigned to Layout ID {settings.active_layout_id}."
            )
        else:
            print(
                "[WARNING] Image captured, but no active layout is currently set to assign it to."
            )

        print(f"\n[SUCCESS]")
        print(f"File:   {full_save_path}")

    except Exception as e:
        print(f"[ERROR] Database update failed: {e}")


def run():
    # Prompts for folder structure removed to align with the flattened architecture.
    # The capture can now be fired cleanly via CLI or triggered seamlessly from a GUI.
    print("[PROCESS] Initializing screen capture...")
    _capture_android_screen()


if __name__ == "__main__":
    run()
