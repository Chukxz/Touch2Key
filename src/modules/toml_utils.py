import os
import tomlkit
from pathlib import Path

from modules.utils import TOML_PATH

def create_default_toml():
    print(f"\n[UTILITY] - Resetting '{TOML_PATH}' to default.")
    doc = tomlkit.document()

    system = tomlkit.table()
    system.add("left_handed", False)
    system.add("image_path", "")
    system.add("json_path", "")
    system.add("json_dev_res", [360, 800])
    system.add("json_dev_dpi", 160)
    doc.add("system", system)

    mouse = tomlkit.table()
    mouse.add("sensitivity", 1.0)
    doc.add("mouse", mouse)

    joystick = tomlkit.table()
    joystick.add("deadzone", 0.1)
    joystick.add("hysteresis", 5.0)
    joystick.add("mouse_wheel_radius", 50.0)
    joystick.add("sprint_distance", 10.0)
    doc.add("joystick", joystick)

    keys = tomlkit.table()
    keys.add("toggle_key", "")
    keys.add("sprint_key", "")
    doc.add("keys", keys)

    try:
        with open(TOML_PATH, "w", encoding="utf-8", newline="") as f:
            tomlkit.dump(doc, f)
        print(f"\n[UTILITY] - Successfully created settings.toml at '{TOML_PATH}'.")
    except Exception as e:
        print(f"\n[UTILITY] - Failed to create settings.toml: {e}.")


def get_keys_from_toml() -> tuple[str | None, str | None]:
    try:
        if not TOML_PATH.exists():
            return None, None
        with open(TOML_PATH, "r", encoding="utf-8", newline="") as f:
            doc = tomlkit.load(f)
        keys = doc.get("keys", {})
        toggle = keys.get("toggle_key") or None
        sprint = keys.get("sprint_key") or None
        return toggle, sprint
    except Exception:
        return None, None


def update_toml_keys(toggle_key: str | None, sprint_key: str | None):
    try:
        if not TOML_PATH.exists():
            create_default_toml()
        with open(TOML_PATH, "r", encoding="utf-8", newline="") as f:
            doc = tomlkit.load(f)
        if "keys" not in doc:
            doc.append("keys", tomlkit.table())
        doc["keys"]["toggle_key"] = toggle_key or ""
        doc["keys"]["sprint_key"] = sprint_key or ""
        with open(TOML_PATH, "w", encoding="utf-8", newline="") as f:
            tomlkit.dump(doc, f)
    except Exception as e:
        print(f"\n[UTILITY] - Could not save key config: {e}.")


def update_toml(
    w=None,
    h=None,
    dpi=None,
    image_path=None,
    json_path=None,
    mouse_wheel_radius=None,
    sprint_distance=None,
    strict=False,
):
    try:
        if not os.path.exists(TOML_PATH):
            create_default_toml()

        with open(TOML_PATH, "r", encoding="utf-8", newline="") as f:
            doc = tomlkit.load(f)

        table_keys = doc.keys()

        if "joystick" not in doc:
            doc.append("joystick", tomlkit.table())
        joystick = doc["joystick"]

        if "system" not in table_keys:
            doc.append("system", tomlkit.table())
        system = doc["system"]

        if mouse_wheel_radius is not None:
            joystick.update({"mouse_wheel_radius": mouse_wheel_radius})
        if sprint_distance is not None:
            joystick.update({"sprint_distance": sprint_distance})

        if w and h:
            system.update({"json_dev_res": [w, h]})
        if dpi:
            system.update({"json_dev_dpi": dpi})

        i_path = Path(image_path).as_posix() if image_path else ""
        if image_path is not None:
            system.update({"image_path": i_path})

        j_path = Path(json_path).as_posix() if json_path else ""
        if json_path is not None:
            system.update({"json_path": j_path})

        with open(TOML_PATH, "w", encoding="utf-8", newline="") as f:
            tomlkit.dump(doc, f)

    except Exception as e:
        if os.path.exists(TOML_PATH):
            os.replace(TOML_PATH, str(TOML_PATH) + ".bak")
            print("\n[UTILITY] - Settings were corrupted and reset. Backup created.")
        create_default_toml()
        if strict:
            raise e
        else:
            print(f"\n[UTILITY] - Could not update Toml: {e}.")
