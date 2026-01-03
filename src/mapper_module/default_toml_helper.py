import tomlkit
from .utils import TOML_PATH

def create_default_toml():
    """Wipes the existing settings.toml and creates a fresh default configuration."""
    
    # Create the TOML structure in memory
    doc = tomlkit.document()
    
    # [system] - Core paths and hardware baseline
    system = tomlkit.table()
    system.add("device_nickname", "Default_Device")
    system.add("hud_image_path", "")
    system.add("json_path", "")
    system.add("json_dev_res", [2400, 1080]) # Default fallback resolution
    system.add("json_dev_dpi", 160)
    system.add("json_dev_name", "Device")
    doc.add("system", system)

    # [mouse] - Sensitivity settings
    mouse = tomlkit.table()
    mouse.add("sensitivity", 1.0)
    mouse.add("invert_y", False)
    doc.add("mouse", mouse)

    # [joystick] - Movement and radius settings
    joystick = tomlkit.table()
    joystick.add("deadzone", 0.1)
    joystick.add("hysteresis", 5.0)
    joystick.add("mouse_wheel_radius", 0.0)
    joystick.add("sprint_distance", 0.0)
    doc.add("joystick", joystick)

    try:
        # Opening with "w" automatically clears (truncates) the file before writing
        with open(TOML_PATH, "w", encoding="utf-8") as f:
            tomlkit.dump(doc, f)
        print(f"[System] Successfully reset and created settings.toml at {TOML_PATH}")
    except Exception as e:
        print(f"[Error] Failed to create settings.toml: {e}")