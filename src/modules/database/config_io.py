from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

import tomlkit

from modules.database import store
from modules.database.legacy_migration import migrate_all, migrate_json_layout, migrate_toml_config
from modules.utils import CIRCLE, JSONS_FOLDER, TOML_PATH


def export_layout_json(layout_id: int, target_path: Optional[Path] = None) -> Path:
    """Exports a single layout row and its zones to a JSON file."""
    layout = store.layouts.get(layout_id)
    if not layout:
        raise ValueError(f"Layout ID {layout_id} does not exist.")

    JSONS_FOLDER.mkdir(parents=True, exist_ok=True)
    out_file = target_path or (JSONS_FOLDER / f"{layout.name}.json")

    zones = store.zones.list_for_layout(layout.id)
    content = []
    for zone in zones:
        content.append({
            "name": zone.name,
            "scancode": zone.scancode,
            "type": zone.zone_type,
            "cx": zone.cx or 0.0,
            "cy": zone.cy or 0.0,
            "val1": zone.r if zone.zone_type == CIRCLE else (zone.x1 or 0.0),
            "val2": zone.y1 or 0.0,
            "val3": zone.x2 or 0.0,
            "val4": zone.y2 or 0.0,
            "move_camera": bool(zone.move_camera),
            "priority": zone.priority,
        })

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

    with open(out_file, "w", encoding="utf-8") as f:
        json.dump(json_data, f, indent=4)

    return out_file


def export_settings_toml(
    target_path: Path = TOML_PATH,
    linked_json_path: Optional[Path] = None,
) -> Path:
    """Exports app_settings to TOML, optionally binding an active layout JSON path."""
    s = store.settings.get()
    active_layout = store.get_active_layout()

    doc = tomlkit.document()

    # System Section
    system = tomlkit.table()
    system.add("left_handed", bool(s.left_handed))
    system.add("json_dev_width", active_layout.width if active_layout else s.json_dev_width)
    system.add("json_dev_height", active_layout.height if active_layout else s.json_dev_height)
    system.add("json_dev_dpi", active_layout.dpi if active_layout else s.json_dev_dpi)
    system.add("image_path", active_layout.image_path if active_layout else "")

    if linked_json_path:
        system.add("json_path", str(linked_json_path.resolve()))
    else:
        system.add("json_path", "")

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
    joystick.add("anchored_floating_joystick", bool(s.anchored_floating_joystick))
    joystick.add("joystick_snap_radius", float(s.joystick_snap_radius))
    doc.add("joystick", joystick)

    # Mouse Section
    mouse = tomlkit.table()
    mouse.add("sensitivity", float(s.sensitivity))
    doc.add("mouse", mouse)

    # Keys Section
    keys = tomlkit.table()
    keys.add("toggle_key", s.toggle_key or "")
    keys.add("sprint_key", s.sprint_key or "")
    doc.add("keys", keys)

    target_path.parent.mkdir(parents=True, exist_ok=True)
    with open(target_path, "w", encoding="utf-8") as f:
        f.write(tomlkit.dumps(doc))

    return target_path


def export_bundle(target_dir: Path, profile_name: Optional[str] = None) -> tuple[Path, Path]:
    """Exports both active layout (.json) and linked settings (.toml) into a directory."""
    active_layout = store.get_active_layout()
    if not active_layout:
        raise ValueError("No active layout available to bundle.")

    name = profile_name or active_layout.name
    target_dir.mkdir(parents=True, exist_ok=True)

    json_file = export_layout_json(active_layout.id, target_dir / f"{name}.json")
    toml_file = export_settings_toml(target_dir / f"{name}.toml", linked_json_path=json_file)

    return toml_file, json_file


def import_any(file_path: Path) -> bool:
    """Universal importer supporting .json (layout), .toml (settings), or bundled .toml."""
    if not file_path.exists():
        return False

    suffix = file_path.suffix.lower()

    if suffix == ".json":
        layout_id = migrate_json_layout(file_path, set_active=True)
        return layout_id is not None

    elif suffix == ".toml":
        migrate_all(file_path)
        return True

    return False
