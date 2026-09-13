"""
One-time importer from the legacy TOML config + JSON layout files into
the sqlite database. Intended to run once per install (e.g. behind an
explicit "Import legacy config" GUI/CLI action, or a one-time flag file
checked at startup) -- NOT called unconditionally on every launch,
since re-running migrate_toml_config() would silently overwrite any
settings changes already made through the new GUI.

ASSUMPTIONS ABOUT THE LEGACY TOML SHAPE -- please confirm these against
the real create_default_toml()/hard_reset_toml.py before relying on
this in production. They're inferred from config.py's AppConfig.get()
calls and json_loader.py's usage, not from the TOML schema itself:

    [system]
    left_handed = false
    "hud_image_path" = ""
    json_path = "path/to/layout.json"
    json_dev_res = [360, 800]
    json_dev_dpi = 160

    [joystick]
    mouse_wheel_radius = 50.0
    sprint_distance = 10.0
    deadzone = 0.1
    hysteresis = 5.0

    [mouse]
    sensitivity = 1.0
    
    [keys]
    toggle_key = ""
    sprint_key = ""
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Optional

import tomlkit

from modules.utils import TOML_PATH
from . import store

logger = logging.getLogger("modules.database.legacy_migration")


def _read_keys(doc: dict) -> tuple[Optional[str], Optional[str]]:
    keys = doc.get("keys", {})
    toggle_key = keys.get("toggle_key")
    sprint_key = keys.get("sprint_key")
    return toggle_key, sprint_key


def migrate_toml_config(toml_path: Path | str = TOML_PATH) -> None:
    """Imports [system]/[joystick]/[mouse] (+ best-guess key bindings)
    into the single app_settings row. Safe to call on a missing file --
    logs and returns rather than raising, since "no legacy file" just
    means there's nothing to migrate, not an error."""
    path = Path(toml_path)
    if not path.exists():
        logger.info("No legacy TOML config found at %s; skipping.", path)
        return

    try:
        with path.open("r", encoding="utf-8") as f:
            doc = tomlkit.load(f)
    except Exception as e:
        logger.error("Failed to parse legacy TOML at %s: %s", path, e)
        return

    system = doc.get("system", {})
    joystick = doc.get("joystick", {})
    mouse = doc.get("mouse", {})
    toggle_key, sprint_key = _read_keys(doc)

    width, height = system.get("json_dev_res", [360, 800])

    fields: dict[str, Any] = {
        "left_handed": bool(system.get("left_handed", False)),
        "json_dev_width": int(width),
        "json_dev_height": int(height),
        "json_dev_dpi": int(system.get("json_dev_dpi", 160)),
        "deadzone": float(joystick.get("deadzone", 0.1)),
        "hysteresis": float(joystick.get("hysteresis", 5.0)),
        "sensitivity": float(mouse.get("sensitivity", 1.0)),
        "toggle_key": toggle_key,
        "sprint_key": sprint_key,
    }

    store.settings.update(**fields)
    logger.info("Migrated legacy TOML config from %s into app_settings.", path)


def migrate_json_layout(
    json_path: Path | str, layout_name: str = "Legacy", set_active: bool = True
) -> Optional[int]:
    """Imports a single legacy JSON layout file's metadata + content
    into a new `layouts` row plus its `layout_zones`. Mirrors
    JSONLoader._process_json's parsing logic, but skips its
    normalize-by-width/height step: values are stored raw here, same
    as the original file, since normalization is the runtime loader's
    job and should stay that way regardless of where the data lives.

    Returns the new (or already-existing) layout's id, or None if the
    file was missing or invalid."""
    path = Path(json_path)
    if not path.exists():
        logger.warning("Legacy JSON layout not found at %s; skipping.", path)
        return None

    try:
        with path.open("r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError) as e:
        logger.error("Failed to read/parse legacy JSON layout %s: %s", path, e)
        return None

    try:
        metadata = data["metadata"]
        content = data["content"]
    except KeyError as e:
        logger.error("Legacy JSON layout %s missing expected key: %s", path, e)
        return None

    existing = store.layouts.get_by_name(layout_name)
    if existing is not None:
        logger.info(
            "Layout '%s' already exists (id=%s); skipping JSON import to avoid duplicates.",
            layout_name,
            existing.id,
        )
        layout_id = existing.id
    else:
        layout = store.layouts.create(
            name=layout_name,
            width=int(metadata["width"]),
            height=int(metadata["height"]),
            dpi=int(metadata["dpi"]),
            mouse_wheel_radius=float(metadata.get("mouse_wheel_radius", 50.0)),
            sprint_distance=float(metadata.get("sprint_distance", 10.0)),
        )
        layout_id = layout.id
        imported = 0

        for item in content:
            scancode = item.get("scancode")
            if scancode is None:
                continue

            # json_loader.py compares item["type"] against CIRCLE/RECT
            # constants imported from utils; this migration only needs
            # the underlying string values, since it doesn't run inside
            # the hot touch loop where the int/enum form matters for speed.
            zone_type_raw = item.get("type")
            if zone_type_raw == "CIRCLE":
                zone_type = "CIRCLE"
            elif zone_type_raw == "RECT":
                zone_type = "RECT"
            else:
                logger.warning(
                    "Skipping zone with unrecognized type %r for scancode %s.",
                    zone_type_raw,
                    scancode,
                )
                continue

            try:
                if zone_type == "CIRCLE":
                    store.zones.create(
                        layout_id=layout_id,
                        scancode=str(scancode),
                        name=item.get("name", ""),
                        zone_type="CIRCLE",
                        cx=float(item["cx"]),
                        cy=float(item["cy"]),
                        r=float(item["val1"]),
                        move_camera=bool(item.get("move_camera", False)),
                    )
                else:
                    store.zones.create(
                        layout_id=layout_id,
                        scancode=str(scancode),
                        name=item.get("name", ""),
                        zone_type="RECT",
                        x1=float(item["val1"]),
                        y1=float(item["val2"]),
                        x2=float(item["val3"]),
                        y2=float(item["val4"]),
                        move_camera=bool(item.get("move_camera", False)),
                    )
                imported += 1
            except (KeyError, ValueError) as e:
                logger.warning("Skipping invalid zone (scancode=%s): %s", scancode, e)
                continue

        logger.info(
            "Migrated legacy JSON layout %s into layouts.id=%s (%d/%d zones imported).",
            path,
            layout_id,
            imported,
            len(content),
        )

    if set_active:
        store.set_active_layout(layout_id)

    return layout_id


def migrate_all(toml_path: Path | str = TOML_PATH) -> None:
    """Runs both migrations in order. The JSON layout path is read
    from the legacy TOML's [system].json_path, since that's the only
    place the old config recorded which layout file was active."""
    path = Path(toml_path)
    json_path: Optional[str] = None

    if path.exists():
        try:
            with path.open("r", encoding="utf-8") as f:
                doc = tomlkit.load(f)
            json_path = doc.get("system", {}).get("json_path")
        except Exception as e:
            logger.error("Could not read json_path from legacy TOML: %s", e)

    migrate_toml_config(path)

    if json_path:
        migrate_json_layout(json_path)
    else:
        logger.info(
            "No json_path found in legacy TOML; skipping JSON layout migration."
        )
