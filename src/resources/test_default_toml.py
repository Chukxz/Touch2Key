import tomlkit
from tomlkit import document, table
from pathlib import Path


def create_test_default_toml():
    # Create the main document
    doc = document()

    # --- [system] Section ---
    # Create a table (section)
    sys_table = table()
    sys_table.comment("Auto generated, edit at your own risk.")
        
    sys_table.add("hud_image_path", "./mp_hud.jpg")
    sys_table["hud_image_path"].comment("Path to the HUD image file.")
    
    sys_table.add("csv_path", "")
    sys_table["csv_path"].comment("Path to the CSV file defining mapping zones.")
    sys_table.add("csv_dev_res", (720, 1612))
    sys_table["csv_dev_res"].comment("Device resolution for the CSV file.")
    sys_table.add("csv_dev_dpi", 320)
    sys_table["csv_dev_dpi"].comment("Device DPI for the CSV file.")
    sys_table.add("csv_dev_name", "Chuksxz")
    sys_table["csv_dev_name"].comment("Device name for the CSV file.")

        
    doc.add("system", sys_table)

    # --- [key] Section ---
    key_table = table()
    key_table.comment("Auto generated, edit at your own risk.")
    key_table.add("mouse_wheel_mapping_code", "JOY")    
    doc.add("key", key_table)

    # --- [mouse] Section ---
    mouse_table = table()
    mouse_table.comment("Auto generated, edit at your own risk.")
    mouse_table.add("sensitivity", 15.0)
    mouse_table["sensitivity"].comment("Adjust this multiplier to tune how fast the camera turns, roughly: 1.0 means \"1 DP unit = 1 Mouse Mickey.")
    mouse_table.add("invert_y", False)
    doc.add("mouse", mouse_table)

    # --- [joystick] Section ---
    joy_table = table()
    joy_table.comment("Auto generated, edit at your own risk.")
    joy_table.add("deadzone", 0.15)
    joy_table["deadzone"].comment("Deadzone (0.0 - 1.0).")
    joy_table.add("hysteresis", 5.0)
    joy_table["hysteresis"].comment("Hysteresis Angle (Degrees).")
    joy_table.add("fixed_center", False)
    doc.add("joystick", joy_table)

    # Write to file
    with open(Path("../mapper_module/settings.toml").resolve(), "w") as f:
        f.write(tomlkit.dumps(doc))

    print("settings.toml created successfully.")

if __name__ == "__main__":
    create_test_default_toml()
    
