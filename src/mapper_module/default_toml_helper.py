import tomlkit
import os

# We need to know where settings.toml lives
# Assuming this file is in src/mapper_module/
CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
SRC_DIR = os.path.dirname(CURRENT_DIR)
PROJECT_ROOT = os.path.dirname(SRC_DIR)
TOML_PATH = os.path.join(PROJECT_ROOT, "settings.toml")

def create_default_toml():
    """Creates a fresh settings.toml if one is missing or corrupted."""
    if os.path.exists(TOML_PATH):
        return

    doc = tomlkit.document()
    
    # [system]
    system = tomlkit.table()
    system.add("hud_image_path", "resources/images/screenshot.png")
    system.add("json_path", "resources/jsons/layout.json")
    system.add("json_dev_res", [2400, 1080]) # Default resolution
    system.add("json_dev_dpi", 160)
    doc.add("system", system)

    # [mouse]
    mouse = tomlkit.table()
    mouse.add("sensitivity", 1.0)
    mouse.add("invert_y", False)
    doc.add("mouse", mouse)

    # [joystick]
    joystick = tomlkit.table()
    joystick.add("deadzone", 0.1)
    joystick.add("hysteresis", 5.0)
    joystick.add("mouse_wheel_radius", 0.0) # Will be auto-filled by plotter
    joystick.add("sprint_distance", 0.0)    # Will be auto-filled by plotter
    doc.add("joystick", joystick)

    try:
        with open(TOML_PATH, "w", encoding="utf-8") as f:
            tomlkit.dump(doc, f)
        print(f"[System] Created default settings.toml at {TOML_PATH}")
    except Exception as e:
        print(f"[Error] Failed to create settings.toml: {e}")