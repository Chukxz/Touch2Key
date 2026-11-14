"""Config import/export for Touch2Key.

Export: layouts -> JSON, settings -> TOML, profile bundles (both).
Import: TOML configs and JSON layout files into SQLite with lossless pipeline
preservation and 5-stage synthesis fallback.
"""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Any, Optional

import tomlkit

from modules.core.pipeline import PipelineConfig
from modules.database import store
from modules.utils import (
    ADB_RATE_CAP_MAX,
    ADB_RATE_CAP_MIN,
    BEZEL,
    BEZEL_DP_THICKNESS,
    BOTTOM_BEZEL_ID,
    CIRCLE,
    DEADZONE_MAX,
    DEADZONE_MIN,
    EXCLUDED_KEYS,
    HYSTERESIS_MAX,
    HYSTERESIS_MIN,
    JSONS_FOLDER,
    MOUSE_WHEEL_SIMULATOR_CODE,
    PPS_ALERT_MAX,
    PPS_ALERT_MIN,
    PROFILES_FOLDER,
    RECTANGLE,
    SENSITIVITY_MAX,
    SENSITIVITY_MIN,
    TOML_PATH,
    TOP_BEZEL_ID,
    TYPEMATIC_DELAY_MAX_MS,
    TYPEMATIC_DELAY_MIN_MS,
    TYPEMATIC_RATE_MAX_HZ,
    TYPEMATIC_RATE_MIN_HZ,
    clamp,
    get_scancode_from_key,
)

logger = logging.getLogger("modules.database.config_io")

_ILLEGAL_FILENAME_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def safe_filename(name: str) -> str:
    """Layout names may contain characters that are illegal in file names."""
    cleaned = _ILLEGAL_FILENAME_CHARS.sub("_", name).strip(" .")
    return cleaned or "profile"


def _normalize_hotkeys(raw: Any) -> str:
    """Comma-separated, lower-cased, de-duplicated key names ("" if none/invalid).

    Accepts the current comma-separated string, a TOML array, or a legacy single
    key / 'a+b' combo. All-or-nothing: one unsupported key drops the whole hotkey,
    because a partial chord would fire the wrong keys in the game.
    """
    if raw is None:
        return ""

    if isinstance(raw, (list, tuple)):
        tokens = [str(k) for k in raw]
    else:
        tokens = str(raw).replace("+", ",").split(",")

    keys: list[str] = []
    for token in tokens:
        key = token.strip().lower()
        if not key or key in keys:
            continue
        if get_scancode_from_key(key) is None:
            logger.warning(
                "Ignoring toggle hotkeys %r in imported config: unsupported key %r.",
                raw,
                key,
            )
            return ""
        keys.append(key)

    return ",".join(keys)


def _read_keys(doc: dict[str, Any]) -> tuple[str, Optional[str]]:
    """(toggle_hotkeys, sprint_key)."""
    keys = doc.get("keys", {})
    raw_hotkeys = keys.get("toggle_hotkeys")
    return _normalize_hotkeys(raw_hotkeys), keys.get("sprint_key")


# ---------------------------------------------------------------------------
# Export
# ---------------------------------------------------------------------------


def export_layout_json(layout_id: int, target_path: Optional[Path] = None) -> Path:
    """Exports a single layout row and its zones to a JSON file in data/jsons/."""
    layout = store.layouts.get(layout_id)
    if not layout:
        raise ValueError(f"Layout ID {layout_id} does not exist.")

    JSONS_FOLDER.mkdir(parents=True, exist_ok=True)
    out_file = target_path or (JSONS_FOLDER / f"{safe_filename(layout.name)}.json")

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
                "ignore_app_settings": bool(zone.ignore_app_settings),
                "pipeline": json.loads(zone.pipeline_json or "{}"),
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
    layout=None,
) -> Path:
    """Exports app_settings to TOML in data/settings.toml or custom target.

    `layout` selects which layout's canvas/image fields are written (defaults to the
    active layout).
    """
    s = store.settings.get()
    active_layout = layout if layout is not None else store.get_active_layout()

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
    # image_path is None for layouts without an image; TOML has no null.
    system.add("image_path", (active_layout.image_path if active_layout else "") or "")

    if linked_json_path:
        system.add("json_path", str(linked_json_path.resolve()))
    else:
        system.add("json_path", "")

    system.add("two_finger_tap_enabled", bool(s.two_finger_tap_enabled))
    system.add("bezel_toggle_enabled", bool(s.bezel_toggle_enabled))
    system.add(
        "profile_sort_order",
        str(getattr(s, "profile_sort_order", "Recently Modified")),
    )
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
    keys.add("toggle_hotkeys", s.toggle_hotkeys or "")
    keys.add("sprint_key", s.sprint_key or "")
    doc.add("keys", keys)

    # Typematic Section
    typematic = tomlkit.table()
    typematic.add("enabled", bool(s.typematic_enabled))
    typematic.add("delay_ms", float(s.typematic_delay_ms))
    typematic.add("rate_hz", float(s.typematic_rate_hz))
    typematic.add("exclude_keys", s.typematic_excluded_keys or "")
    doc.add("typematic", typematic)

    target_path.parent.mkdir(parents=True, exist_ok=True)
    with open(target_path, "w", encoding="utf-8") as f:
        f.write(tomlkit.dumps(doc))

    logger.info("Exported settings TOML to %s", target_path)
    return target_path


def export_bundle(
    target_dir: Optional[Path] = None,
    profile_name: Optional[str] = None,
    layout_id: Optional[int] = None,
) -> tuple[Path, Path]:
    """Exports a layout (.json) and linked settings (.toml) into <target_dir>/<name>/.

    `layout_id` selects the layout to bundle; it defaults to the active layout.
    """
    layout = (
        store.layouts.get(layout_id)
        if layout_id is not None
        else store.get_active_layout()
    )
    if not layout:
        raise ValueError("No layout available to bundle.")

    name = safe_filename(profile_name or layout.name)

    PROFILES_FOLDER.mkdir(parents=True, exist_ok=True)
    out_dir = (target_dir or PROFILES_FOLDER) / name
    out_dir.mkdir(parents=True, exist_ok=True)

    json_file = export_layout_json(layout.id, out_dir / f"{name}.json")
    toml_file = export_settings_toml(
        out_dir / f"{name}.toml", linked_json_path=json_file, layout=layout
    )

    logger.info("Exported full profile bundle to %s", out_dir)
    return toml_file, json_file


# ---------------------------------------------------------------------------
# Import
# ---------------------------------------------------------------------------


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
    toggle_hotkeys, sprint_key = _read_keys(doc)

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
        # A missing value means "factory default". An explicit "" means "no
        # exclusions" (KeyMapper treats "" as an empty set, not as the default).
        typ_excludes = typematic_table.get(
            "exclude_keys",
            keys_table.get("typematic_exclude_keys", EXCLUDED_KEYS),
        )

        # Ranges come from modules.utils (same as the Settings page spin boxes).
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
            "toggle_hotkeys": toggle_hotkeys,
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


def _bezel_dp_from_item(item: dict[str, Any]) -> int:
    """Bezel thickness (dp) from a JSON bezel item's pipeline, else the default."""
    try:
        region = item["pipeline"]["region"]
        return int(float(region["bezel_dp_thickness"]))
    except (KeyError, TypeError, ValueError):
        return int(BEZEL_DP_THICKNESS)


def migrate_json_layout(
    json_path: Path | str,
    image_path: str = "",
    layout_name: str | None = None,
    set_active: bool = True,
) -> Optional[int]:
    """Imports a JSON layout file into SQLite with pipeline configuration validation.

    If a layout with the same name exists, its canvas metadata and ALL of its zones
    are replaced by the file's content (name is kept; image_path only changes when one
    is given). Everything is written in a single transaction, so a failure leaves the
    database exactly as it was: no half-imported layout, no lost zones.

    Each zone's behavior lives in its nested `pipeline` object (including
    `semantic.pointer`); a zone with no/empty `pipeline` gets a synthesized default.
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
        logger.error(
            "JSON layout %s has missing or invalid metadata/content: %s", path, e
        )
        return None

    target_name = layout_name or path.stem
    existing = store.layouts.get_by_name(target_name)
    app_settings = store.settings.get()

    # Build every zone in memory first; nothing touches the DB until all are valid.
    top_dp = bottom_dp = int(BEZEL_DP_THICKNESS)
    zones: list[dict[str, Any]] = []

    try:
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

            # The two system bezels are regenerated by the repository from the
            # layout geometry; only their thickness is taken from the file.
            if zone_type == BEZEL and int(scancode) in (TOP_BEZEL_ID, BOTTOM_BEZEL_ID):
                if int(scancode) == TOP_BEZEL_ID:
                    top_dp = _bezel_dp_from_item(item)
                else:
                    bottom_dp = _bezel_dp_from_item(item)
                continue

            zone_name = str(item.get("name", ""))
            ignore_app_settings = bool(item.get("ignore_app_settings", False))

            pipeline = item.get("pipeline")
            if pipeline is not None and not isinstance(pipeline, dict):
                raise TypeError(f"'pipeline' of zone {scancode} must be an object")

            if pipeline:
                pipeline_json = json.dumps(pipeline)
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

                p_cfg.set_region_config(reg_idx, BEZEL_DP_THICKNESS, 0)
                p_cfg.set_origin_config(orig_idx)
                p_cfg.set_constraint_config(const_idx)
                # `deadzone` is a 0..1 ratio; WheelMapper multiplies it by the
                # wheel radius itself, so it must NOT be pre-multiplied here.
                p_cfg.set_transform_config(
                    trans_idx,
                    app_settings.sensitivity_x,
                    app_settings.sensitivity_y,
                    app_settings.deadzone,
                    app_settings.hysteresis,
                )
                p_cfg.set_semantic_config(sem_idx, False)
                pipeline_json = p_cfg.get_pipeline_json_from_config()

            zones.append(
                {
                    "scancode": int(scancode),
                    "name": zone_name,
                    "zone_type": zone_type,
                    "cx": float(item.get("cx", 0.0)),
                    "cy": float(item.get("cy", 0.0)),
                    "r": float(item.get("val1", 0.0)) if zone_type == CIRCLE else None,
                    "x1": float(item.get("val1", 0.0)),
                    "y1": float(item.get("val2", 0.0)),
                    "x2": float(item.get("val3", 0.0)),
                    "y2": float(item.get("val4", 0.0)),
                    "ignore_app_settings": ignore_app_settings,
                    "pipeline_json": pipeline_json,
                }
            )
    except Exception:
        logger.exception("Invalid zone data in %s; nothing was imported.", path)
        return None

    layout_fields: dict[str, Any] = {
        "width": width,
        "height": height,
        "dpi": dpi,
        "mouse_wheel_radius": mouse_wheel_radius,
        "sprint_distance": sprint_distance,
    }
    if existing is None:
        layout_fields["name"] = target_name
        layout_fields["image_path"] = image_path
    elif image_path:
        layout_fields["image_path"] = image_path

    try:
        layout = store.layouts.save_with_zones(
            existing.id if existing is not None else None,
            layout_fields,
            top_dp,
            bottom_dp,
            zones,
        )
    except Exception:
        logger.exception("Import of %s failed; database left unchanged.", path)
        return None

    logger.info(
        "Imported JSON layout %s into layouts.id=%s (%d/%d zones, %s).",
        path,
        layout.id,
        len(zones),
        len(content),
        "replaced existing" if existing is not None else "new layout",
    )

    if set_active:
        store.settings.update(active_layout_id=layout.id)

    return layout.id


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


def import_any(file_or_dir_path: Path | str) -> bool:
    """Universal importer supporting .json layout, .toml config, or bundled profile directories."""
    path = Path(file_or_dir_path)
    if not path.exists():
        logger.warning("Import target '%s' does not exist.", path)
        return False

    if path.is_dir():
        toml_files = sorted(path.glob("*.toml"))
        if toml_files:
            ok = migrate_all(toml_files[0])
            if ok:
                logger.info("Imported profile bundle from directory: %s", path)
            return ok
        json_files = sorted(path.glob("*.json"))
        if json_files:
            return migrate_json_layout(json_files[0], set_active=True) is not None
        return False

    suffix = path.suffix.lower()
    if suffix == ".json":
        layout_id = migrate_json_layout(path, set_active=True)
        return layout_id is not None
    elif suffix == ".toml":
        return migrate_all(path)

    return False
