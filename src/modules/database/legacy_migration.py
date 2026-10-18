"""One-time and on-demand importer from TOML configs and JSON layout files

into SQLite with lossless pipeline preservation and 5-stage synthesis fallback.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Optional

import tomlkit

from modules.core.pipeline import PipelineConfig
from modules.database import store
from modules.limits import (
    ADB_RATE_CAP_MAX,
    ADB_RATE_CAP_MIN,
    DEADZONE_MAX,
    DEADZONE_MIN,
    HYSTERESIS_MAX,
    HYSTERESIS_MIN,
    PPS_ALERT_MAX,
    PPS_ALERT_MIN,
    SENSITIVITY_MAX,
    SENSITIVITY_MIN,
    TYPEMATIC_DELAY_MAX_MS,
    TYPEMATIC_DELAY_MIN_MS,
    TYPEMATIC_RATE_MAX_HZ,
    TYPEMATIC_RATE_MIN_HZ,
    clamp,
)
from modules.utils import (
    BEZEL,
    BEZEL_DP_THICKNESS,
    CIRCLE,
    JSONS_FOLDER,
    MOUSE_WHEEL_SIMULATOR_CODE,
    RECTANGLE,
    TOML_PATH,
)

logger = logging.getLogger("modules.database.legacy_migration")


def _read_keys(doc: dict[str, Any]) -> tuple[Optional[str], Optional[str]]:
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
    keys_table = doc.get("keys", {})
    typematic_table = doc.get("typematic", {})
    toggle_key, sprint_key = _read_keys(doc)

    try:
        width, height = system.get(
            "json_dev_res",
            [
                system.get("json_dev_width", 360),
                system.get("json_dev_height", 800),
            ],
        )

        two_finger_tap_enabled = system.get("two_finger_tap_enabled", True)
        bezel_toggle_enabled = system.get("bezel_toggle_enabled", True)
        sort_order = system.get("profile_sort_order", "Recently Modified")

        typ_enabled = typematic_table.get(
            "enabled", keys_table.get("typematic_enabled", True)
        )
        typ_delay = typematic_table.get(
            "delay_ms", keys_table.get("typematic_delay_ms", 250.0)
        )
        typ_rate = typematic_table.get(
            "rate_hz", keys_table.get("typematic_rate_hz", 30.0)
        )
        typ_excludes = typematic_table.get(
            "exclude_keys",
            keys_table.get("typematic_exclude_keys", ""),
        )

        # Ranges come from modules.limits (same as the Settings page spin boxes).
        fields: dict[str, Any] = {
            "left_handed": bool(system.get("left_handed", False)),
            "json_dev_width": int(width),
            "json_dev_height": int(height),
            "json_dev_dpi": int(system.get("json_dev_dpi", 160)),
            "deadzone": clamp(
                float(joystick.get("deadzone", 0.1)), DEADZONE_MIN, DEADZONE_MAX
            ),
            "hysteresis": clamp(
                float(joystick.get("hysteresis", 5.0)), HYSTERESIS_MIN, HYSTERESIS_MAX
            ),
            "anchored_joystick": bool(joystick.get("anchored_joystick", False)),
            "floating_joystick": bool(joystick.get("floating_joystick", False)),
            "sensitivity_x": clamp(
                float(mouse.get("sensitivity_x", 1.0)), SENSITIVITY_MIN, SENSITIVITY_MAX
            ),
            "sensitivity_y": clamp(
                float(mouse.get("sensitivity_y", 1.0)), SENSITIVITY_MIN, SENSITIVITY_MAX
            ),
            "toggle_key": str(toggle_key) if toggle_key else "",
            "sprint_key": str(sprint_key) if sprint_key else "",
            "adb_rate_cap": clamp(
                float(performance.get("adb_rate_cap", 250.0)),
                ADB_RATE_CAP_MIN,
                ADB_RATE_CAP_MAX,
            ),
            "pps_alert_threshold": clamp(
                float(performance.get("pps_alert_threshold", 60.0)),
                PPS_ALERT_MIN,
                PPS_ALERT_MAX,
            ),
            "typematic_enabled": bool(typ_enabled),
            "typematic_delay_ms": clamp(
                float(typ_delay), TYPEMATIC_DELAY_MIN_MS, TYPEMATIC_DELAY_MAX_MS
            ),
            "typematic_rate_hz": clamp(
                float(typ_rate), TYPEMATIC_RATE_MIN_HZ, TYPEMATIC_RATE_MAX_HZ
            ),
            "typematic_excluded_keys": (
                str(typ_excludes) if typ_excludes is not None else None
            ),
            "two_finger_tap_enabled": bool(two_finger_tap_enabled),
            "bezel_toggle_enabled": bool(bezel_toggle_enabled),
            "profile_sort_order": str(sort_order),
        }
    except (TypeError, ValueError) as e:
        logger.error("Invalid value in TOML at %s: %s", path, e)
        return False

    store.settings.update(**fields)
    logger.info("Migrated TOML config from %s into app_settings.", path)
    return True


def migrate_json_layout(
    json_path: Path | str,
    image_path: str = "",
    layout_name: str | None = None,
    set_active: bool = True,
) -> Optional[int]:
    """Imports a JSON layout file into SQLite with pipeline configuration validation.

    If a layout with the same name already exists it is linked (not overwritten).
    A layout that fails halfway through is deleted again, never left half-imported.
    """
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
        if not isinstance(content, list):
            raise TypeError("'content' must be a list")
        width = int(metadata["width"])
        height = int(metadata["height"])
        dpi = int(metadata["dpi"])
        mouse_wheel_radius = float(metadata.get("mouse_wheel_radius", 50.0))
        sprint_distance = float(metadata.get("sprint_distance", 10.0))
    except (KeyError, TypeError, ValueError) as e:
        logger.error("JSON layout %s has missing or invalid metadata/content: %s", path, e)
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
            width=width,
            height=height,
            dpi=dpi,
            mouse_wheel_radius=mouse_wheel_radius,
            sprint_distance=sprint_distance,
            image_path=image_path,
        )
        layout_id = layout.id

        try:
            has_explicit_bezels = any(
                str(item.get("type", "")).upper() == BEZEL for item in content
            )
            if has_explicit_bezels:
                store.zones.delete_all_for_layout(layout_id)

            app_settings = store.settings.get()
            imported = 0

            for item in content:
                scancode = item.get("scancode")
                if scancode is None:
                    continue

                zone_type = str(item.get("type", "")).upper()
                if zone_type not in (CIRCLE, RECTANGLE, BEZEL):
                    logger.warning(
                        "Skipping zone with unrecognized type %r for scancode %s.",
                        zone_type,
                        scancode,
                    )
                    continue

                priority = int(item.get("priority", 0))
                pointer = bool(item.get("pointer", False))
                zone_name = str(item.get("name", ""))
                ignore_app_settings = bool(item.get("ignore_app_settings", False))

                existing_pipeline_json = item.get("pipeline_json")
                if existing_pipeline_json and isinstance(existing_pipeline_json, str):
                    pipeline_json = existing_pipeline_json
                else:
                    p_cfg = PipelineConfig()
                    reg_idx = 1 if zone_type == CIRCLE else 2
                    orig_idx = 1
                    const_idx = 0
                    trans_idx = 1
                    sem_idx = 0

                    # Compare scancodes, not names (name is a str, the code an int).
                    if int(scancode) == MOUSE_WHEEL_SIMULATOR_CODE:
                        sem_idx = 1
                        trans_idx = 2
                        if app_settings.anchored_joystick:
                            orig_idx = 2
                            const_idx = 2
                        elif app_settings.floating_joystick:
                            orig_idx = 1
                            const_idx = 2
                        else:
                            orig_idx = 0
                            const_idx = 1

                    elif zone_type == BEZEL:
                        orig_idx = 0
                        const_idx = 0
                        trans_idx = 0
                        sem_idx = 3

                    p_cfg.set_region_config(reg_idx, BEZEL_DP_THICKNESS, priority)
                    p_cfg.set_origin_config(orig_idx)
                    p_cfg.set_constraint_config(const_idx)
                    p_cfg.set_transform_config(
                        trans_idx,
                        app_settings.sensitivity_x,
                        app_settings.sensitivity_y,
                        app_settings.deadzone * mouse_wheel_radius,
                        app_settings.hysteresis,
                    )
                    p_cfg.set_semantic_config(sem_idx, pointer)
                    pipeline_json = p_cfg.get_pipeline_json_from_config()

                store.zones.create(
                    layout_id=layout_id,
                    scancode=int(scancode),
                    name=str(zone_name),
                    zone_type=zone_type,
                    cx=float(item.get("cx")),
                    cy=float(item.get("cy")),
                    r=float(item.get("val1")) if zone_type == CIRCLE else None,
                    x1=float(item.get("val1")),
                    y1=float(item.get("val2")),
                    x2=float(item.get("val3")),
                    y2=float(item.get("val4")),
                    ignore_app_settings=ignore_app_settings,
                    pipeline_json=pipeline_json,
                )
                imported += 1

            logger.info(
                "Migrated JSON layout %s into layouts.id=%s (%d/%d zones imported).",
                path,
                layout_id,
                imported,
                len(content),
            )

            layout_record = store.layouts.get(layout_id)
            if layout_record:
                store.zones.ensure_bezels(layout_record)

        except Exception:
            logger.exception(
                "Import of %s failed; removing the partially imported layout.", path
            )
            try:
                store.layouts.delete(layout_id)
            except Exception:
                logger.exception("Could not remove partial layout id=%s", layout_id)
            return None

    if set_active:
        store.settings.update(active_layout_id=layout_id)

    return layout_id


def migrate_all(toml_path: Path | str = TOML_PATH) -> bool:
    """Migrates settings and resolves active layout from the TOML document.

    Returns True if settings and/or a layout were imported.
    """
    path = Path(toml_path)
    json_path: Optional[str] = None
    image_path: str = ""

    if path.exists():
        try:
            with path.open("r", encoding="utf-8") as f:
                doc = tomlkit.load(f)

            system_table = doc.get("system", {})
            json_path = system_table.get("json_path")
            image_path = system_table.get("image_path", "") or ""
        except Exception as e:
            logger.error("Could not read layout references from TOML: %s", e)

    ok = migrate_toml_config(path)

    resolved_json: Optional[Path] = None
    if json_path:
        candidate = Path(json_path)
        if candidate.is_file():
            resolved_json = candidate
        elif (path.parent / candidate.name).is_file():
            resolved_json = path.parent / candidate.name
        elif (JSONS_FOLDER / candidate.name).is_file():
            resolved_json = JSONS_FOLDER / candidate.name

    if not resolved_json and path.is_file():
        # Only guess when it is unambiguous; picking the first of several would
        # silently activate an unrelated layout.
        local_jsons = sorted(path.parent.glob("*.json"))
        if len(local_jsons) == 1:
            resolved_json = local_jsons[0]

    if resolved_json:
        layout_id = migrate_json_layout(
            json_path=resolved_json, image_path=image_path, set_active=True
        )
        ok = ok or layout_id is not None
    else:
        logger.info(
            "No valid JSON layout found for TOML at %s; settings migration only.",
            path,
        )

    return ok
