#!/usr/bin/env python3
"""
CLI Layout & Profile Manager.

Provides terminal-based profile switching, duplication, renaming,
zone/pipeline inspection, JSON layout import/export, TOML app_settings
import/export, schema reset, and bulk synchronization of zones to AppSettings.
"""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Optional

from modules.database import reset_layout_zones_to_app_settings, store
from modules.database.config_io import (
    export_bundle,
    export_layout_json,
    export_settings_toml,
    import_any,
)
from modules.database.legacy_migration import (
    migrate_json_layout,
    migrate_toml_config,
)
from modules.utils import JSONS_FOLDER, PROFILES_FOLDER, TOML_PATH

# ---------------------------------------------------------------------------
# Profile Inspection & Management
# ---------------------------------------------------------------------------


def list_profiles() -> None:
    """Lists all saved layouts with resolution, DPI, and zone metrics."""
    layouts = store.layouts.list_all()
    active_layout = store.get_active_layout()
    active_id = active_layout.id if active_layout else None

    if not layouts:
        print("\nNo layouts found in the database.\n")
        return

    print("\n--- Available Profiles ---")
    for l in layouts:
        zones = store.zones.list_for_layout(l.id)
        active_flag = " [* ACTIVE]" if l.id == active_id else ""
        img_flag = f" (Img: {Path(l.image_path).name})" if l.image_path else ""
        print(
            f"  [{l.id}] {l.name} - {l.width}x{l.height} @ {l.dpi} DPI "
            f"[{len(zones)} zones]{img_flag}{active_flag}"
        )
    print()


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

    print(f"\n--- Zones / Pipelines for '{layout.name}' (ID: {layout_id}) ---")
    for z in zones:
        if z.zone_type == "CIRCLE":
            coords = f"Center=({z.cx}, {z.cy}), R={z.r}"
        elif z.zone_type == "RECTANGLE":
            coords = f"Rect=({z.x1}, {z.y1}) -> ({z.x2}, {z.y2})"
        else:
            coords = "Bezel Notch"
        cam_flag = " [MoveCam/TrackFire]" if z.move_camera else ""
        print(
            f"  [{z.id}] {z.name or 'Unnamed'} | Key: {z.scancode} | "
            f"Type: {z.zone_type} | Prio: {z.priority} | {coords}{cam_flag}"
        )
    print()


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

    if store.layouts.get_by_name(clean_name) is not None:
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

    if store.layouts.get_by_name(clean_name) is not None:
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
    if not target:
        print(f"Error: Layout ID {layout_id} does not exist.")
        return False

    active_layout = store.get_active_layout()
    if active_layout and active_layout.id == layout_id:
        store.settings.update(active_layout_id=None)

    store.zones.delete_all_for_layout(layout_id)
    store.layouts.delete(layout_id)
    print(f"Layout '{target.name}' (ID: {layout_id}) and all mapped zones deleted.")
    return True


def clear_zones(layout_id: int) -> bool:
    """Removes all touch zones from a profile while keeping the layout entry."""
    target = store.layouts.get(layout_id)
    if not target:
        print(f"Error: Layout ID {layout_id} not found.")
        return False

    store.zones.delete_all_for_layout(layout_id)
    print(f"All touch zones cleared for layout '{target.name}' (ID: {layout_id}).")
    return True


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


# ---------------------------------------------------------------------------
# Interactive Terminal Menu
# ---------------------------------------------------------------------------


def interactive_menu() -> None:
    """Terminal CLI UI loop."""
    while True:
        list_profiles()
        print("Commands:")
        print("  [s]   Select / Switch Active Profile")
        print("  [lz]  List Zones / Pipelines for Profile")
        print("  [cp]  Duplicate Profile")
        print("  [rn]  Rename Profile")
        print("  [cz]  Clear Zones for Profile")
        print("  [rz]  Reset All Zones in Layout to App Settings")
        print("  [d]   Delete Profile")
        print("  [i]   Import Layout from JSON")
        print("  [e]   Export Profile to JSON")
        print("  [st]  Export App Settings to settings.toml")
        print("  [lt]  Import App Settings from settings.toml")
        print("  [eb]  Export Full Bundle to data/profiles/")
        print("  [ib]  Import Any Config (.toml, .json, or Bundle Directory)")
        print("  [r]   Reset App Settings to Defaults")
        print("  [q]   Quit")

        choice = input("\nEnter command: ").strip().lower()

        if choice == "q":
            break

        elif choice == "s":
            raw_id = input("Enter Layout ID to activate: ").strip()
            if raw_id.isdigit():
                set_active_profile(int(raw_id))

        elif choice == "lz":
            raw_id = input("Enter Layout ID to view zones: ").strip()
            if raw_id.isdigit():
                list_layout_zones(int(raw_id))

        elif choice == "cp":
            raw_id = input("Enter Layout ID to duplicate: ").strip()
            if raw_id.isdigit():
                target_id = int(raw_id)
                source = store.layouts.get(target_id)
                if source:
                    new_name = input(
                        f"Enter name for copy of '{source.name}': "
                    ).strip()
                    duplicate_profile(target_id, new_name)

        elif choice == "rn":
            raw_id = input("Enter Layout ID to rename: ").strip()
            if raw_id.isdigit():
                target_id = int(raw_id)
                target = store.layouts.get(target_id)
                if target:
                    new_name = input(f"Enter new name for '{target.name}': ").strip()
                    rename_profile(target_id, new_name)

        elif choice == "cz":
            raw_id = input("Enter Layout ID to clear zones: ").strip()
            if raw_id.isdigit():
                target_id = int(raw_id)
                confirm = (
                    input(f"Clear all zones for Layout ID {target_id}? (y/N): ")
                    .strip()
                    .lower()
                )
                if confirm == "y":
                    clear_zones(target_id)

        elif choice == "rz":
            raw_id = input(
                "Enter Layout ID to reset zones (Leave blank for active): "
            ).strip()
            target_id = int(raw_id) if raw_id.isdigit() else None
            active = (
                store.layouts.get(target_id) if target_id else store.get_active_layout()
            )
            if active:
                count = reset_layout_zones_to_app_settings(active.id)
                print(
                    f"Reset {count} zones in layout '{active.name}' to default AppSettings."
                )
            else:
                print("No layout selected or active.")

        elif choice == "d":
            raw_id = input("Enter Layout ID to delete: ").strip()
            if raw_id.isdigit():
                target_id = int(raw_id)
                confirm = (
                    input(
                        f"Confirm delete Layout ID {target_id} and its zones? (y/N): "
                    )
                    .strip()
                    .lower()
                )
                if confirm == "y":
                    delete_profile(target_id)

        elif choice == "i":
            raw_path = (
                input(f"Enter path to JSON file [Default: {JSONS_FOLDER}]: ")
                .strip()
                .strip('"')
            )
            if raw_path:
                import_profile_json(Path(raw_path))

        elif choice == "e":
            raw_id = input("Enter Layout ID to export: ").strip()
            if raw_id.isdigit():
                export_profile_json(int(raw_id))

        elif choice == "st":
            path = export_settings_toml()
            print(f"Settings exported successfully to: {path}")

        elif choice == "lt":
            if migrate_toml_config():
                print("Settings imported successfully from settings.toml.")
            else:
                print("Failed to import settings.toml (file missing or invalid).")

        elif choice == "eb":
            raw_id = input(
                "Enter Layout ID to bundle (Leave blank for active): "
            ).strip()
            target_id = int(raw_id) if raw_id.isdigit() else None
            try:
                active = (
                    store.layouts.get(target_id)
                    if target_id
                    else store.get_active_layout()
                )
                if active:
                    t_path, j_path = export_bundle(profile_name=active.name)
                    print(f"Bundle exported:\n  - TOML: {t_path}\n  - JSON: {j_path}")
                else:
                    print("No active layout available to bundle.")
            except Exception as exc:
                print(f"Export bundle failed: {exc}")

        elif choice == "ib":
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

        elif choice == "r":
            confirm = (
                input("Reset all app settings to defaults? (y/N): ").strip().lower()
            )
            if confirm == "y":
                store.settings.reset_to_defaults()
                print("Application settings reset to defaults.")

        print("-" * 40)


# ---------------------------------------------------------------------------
# CLI Argument Entry Point
# ---------------------------------------------------------------------------


def run() -> None:
    parser = argparse.ArgumentParser(description="CLI Layout & Profile Manager")
    parser.add_argument(
        "-l", "--list", action="store_true", help="List all saved profiles"
    )
    parser.add_argument(
        "-s", "--set-active", type=int, metavar="ID", help="Set active layout by ID"
    )
    parser.add_argument(
        "--list-zones",
        type=int,
        metavar="ID",
        help="List all zones/pipelines for layout by ID",
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
        help="Custom output path for JSON export",
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
        help="Export profile bundle (.toml + .json) into data/profiles/",
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
        "--reset-settings", action="store_true", help="Reset app settings to defaults"
    )

    args = parser.parse_args()

    try:
        if args.list:
            list_profiles()
        elif args.set_active is not None:
            set_active_profile(args.set_active)
        elif args.list_zones is not None:
            list_layout_zones(args.list_zones)
        elif args.duplicate is not None:
            duplicate_profile(int(args.duplicate[0]), args.duplicate[1])
        elif args.rename is not None:
            rename_profile(int(args.rename[0]), args.rename[1])
        elif args.delete is not None:
            delete_profile(args.delete)
        elif args.clear_zones is not None:
            clear_zones(args.clear_zones)
        elif args.reset_zones is not None:
            target_id = args.reset_zones
            if target_id == -1:
                active = store.get_active_layout()
                target_id = active.id if active else None
            if target_id is not None:
                count = reset_layout_zones_to_app_settings(target_id)
                print(f"Reset {count} zones in layout ID {target_id} to AppSettings.")
            else:
                print("No layout specified or active.")
        elif args.import_json is not None:
            import_profile_json(args.import_json)
        elif args.export_json is not None:
            export_profile_json(args.export_json, args.output)
        elif args.export_toml is not None:
            path = export_settings_toml(args.export_toml)
            print(f"Settings exported to: {path}")
        elif args.import_toml is not None:
            if migrate_toml_config(args.import_toml):
                print(f"Settings imported from: {args.import_toml}")
            else:
                print(f"Failed to import settings from: {args.import_toml}")
        elif args.export_bundle is not None:
            t_path, j_path = export_bundle(args.export_bundle)
            print(f"Bundle exported:\n  - TOML: {t_path}\n  - JSON: {j_path}")
        elif args.import_bundle is not None:
            if import_any(args.import_bundle):
                print(f"Bundle imported from: {args.import_bundle}")
            else:
                print(f"Failed to import bundle from: {args.import_bundle}")
        elif args.import_any is not None:
            if import_any(args.import_any):
                print(f"Configuration imported from: {args.import_any}")
            else:
                print(f"Failed to import configuration from: {args.import_any}")
        elif args.reset_settings:
            store.settings.reset_to_defaults()
            print("Application settings reset to defaults.")
        else:
            interactive_menu()
    finally:
        store.close()


if __name__ == "__main__":
    run()
