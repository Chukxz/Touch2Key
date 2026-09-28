"""One-time importer from legacy/current TOML config and JSON layout files

into the SQLite database with full 5-stage pipeline synthesis.
"""

import json
import logging
from pathlib import Path
from typing import Any, Optional

import tomlkit

from modules.database import store
from modules.utils import (
    JSONS_FOLDER,
    TOML_PATH,
    CIRCLE,
    RECTANGLE,
    BEZEL,
    MOUSE_WHEEL_CODE,
)

from modules.core.pipeline import PipelineConfig

from modules.core.bezel_validator import (
    ensure_system_bezels,
)

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
    keys_table = doc.get("keys", {})
    typematic_table = doc.get("typematic", {})
    toggle_key, sprint_key = _read_keys(doc)

    width, height = system.get(
        "json_dev_res",
        [
            system.get("json_dev_width", 360),
            system.get("json_dev_height", 800),
        ],
    )

    double_tap_enabled = system.get("double_tap_enabled", True)
    bezel_toggle_enabled = system.get("bezel_toggle_enabled", True)

    # Read typematic values from [typematic] or fall back to legacy [keys] definitions
    typ_enabled = typematic_table.get(
        "enabled", keys_table.get("typematic_enabled", True)
    )
    typ_delay = typematic_table.get(
        "delay_ms", keys_table.get("typematic_delay_ms", 250.0)
    )
    typ_rate = typematic_table.get("rate_hz", keys_table.get("typematic_rate_hz", 30.0))
    typ_excludes = typematic_table.get(
        "exclude_keys",
        keys_table.get("typematic_exclude_keys", "w,a,s,d,shift,ctrl,alt"),
    )

    fields: dict[str, Any] = {
        "left_handed": bool(system.get("left_handed", False)),
        "json_dev_width": int(width),
        "json_dev_height": int(height),
        "json_dev_dpi": int(system.get("json_dev_dpi", 160)),
        "deadzone": float(joystick.get("deadzone", 0.1)),
        "hysteresis": float(joystick.get("hysteresis", 5.0)),
        "anchored_joystick": bool(joystick.get("anchored_joystick", False)),
        "floating_joystick": bool(joystick.get("floating_joystick", False)),
        "sensitivity_x": float(mouse.get("sensitivity_x", 1.0)),
        "sensitivity_y": float(mouse.get("sensitivity_y", 1.0)),
        "toggle_key": str(toggle_key) if toggle_key else "",
        "sprint_key": str(sprint_key) if sprint_key else "",
        "adb_rate_cap": float(performance.get("adb_rate_cap", 250.0)),
        "pps_alert_threshold": float(performance.get("pps_alert_threshold", 60.0)),
        "typematic_enabled": bool(typ_enabled),
        "typematic_delay_ms": float(typ_delay),
        "typematic_rate_hz": float(typ_rate),
        "typematic_exclude_keys": (
            str(typ_excludes) if typ_excludes is not None else None
        ),
        "double_tap_enabled": bool(double_tap_enabled),
        "bezel_toggle_enabled": bool(bezel_toggle_enabled),
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
    """Imports a JSON layout file into SQLite with synthesized 5-stage pipeline configs."""
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
        logger.error(
            "JSON layout %s missing expected metadata/content key: %s", path, e
        )
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
            auto_seed_bezels=False,  # We are importing zones, do not seed defaults
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
            if zone_type not in (CIRCLE, RECTANGLE, BEZEL):
                logger.warning(
                    "Skipping zone with unrecognized type %r for scancode %s.",
                    zone_type,
                    scancode,
                )
                continue

            priority = int(item.get("priority", 0))
            pointer = bool(item.get("pointer", False))
            Pipeline_Config = PipelineConfig()
            zone_name = str(item.get("name", ""))
            app_settings = store.settings.get()

            Pipeline_Config.set_region_config(2, priority)
            Pipeline_Config.set_origin_config(1)
            Pipeline_Config.set_constraint_config(0)
            Pipeline_Config.set_transform_config(1)
            Pipeline_Config.set_semantic_config(0, pointer)

            if zone_type == CIRCLE:
                reg_idx = 1

                if zone_name == MOUSE_WHEEL_CODE:
                    Pipeline_Config.set_semantic_config(1)

                    reg_idx = 1
                    orig_idx = 0
                    const_idx = 1

                    if app_settings.floating_joystick:
                        reg_idx = 2
                        orig_idx = 1
                        const_idx = 2

                    if app_settings.anchored_joystick:
                        reg_idx = 2
                        orig_idx = 2
                        const_idx = 2

                    Pipeline_Config.set_origin_config(orig_idx)
                    Pipeline_Config.set_constraint_config(const_idx)

                Pipeline_Config.set_region_config(reg_idx)

            elif zone_type == BEZEL:
                Pipeline_Config.set_origin_config(0)
                Pipeline_Config.set_transform_config(0)
                Pipeline_Config.set_semantic_config(3)

            store.zones.create(
                layout_id=layout_id,
                scancode=str(scancode),
                name=item.get("name", ""),
                zone_type=zone_type,
                cx=item.get("cx", None),
                cy=item.get("cy", None),
                r=item.get("val1", None) if zone_type == CIRCLE else None,
                x1=item.get("val1", None),
                y1=item.get("val2", None),
                x2=item.get("val3", None),
                y2=item.get("val4", None),
                pipeline_json=Pipeline_Config.get_pipeline_json_from_config(),
            )

            imported += 1

        logger.info(
            "Migrated JSON layout %s into layouts.id=%s (%d/%d zones imported).",
            path,
            layout_id,
            imported,
            len(content),
        )

        ensure_system_bezels(layout_id, store.layouts, store.zones)

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

    migrate_toml_config(path)

    if json_path:
        migrate_json_layout(json_path=json_path, image_path=image_path, set_active=True)
    else:
        logger.info(
            "No json_path configured in TOML; completed settings migration only."
        )
