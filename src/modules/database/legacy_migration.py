# src/modules/database/legacy_migration.py

"""
One-time importer from legacy/current TOML config and JSON layout files
into the SQLite database.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Optional

import tomlkit

from modules.utils import JSONS_FOLDER, TOML_PATH
from . import store

logger = logging.getLogger("modules.database.legacy_migration")


def _read_keys(doc: dict) -> tuple[Optional[str], Optional[str]]:
    keys = doc.get("keys", {})
    toggle_key = keys.get("toggle_key")
    sprint_key = keys.get("sprint_key")
    return toggle_key, sprint_key


def migrate_toml_config(toml_path: Path | str = TOML_PATH) -> bool:
    """Imports settings from a TOML document into the app_settings table."""
    path = Path(toml_path)
    if not path.exists():
        logger.info("No TOML config found at %s; skipping.", path)
        return False

    try:
        with path.open("r", encoding="utf-8") as f:
            doc = tomlkit.load(f)
    except Exception as e:
        logger.error("Failed to parse TOML at %s: %s", path, e)
        return False

    system = doc.get("system", {})
    joystick = doc.get("joystick", {})
    mouse = doc.get("mouse", {})
    performance = doc.get("performance", {})
    toggle_key, sprint_key = _read_keys(doc)

    width, height = system.get(
        "json_dev_res",
        [
            system.get("json_dev_width", 360),
            system.get("json_dev_height", 800),
        ],
    )

    fields: dict[str, Any] = {
        "left_handed": int(bool(system.get("left_handed", False))),
        "json_dev_width": int(width),
        "json_dev_height": int(height),
        "json_dev_dpi": int(system.get("json_dev_dpi", 160)),
        "deadzone": float(joystick.get("deadzone", 0.1)),
        "hysteresis": float(joystick.get("hysteresis", 5.0)),
        "anchored_floating_joystick": int(
            bool(joystick.get("anchored_floating_joystick", False))
        ),
        "joystick_snap_radius": float(joystick.get("joystick_snap_radius", 80.0)),
        "sensitivity": float(mouse.get("sensitivity", 1.0)),
        "toggle_key": str(toggle_key) if toggle_key else "",
        "sprint_key": str(sprint_key) if sprint_key else "",
        "adb_rate_cap": float(performance.get("adb_rate_cap", 250.0)),
        "pps_alert_threshold": float(performance.get("pps_alert_threshold", 60.0)),
    }

    store.settings.update(**fields)
    logger.info("Migrated TOML config from %s into app_settings.", path)
    return True


def migrate_json_layout(
    json_path: Path | str,
    image_path: str = "",
    layout_name: str | None = None,
    set_active: bool = True,
) -> Optional[int]:
    """Imports a JSON layout file into a new layouts row plus its layout_zones."""
    path = Path(json_path)
    if not path.is_absolute() and not path.exists():
        path = JSONS_FOLDER / path

    if not path.exists():
        logger.warning("JSON layout not found at %s; skipping.", path)
        return None

    try:
        with path.open("r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError) as e:
        logger.error("Failed to read/parse JSON layout %s: %s", path, e)
        return None

    try:
        metadata = data["metadata"]
        content = data["content"]
    except KeyError as e:
        logger.error("JSON layout %s missing expected metadata/content key: %s", path, e)
        return None

    target_name = layout_name or path.stem

    existing = store.layouts.get_by_name(target_name)
    if existing is not None:
        logger.info(
            "Layout '%s' already exists (id=%s); linking existing layout.",
            target_name,
            existing.id,
        )
        layout_id = existing.id
    else:
        layout = store.layouts.create(
            name=target_name,
            width=int(metadata["width"]),
            height=int(metadata["height"]),
            dpi=int(metadata["dpi"]),
            mouse_wheel_radius=float(metadata.get("mouse_wheel_radius", 50.0)),
            sprint_distance=float(metadata.get("sprint_distance", 10.0)),
            image_path=image_path,
        )
        layout_id = layout.id
        imported = 0

        for item in content:
            scancode = item.get("scancode")
            if scancode is None:
                continue

            zone_type = str(item.get("type", "")).upper()
            if zone_type not in ("CIRCLE", "RECTANGLE"):
                logger.warning(
                    "Skipping zone with unrecognized type %r for scancode %s.",
                    zone_type,
                    scancode,
                )
                continue

            try:
                priority = int(item.get("priority", 0))
                move_camera = bool(item.get("move_camera", False))

                if zone_type == "CIRCLE":
                    store.zones.create(
                        layout_id=layout_id,
                        scancode=str(scancode),
                        name=item.get("name", ""),
                        zone_type="CIRCLE",
                        cx=float(item["cx"]),
                        cy=float(item["cy"]),
                        r=float(item["val1"]),
                        move_camera=move_camera,
                        priority=priority,
                    )
                else:
                    store.zones.create(
                        layout_id=layout_id,
                        scancode=str(scancode),
                        name=item.get("name", ""),
                        zone_type="RECTANGLE",
                        x1=float(item["val1"]),
                        y1=float(item["val2"]),
                        x2=float(item["val3"]),
                        y2=float(item["val4"]),
                        move_camera=move_camera,
                        priority=priority,
                    )
                imported += 1
            except (KeyError, ValueError) as e:
                logger.warning("Skipping invalid zone (scancode=%s): %s", scancode, e)
                continue

        logger.info(
            "Migrated JSON layout %s into layouts.id=%s (%d/%d zones imported).",
            path,
            layout_id,
            imported,
            len(content),
        )

    if set_active:
        store.settings.update(active_layout_id=layout_id)

    return layout_id


def migrate_all(toml_path: Path | str = TOML_PATH) -> None:
    """Migrates settings and resolves active layout from the TOML."""
    path = Path(toml_path)
    json_path: Optional[str] = None
    image_path: str = ""

    if path.exists():
        try:
            with path.open("r", encoding="utf-8") as f:
                doc = tomlkit.load(f)

            system_table = doc.get("system", {})
            json_path = system_table.get("json_path")
            image_path = system_table.get("image_path", "")
        except Exception as e:
            logger.error("Could not read layout references from TOML: %s", e)

    # 1. Migrate settings row
    migrate_toml_config(path)

    # 2. Migrate layout file and set active
    if json_path:
        migrate_json_layout(json_path=json_path, image_path=image_path, set_active=True)
    else:
        logger.info("No json_path configured in TOML; completed settings migration only.")
