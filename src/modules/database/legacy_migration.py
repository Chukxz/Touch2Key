# LEGACY_MIGRATION.PY

"""
One-time importer for existing users' TOML config and JSON layout
files, so migrating to sqlite doesn't discard an already-tuned setup.

Intended to run once -- e.g. from a `touch2key-migrate` console script,
or a first-run GUI prompt shown only when touch2key.db doesn't exist
yet but a legacy TOML config does -- not on every startup. Deliberately
kept out of db/__init__.py's imports (and out of Store itself) so
pulling in tomlkit and doing file I/O isn't a cost every normal run
pays; import this module explicitly where migration actually happens:

    from mapper_module.db import Store, default_db_path
    from mapper_module.db.legacy_migration import (
        import_legacy_config, import_legacy_layout,
    )

    store = Store(default_db_path())
    import_legacy_config(store, old_toml_path)
    layout = import_legacy_layout(store, old_json_path, name="Imported")
    store.layouts.set_active(layout.id)
"""

from __future__ import annotations
import json
import logging
from pathlib import Path

import tomlkit

from mapper_module.utils import CIRCLE, RECT
from .repositories import Layout
from . import Store

logger = logging.getLogger("mapper_module.db")


def import_legacy_config(store: Store, toml_path: str | Path) -> None:
    """Copies [system]/[joystick]/[mouse] values from an existing TOML
    config into app_settings. Missing sections or keys are left at
    their sqlite schema defaults rather than raising -- a partially
    filled legacy TOML (or one from an older Touch2Key version with
    fewer settings) shouldn't block migration for the fields it does
    have."""
    toml_path = Path(toml_path)
    if not toml_path.exists():
        logger.info("No legacy TOML config found at %s; skipping.", toml_path)
        return

    with toml_path.open("r", encoding="utf-8") as f:
        data = tomlkit.load(f)

    system = data.get("system", {})
    joystick = data.get("joystick", {})
    mouse = data.get("mouse", {})

    fields: dict = {}
    if "left_handed" in system:
        fields["left_handed"] = bool(system["left_handed"])
    if "json_dev_res" in system:
        width, height = system["json_dev_res"]
        fields["json_dev_width"] = int(width)
        fields["json_dev_height"] = int(height)
    if "json_dev_dpi" in system:
        fields["json_dev_dpi"] = int(system["json_dev_dpi"])
    if "toggle_key" in system:
        fields["toggle_key"] = system["toggle_key"] or None
    if "sprint_key" in system:
        fields["sprint_key"] = system["sprint_key"] or None
    if "deadzone" in joystick:
        fields["deadzone"] = float(joystick["deadzone"])
    if "hysteresis" in joystick:
        fields["hysteresis"] = float(joystick["hysteresis"])
    if "sensitivity" in mouse:
        fields["sensitivity"] = float(mouse["sensitivity"])

    if fields:
        store.settings.update(**fields)
        logger.info("Imported %d setting(s) from %s.", len(fields), toml_path)


def import_legacy_layout(store: Store, json_path: str | Path, name: str) -> Layout:
    """Imports one JSON layout file (the format json_loader.py used to
    read directly) as a new named row in `layouts` plus its zones in
    `layout_zones`.

    Coordinates are stored exactly as they appear in the source JSON --
    raw device-pixel values, unnormalized. json_loader.py used to
    divide by device resolution at load time to get 0..1 floats for the
    hot touch-processing path; that normalization is a runtime concern
    for whatever replaces JSONLoader against this store, not a storage
    concern here. Keeping raw pixel values in the DB also matches what
    a zone-editing canvas drawn over a screenshot needs directly.
    """
    json_path = Path(json_path)
    with json_path.open("r", encoding="utf-8") as f:
        data = json.load(f)

    metadata = data["metadata"]
    content = data.get("content", [])

    layout = store.layouts.create(
        name=name,
        width=metadata["width"],
        height=metadata["height"],
        dpi=metadata["dpi"],
        mouse_wheel_radius=metadata.get("mouse_wheel_radius", 50.0),
        sprint_distance=metadata.get("sprint_distance", 10.0),
    )

    zones: list[dict] = []
    skipped = 0

    for item in content:
        scancode = item.get("scancode")
        raw_type = item.get("type")

        if raw_type == CIRCLE:
            zone_type = "circle"
        elif raw_type == RECT:
            zone_type = "rect"
        else:
            zone_type = None

        if scancode is None or zone_type is None:
            skipped += 1
            continue

        zone = {
            "scancode": scancode,
            "name": item.get("name", ""),
            "zone_type": zone_type,
            "move_camera": bool(item.get("move_camera", False)),
        }

        try:
            if zone_type == "circle":
                zone["cx"] = float(item["cx"])
                zone["cy"] = float(item["cy"])
                zone["r"] = float(item["val1"])
            else:
                zone["x1"] = float(item["val1"])
                zone["y1"] = float(item["val2"])
                zone["x2"] = float(item["val3"])
                zone["y2"] = float(item["val4"])
        except (KeyError, ValueError, TypeError):
            skipped += 1
            continue

        zones.append(zone)

    store.zones.replace_all_for_layout(layout.id, zones)

    if skipped:
        logger.warning(
            "Skipped %d malformed zone(s) while importing %s.", skipped, json_path
        )

    logger.info(
        "Imported layout '%s' (%d zone(s)) from %s.", name, len(zones), json_path
    )
    return layout
