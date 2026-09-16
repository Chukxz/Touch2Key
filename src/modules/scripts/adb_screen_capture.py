from __future__ import annotations

import datetime
from pathlib import Path
import subprocess
from PIL import Image

from modules.database import store
from modules.utils import (
    ADB,
    IMAGES_FOLDER,
    get_adb_device,
    get_dpi,
    get_rotation,
    get_screen_size,
    rotate_resolution,
)


def capture_android_screen(custom_img_name: str | None = None) -> Path:
    device_id = get_adb_device()
    if not device_id:
        raise RuntimeError("No ADB device detected.")

    raw_res = get_screen_size(device_id)
    if raw_res is None:
        raise RuntimeError("Could not retrieve screen resolution.")

    dpi = get_dpi(device_id)
    img_rotation = get_rotation(device_id)
    width, height = rotate_resolution(raw_res[0], raw_res[1], img_rotation)

    timestamp = datetime.datetime.now().strftime("hud_%Y%m%d_%H%M%S")
    prefix = f"{custom_img_name.replace(' ', '_')}_" if custom_img_name else ""
    filename = f"{prefix}{timestamp}_r{img_rotation}.png"

    IMAGES_FOLDER.mkdir(parents=True, exist_ok=True)
    full_save_path = (IMAGES_FOLDER / filename).resolve()
    android_tmp = "/data/local/tmp/temp_cap.png"

    try:
        print(f"[PROCESS] Capturing {width}x{height} screen (Orientation: {img_rotation})...")
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
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
        raise RuntimeError(f"ADB screen capture failed: {exc}") from exc
    finally:
        try:
            subprocess.run(
                [ADB, "-s", device_id, "shell", "rm", android_tmp],
                timeout=10,
                stderr=subprocess.DEVNULL,
            )
        except Exception:
            pass

    # Embed DPI metadata into PNG header
    try:
        with Image.open(full_save_path) as img:
            img.save(full_save_path, dpi=(dpi, dpi))
            print(f"[INFO] DPI ({dpi}) embedded.")
    except Exception as exc:
        print(f"[WARNING] DPI metadata write failed: {exc}")

    # Synchronize with active database layout
    active_layout = store.get_active_layout()
    if active_layout is not None:
        store.layouts.update(
            active_layout.id,
            image_path=str(full_save_path),
            width=width,
            height=height,
            dpi=dpi,
        )
        print(f"[INFO] Image and resolution linked to Layout ID {active_layout.id} ('{active_layout.name}').")
    else:
        print("[WARNING] Image captured, but no active layout is set in database.")

    print(f"\n[SUCCESS]\nFile: {full_save_path}")
    return full_save_path


def run() -> None:
    print("[PROCESS] Initializing screen capture...")
    try:
        capture_android_screen()
    except Exception as exc:
        print(f"[ERROR] {exc}")


if __name__ == "__main__":
    run()
