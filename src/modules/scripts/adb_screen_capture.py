"""
Android screen capture script via ADB with resolution, rotation, and DPI metadata synchronization.
"""

from __future__ import annotations

import sys
import datetime
import logging
from pathlib import Path
import subprocess
from PIL import Image

from modules.database import store
from modules.log_manager import AppLogManager
from modules.utils import (
    ADB,
    IMAGES_FOLDER,
    get_adb_device,
    get_dpi,
    get_rotation,
    get_screen_size,
    rotate_resolution,
)

logger = logging.getLogger("modules.scripts.adb_screen_capture")


def capture_android_screen(custom_img_name: str | None = None, parent=None) -> Path:
    """
    Captures an Android screen screenshot via ADB, embeds DPI metadata into the PNG header,
    and binds the file path and resolution metrics to the active SQLite layout.
    """
    device_id = get_adb_device()
    if not device_id:
        err = "No ADB device detected."
        logger.error(err)
        raise RuntimeError(err)

    raw_res = get_screen_size(device_id)
    if raw_res is None:
        err = "Could not retrieve screen resolution from ADB."
        logger.error(err)
        raise RuntimeError(err)

    dpi = get_dpi(device_id)
    img_rotation = get_rotation(device_id)
    width, height = rotate_resolution(raw_res[0], raw_res[1], img_rotation)

    timestamp = datetime.datetime.now().strftime("hud_%Y%m%d_%H%M%S")
    prefix = f"{custom_img_name.replace(' ', '_')}_" if custom_img_name else ""
    filename = f"{prefix}{timestamp}_r{img_rotation}.png"

    IMAGES_FOLDER.mkdir(parents=True, exist_ok=True)
    full_save_path = (IMAGES_FOLDER / filename).resolve()
    android_tmp = "/data/local/tmp/temp_cap.png"

    logger.info(
        "Capturing %sx%s screen (Orientation: %s)...", width, height, img_rotation
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

    # Embed DPI metadata into PNG header
    try:
        with Image.open(full_save_path) as img:
            img.save(full_save_path, dpi=(dpi, dpi))
            logger.info("DPI metadata (%s) embedded into image.", dpi)
    except Exception as exc:
        logger.warning("DPI metadata write failed: %s", exc)

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
        logger.info(
            "Image and resolution linked to Layout ID %s ('%s').",
            active_layout.id,
            active_layout.name,
        )
    else:
        logger.warning("Image captured, but no active layout is set in database.")

    logger.info("SUCCESS: Saved screen capture to %s", full_save_path)
    return full_save_path


def run() -> None:
    # Initialize CLI logging so print/log statements show in terminal and log files
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
