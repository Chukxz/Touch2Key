"""CLI Layout & Profile Manager.

Provides terminal-based profile switching, creation, sorting, filtering,
duplication, renaming, zone/pipeline inspection and per-zone editing, bezel
tuning, JSON layout import/export, TOML app_settings import/export, schema
reset/wipe, bulk and single-zone synchronization to AppSettings, input/joystick
tuning, global keybinding configuration, and typematic configuration/reset routines.
"""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Optional, Any

from PIL import Image

from modules import AppLogManager
from modules.core.pipeline import PipelineConfig
from modules.database import reset_layout_zones_to_app_settings, store
from modules.database.config_io import (
    export_bundle,
    export_layout_json,
    export_settings_toml,
    import_any,
    safe_filename,
)
from modules.database.legacy_migration import (
    migrate_json_layout,
    migrate_toml_config,
)
from modules.database.repositories import DuplicateNameError
from modules.cli.key_capture import capture_keys_cli, capture_performance_settings_cli
from modules.utils import (
    BEZEL,
    BOTTOM_BEZEL_ID,
    CIRCLE,
    DEADZONE_MAX,
    DEADZONE_MIN,
    EXCLUDED_KEYS,
    HYSTERESIS_MAX,
    HYSTERESIS_MIN,
    IMAGES_FOLDER,
    JSONS_FOLDER,
    MAX_BEZEL_DP,
    MAX_PRIORITY,
    MIN_BEZEL_DP,
    MIN_PRIORITY,
    MOUSE_WHEEL_SIMULATOR_CODE,
    PROFILES_FOLDER,
    RECTANGLE,
    SCANCODES,
    SENSITIVITY_MAX,
    SENSITIVITY_MIN,
    SPECIAL_MAP,
    SPRINT_DISTANCE_CODE,
    TOML_PATH,
    TOP_BEZEL_ID,
    TYPEMATIC_DELAY_MAX_MS,
    TYPEMATIC_DELAY_MIN_MS,
    TYPEMATIC_RATE_MAX_HZ,
    TYPEMATIC_RATE_MIN_HZ,
    clamp,
    get_key_from_scancode,
    get_scancode_from_key,
)

VALID_SORT_ORDERS = ("Recently Modified", "Name (A-Z)", "Created (Newest)")

# ---------------------------------------------------------------------------
# Input & Validation Helpers
# ---------------------------------------------------------------------------


def get_target_id(raw_id: str):
    if raw_id.isdigit():
        if store.layouts.get(int(raw_id)) is not None:
            target_id = int(raw_id)
        else:
            target_id = None
            print(f"Error: No layout with ID {int(raw_id)} found in the database.")

    else:
        print(
            f"Warning: Provided layout ID {raw_id} is not a digit, falling back to active layout."
        )
        layout = store.get_active_layout()
        if layout:
            target_id = layout.id
        else:
            target_id = None
            print("Error: No active ayout found in the database")

    return target_id


def _prompt_float(prompt: str, current: float) -> float:
    """Asks for a float; blank or invalid input keeps `current`."""
    raw = input(prompt).strip()
    if not raw:
        return current
    try:
        return float(raw)
    except ValueError:
        print(f"Invalid number '{raw}'; keeping {current}.")
        return current


def _prompt_int(prompt: str, current: int) -> int:
    """Asks for an int; blank or invalid input keeps `current`."""
    raw = input(prompt).strip()
    if not raw:
        return current
    try:
        return int(raw)
    except ValueError:
        print(f"Invalid integer '{raw}'; keeping {current}.")
        return current


def _normalize_excluded_keys(raw_csv: str, current_csv: Optional[str] = None) -> str:
    """Expands +wasd / +arrows presets and validates every key via get_scancode_from_key."""
    seq: list[str] = []
    if current_csv:
        seq.extend(k.strip().lower() for k in current_csv.split(",") if k.strip())

    tokens = [t.strip().lower() for t in raw_csv.split(",") if t.strip()]
    if tokens in (["none"], ["clear"]):
        return ""

    if not any(t.startswith("+") for t in tokens):
        seq.clear()

    for token in tokens:
        if token == "+wasd":
            candidates = ["w", "a", "s", "d"]
        elif token == "+arrows":
            candidates = ["left", "up", "down", "right"]
        else:
            candidates = [token.lstrip("+")]

        for key in candidates:
            if get_scancode_from_key(key) is None:
                print(f"Warning: Skipping unsupported key '{key}'.")
                continue
            if key not in seq:
                seq.append(key)

    return ",".join(seq)


# ---------------------------------------------------------------------------
# Profile Inspection & Management
# ---------------------------------------------------------------------------


def set_profile_image(layout_id: int, image_path_input: str | Path) -> bool:
    """Sets background image for a layout with fallback check in IMAGES_FOLDER."""
    target = store.layouts.get(layout_id)
    if not target:
        print(f"Error: Layout ID {layout_id} not found.")
        return False

    path = Path(image_path_input)
    if not path.exists():
        alt_path = IMAGES_FOLDER / image_path_input
        if alt_path.exists():
            path = alt_path
        else:
            print(
                f"Error: Image file '{image_path_input}' not found (checked direct path and {IMAGES_FOLDER})."
            )
            return False

    # Keep the same portable path convention as Layout Studio: a bare filename
    # for images in IMAGES_FOLDER, otherwise an absolute path.
    resolved_path = path.resolve()
    if resolved_path.parent == IMAGES_FOLDER.resolve():
        stored_ref = path.name
    else:
        stored_ref = str(resolved_path)

    # Layout Studio treats the selected image dimensions as the canvas dimensions.
    # Use the repository's atomic helper so changing resolution rescales non-bezel
    # zones and layout-level distances in the same transaction.
    try:
        with Image.open(resolved_path) as image:
            width, height = image.size
            if width <= 0 or height <= 0:
                raise ValueError("Image has invalid dimensions.")

        updated = store.layouts.apply_image_params(
            layout_id,
            width=width,
            height=height,
            dpi=target.dpi,
            image_path=stored_ref,
        )
    except Exception as exc:
        print(
            f"Error: Could not apply image '{path.name}' to profile '{target.name}': {exc}"
        )
        return False

    print(
        f"Updated profile '{updated.name}' background image to: {path.name} "
        f"({updated.width}x{updated.height}; existing DPI {updated.dpi} retained)."
    )
    return True


def configure_directional_keys(layout_id) -> None:
    show_directional_keys(layout_id)
    directions = {"up", "left", "down", "right"}
    was_set = [False, False, False, False]
    i = 0

    for direction in directions:
        was_set[i] = set_directional_key(layout_id, direction)
        i += 1

    if any(was_set):
        print(
            f"Directional scancodes successfully updated for layout with ID: {layout_id}."
        )
    show_directional_keys(layout_id)


def show_input_controls() -> None:
    """Prints all global touch, joystick, sensitivity, deadzone, hysteresis, and keybinding settings."""
    s = store.settings.get()
    print("\n--- Handedness, Touch, Input Controls & Global Keybindings ---")
    print(f"  Left-Handed Mode:  {'Yes' if s.left_handed else 'No'}")
    print(f"  Floating Joystick: {'Yes' if s.floating_joystick else 'No'}")
    print(f"  Anchored Joystick: {'Yes' if s.anchored_joystick else 'No'}")
    print(f"  Sensitivity X / Y: {s.sensitivity_x:.2f} / {s.sensitivity_y:.2f}")
    print(f"  Deadzone:          {s.deadzone:.2f}")
    print(f"  Hysteresis:        {s.hysteresis:.1f}°")


def configure_input_controls_interactive() -> None:
    """Prompts for touch/input tuning knobs and global keybindings interactively."""
    s = store.settings.get()
    show_input_controls()

    lh = (
        input(f"Left-handed mode? (y/n, current: {'y' if s.left_handed else 'n'}): ")
        .strip()
        .lower()
    )
    fl = (
        input(
            f"Floating joystick? (y/n, current: {'y' if s.floating_joystick else 'n'}): "
        )
        .strip()
        .lower()
    )
    an = (
        input(
            f"Anchored joystick? (y/n, current: {'y' if s.anchored_joystick else 'n'}): "
        )
        .strip()
        .lower()
    )

    sx = clamp(
        _prompt_float(
            f"Sensitivity X ({SENSITIVITY_MIN}-{SENSITIVITY_MAX}, current: {s.sensitivity_x:.2f}): ",
            s.sensitivity_x,
        ),
        SENSITIVITY_MIN,
        SENSITIVITY_MAX,
    )
    sy = clamp(
        _prompt_float(
            f"Sensitivity Y ({SENSITIVITY_MIN}-{SENSITIVITY_MAX}, current: {s.sensitivity_y:.2f}): ",
            s.sensitivity_y,
        ),
        SENSITIVITY_MIN,
        SENSITIVITY_MAX,
    )
    dz = clamp(
        _prompt_float(
            f"Deadzone ({DEADZONE_MIN}-{DEADZONE_MAX}, current: {s.deadzone:.2f}): ",
            s.deadzone,
        ),
        DEADZONE_MIN,
        DEADZONE_MAX,
    )
    hys = clamp(
        _prompt_float(
            f"Hysteresis ({HYSTERESIS_MIN}-{HYSTERESIS_MAX}°, current: {s.hysteresis:.1f}): ",
            s.hysteresis,
        ),
        HYSTERESIS_MIN,
        HYSTERESIS_MAX,
    )

    updates: dict = {
        "left_handed": s.left_handed if lh not in ("y", "n") else (lh == "y"),
        "floating_joystick": (
            s.floating_joystick if fl not in ("y", "n") else (fl == "y")
        ),
        "anchored_joystick": (
            s.anchored_joystick if an not in ("y", "n") else (an == "y")
        ),
        "sensitivity_x": sx,
        "sensitivity_y": sy,
        "deadzone": dz,
        "hysteresis": hys,
    }

    store.settings.update(**updates)
    print("Input controls and global keybindings updated successfully.")
    show_input_controls()


def reset_input_controls_defaults() -> None:
    """Resets only input/joystick tuning knobs to factory defaults."""
    store.settings.update(
        left_handed=False,
        floating_joystick=False,
        anchored_joystick=False,
        sensitivity_x=1.0,
        sensitivity_y=1.0,
        deadzone=0.1,
        hysteresis=5.0,
    )
    print("Input controls reset to factory defaults.")
    show_input_controls()


def set_profile_sort_order(sort_order: str) -> bool:
    """Persists the profile list sort order in AppSettings."""
    matching = next(
        (m for m in VALID_SORT_ORDERS if m.lower() == sort_order.strip().lower()),
        None,
    )
    if not matching:
        print(
            f"Error: Invalid sort order '{sort_order}'. Choose from: {', '.join(VALID_SORT_ORDERS)}"
        )
        return False

    store.settings.update(profile_sort_order=matching)
    print(f"Profile sort order updated to: '{matching}'.")
    return True


def list_profiles(search_query: str = "") -> None:
    """Lists all saved layouts with resolution, DPI, sort order, and zone metrics."""
    layouts = store.layouts.list_all()
    settings = store.settings.get()
    active_layout = store.get_active_layout()
    active_id = active_layout.id if active_layout else None
    sort_mode = getattr(settings, "profile_sort_order", "Recently Modified")

    if not layouts:
        print("\nNo layouts found in the database.\n")
        return

    if sort_mode == "Recently Modified":
        layouts.sort(key=lambda l: l.updated_at or l.created_at or "", reverse=True)
    elif sort_mode == "Created (Newest)":
        layouts.sort(key=lambda l: l.created_at or "", reverse=True)
    elif sort_mode == "Name (A-Z)":
        layouts.sort(key=lambda l: l.name.lower())

    if search_query.strip():
        q = search_query.strip().lower()
        layouts = [l for l in layouts if q in l.name.lower()]
        if not layouts:
            print(f"\nNo profiles matching '{search_query.strip()}'.\n")
            return

    # One query; excludes the bezels (same count the GUI shows).
    zone_counts = store.zones.count_by_layout()

    header_filter = (
        f" | Filter: '{search_query.strip()}'" if search_query.strip() else ""
    )
    print(f"\n--- Available Profiles (Sort: {sort_mode}{header_filter}) ---")
    for l in layouts:
        active_flag = " [* ACTIVE]" if l.id == active_id else ""
        img_flag = f" (Img: {Path(l.image_path).name})" if l.image_path else ""
        mod_ts = (l.updated_at or l.created_at or "")[:16].replace("T", " ")
        mod_flag = f" [Modified: {mod_ts}]" if mod_ts else ""
        print(
            f"  [{l.id}] {l.name} - {l.width}x{l.height} @ {l.dpi} DPI "
            f"[{zone_counts.get(l.id, 0)} zones]{img_flag}{mod_flag}{active_flag}"
        )
    print()


def create_new_profile(
    name: str,
    width: Optional[int] = None,
    height: Optional[int] = None,
    dpi: Optional[int] = None,
) -> Optional[int]:
    """Creates a new blank layout (defaulting to AppSettings canvas dimensions) and activates it."""
    clean_name = name.strip()
    if not clean_name:
        print("Error: Profile name cannot be empty.")
        return None

    if store.layouts.name_exists(clean_name):
        print(f"Error: A layout named '{clean_name}' already exists.")
        return None

    s = store.settings.get()
    w = int(width) if width is not None else s.json_dev_width
    h = int(height) if height is not None else s.json_dev_height
    d = int(dpi) if dpi is not None else s.json_dev_dpi

    try:
        new_layout = store.layouts.create(name=clean_name, width=w, height=h, dpi=d)
        store.settings.update(active_layout_id=new_layout.id)
        print(
            f"Created and activated new profile '{new_layout.name}' "
            f"(ID: {new_layout.id}, {w}x{h} @ {d} DPI)."
        )
        return new_layout.id
    except DuplicateNameError:
        print(f"Error: A layout named '{clean_name}' already exists.")
        return None
    except Exception as exc:
        print(f"Failed to create profile: {exc}")
        return None


def list_layout_zones(layout_id: int) -> None:
    """Displays all configured pipelines/zones for a specific layout."""
    layout = store.layouts.get(layout_id)
    if not layout:
        print(f"Error: Layout ID {layout_id} not found.")
        return

    zones = store.zones.list_for_layout(layout_id)
    if not zones:
        print(
            f"\nNo pipelines/zones configured for layout '{layout.name}' (ID: {layout_id}).\n"
        )
        return

    print(f"\n--- Zones / Pipelines for Layout '{layout.name}' (ID: {layout_id}) ---")

    for z in zones:
        coords = "N/A"
        extra = ""
        if z.zone_type == CIRCLE:
            coords = f"Center=({z.cx}, {z.cy}), R={z.r}"
        elif z.zone_type == RECTANGLE:
            coords = f"Rect=({z.x1}, {z.y1}) -> ({z.x2}, {z.y2})"
        elif z.zone_type == BEZEL:
            z.set_parsed_config_from_json()
            _, _, dp_thick, _ = z.CONFIG_HELPER.get_region_config()
            coords = f"Rect=({z.x1}, {z.y1}) -> ({z.x2}, {z.y2}) [{dp_thick} dp]"

        if z.zone_type != BEZEL:
            z.set_parsed_config_from_json()
            _, _, sx, sy, dz, hys = z.CONFIG_HELPER.get_transform_config()
            ign = "Yes" if z.ignore_app_settings else "No"
            extra = (
                f" | IgnApp: {ign} | Sens: ({sx:.2f}, {sy:.2f}) "
                f"| DZ: {dz:.2f} | Hys: {hys:.1f}°"
            )

        cam_flag = " [MoveCam/TrackFire]" if z.pointer else ""
        print(
            f"  [{z.id}] {z.name or 'Unnamed'} | Key: {z.scancode} | "
            f"Type: {z.zone_type} | Prio: {z.priority} | {coords}{extra}{cam_flag}"
        )

    print()


def set_bezel_thickness(
    layout_id: int, top_dp: Optional[float] = None, bottom_dp: Optional[float] = None
) -> bool:
    """Updates top and/or bottom bezel thickness (in dp) for a layout."""
    layout = store.layouts.get(layout_id)
    if not layout:
        print(f"Error: Layout ID {layout_id} not found.")
        return False

    zones = store.zones.list_for_layout(layout_id, auto_heal=True)
    for z in zones:
        if z.zone_type == BEZEL and z.scancode == TOP_BEZEL_ID and top_dp is not None:
            clamped_top = int(clamp(top_dp, MIN_BEZEL_DP, MAX_BEZEL_DP))
            store.zones.update_bezel(layout, z, True, clamped_top)
        elif (
            z.zone_type == BEZEL
            and z.scancode == BOTTOM_BEZEL_ID
            and bottom_dp is not None
        ):
            clamped_bot = int(clamp(bottom_dp, MIN_BEZEL_DP, MAX_BEZEL_DP))
            store.zones.update_bezel(layout, z, False, clamped_bot)

    print(f"Bezels updated for layout '{layout.name}' (ID: {layout_id}).")
    return True


def list_supported_keys() -> None:
    print("--- Supported keys ---")
    print(format_supported_keys([SCANCODES, SPECIAL_MAP]))


def format_supported_keys(input_dict_list: list[dict[str, Any]]):
    output = ""

    MIN_LEN = 60
    KEY_WIDTH = 20
    line = ""
    line_len = 0

    for input_dict in input_dict_list:
        for key in input_dict.keys():
            key_len = len(key)

            if line_len > MIN_LEN:
                output += line + "\n"
                line = ""
                line_len = 0

            suffix_len = min(0, KEY_WIDTH - key_len - 2)
            line += f"'{key}'" + " " * suffix_len
            line_len += key_len + suffix_len + 2

    return output


def show_directional_keys(layout_id: int) -> None:
    layout = store.layouts.get(layout_id)
    if not layout:
        print(f"Error: Layout ID {layout_id} not found.")

    directional_scancodes = store.zones.get_mouse_wheel_directional_scancodes(layout)
    norm_keys = [
        (get_key_from_scancode(_d_s) or "").upper() for _d_s in directional_scancodes
    ]
    print(
        f"\n--- Directional Keys: {str(norm_keys).replace("[", "").replace("]", "").replace("'", "")} ---"
    )


def set_directional_key(layout_id: int, direction: str | None) -> bool:
    """`direction_rev_map` {'up': 0, 'left': 1, 'down': 2, 'right': 3}"""
    layout = store.layouts.get(layout_id)
    if not layout:
        print(f"Error: Layout ID {layout_id} not found.")
        return False

    if not direction:
        print(f"Error: Direction not specified.")
        return False

    mouse_wheel_zone = store.zones.get_mouse_wheel_zone(layout)
    if mouse_wheel_zone is None:
        print("Error: Layout has no Mouse Wheel")
        return False

    key = input(
        f"Enter key for '{direction}' e.g. 'w' or 'u' or '2' (alphanumeric single characters),\nfor arrow keys use 'up', 'left', 'down' or 'right'\nor use --list-supported-keys to view the supported keys: "
    )
    key_scancode = get_scancode_from_key(key)

    if key_scancode is None:
        print(
            f"Error: Key '{key}' is not supported, use --list-supported-keys to view the supported keys."
        )
        return False

    direction_rev_map = {"up": 0, "left": 1, "down": 2, "right": 3}
    direction_id = direction_rev_map.get(direction)

    if direction_id is None:
        print(f"Error: {direction.capitalize()} direction is invalid.")
        return False

    store.zones.set_mouse_wheel_directional_scancodes(
        layout, direction_id, key_scancode
    )
    print(
        f"'{direction.capitalize()}' directional scancode successfully updated to '{key_scancode}' (Key: '{key}') for layout '{layout.name}' (ID: {layout_id})."
    )

    return True


def edit_single_zone(
    zone_id: int,
    priority: Optional[int] = None,
    ignore_app_settings: Optional[bool] = None,
    pointer: Optional[bool] = None,
    sens_x: Optional[float] = None,
    sens_y: Optional[float] = None,
    deadzone: Optional[float] = None,
    hysteresis: Optional[float] = None,
) -> bool:
    """Updates a single non-bezel zone's pipeline and inspector properties."""
    zone = store.zones.get(zone_id)
    if not zone or zone.zone_type == BEZEL:
        print(f"Error: Non-bezel Zone ID {zone_id} not found.")
        return False

    p_cfg = PipelineConfig()
    p_cfg.set_pipeline_config_from_json(zone.pipeline_json)

    r_idx, _, b_dp, cur_prio = p_cfg.get_region_config()
    new_prio = (
        int(clamp(priority, MIN_PRIORITY, MAX_PRIORITY))
        if priority is not None
        else cur_prio
    )
    p_cfg.set_region_config(r_idx, b_dp, new_prio)

    s_idx, _, cur_ptr = p_cfg.get_semantic_config()
    if pointer is not None and zone.scancode not in (
        MOUSE_WHEEL_SIMULATOR_CODE,
        SPRINT_DISTANCE_CODE,
    ):
        cur_ptr = pointer
    p_cfg.set_semantic_config(s_idx, cur_ptr)

    t_idx, _, cur_sx, cur_sy, cur_dz, cur_hys = p_cfg.get_transform_config()
    is_wheel = zone.scancode == MOUSE_WHEEL_SIMULATOR_CODE
    if cur_ptr or is_wheel:
        if sens_x is not None:
            cur_sx = clamp(sens_x, SENSITIVITY_MIN, SENSITIVITY_MAX)
        if sens_y is not None:
            cur_sy = clamp(sens_y, SENSITIVITY_MIN, SENSITIVITY_MAX)
    if is_wheel:
        if deadzone is not None:
            cur_dz = clamp(deadzone, DEADZONE_MIN, DEADZONE_MAX)
        if hysteresis is not None:
            cur_hys = clamp(hysteresis, HYSTERESIS_MIN, HYSTERESIS_MAX)
    p_cfg.set_transform_config(t_idx, cur_sx, cur_sy, cur_dz, cur_hys)

    ign = (
        zone.ignore_app_settings if ignore_app_settings is None else ignore_app_settings
    )
    store.zones.update(
        zone_id,
        ignore_app_settings=ign,
        pipeline_json=p_cfg.get_pipeline_json_from_config(),
    )
    print(f"Zone ID {zone_id} ('{zone.name or 'Unnamed'}') updated successfully.")
    return True


def reset_single_zone_to_app_settings(zone_id: int) -> bool:
    """Resets a single non-bezel zone's transform parameters to global AppSettings."""
    zone = store.zones.get(zone_id)
    if not zone or zone.zone_type == BEZEL:
        print(f"Error: Non-bezel Zone ID {zone_id} not found.")
        return False

    s = store.settings.get()
    p_cfg = PipelineConfig()
    p_cfg.set_pipeline_config_from_json(zone.pipeline_json)
    t_idx, _, _, _, _, _ = p_cfg.get_transform_config()
    p_cfg.set_transform_config(
        t_idx,
        s.sensitivity_x,
        s.sensitivity_y,
        s.deadzone,
        s.hysteresis,
    )
    store.zones.update(
        zone_id,
        ignore_app_settings=False,
        pipeline_json=p_cfg.get_pipeline_json_from_config(),
    )
    print(f"Zone ID {zone_id} ('{zone.name or 'Unnamed'}') reset to AppSettings.")
    return True


def delete_single_zone(zone_id: int) -> bool:
    """Deletes a single non-bezel zone by its ID."""
    zone = store.zones.get(zone_id)
    if not zone or zone.zone_type == BEZEL:
        print(f"Error: Non-bezel Zone ID {zone_id} not found.")
        return False

    store.zones.delete(zone_id, delete_bezel=False)
    print(f"Zone ID {zone_id} ('{zone.name or 'Unnamed'}') deleted.")
    return True


def set_active_profile(layout_id: int) -> bool:
    """Sets a profile as active in app_settings."""
    target = store.layouts.get(layout_id)
    if not target:
        print(f"Error: Layout ID {layout_id} does not exist.")
        return False

    store.settings.update(active_layout_id=layout_id)
    print(f"Active profile updated to: '{target.name}' (ID: {target.id})")
    return True


def duplicate_profile(layout_id: int, new_name: str) -> Optional[int]:
    """Duplicates an existing layout along with all its touch zones."""
    source = store.layouts.get(layout_id)
    if not source:
        print(f"Error: Source layout ID {layout_id} not found.")
        return None

    clean_name = new_name.strip()
    if not clean_name:
        print("Error: Target name cannot be empty.")
        return None

    if store.layouts.name_exists(clean_name):
        print(f"Error: A layout named '{clean_name}' already exists.")
        return None

    try:
        new_layout = store.layouts.duplicate(layout_id, clean_name)
        print(
            f"Duplicated '{source.name}' -> '{new_layout.name}' (ID: {new_layout.id})."
        )
        return new_layout.id
    except Exception as exc:
        print(f"Failed to duplicate profile: {exc}")
        return None


def rename_profile(layout_id: int, new_name: str) -> bool:
    """Renames an existing layout row."""
    target = store.layouts.get(layout_id)
    if not target:
        print(f"Error: Layout ID {layout_id} not found.")
        return False

    clean_name = new_name.strip()
    if not clean_name:
        print("Error: New name cannot be empty.")
        return False

    # Match Layout Studio: the current profile's own name is not a conflict.
    if clean_name == target.name:
        print(f"Profile '{target.name}' is already named that; no changes made.")
        return True

    if store.layouts.name_exists(clean_name, exclude_id=layout_id):
        print(f"Error: A layout named '{clean_name}' already exists.")
        return False

    try:
        store.layouts.update(layout_id, name=clean_name)
        print(f"Profile {layout_id} successfully renamed to '{clean_name}'.")
        return True
    except Exception as exc:
        print(f"Failed to rename profile: {exc}")
        return False


def delete_profile(layout_id: int) -> bool:
    """Deletes a profile and clears active references if necessary."""
    target = store.layouts.get(layout_id)
    if not target or not store.layouts.delete_profile(layout_id):
        print(f"Error: Layout ID {layout_id} does not exist.")
        return False

    print(f"Layout '{target.name}' (ID: {layout_id}) and all mapped zones deleted.")
    return True


def clear_zones(layout_id: int) -> bool:
    """Removes all touch zones from a profile while keeping the layout entry and its bezels."""
    target = store.layouts.get(layout_id)
    if not target:
        print(f"Error: Layout ID {layout_id} not found.")
        return False

    # Delete only non-bezel zones so custom bezel thickness survives.
    store.zones.clear_non_bezel_zones(layout_id)

    print(
        f"All touch zones cleared (bezels kept) for layout '{target.name}' (ID: {layout_id})."
    )
    return True


def wipe_database() -> None:
    """Atomically deletes all layouts, zones, and resets app_settings to factory defaults."""
    store.settings.wipe_database()
    print("Database wiped and reset to factory defaults.")


# ---------------------------------------------------------------------------
# Typematic Inspection & Configuration
# ---------------------------------------------------------------------------


def show_typematic() -> None:
    """Prints current typematic / auto-repeat configuration."""
    s = store.settings.get()
    print("\n--- Typematic (Key Repeat) Settings ---")
    print(f"  Enabled:       {'Yes' if s.typematic_enabled else 'No'}")
    print(f"  Initial Delay: {s.typematic_delay_ms:.1f} ms")
    print(f"  Repeat Rate:   {s.typematic_rate_hz:.1f} Hz (events/sec)")
    print(f"  Excluded Keys: {s.typematic_excluded_keys or 'None'}")


def configure_typematic_interactive() -> None:
    """Prompts for typematic fields interactively."""
    s = store.settings.get()
    show_typematic()

    en_in = (
        input(
            f"Enable typematic? (y/n, current: {'y' if s.typematic_enabled else 'n'}): "
        )
        .strip()
        .lower()
    )
    enabled = s.typematic_enabled if not en_in else (en_in == "y")

    delay = clamp(
        _prompt_float(
            f"Initial repeat delay ms {TYPEMATIC_DELAY_MIN_MS:.0f}-{TYPEMATIC_DELAY_MAX_MS:.0f} "
            f"(current: {s.typematic_delay_ms:.1f}): ",
            s.typematic_delay_ms,
        ),
        TYPEMATIC_DELAY_MIN_MS,
        TYPEMATIC_DELAY_MAX_MS,
    )
    rate = clamp(
        _prompt_float(
            f"Repeat rate Hz {TYPEMATIC_RATE_MIN_HZ:.0f}-{TYPEMATIC_RATE_MAX_HZ:.0f} "
            f"(current: {s.typematic_rate_hz:.1f}): ",
            s.typematic_rate_hz,
        ),
        TYPEMATIC_RATE_MIN_HZ,
        TYPEMATIC_RATE_MAX_HZ,
    )

    ex_in = input(
        f"Excluded keys comma-separated (supports +wasd, +arrows, or 'clear'; current: {s.typematic_excluded_keys or ''}): "
    ).strip()
    excludes = (
        s.typematic_excluded_keys
        if not ex_in
        else _normalize_excluded_keys(ex_in, s.typematic_excluded_keys)
    )

    store.settings.update(
        typematic_enabled=enabled,
        typematic_delay_ms=delay,
        typematic_rate_hz=rate,
        typematic_excluded_keys=excludes,
    )
    print("Typematic settings updated successfully.")
    show_typematic()


def reset_typematic_defaults() -> None:
    """Resets only typematic timing and exclusion keys to factory defaults."""
    store.settings.update(
        typematic_enabled=True,
        typematic_delay_ms=250.0,
        typematic_rate_hz=30.0,
        typematic_excluded_keys=EXCLUDED_KEYS,
    )
    print("Typematic settings reset to factory defaults.")
    show_typematic()


# ---------------------------------------------------------------------------
# System Inspection & Configuration
# ---------------------------------------------------------------------------


def show_system() -> None:
    """Prints current two finger tap and bezel toggle fields configuration."""
    s = store.settings.get()
    print("\n--- System Settings ---")
    print(f"  Two finger tap Enabled:  {'Yes' if s.two_finger_tap_enabled else 'No'}")
    print(f"  Bezels Enabled:      {'Yes' if s.bezel_toggle_enabled else 'No'}")


def configure_system_interactive() -> None:
    """Prompts for two finger tap and bezel toggle fields interactively."""
    s = store.settings.get()
    show_system()

    en_two_finger_tap_in = (
        input(
            f"Enable two finger tap toggle? (y/n, current: {'y' if s.two_finger_tap_enabled else 'n'}): "
        )
        .strip()
        .lower()
    )
    two_finger_tap_enabled = (
        s.two_finger_tap_enabled
        if not en_two_finger_tap_in
        else (en_two_finger_tap_in == "y")
    )

    en_bezel_in = (
        input(
            f"Enable bezel toggle? (y/n, current: {'y' if s.bezel_toggle_enabled else 'n'}): "
        )
        .strip()
        .lower()
    )
    bezel_toggle_enabled = (
        s.bezel_toggle_enabled if not en_bezel_in else (en_bezel_in == "y")
    )

    store.settings.update(
        two_finger_tap_enabled=two_finger_tap_enabled,
        bezel_toggle_enabled=bezel_toggle_enabled,
    )
    print("Two finger tap and Bezel Toggle settings updated successfully.")
    show_system()


def reset_system_defaults() -> None:
    """Resets only two finger tap and bezel toggle settings to factory defaults."""
    store.settings.update(two_finger_tap_enabled=True, bezel_toggle_enabled=True)
    print("Two finger tap and Bezel Toggle settings reset to factory defaults.")
    show_system()


# ---------------------------------------------------------------------------
# Import & Export Pipelines
# ---------------------------------------------------------------------------


def import_profile_json(file_path: Path) -> Optional[int]:
    """Imports a JSON layout mapping file into SQLite and activates it."""
    if not file_path.exists():
        print(f"Error: File '{file_path}' not found.")
        return None

    layout_id = migrate_json_layout(
        json_path=file_path,
        image_path="",
        set_active=True,
    )
    if layout_id:
        print(
            f"Imported '{file_path.name}' successfully as Active Layout (ID: {layout_id})."
        )
    else:
        print(f"Failed to import '{file_path.name}'.")
    return layout_id


def export_profile_json(
    layout_id: int, output_path: Path | None = None
) -> Optional[Path]:
    """Exports a specific layout ID to a standard JSON layout file."""
    try:
        out_file = export_layout_json(layout_id, output_path)
        print(f"Layout exported successfully to: {out_file}")
        return out_file
    except Exception as exc:
        print(f"Export failed: {exc}")
        return None


def export_profile_toml(
    layout_id: Optional[int] = None, output_path: Path | None = None
) -> Optional[Path]:
    """Exports app_settings to TOML; if layout_id is given, also exports & links its JSON like Layout Studio."""
    try:
        if layout_id is not None:
            layout = store.layouts.get(layout_id)
            if not layout:
                print(f"Error: Layout ID {layout_id} not found.")
                return None
            JSONS_FOLDER.mkdir(parents=True, exist_ok=True)
            json_path = JSONS_FOLDER / f"{safe_filename(layout.name)}.json"
            export_layout_json(layout_id, json_path)
            target_out = output_path or (
                PROFILES_FOLDER / f"{safe_filename(layout.name)}.toml"
            )
            out_file = export_settings_toml(
                target_out, linked_json_path=json_path, layout=layout
            )
        else:
            out_file = export_settings_toml(output_path or TOML_PATH)

        print(f"Settings exported successfully to: {out_file}")
        return out_file
    except Exception as exc:
        print(f"TOML export failed: {exc}")
        return None


# ---------------------------------------------------------------------------
# Interactive Terminal Menu
# ---------------------------------------------------------------------------


def interactive_menu() -> None:
    """Terminal CLI UI loop."""
    search_filter = ""

    while True:
        list_profiles(search_filter)
        print("\nCommands:")
        print("  [s]    Select / Switch Active Profile")
        print("  [n]    Create New Blank Profile")
        print("  [so]   Set Profile Sort Order")
        print("  [fl]   Filter Profiles by Name")
        print("  [si]   Set Profile Background Image")
        print("  [lk]   List Supported Keys")
        print("  [ik]   View / Configure Directional Keys")
        print(
            "  [ic]   View / Configure Handedness, Touch, Input Controls & Global Keybindings"
        )
        print("  [ric]  Reset Input Controls to Defaults")
        print("  [ck]   Capture Global Keybindings (Toggle & Sprint)")
        print("  [pf]   Configure ADB Rate Cap & PPS Alert Threshold")
        print("  [lz]   List Zones / Pipelines for Profile")
        print("  [bz]   Configure Bezel Thickness (Top / Bottom dp)")
        print(
            "  [ez]   Edit Single Zone Pipeline (Priority / Sens / Deadzone / Pointer)"
        )
        print("  [rz1]  Reset Single Zone to AppSettings")
        print("  [dz]   Delete Single Zone by ID")
        print("  [cp]   Duplicate Profile")
        print("  [rn]   Rename Profile")
        print("  [cz]   Clear Zones for Profile")
        print("  [rz]   Reset All Zones in Layout to App Settings")
        print("  [d]    Delete Profile")
        print("  [ty]   View / Configure Typematic (Auto-Repeat) Settings")
        print("  [rty]  Reset Typematic Settings to Defaults")
        print("  [ss]   View / Configure two finger tap and Bezel Toggle Settings")
        print("  [rss]  Reset two finger tap and Bezel Toggle Settings to Defaults")
        print("  [i]    Import Layout from JSON")
        print("  [e]    Export Profile to JSON")
        print("  [st]   Export App Settings to TOML (Standalone or Linked to Profile)")
        print("  [lt]   Import App Settings from settings.toml")
        print("  [eb]   Export Full Bundle to data/profiles/")
        print("  [ib]   Import Any Config (.toml, .json, or Bundle Directory)")
        print("  [r]    Reset All App Settings to Defaults")
        print("  [w]    Wipe Database (Factory Reset)")
        print("  [q]    Quit")

        choice = input("\nEnter command: ").strip().lower()

        if choice == "q":
            break

        if choice == "s":
            raw_id = input(
                "Enter Layout ID to activate (Leave blank for active): "
            ).strip()
            target_id = get_target_id(raw_id)

            if target_id is not None:
                set_active_profile(target_id)

        if choice == "n":
            name = input("Enter new profile name: ").strip()

            if name:
                s = store.settings.get()
                w = _prompt_int(
                    f"Canvas width (blank for {s.json_dev_width}): ", s.json_dev_width
                )
                h = _prompt_int(
                    f"Canvas height (blank for {s.json_dev_height}): ",
                    s.json_dev_height,
                )
                d = _prompt_int(
                    f"Canvas DPI (blank for {s.json_dev_dpi}): ", s.json_dev_dpi
                )
                create_new_profile(name, w, h, d)

        if choice == "so":
            print("Available sort orders:")

            for idx, mode in enumerate(VALID_SORT_ORDERS, start=1):
                print(f"  [{idx}] {mode}")
            sel = input("Select sort order (1-3 or name): ").strip()

            if sel in ("1", "2", "3"):
                set_profile_sort_order(VALID_SORT_ORDERS[int(sel) - 1])

            elif sel:
                set_profile_sort_order(sel)

        if choice == "fl":
            search_filter = input(
                "Enter search filter (leave blank to show all): "
            ).strip()

        if choice == "si":
            raw_id = input("Enter Layout ID (Leave blank for active): ").strip()
            img_path = (
                input(f"Enter image filename or path [Search dir: {IMAGES_FOLDER}]: ")
                .strip()
                .strip('"')
            )
            target_id = get_target_id(raw_id)

            if target_id is not None:
                if raw_id.isdigit() and img_path:
                    set_profile_image(target_id, img_path)

        if choice == "lk":
            list_supported_keys()

        if choice == "ik":
            raw_id = input("Enter Layout ID (Leave blank for active): ").strip()
            target_id = get_target_id(raw_id)

            if target_id is not None:
                configure_directional_keys(target_id)

        if choice == "ic":
            configure_input_controls_interactive()

        if choice == "ric":
            confirm = (
                input("Reset input controls to factory defaults? (y/N): ")
                .strip()
                .lower()
            )

            if confirm == "y":
                reset_input_controls_defaults()

        if choice == "ck":
            capture_keys_cli()

        if choice == "pf":
            capture_performance_settings_cli()

        if choice == "lz":
            raw_id = input(
                "Enter Layout ID to view zones (Leave blank for active): "
            ).strip()
            target_id = get_target_id(raw_id)

            if target_id is not None:
                list_layout_zones(target_id)

        if choice == "bz":
            raw_id = input("Enter Layout ID (Leave blank for active): ").strip()
            target_id = get_target_id(raw_id)

            if target_id is not None:
                top_in = input(
                    f"Top bezel dp ({MIN_BEZEL_DP}-{MAX_BEZEL_DP}, blank to keep): "
                ).strip()
                bot_in = input(
                    f"Bottom bezel dp ({MIN_BEZEL_DP}-{MAX_BEZEL_DP}, blank to keep): "
                ).strip()
                top_val = float(top_in) if top_in else None
                bot_val = float(bot_in) if bot_in else None
                set_bezel_thickness(target_id, top_val, bot_val)

            else:
                print("No valid layout selected.")

        if choice == "ez":
            raw_zid = input("Enter Zone ID to edit: ").strip()

            if raw_zid.isdigit():
                zid = int(raw_zid)
                zone = store.zones.get(zid)

                if not zone or zone.zone_type == BEZEL:
                    print(f"Error: Non-bezel Zone ID {zid} not found.")

                else:
                    zone.set_parsed_config_from_json()
                    _, _, sx, sy, dz, hys = zone.CONFIG_HELPER.get_transform_config()
                    prio = _prompt_int(
                        f"Priority ({MIN_PRIORITY}-{MAX_PRIORITY}, current: {zone.priority}): ",
                        zone.priority,
                    )
                    ign_in = (
                        input(
                            f"Ignore global AppSettings? (y/n, current: {'y' if zone.ignore_app_settings else 'n'}): "
                        )
                        .strip()
                        .lower()
                    )
                    ign = (
                        zone.ignore_app_settings
                        if ign_in not in ("y", "n")
                        else (ign_in == "y")
                    )
                    ptr_in = (
                        input(
                            f"Output is Pointer Button? (y/n, current: {'y' if zone.pointer else 'n'}): "
                        )
                        .strip()
                        .lower()
                    )

                    ptr = zone.pointer if ptr_in not in ("y", "n") else (ptr_in == "y")
                    new_sx = _prompt_float(f"Sensitivity X (current: {sx:.2f}): ", sx)
                    new_sy = _prompt_float(f"Sensitivity Y (current: {sy:.2f}): ", sy)
                    new_dz = _prompt_float(f"Deadzone (current: {dz:.2f}): ", dz)
                    new_hys = _prompt_float(f"Hysteresis (current: {hys:.1f}): ", hys)
                    edit_single_zone(
                        zid,
                        priority=prio,
                        ignore_app_settings=ign,
                        pointer=ptr,
                        sens_x=new_sx,
                        sens_y=new_sy,
                        deadzone=new_dz,
                        hysteresis=new_hys,
                    )

        if choice == "rz1":
            raw_zid = input("Enter Zone ID to reset to AppSettings: ").strip()

            if raw_zid.isdigit():
                reset_single_zone_to_app_settings(int(raw_zid))

        if choice == "dz":
            raw_zid = input("Enter Zone ID to delete: ").strip()
            if raw_zid.isdigit():
                delete_single_zone(int(raw_zid))

        if choice == "cp":
            raw_id = input(
                "Enter Layout ID to duplicate (Leave blank for active): "
            ).strip()
            target_id = get_target_id(raw_id)

            if target_id is not None:
                source = store.layouts.get(target_id)
                if source:
                    new_name = input(
                        f"Enter name for copy of '{source.name}': "
                    ).strip()
                    duplicate_profile(target_id, new_name)

        if choice == "rn":
            raw_id = input(
                "Enter Layout ID to rename (Leave blank for active): "
            ).strip()
            target_id = get_target_id(raw_id)

            if target_id is not None:
                target = store.layouts.get(target_id)
                if target:
                    new_name = input(f"Enter new name for '{target.name}': ").strip()
                    rename_profile(target_id, new_name)

        if choice == "cz":
            raw_id = input(
                "Enter Layout ID to clear zones (Leave blank for active): "
            ).strip()
            target_id = get_target_id(raw_id)

            if target_id is not None:
                confirm = (
                    input(f"Clear all zones for Layout ID {target_id}? (y/N): ")
                    .strip()
                    .lower()
                )
                if confirm == "y":
                    clear_zones(target_id)

        if choice == "rz":
            raw_id = input(
                "Enter Layout ID to reset zones (Leave blank for active): "
            ).strip()
            target_id = get_target_id(raw_id)

            if target_id is not None:
                target_layout = store.layouts.get(target_id)
                if target_layout:
                    count = reset_layout_zones_to_app_settings(target_layout.id)
                    print(
                        f"Reset {count} zones in layout '{target_layout.name}' to default AppSettings."
                    )
                else:
                    print("No layout selected or active.")

        if choice == "d":
            raw_id = input(
                "Enter Layout ID to delete (Leave blank for active): "
            ).strip()
            target_id = get_target_id(raw_id)

            if target_id is not None:
                confirm = (
                    input(
                        f"Confirm delete Layout ID {target_id} and its zones? (y/N): "
                    )
                    .strip()
                    .lower()
                )
                if confirm == "y":
                    delete_profile(target_id)

        if choice == "ty":
            configure_typematic_interactive()

        if choice == "rty":
            confirm = (
                input("Reset typematic settings to defaults? (y/N): ").strip().lower()
            )

            if confirm == "y":
                reset_typematic_defaults()

        if choice == "ss":
            configure_system_interactive()

        if choice == "rss":
            confirm = (
                input(
                    "Reset two finger tap and bezel toggle settings to defaults? (y/N): "
                )
                .strip()
                .lower()
            )

            if confirm == "y":
                reset_system_defaults()

        if choice == "i":
            raw_path = (
                input(f"Enter path to JSON file [Default: {JSONS_FOLDER}]: ")
                .strip()
                .strip('"')
            )

            if raw_path:
                import_profile_json(Path(raw_path))

        if choice == "e":
            raw_id = input(
                "Enter Layout ID to export (Leave blank for active): "
            ).strip()
            target_id = get_target_id(raw_id)

            if target_id is not None:
                export_profile_json(target_id)

        if choice == "st":
            raw_id = input(
                "Enter Layout ID to link with TOML (Leave blank for standalone settings.toml): "
            ).strip()
            linked_id = int(raw_id) if raw_id.isdigit() else None
            export_profile_toml(layout_id=linked_id)

        if choice == "lt":

            if migrate_toml_config():
                print("Settings imported successfully from settings.toml.")

            else:
                print("Failed to import settings.toml (file missing or invalid).")

        if choice == "eb":
            raw_id = input(
                "Enter Layout ID to bundle (Leave blank for active): "
            ).strip()
            target_id = get_target_id(raw_id)

            try:
                target_layout = store.layouts.get(target_id)
                if target_layout:
                    t_path, j_path = export_bundle(
                        profile_name=target_layout.name, layout_id=target_layout.id
                    )
                    print(f"Bundle exported:\n  - TOML: {t_path}\n  - JSON: {j_path}")
                else:
                    print("No active layout available to bundle.")

            except Exception as exc:
                print(f"Export bundle failed: {exc}")

        if choice == "ib":
            raw_path = (
                input(
                    f"Enter path to file or bundle folder [Default: {PROFILES_FOLDER}]: "
                )
                .strip()
                .strip('"')
            )

            if raw_path and import_any(Path(raw_path)):
                print("Configuration imported and synced to SQLite.")

            else:
                print(
                    "Import failed. Check that file/folder exists and syntax is valid."
                )

        if choice == "r":
            confirm = (
                input("Reset all app settings to defaults? (y/N): ").strip().lower()
            )

            if confirm == "y":
                store.settings.reset_to_defaults()
                print("Application settings reset to defaults.")

        if choice == "w":
            confirm = (
                input("WARNING: Wipe ALL layouts, zones, and reset settings? (y/N): ")
                .strip()
                .lower()
            )

            if confirm == "y":
                wipe_database()

        print("-" * 40)


# ---------------------------------------------------------------------------
# CLI Argument Entry Point
# ---------------------------------------------------------------------------


def run() -> None:
    parser = argparse.ArgumentParser(description="CLI Layout & Profile Manager")
    parser.add_argument(
        "-k",
        "--list-supported-keys",
        action="store_true",
        help="List all supported keys",
    )
    parser.add_argument(
        "-l", "--list", action="store_true", help="List all saved profiles"
    )
    parser.add_argument(
        "--filter",
        type=str,
        default="",
        metavar="QUERY",
        help="Filter listed profiles by name substring",
    )
    parser.add_argument(
        "--sort",
        type=str,
        choices=VALID_SORT_ORDERS,
        help="Set and persist profile sort order",
    )
    parser.add_argument(
        "--new",
        type=str,
        metavar="NAME",
        help="Create and activate a new blank profile",
    )
    parser.add_argument(
        "--dims",
        type=int,
        nargs=3,
        metavar=("WIDTH", "HEIGHT", "DPI"),
        help="Optional canvas dimensions (WIDTH HEIGHT DPI) when using --new",
    )
    parser.add_argument(
        "-s", "--set-active", type=int, metavar="ID", help="Set active layout by ID"
    )
    parser.add_argument(
        "--set-image",
        nargs=2,
        metavar=("LAYOUT_ID", "IMAGE_PATH"),
        help="Set background image path for a specific layout by its ID",
    )

    # Input Controls & Global Keybindings CLI flags
    parser.add_argument(
        "--show-input",
        action="store_true",
        help="Display touch, joystick, sensitivity, deadzone, hysteresis, and keybinding settings",
    )
    parser.add_argument(
        "--set-left-handed",
        choices=["on", "off"],
        help="Enable or disable left-handed mode",
    )
    parser.add_argument(
        "--set-floating-joystick",
        choices=["on", "off"],
        help="Enable or disable floating joystick",
    )
    parser.add_argument(
        "--set-anchored-joystick",
        choices=["on", "off"],
        help="Enable or disable anchored joystick",
    )
    parser.add_argument(
        "--sensitivity-x",
        type=float,
        metavar="VAL",
        help="Set global X sensitivity",
    )
    parser.add_argument(
        "--sensitivity-y",
        type=float,
        metavar="VAL",
        help="Set global Y sensitivity",
    )
    parser.add_argument(
        "--deadzone",
        type=float,
        metavar="VAL",
        help="Set global joystick deadzone",
    )
    parser.add_argument(
        "--hysteresis",
        type=float,
        metavar="DEG",
        help="Set global directional hysteresis in degrees",
    )
    parser.add_argument(
        "--reset-input",
        action="store_true",
        help="Reset touch and input controls to factory defaults",
    )

    # Zone & Bezel CLI flags
    parser.add_argument(
        "--list-zones",
        type=int,
        metavar="ID",
        help="List all zones/pipelines for layout by ID",
    )
    parser.add_argument(
        "--set-bezels",
        type=float,
        nargs=3,
        metavar=("LAYOUT_ID", "TOP_DP", "BOTTOM_DP"),
        help="Set top and bottom bezel thickness in dp for a layout",
    )
    parser.add_argument(
        "--show-directional-keys",
        type=int,
        metavar="ID",
        help="Display directional keys for a layout",
    )
    parser.add_argument(
        "--edit-layout-directionals",
        type=int,
        metavar="LAYOUT_ID",
        help="Edit a layout's directionals by ID (combine with the --set-key flag)",
    )
    parser.add_argument(
        "--set-key",
        choices=["up", "left", "down", "right"],
        help="Set the specified directional key for --edit-layout-directionals",
    )
    parser.add_argument(
        "--edit-zone",
        type=int,
        metavar="ZONE_ID",
        help="Edit a single non-bezel zone by ID (combine with --zone-* flags)",
    )
    parser.add_argument(
        "--zone-priority",
        type=int,
        metavar="PRIO",
        help="Zone priority value for --edit-zone",
    )
    parser.add_argument(
        "--zone-ignore-app-settings",
        choices=["on", "off"],
        help="Toggle ignore_app_settings for --edit-zone",
    )
    parser.add_argument(
        "--zone-pointer",
        choices=["on", "off"],
        help="Toggle pointer button semantics for --edit-zone",
    )
    parser.add_argument(
        "--zone-sens-x",
        type=float,
        metavar="VAL",
        help="Zone X sensitivity for --edit-zone",
    )
    parser.add_argument(
        "--zone-sens-y",
        type=float,
        metavar="VAL",
        help="Zone Y sensitivity for --edit-zone",
    )
    parser.add_argument(
        "--zone-deadzone",
        type=float,
        metavar="VAL",
        help="Zone deadzone for --edit-zone",
    )
    parser.add_argument(
        "--zone-hysteresis",
        type=float,
        metavar="DEG",
        help="Zone hysteresis for --edit-zone",
    )
    parser.add_argument(
        "--reset-zone",
        type=int,
        metavar="ZONE_ID",
        help="Reset a single zone by ID to global AppSettings",
    )
    parser.add_argument(
        "--delete-zone",
        type=int,
        metavar="ZONE_ID",
        help="Delete a single non-bezel zone by ID",
    )
    parser.add_argument(
        "--duplicate",
        nargs=2,
        metavar=("ID", "NAME"),
        help="Duplicate layout by ID to a new name",
    )
    parser.add_argument(
        "--rename", nargs=2, metavar=("ID", "NAME"), help="Rename layout by ID"
    )
    parser.add_argument(
        "--delete", type=int, metavar="ID", help="Delete layout and zones by ID"
    )
    parser.add_argument(
        "--clear-zones",
        type=int,
        metavar="ID",
        help="Clear all touch zones for layout by ID",
    )
    parser.add_argument(
        "--reset-zones",
        type=int,
        nargs="?",
        const=-1,
        metavar="ID",
        help="Reset layout zones to AppSettings",
    )

    # Typematic CLI flags
    parser.add_argument(
        "--show-typematic",
        action="store_true",
        help="Display typematic / repeat settings",
    )
    parser.add_argument(
        "--set-typematic",
        choices=["on", "off"],
        help="Enable or disable typematic auto-repeat",
    )
    parser.add_argument(
        "--typematic-delay",
        type=float,
        metavar="MS",
        help="Set typematic initial repeat delay in milliseconds",
    )
    parser.add_argument(
        "--typematic-rate",
        type=float,
        metavar="HZ",
        help="Set typematic repeat rate in Hz (events/sec)",
    )
    parser.add_argument(
        "--typematic-excludes",
        type=str,
        metavar="KEYS",
        help="Set comma-separated excluded keys (supports '+wasd', '+arrows', or 'clear')",
    )
    parser.add_argument(
        "--reset-typematic",
        action="store_true",
        help="Reset only typematic/auto-repeat settings to factory defaults",
    )

    # System Settings CLI flags
    parser.add_argument(
        "--show-system",
        action="store_true",
        help="Display system settings (two finger tap and bezel toggles)",
    )
    parser.add_argument(
        "--set-two-finger-tap",
        choices=["on", "off"],
        help="Enable or disable the two finger tap menu gesture",
    )
    parser.add_argument(
        "--set-bezel-toggle",
        choices=["on", "off"],
        help="Enable or disable bezel touch toggles",
    )
    parser.add_argument(
        "--reset-system",
        action="store_true",
        help="Reset system settings to factory defaults",
    )

    # Import / Export & Reset flags
    parser.add_argument(
        "-i",
        "--import-json",
        type=Path,
        metavar="PATH",
        help="Import a layout from JSON",
    )
    parser.add_argument(
        "-e",
        "--export-json",
        type=int,
        metavar="ID",
        help="Export a layout to JSON by ID",
    )
    parser.add_argument(
        "-o",
        "--output",
        type=Path,
        metavar="OUT_PATH",
        help="Custom output path for JSON or TOML export",
    )
    parser.add_argument(
        "--export-toml",
        type=Path,
        nargs="?",
        const=TOML_PATH,
        metavar="OUT_PATH",
        help="Export app_settings to TOML",
    )
    parser.add_argument(
        "--export-toml-layout",
        type=int,
        metavar="LAYOUT_ID",
        help="Export app_settings to TOML linked to a specific layout ID",
    )
    parser.add_argument(
        "--import-toml",
        type=Path,
        nargs="?",
        const=TOML_PATH,
        metavar="IN_PATH",
        help="Import app_settings from TOML",
    )
    parser.add_argument(
        "--export-bundle",
        type=Path,
        nargs="?",
        const=PROFILES_FOLDER,
        metavar="OUT_DIR",
        help="Export profile bundle (.toml + .json) into target directory",
    )
    parser.add_argument(
        "--bundle-layout-id",
        type=int,
        metavar="LAYOUT_ID",
        help="Optional layout ID to bundle when using --export-bundle",
    )
    parser.add_argument(
        "--import-bundle",
        type=Path,
        metavar="PATH",
        help="Import profile bundle via settings.toml or folder",
    )
    parser.add_argument(
        "--import-any",
        type=Path,
        metavar="PATH",
        help="Import any config file (.json, .toml, or directory)",
    )
    parser.add_argument(
        "--reset-settings",
        action="store_true",
        help="Reset all app settings to defaults",
    )
    parser.add_argument(
        "--wipe-database",
        action="store_true",
        help="Delete all layouts/zones and reset settings to factory defaults",
    )

    args = parser.parse_args()
    has_args = False

    try:
        input_updates = {}

        if args.set_left_handed is not None:
            has_args = True
            input_updates["left_handed"] = args.set_left_handed == "on"

        if args.set_floating_joystick is not None:
            has_args = True
            input_updates["floating_joystick"] = args.set_floating_joystick == "on"

        if args.set_anchored_joystick is not None:
            has_args = True
            input_updates["anchored_joystick"] = args.set_anchored_joystick == "on"

        if args.sensitivity_x is not None:
            has_args = True
            input_updates["sensitivity_x"] = clamp(
                args.sensitivity_x, SENSITIVITY_MIN, SENSITIVITY_MAX
            )
            has_args = True

        if args.sensitivity_y is not None:
            input_updates["sensitivity_y"] = clamp(
                args.sensitivity_y, SENSITIVITY_MIN, SENSITIVITY_MAX
            )

        if args.deadzone is not None:
            has_args = True
            input_updates["deadzone"] = clamp(args.deadzone, DEADZONE_MIN, DEADZONE_MAX)

        if args.hysteresis is not None:
            has_args = True
            input_updates["hysteresis"] = clamp(
                args.hysteresis, HYSTERESIS_MIN, HYSTERESIS_MAX
            )

        if input_updates:
            store.settings.update(**input_updates)
            print("Input controls and keybindings updated successfully.")
            show_input_controls()

        if args.reset_input:
            has_args = True
            reset_input_controls_defaults()

        if args.show_input:
            has_args = True
            show_input_controls()

        typematic_updates = {}

        if args.set_typematic is not None:
            has_args = True
            typematic_updates["typematic_enabled"] = (
                True if args.set_typematic == "on" else False
            )

        if args.typematic_delay is not None:
            has_args = True
            typematic_updates["typematic_delay_ms"] = clamp(
                args.typematic_delay, TYPEMATIC_DELAY_MIN_MS, TYPEMATIC_DELAY_MAX_MS
            )

        if args.typematic_rate is not None:
            has_args = True
            typematic_updates["typematic_rate_hz"] = clamp(
                args.typematic_rate, TYPEMATIC_RATE_MIN_HZ, TYPEMATIC_RATE_MAX_HZ
            )

        if args.typematic_excludes is not None:
            has_args = True
            current_ex = store.settings.get().typematic_excluded_keys
            typematic_updates["typematic_excluded_keys"] = _normalize_excluded_keys(
                args.typematic_excludes, current_ex
            )

        if typematic_updates:
            store.settings.update(**typematic_updates)
            print("Typematic settings updated successfully.")
            show_typematic()

        if args.reset_typematic:
            has_args = True
            reset_typematic_defaults()

        if args.show_typematic:
            has_args = True
            show_typematic()

        system_updates = {}

        if args.set_two_finger_tap is not None:
            has_args = True
            system_updates["two_finger_tap_enabled"] = (
                True if args.set_two_finger_tap == "on" else False
            )

        if args.set_bezel_toggle is not None:
            has_args = True
            system_updates["bezel_toggle_enabled"] = (
                True if args.set_bezel_toggle == "on" else False
            )

        if system_updates:
            store.settings.update(**system_updates)
            print("System settings updated successfully.")
            show_system()

        if args.reset_system:
            has_args = True
            reset_system_defaults()

        if args.show_system:
            has_args = True
            show_system()

        if args.list_supported_keys:
            has_args = True
            list_supported_keys()

        if args.sort is not None:
            has_args = True
            set_profile_sort_order(args.sort)

        if args.list or args.filter:
            has_args = True
            list_profiles(args.filter)

        if args.new is not None:
            has_args = True
            w, h, d = args.dims if args.dims else (None, None, None)
            create_new_profile(args.new, w, h, d)

        if args.set_image is not None:
            has_args = True
            set_profile_image(int(args.set_image[0]), args.set_image[1])

        if args.set_active is not None:
            has_args = True
            set_active_profile(args.set_active)

        if args.list_zones is not None:
            has_args = True
            list_layout_zones(args.list_zones)

        if args.set_bezels is not None:
            has_args = True
            set_bezel_thickness(
                int(args.set_bezels[0]), args.set_bezels[1], args.set_bezels[2]
            )

        if args.show_directional_keys is not None:
            has_args = True
            show_directional_keys(args.show_directional_keys)

        if args.edit_layout_directionals is not None:
            has_args = True
            set_directional_key(args.edit_layout_directionals, args.set_key)

        if args.edit_zone is not None:
            has_args = True
            edit_single_zone(
                args.edit_zone,
                priority=args.zone_priority,
                ignore_app_settings=(
                    None
                    if args.zone_ignore_app_settings is None
                    else (args.zone_ignore_app_settings == "on")
                ),
                pointer=(
                    None if args.zone_pointer is None else (args.zone_pointer == "on")
                ),
                sens_x=args.zone_sens_x,
                sens_y=args.zone_sens_y,
                deadzone=args.zone_deadzone,
                hysteresis=args.zone_hysteresis,
            )
            has_args = True

        if args.reset_zone is not None:
            has_args = True
            reset_single_zone_to_app_settings(args.reset_zone)

        if args.delete_zone is not None:
            has_args = True
            delete_single_zone(args.delete_zone)

        if args.duplicate is not None:
            has_args = True
            duplicate_profile(int(args.duplicate[0]), args.duplicate[1])

        if args.rename is not None:
            has_args = True
            rename_profile(int(args.rename[0]), args.rename[1])

        if args.delete is not None:
            has_args = True
            delete_profile(args.delete)

        if args.clear_zones is not None:
            has_args = True
            clear_zones(args.clear_zones)

        if args.reset_zones is not None:
            has_args = True
            target_id = args.reset_zones
            if target_id == -1:
                active = store.get_active_layout()
                target_id = active.id if active else None
            if target_id is not None:
                count = reset_layout_zones_to_app_settings(target_id)
                print(f"Reset {count} zones in layout ID {target_id} to AppSettings.")
            else:
                print("No layout specified or active.")

        if args.import_json is not None:
            has_args = True
            import_profile_json(args.import_json)

        if args.export_json is not None:
            has_args = True
            export_profile_json(args.export_json, args.output)

        if args.export_toml_layout is not None:
            has_args = True
            export_profile_toml(args.export_toml_layout, args.output)

        if args.export_toml is not None:
            has_args = True
            export_profile_toml(None, args.export_toml)

        if args.import_toml is not None:
            has_args = True
            if migrate_toml_config(args.import_toml):
                print(f"Settings imported from: {args.import_toml}")
            else:
                print(f"Failed to import settings from: {args.import_toml}")

        if args.export_bundle is not None:
            has_args = True

            if args.bundle_layout_id is not None:
                target = store.layouts.get(args.bundle_layout_id)
                if not target:
                    print(f"Error: Layout ID {args.bundle_layout_id} not found.")
                else:
                    t_path, j_path = export_bundle(
                        args.export_bundle,
                        profile_name=target.name,
                        layout_id=target.id,
                    )
            else:
                t_path, j_path = export_bundle(args.export_bundle)
            print(f"Bundle exported:\n  - TOML: {t_path}\n  - JSON: {j_path}")

        if args.import_bundle is not None:
            has_args = True
            if import_any(args.import_bundle):
                print(f"Bundle imported from: {args.import_bundle}")
            else:
                print(f"Failed to import bundle from: {args.import_bundle}")

        if args.import_any is not None:
            has_args = True
            if import_any(args.import_any):
                print(f"Configuration imported from: {args.import_any}")
            else:
                print(f"Failed to import configuration from: {args.import_any}")

        if args.reset_settings:
            has_args = True
            store.settings.reset_to_defaults()
            print("Application settings reset to defaults.")

        if args.wipe_database:
            has_args = True
            wipe_database()

        if not has_args:
            interactive_menu()

    finally:
        store.close()


def main() -> None:
    """Dedicated CLI management entry point."""
    AppLogManager.setup_logging(log_prefix="touch2key_manage")
    run()


if __name__ == "__main__":
    main()
