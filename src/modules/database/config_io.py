from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Optional
import tomlkit

from modules.database import store
from modules.database.legacy_migration import migrate_all, migrate_json_layout
from modules.utils import CIRCLE, JSONS_FOLDER, PROFILES_FOLDER, TOML_PATH

logger = logging.getLogger("modules.database.config_io")


def export_layout_json(layout_id: int, target_path: Optional[Path] = None) -> Path:
    """Exports a single layout row and its zones to a JSON file in data/jsons/."""
    layout = store.layouts.get(layout_id)
    if not layout:
        raise ValueError(f"Layout ID {layout_id} does not exist.")

    JSONS_FOLDER.mkdir(parents=True, exist_ok=True)
    out_file = target_path or (JSONS_FOLDER / f"{layout.name}.json")

    zones = store.zones.list_for_layout(layout.id)
    content = []
    for zone in zones:
        content.append(
            {
                "name": zone.name,
                "scancode": zone.scancode,
                "type": zone.zone_type,
                "cx": zone.cx or 0.0,
                "cy": zone.cy or 0.0,
                "val1": zone.r if zone.zone_type == CIRCLE else (zone.x1 or 0.0),
                "val2": zone.y1 or 0.0,
                "val3": zone.x2 or 0.0,
                "val4": zone.y2 or 0.0,
                "pointer": bool(zone.pointer),
                "priority": zone.priority,
            }
        )

    json_data = {
        "metadata": {
            "width": layout.width,
            "height": layout.height,
            "dpi": layout.dpi,
            "mouse_wheel_radius": layout.mouse_wheel_radius,
            "sprint_distance": layout.sprint_distance,
        },
        "content": content,
    }

    out_file.parent.mkdir(parents=True, exist_ok=True)
    with open(out_file, "w", encoding="utf-8") as f:
        json.dump(json_data, f, indent=4)

    logger.info("Exported layout JSON to %s", out_file)
    return out_file


def export_settings_toml(
    target_path: Path = TOML_PATH,
    linked_json_path: Optional[Path] = None,
) -> Path:
    """Exports app_settings to TOML in data/settings.toml or custom target."""
    s = store.settings.get()
    active_layout = store.get_active_layout()

    doc = tomlkit.document()

    # System Section
    system = tomlkit.table()
    system.add("left_handed", bool(s.left_handed))
    system.add(
        "json_dev_width", active_layout.width if active_layout else s.json_dev_width
    )
    system.add(
        "json_dev_height", active_layout.height if active_layout else s.json_dev_height
    )
    system.add("json_dev_dpi", active_layout.dpi if active_layout else s.json_dev_dpi)
    system.add("image_path", active_layout.image_path if active_layout else "")

    if linked_json_path:
        system.add("json_path", str(linked_json_path.resolve()))
    else:
        system.add("json_path", "")
        
    system.add("double_tap_enabled", bool(s.double_tap_enabled))
    system.add("system_toggle_enabled", bool(s.system_toggle_enabled))
    doc.add("system", system)

    # Performance Section
    perf = tomlkit.table()
    perf.add("adb_rate_cap", float(s.adb_rate_cap))
    perf.add("pps_alert_threshold", float(s.pps_alert_threshold))
    doc.add("performance", perf)

    # Joystick Section
    joystick = tomlkit.table()
    joystick.add("deadzone", float(s.deadzone))
    joystick.add("hysteresis", float(s.hysteresis))
    joystick.add("anchored_joystick", bool(s.anchored_joystick))
    joystick.add("floating_joystick", bool(s.floating_joystick))
    doc.add("joystick", joystick)

    # Mouse Section
    mouse = tomlkit.table()
    mouse.add("sensitivity_x", float(s.sensitivity_x))
    mouse.add("sensitivity_y", float(s.sensitivity_y))
    doc.add("mouse", mouse)

    # Keys Section
    keys = tomlkit.table()
    keys.add("toggle_key", s.toggle_key or "")
    keys.add("sprint_key", s.sprint_key or "")
    doc.add("keys", keys)

    # Typematic Section
    typematic = tomlkit.table()
    typematic.add("enabled", bool(s.typematic_enabled))
    typematic.add("delay_ms", float(s.typematic_delay_ms))
    typematic.add("rate_hz", float(s.typematic_rate_hz))
    typematic.add("exclude_keys", s.typematic_exclude_keys or "w,a,s,d,shift,ctrl,alt")
    doc.add("typematic", typematic)

    target_path.parent.mkdir(parents=True, exist_ok=True)
    with open(target_path, "w", encoding="utf-8") as f:
        f.write(tomlkit.dumps(doc))

    logger.info("Exported settings TOML to %s", target_path)
    return target_path


def export_bundle(
    target_dir: Optional[Path] = None, profile_name: Optional[str] = None
) -> tuple[Path, Path]:
    """Exports both active layout (.json) and linked settings (.toml) into data/profiles/<name>/."""
    active_layout = store.get_active_layout()
    if not active_layout:
        raise ValueError("No active layout available to bundle.")

    name = profile_name or active_layout.name

    PROFILES_FOLDER.mkdir(parents=True, exist_ok=True)
    out_dir = (target_dir or PROFILES_FOLDER) / f"{name}"
    out_dir.mkdir(parents=True, exist_ok=True)

    json_file = export_layout_json(active_layout.id, out_dir / f"{name}.json")
    toml_file = export_settings_toml(
        out_dir / f"{name}.toml", linked_json_path=json_file
    )

    logger.info("Exported full profile bundle to %s", out_dir)
    return toml_file, json_file


def import_any(file_or_dir_path: Path) -> bool:
    """Universal importer supporting .json layout, .toml config, or bundled profile directories."""
    path = Path(file_or_dir_path)
    if not path.exists():
        logger.warning("Import target '%s' does not exist.", path)
        return False

    if path.is_dir():
        toml_files = list(path.glob("*.toml"))
        if toml_files:
            migrate_all(toml_files[0])
            logger.info("Imported profile bundle from directory: %s", path)
            return True
        json_files = list(path.glob("*.json"))
        if json_files:
            return migrate_json_layout(json_files[0], set_active=True) is not None
        return False

    suffix = path.suffix.lower()
    if suffix == ".json":
        layout_id = migrate_json_layout(path, set_active=True)
        return layout_id is not None
    elif suffix == ".toml":
        migrate_all(path)
        return True

    return False
