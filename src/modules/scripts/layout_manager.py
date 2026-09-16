#!/usr/bin/env python3
"""
CLI Layout & Profile Manager.

Provides quick terminal-based profile switching, JSON import/export,
and active layout configuration without opening the PySide6 GUI.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from modules.database import store
from modules.database.legacy_migration import migrate_json_layout
from modules.utils import CIRCLE, JSONS_FOLDER


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


def import_profile(file_path: Path) -> None:
    if not file_path.exists():
        print(f"Error: File '{file_path}' not found.")
        return

    layout_id = migrate_json_layout(
        json_path=file_path,
        image_path="",
        set_active=True,
    )
    if layout_id:
        print(f"Imported '{file_path.name}' successfully as Active Layout (ID: {layout_id}).")
    else:
        print(f"Failed to import '{file_path.name}'.")


def export_profile(layout_id: int, output_path: Path | None = None) -> None:
    layout = store.layouts.get(layout_id)
    if not layout:
        print(f"Error: Layout ID {layout_id} does not exist.")
        return

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


def interactive_menu() -> None:
    while True:
        list_profiles()
        print("Commands:")
        print("  [st] Export App Settings to settings.toml")
        print("  [lt] Import App Settings from settings.toml")
        print("  [s] Select / Switch Active Profile")
        print("  [i] Import JSON Profile")
        print("  [e] Export Profile to JSON")
        print("  [d] Delete Profile")
        print("  [q] Quit")

        choice = input("\nEnter command: ").strip().lower()

        if choice == "q":
            break
        elif choice == "st":
            export_settings_to_toml()
            print("Settings exported to settings.toml.")
        elif choice == "lt":
            if import_settings_from_toml():
                print("Settings imported successfully from settings.toml.")
            else:
                print("Failed to import settings.toml (file not found or invalid).")
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
        elif choice == "d":
            raw_id = input("Enter Layout ID to delete: ").strip()
            if raw_id.isdigit():
                target_id = int(raw_id)
                confirm = input(f"Confirm delete Layout ID {target_id}? (y/N): ").strip().lower()
                if confirm == "y":
                    store.layouts.delete(target_id)
                    print(f"Layout ID {target_id} deleted.")
        print("-" * 40)


def main() -> None:
    parser = argparse.ArgumentParser(description="Touch2Key CLI Layout Manager")
    parser.add_argument("-l", "--list", action="store_true", help="List all saved profiles")
    parser.add_argument("-s", "--set-active", type=int, metavar="ID", help="Set active layout by ID")
    parser.add_argument("-i", "--import-json", type=Path, metavar="PATH", help="Import a layout from JSON")
    parser.add_argument("-e", "--export-json", type=int, metavar="ID", help="Export a layout to JSON by ID")
    parser.add_argument("-o", "--output", type=Path, metavar="OUT_PATH", help="Custom output path for export")

    args = parser.parse_args()

    if args.list:
        list_profiles()
    elif args.set_active is not None:
        set_active_profile(args.set_active)
    elif args.import_json is not None:
        import_profile(args.import_json)
    elif args.export_json is not None:
        export_profile(args.export_json, args.output)
    else:
        interactive_menu()

    store.close()


if __name__ == "__main__":
    main()