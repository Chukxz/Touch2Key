"""CLI Layout & Profile Manager.

Provides terminal-based profile switching, duplication, renaming,
zone/pipeline inspection, JSON layout import/export, TOML app_settings
import/export, schema reset, bulk synchronization of zones to AppSettings,
and typematic (keyboard repeat) configuration and reset routines.
"""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Optional

from modules import AppLogManager
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
from modules.utils import (
    BEZEL,
    CIRCLE,
    EXCLUDED_KEYS,
    IMAGES_FOLDER,
    JSONS_FOLDER,
    PROFILES_FOLDER,
    RECTANGLE,
    TOML_PATH,
)

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

    store.layouts.update(layout_id, image_path=str(path.resolve()))
    print(f"Updated profile '{target.name}' background image to: {path.name}")
    return True


def show_left_handed() -> None:
    s = store.settings.get()
    print("\n--- Left-Handed Mode ---")
    print(f"  Left-Handed: {'Yes' if s.left_handed else 'No'}\n")


def configure_left_handed_interactive() -> None:
    s = store.settings.get()
    show_left_handed()
    val_in = (
        input(
            f"Enable left-handed mode? (y/n, current: {'y' if s.left_handed else 'n'}): "
        )
        .strip()
        .lower()
    )
    if val_in in ("y", "n"):
        store.settings.update(left_handed=(val_in == "y"))
        print("Left-handed mode updated successfully.")
    show_left_handed()


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
        coords = "N/A"
        if z.zone_type == CIRCLE:
            coords = f"Center=({z.cx}, {z.cy}), R={z.r}"
        elif z.zone_type in (RECTANGLE, BEZEL):
            coords = f"Rect=({z.x1}, {z.y1}) -> ({z.x2}, {z.y2})"

        cam_flag = " [MoveCam/TrackFire]" if z.pointer else ""
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
    """Removes all touch zones from a profile while keeping the layout entry and reseeding its bezels."""
    target = store.layouts.get(layout_id)
    if not target:
        print(f"Error: Layout ID {layout_id} not found.")
        return False

    store.zones.delete_all_for_layout(layout_id)
    store.zones.list_for_layout(layout_id)

    print(
        f"All touch zones cleared (system bezels auto-restored) for layout '{target.name}' (ID: {layout_id})."
    )
    return True


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

    delay_in = input(
        f"Initial repeat delay ms (current: {s.typematic_delay_ms:.1f}): "
    ).strip()
    delay = float(delay_in) if delay_in else s.typematic_delay_ms

    rate_in = input(f"Repeat rate Hz (current: {s.typematic_rate_hz:.1f}): ").strip()
    rate = float(rate_in) if rate_in else s.typematic_rate_hz

    ex_in = input(
        f"Excluded keys comma-separated (current: {s.typematic_excluded_keys or ''}): "
    ).strip()
    excludes = s.typematic_excluded_keys if not ex_in else ex_in

    if excludes:
        excludes = ",".join(k.strip().lower() for k in excludes.split(",") if k.strip())

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
    """Prints current double-tap and bezel toggle fields configuration."""
    s = store.settings.get()
    print("\n--- System Settings ---")
    print(f"  Double Tap Enabled:  {'Yes' if s.double_tap_enabled else 'No'}")
    print(f"  Bezels Enabled:      {'Yes' if s.bezel_toggle_enabled else 'No'}")


def configure_system_interactive() -> None:
    """Prompts for double-tap and bezel toggle fields interactively."""
    s = store.settings.get()
    show_system()

    en_double_tap_in = (
        input(
            f"Enable double tap toggle? (y/n, current: {'y' if s.double_tap_enabled else 'n'}): "
        )
        .strip()
        .lower()
    )
    double_tap_enabled = (
        s.double_tap_enabled if not en_double_tap_in else (en_double_tap_in == "y")
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
        double_tap_enabled=double_tap_enabled, bezel_toggle_enabled=bezel_toggle_enabled
    )
    print("Double Tap and Bezel Toggle settings updated successfully.")
    show_system()


def reset_system_defaults() -> None:
    """Resets only double tap and bezel toggle settings to factory defaults."""
    store.settings.update(double_tap_enabled=True, bezel_toggle_enabled=True)
    print("Double Tap and Bezel Toggle settings reset to factory defaults.")
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


# ---------------------------------------------------------------------------
# Interactive Terminal Menu
# ---------------------------------------------------------------------------


def interactive_menu() -> None:
    """Terminal CLI UI loop."""
    while True:
        list_profiles()
        print("\n\nCommands:")
        print("  [s]    Select / Switch Active Profile")
        print("  [si]   Set Profile Background Image")
        print("  [lh]   View / Configure Left-Handed Mode")
        print("  [lz]   List Zones / Pipelines for Profile")
        print("  [cp]   Duplicate Profile")
        print("  [rn]   Rename Profile")
        print("  [cz]   Clear Zones for Profile")
        print("  [rz]   Reset All Zones in Layout to App Settings")
        print("  [d]    Delete Profile")
        print("  [ty]   View / Configure Typematic (Auto-Repeat) Settings")
        print("  [rty]  Reset Typematic Settings to Defaults")
        print("  [ss]   View / Configure Double Tap and Bezel Toggle Settings")
        print("  [rss]  Reset Double Tap and Bezel Toggle Settings to Defaults")
        print("  [i]    Import Layout from JSON")
        print("  [e]    Export Profile to JSON")
        print("  [st]   Export App Settings to settings.toml")
        print("  [lt]   Import App Settings from settings.toml")
        print("  [eb]   Export Full Bundle to data/profiles/")
        print("  [ib]   Import Any Config (.toml, .json, or Bundle Directory)")
        print("  [r]    Reset All App Settings to Defaults")
        print("  [q]    Quit")

        choice = input("\nEnter command: ").strip().lower()

        if choice == "q":
            break

        elif choice == "s":
            raw_id = input("Enter Layout ID to activate: ").strip()
            if raw_id.isdigit():
                set_active_profile(int(raw_id))

        elif choice == "si":
            raw_id = input("Enter Layout ID: ").strip()
            img_path = (
                input(f"Enter image filename or path [Search dir: {IMAGES_FOLDER}]: ")
                .strip()
                .strip('"')
            )
            if raw_id.isdigit() and img_path:
                set_profile_image(int(raw_id), img_path)

        elif choice == "lh":
            configure_left_handed_interactive()

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
            try:
                target_id = int(raw_id) if raw_id else None
                active = (
                    store.layouts.get(target_id)
                    if target_id
                    else store.get_active_layout()
                )
                if active:
                    count = reset_layout_zones_to_app_settings(active.id)
                    print(
                        f"Reset {count} zones in layout '{active.name}' to default AppSettings."
                    )
                else:
                    print("No layout selected or active.")
            except ValueError:
                print("Invalid layout ID provided.")

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

        elif choice == "ty":
            configure_typematic_interactive()

        elif choice == "rty":
            confirm = (
                input("Reset typematic settings to defaults? (y/N): ").strip().lower()
            )
            if confirm == "y":
                reset_typematic_defaults()

        elif choice == "ss":
            configure_system_interactive()

        elif choice == "rss":
            confirm = (
                input("Reset double tap and bezel toggle settings to defaults? (y/N): ")
                .strip()
                .lower()
            )
            if confirm == "y":
                reset_system_defaults()

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
            try:
                target_id = int(raw_id) if raw_id else None
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
        "--set-image",
        nargs=2,
        metavar=("LAYOUT_ID", "IMAGE_PATH"),
        help="Set background image path for a specific layout by its ID",
    )
    parser.add_argument(
        "--show-left-handed",
        action="store_true",
        help="Display left-handed mode status",
    )
    parser.add_argument(
        "--set-left-handed",
        choices=["on", "off"],
        help="Enable or disable left-handed mode",
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
        help="Set comma-separated excluded keys (e.g. 'w,a,s,d,shift')",
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
        help="Display system settings (double tap and bezel toggles)",
    )
    parser.add_argument(
        "--set-double-tap",
        choices=["on", "off"],
        help="Enable or disable the double-tap menu gesture",
    )
    parser.add_argument(
        "--set-bezel-toggle",
        choices=["on", "off"],
        help="Enable or disable system bezel touch toggles",
    )
    parser.add_argument(
        "--reset-system",
        action="store_true",
        help="Reset system settings to factory defaults",
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
        "--reset-settings",
        action="store_true",
        help="Reset all app settings to defaults",
    )

    args = parser.parse_args()

    try:
        if args.set_left_handed is not None:
            store.settings.update(left_handed=(args.set_left_handed == "on"))
            print("Left-handed mode updated successfully.")
            show_left_handed()
            return

        if args.show_left_handed:
            show_left_handed()
            return

        typematic_updates = {}
        if args.set_typematic is not None:
            typematic_updates["typematic_enabled"] = (
                True if args.set_typematic == "on" else False
            )
        if args.typematic_delay is not None:
            typematic_updates["typematic_delay_ms"] = args.typematic_delay
        if args.typematic_rate is not None:
            typematic_updates["typematic_rate_hz"] = args.typematic_rate
        if args.typematic_excludes is not None:
            typematic_updates["typematic_excluded_keys"] = ",".join(
                k.strip().lower()
                for k in args.typematic_excludes.split(",")
                if k.strip()
            )

        if typematic_updates:
            store.settings.update(**typematic_updates)
            print("Typematic settings updated successfully.")
            show_typematic()
            return

        if args.reset_typematic:
            reset_typematic_defaults()
            return
        elif args.show_typematic:
            show_typematic()
            return

        system_updates = {}
        if args.set_double_tap is not None:
            system_updates["double_tap_enabled"] = (
                True if args.set_double_tap == "on" else False
            )
        if args.set_bezel_toggle is not None:
            system_updates["bezel_toggle_enabled"] = (
                True if args.set_bezel_toggle == "on" else False
            )

        if system_updates:
            store.settings.update(**system_updates)
            print("System settings updated successfully.")
            show_system()
            return

        if args.reset_system:
            reset_system_defaults()
            return
        elif args.show_system:
            show_system()
            return

        if args.list:
            list_profiles()
        elif args.set_image is not None:
            set_profile_image(int(args.set_image[0]), args.set_image[1])
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


def main() -> None:
    """Dedicated CLI management entry point."""
    AppLogManager.setup_logging(is_gui=False, log_prefix="cli_manage")
    run()


if __name__ == "__main__":
    main()
