#!/usr/bin/env python3
"""
CLI Layout & Profile Manager.

Provides quick terminal-based profile switching, JSON layout import/export,
TOML app_settings import/export, and bundled profile migrations without
opening the PySide6 GUI.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Optional

import tomlkit

from modules.database import store
from modules.database.legacy_migration import (
    migrate_all,
    migrate_json_layout,
    migrate_toml_config,
)
from modules.utils import CIRCLE, JSONS_FOLDER, TOML_PATH


# ---------------------------------------------------------------------------
# TOML Settings Helpers
# ---------------------------------------------------------------------------

def export_settings_to_toml(
    target_path: Path = TOML_PATH,
    linked_json_path: Optional[Path] = None,
) -> Path:
    """Exports current app_settings and active layout metadata to a TOML file."""
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


def import_settings_from_toml(source_path: Path = TOML_PATH) -> bool:
    """Imports settings from a TOML file into SQLite app_settings."""
    return migrate_toml_config(source_path)


# ---------------------------------------------------------------------------
# Layout Operations
# ---------------------------------------------------------------------------

def list_profiles() -> None:
    layouts = store.layouts.list_all()
    active_layout = store.get_active_layout()
    active_id = active_layout.id if active_layout else None

    if not layouts:
        print("No layouts found in the database.")
        return

    print("\n--- Available Profiles ---")
    for l in layouts:
        active_flag = " [* ACTIVE]" if l.id == active_id else ""
        print(f"  [{l.id}] {l.name} ({l.width}x{l.height} @ {l.dpi} DPI){active_flag}")
    print()


def set_active_profile(layout_id: int) -> None:
    target = store.layouts.get(layout_id)
    if not target:
        print(f"Error: Layout ID {layout_id} does not exist.")
        return

    store.settings.update(active_layout_id=layout_id)
    print(f"Active profile updated to: '{target.name}' (ID: {target.id})")


def import_profile(file_path: Path) -> Optional[int]:
    if not file_path.exists():
        print(f"Error: File '{file_path}' not found.")
        return None

    layout_id = migrate_json_layout(
        json_path=file_path,
        image_path="",
        set_active=True,
    )
    if layout_id:
        print(f"Imported '{file_path.name}' successfully as Active Layout (ID: {layout_id}).")
    else:
        print(f"Failed to import '{file_path.name}'.")
    return layout_id


def export_profile(layout_id: int, output_path: Path | None = None) -> Optional[Path]:
    layout = store.layouts.get(layout_id)
    if not layout:
        print(f"Error: Layout ID {layout_id} does not exist.")
        return None

    JSONS_FOLDER.mkdir(parents=True, exist_ok=True)
    out_file = output_path or (JSONS_FOLDER / f"{layout.name}.json")

    zones = store.zones.list_for_layout(layout.id)
    output_content = []
    for zone in zones:
        output_content.append({
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
        "content": output_content,
    }

    with open(out_file, "w", encoding="utf-8") as f:
        json.dump(json_data, f, indent=4)

    print(f"Layout exported successfully to: {out_file}")
    return out_file


def export_bundle(target_dir: Path, layout_id: Optional[int] = None) -> tuple[Path, Path]:
    """Exports both a layout (.json) and its linked settings (.toml)."""
    target_dir.mkdir(parents=True, exist_ok=True)

    target_layout = store.layouts.get(layout_id) if layout_id else store.get_active_layout()
    if not target_layout:
        raise ValueError("No layout available to export bundle.")

    json_file = export_profile(target_layout.id, target_dir / f"{target_layout.name}.json")
    toml_file = export_settings_to_toml(target_dir / f"{target_layout.name}.toml", linked_json_path=json_file)

    return toml_file, json_file


# ---------------------------------------------------------------------------
# Interactive Menu
# ---------------------------------------------------------------------------

def interactive_menu() -> None:
    while True:
        list_profiles()
        print("Commands:")
        print("  [s]  Select / Switch Active Profile")
        print("  [i]  Import Layout from JSON")
        print("  [e]  Export Profile to JSON")
        print("  [st] Export App Settings to settings.toml")
        print("  [lt] Import App Settings from settings.toml")
        print("  [eb] Export Full Bundle (settings.toml + layout.json)")
        print("  [ib] Import Full Bundle (settings.toml with linked json_path)")
        print("  [d]  Delete Profile")
        print("  [q]  Quit")

        choice = input("\nEnter command: ").strip().lower()

        if choice == "q":
            break
        elif choice == "st":
            path = export_settings_to_toml()
            print(f"Settings exported successfully to: {path}")
        elif choice == "lt":
            if import_settings_from_toml():
                print("Settings imported successfully from settings.toml.")
            else:
                print("Failed to import settings.toml (file missing or invalid).")
        elif choice == "s":
            raw_id = input("Enter Layout ID to activate: ").strip()
            if raw_id.isdigit():
                set_active_profile(int(raw_id))
        elif choice == "i":
            raw_path = input("Enter path to JSON file: ").strip().strip('"')
            if raw_path:
                import_profile(Path(raw_path))
        elif choice == "e":
            raw_id = input("Enter Layout ID to export: ").strip()
            if raw_id.isdigit():
                export_profile(int(raw_id))
        elif choice == "eb":
            raw_id = input("Enter Layout ID to bundle (Leave blank for active): ").strip()
            target_id = int(raw_id) if raw_id.isdigit() else None
            out_folder = Path("exports")
            try:
                t_path, j_path = export_bundle(out_folder, target_id)
                print(f"Bundle exported:\n  - TOML: {t_path}\n  - JSON: {j_path}")
            except Exception as exc:
                print(f"Export bundle failed: {exc}")
        elif choice == "ib":
            raw_path = input("Enter path to bundle settings.toml: ").strip().strip('"')
            if raw_path and Path(raw_path).exists():
                migrate_all(Path(raw_path))
                print("Bundle imported and synced to SQLite.")
            else:
                print("Invalid or missing TOML file.")
        elif choice == "d":
            raw_id = input("Enter Layout ID to delete: ").strip()
            if raw_id.isdigit():
                target_id = int(raw_id)
                confirm = input(f"Confirm delete Layout ID {target_id}? (y/N): ").strip().lower()
                if confirm == "y":
                    store.zones.delete_all_for_layout(target_id)
                    store.layouts.delete(target_id)
                    print(f"Layout ID {target_id} and associated zones deleted.")
        print("-" * 40)


# ---------------------------------------------------------------------------
# CLI Entry Point
# ---------------------------------------------------------------------------

def run() -> None:
    parser = argparse.ArgumentParser(description="Touch2Key CLI Layout & Config Manager")
    parser.add_argument("-l", "--list", action="store_true", help="List all saved profiles")
    parser.add_argument("-s", "--set-active", type=int, metavar="ID", help="Set active layout by ID")
    parser.add_argument("-i", "--import-json", type=Path, metavar="PATH", help="Import a layout from JSON")
    parser.add_argument("-e", "--export-json", type=int, metavar="ID", help="Export a layout to JSON by ID")
    parser.add_argument("--export-toml", type=Path, nargs="?", const=TOML_PATH, metavar="OUT_PATH", help="Export app_settings to TOML")
    parser.add_argument("--import-toml", type=Path, nargs="?", const=TOML_PATH, metavar="IN_PATH", help="Import app_settings from TOML")
    parser.add_argument("--export-bundle", type=Path, metavar="OUT_DIR", help="Export active profile bundle (.toml + .json) into directory")
    parser.add_argument("--import-bundle", type=Path, metavar="TOML_PATH", help="Import a full profile bundle via its settings.toml")
    parser.add_argument("-o", "--output", type=Path, metavar="OUT_PATH", help="Custom output path for JSON export")

    args = parser.parse_args()

    if args.list:
        list_profiles()
    elif args.set_active is not None:
        set_active_profile(args.set_active)
    elif args.import_json is not None:
        import_profile(args.import_json)
    elif args.export_json is not None:
        export_profile(args.export_json, args.output)
    elif args.export_toml is not None:
        path = export_settings_to_toml(args.export_toml)
        print(f"Settings exported to: {path}")
    elif args.import_toml is not None:
        if import_settings_from_toml(args.import_toml):
            print(f"Settings imported from: {args.import_toml}")
        else:
            print(f"Failed to import settings from: {args.import_toml}")
    elif args.export_bundle is not None:
        t_path, j_path = export_bundle(args.export_bundle)
        print(f"Bundle exported:\n  - TOML: {t_path}\n  - JSON: {j_path}")
    elif args.import_bundle is not None:
        migrate_all(args.import_bundle)
        print(f"Bundle imported from: {args.import_bundle}")
    else:
        interactive_menu()

    store.close()


if __name__ == "__main__":
    run()
