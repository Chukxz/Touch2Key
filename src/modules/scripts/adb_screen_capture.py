"""
Android screen capture script via ADB with resolution, rotation, and DPI metadata synchronization.
"""

from __future__ import annotations

import datetime
import logging
from pathlib import Path
import subprocess
import sys
from PIL import Image

from modules.database import store
from modules.log_manager import AppLogManager
from modules.utils import (
    ADB,
    BASELINE_DPI,
    IMAGES_FOLDER,
    get_adb_device,
    get_dpi,
    get_rotation,
    get_screen_size,
    rotate_resolution,
)

logger = logging.getLogger("modules.scripts.adb_screen_capture")


def _get_device_dpi(device_id: str) -> int:
    """Queries display density via get_dpi with an adb shell wm density fallback."""
    try:
        raw_dpi = get_dpi(device_id)
        if raw_dpi and int(raw_dpi) > 0:
            return int(raw_dpi)
    except Exception:
        pass

    try:
        res = subprocess.run(
            [ADB, "-s", device_id, "shell", "wm", "density"],
            capture_output=True,
            text=True,
            timeout=5,
            check=True,
        )
        for line in res.stdout.strip().splitlines():
            if "density:" in line:
                return int(line.split(":")[-1].strip())
    except Exception as exc:
        logger.debug("ADB wm density fallback failed: %s", exc)

    return BASELINE_DPI


def capture_android_screen(custom_img_name: str | None = None, parent=None) -> Path:
    """
    Captures an Android screen screenshot via ADB, embeds DPI metadata into the PNG header,
    tags density in the filename, and binds resolution and DPI metrics to the active SQLite layout.
    """
    device_id = get_adb_device()
    if not device_id:
        err = "No ADB device detected."
        logger.error(err)
        raise RuntimeError(err)

    dpi = _get_device_dpi(device_id)
    img_rotation = get_rotation(device_id)

    raw_res = get_screen_size(device_id)
    if raw_res:
        width, height = rotate_resolution(raw_res[0], raw_res[1], img_rotation)
    else:
        width, height = 1920, 1080

    timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    prefix = f"{custom_img_name.replace(' ', '_')}_" if custom_img_name else ""
    filename = f"{prefix}hud_{timestamp}_r{img_rotation}_{dpi}dpi.png"

    IMAGES_FOLDER.mkdir(parents=True, exist_ok=True)
    full_save_path = (IMAGES_FOLDER / filename).resolve()
    android_tmp = "/data/local/tmp/temp_cap.png"

    logger.info(
        "Capturing screen via ADB (Density: %d DPI, Orientation: %d)...",
        dpi,
        img_rotation,
    )

    try:
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
        err_msg = f"ADB screen capture failed: {exc}"
        logger.exception(err_msg)
        raise RuntimeError(err_msg) from exc
    finally:
        try:
            subprocess.run(
                [ADB, "-s", device_id, "shell", "rm", android_tmp],
                timeout=10,
                stderr=subprocess.DEVNULL,
            )
        except Exception:
            pass

    # Read and embed DPI safely avoiding Windows file lock conflicts
    actual_width, actual_height = width, height
    try:
        with Image.open(full_save_path) as img:
            img_copy = img.copy()
            actual_width, actual_height = img_copy.size

        # Save detached copy outside the with block so the original handle is closed
        img_copy.save(full_save_path, dpi=(dpi, dpi))
        logger.info(
            "Embedded DPI (%s) into PNG header. Dimensions: %dx%d.",
            dpi,
            actual_width,
            actual_height,
        )
    except Exception as exc:
        logger.warning("Failed to embed DPI into PNG metadata: %s", exc)

    # Synchronize with the active SQLite layout record
    active_layout = store.get_active_layout()
    if active_layout is not None:
        store.layouts.update(
            active_layout.id,
            image_path=filename,
            width=actual_width,
            height=actual_height,
            dpi=dpi,
        )
        logger.info(
            "Synchronized Layout ID %d ('%s') -> %dx%d @ %d DPI (Image: %s)",
            active_layout.id,
            active_layout.name,
            actual_width,
            actual_height,
            dpi,
            filename,
        )
    else:
        logger.warning(
            "Screenshot captured, but no active layout is selected in the database."
        )

    return full_save_path


def run() -> None:
    AppLogManager.setup_logging(is_gui=False, log_prefix="touch2key_capture")
    logger.info("Initializing screen capture...")
    try:
        capture_android_screen()
    except Exception as exc:
        logger.error("Capture process error: %s", exc)
        sys.exit(1)


def main() -> None:
    """Dedicated entry point for pyproject.toml script execution."""
    run()


if __name__ == "__main__":
    main()
