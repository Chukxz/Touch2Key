from __future__ import annotations

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
from modules.database import store


def _capture_android_screen(custom_img_name: str | None = None) -> Path:
    device_id = get_adb_device()
    if not device_id:
        raise RuntimeError("No ADB device detected.")

    res = get_screen_size(device_id)
    if res is None:
        raise RuntimeError("Invalid screen resolution.")

    dpi = get_dpi(device_id)
    timestamp = datetime.datetime.now().strftime("hud_%Y%m%d_%H%M%S")
    img_rotation = get_rotation(device_id)

    base_dir = Path(IMAGES_FOLDER)
    prefix = custom_img_name.replace(" ", "_") + "_" if custom_img_name else ""
    relative_filename = f"{prefix}{timestamp}_r{img_rotation}.png"
    full_save_path = base_dir / relative_filename

    full_save_path.parent.mkdir(parents=True, exist_ok=True)
    android_tmp = "/data/local/tmp/temp_cap.png"

    try:
        print(f"[PROCESS] Capturing {res[0]}x{res[1]} screen...")
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
        raise RuntimeError(f"ADB screen capture failed: {e}") from e
    finally:
        try:
            subprocess.run(
                [ADB, "-s", device_id, "shell", "rm", android_tmp],
                timeout=10,
                stderr=subprocess.DEVNULL,
            )
        except Exception:
            pass

    # Process DPI metadata
    try:
        with Image.open(full_save_path) as img:
            img.save(full_save_path, dpi=(dpi, dpi))
            print(f"[INFO] DPI ({dpi}) embedded.")
    except Exception as e:
        print(f"[WARNING] DPI metadata write failed: {e}")

    # Database Update via store facade
    active_layout = store.get_active_layout()
    if active_layout is not None:
        store.layouts.update(
            active_layout.id,
            image_path=str(relative_filename),
        )
        print(f"[INFO] Image linked to Layout ID {active_layout.id} ('{active_layout.name}').")
    else:
        print("[WARNING] Image captured, but no active layout is set in database.")

    print(f"\n[SUCCESS]\nFile: {full_save_path}")
    return full_save_path


def run() -> None:
    print("[PROCESS] Initializing screen capture...")
    try:
        _capture_android_screen()
    except Exception as e:
        print(f"[ERROR] {e}")


if __name__ == "__main__":
    run()