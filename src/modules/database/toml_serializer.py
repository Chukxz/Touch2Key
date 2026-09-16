from __future__ import annotations

from pathlib import Path
import tomlkit
from modules.database import store
from modules.utils import TOML_PATH


def export_settings_to_toml(target_path: Path = TOML_PATH) -> Path:
    """Exports current app_settings and active layout metadata to a TOML file."""
    s = store.settings.get()
    active_layout = store.get_active_layout()

    doc = tomlkit.document()

    # System Section
    system_table = tomlkit.table()
    system_table.add("left_handed", bool(s.left_handed))
    system_table.add("json_dev_width", active_layout.width if active_layout else s.json_dev_width)
    system_table.add("json_dev_height", active_layout.height if active_layout else s.json_dev_height)
    system_table.add("json_dev_dpi", active_layout.dpi if active_layout else s.json_dev_dpi)
    system_table.add("image_path", active_layout.image_path if active_layout else "")
    doc.add("system", system_table)

    # Performance / Polling
    perf_table = tomlkit.table()
    perf_table.add("adb_rate_cap", float(s.adb_rate_cap))
    perf_table.add("pps_alert_threshold", float(s.pps_alert_threshold))
    doc.add("performance", perf_table)

    # Joystick Settings
    joy_table = tomlkit.table()
    joy_table.add("deadzone", float(s.deadzone))
    joy_table.add("hysteresis", float(s.hysteresis))
    joy_table.add("anchored_floating_joystick", bool(s.anchored_floating_joystick))
    joy_table.add("joystick_snap_radius", float(s.joystick_snap_radius))
    doc.add("joystick", joy_table)

    # Mouse / Aim
    mouse_table = tomlkit.table()
    mouse_table.add("sensitivity", float(s.sensitivity))
    doc.add("mouse", mouse_table)

    # Keys / Hotkeys
    keys_table = tomlkit.table()
    keys_table.add("toggle_key", s.toggle_key or "")
    keys_table.add("sprint_key", s.sprint_key or "")
    doc.add("keys", keys_table)

    target_path.parent.mkdir(parents=True, exist_ok=True)
    with open(target_path, "w", encoding="utf-8") as f:
        f.write(tomlkit.dumps(doc))

    return target_path


def import_settings_from_toml(source_path: Path = TOML_PATH) -> bool:
    """Imports settings from a TOML file and updates SQLite app_settings."""
    if not source_path.exists():
        return False

    with open(source_path, "r", encoding="utf-8") as f:
        doc = tomlkit.load(f)

    updates = {}

    if "system" in doc:
        sys_sec = doc["system"]
        if "left_handed" in sys_sec:
            updates["left_handed"] = int(bool(sys_sec["left_handed"]))
        if "json_dev_width" in sys_sec:
            updates["json_dev_width"] = int(sys_sec["json_dev_width"])
        if "json_dev_height" in sys_sec:
            updates["json_dev_height"] = int(sys_sec["json_dev_height"])
        if "json_dev_dpi" in sys_sec:
            updates["json_dev_dpi"] = int(sys_sec["json_dev_dpi"])

    if "performance" in doc:
        perf_sec = doc["performance"]
        if "adb_rate_cap" in perf_sec:
            updates["adb_rate_cap"] = float(perf_sec["adb_rate_cap"])
        if "pps_alert_threshold" in perf_sec:
            updates["pps_alert_threshold"] = float(perf_sec["pps_alert_threshold"])

    if "joystick" in doc:
        joy_sec = doc["joystick"]
        if "deadzone" in joy_sec:
            updates["deadzone"] = float(joy_sec["deadzone"])
        if "hysteresis" in joy_sec:
            updates["hysteresis"] = float(joy_sec["hysteresis"])
        if "anchored_floating_joystick" in joy_sec:
            updates["anchored_floating_joystick"] = int(bool(joy_sec["anchored_floating_joystick"]))
        if "joystick_snap_radius" in joy_sec:
            updates["joystick_snap_radius"] = float(joy_sec["joystick_snap_radius"])

    if "mouse" in doc:
        mouse_sec = doc["mouse"]
        if "sensitivity" in mouse_sec:
            updates["sensitivity"] = float(mouse_sec["sensitivity"])

    if "keys" in doc:
        keys_sec = doc["keys"]
        if "toggle_key" in keys_sec:
            updates["toggle_key"] = str(keys_sec["toggle_key"])
        if "sprint_key" in keys_sec:
            updates["sprint_key"] = str(keys_sec["sprint_key"])

    if updates:
        store.settings.update(**updates)
        return True

    return False
