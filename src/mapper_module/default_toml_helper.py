import tomlkit
from tomlkit import document, table, comment

def create_default_toml():
    # Create the main document
    doc = document()

    # --- [system] Section ---
    # Create a table (section)
    sys_table = table()
    sys_table.add("circ_csv_path", "")
    sys_table["circ_csv_path"].comment("Path to the CSV file defining circular zones")
    
    sys_table.add("rect_csv_path", "")
    sys_table["rect_csv_path"].comment("Path to the CSV file defining rectangular zones")
    
    sys_table.add("circ_csv_dev_res", (None, None))
    sys_table.add("circ_csv_dev_dpi", None)
    sys_table.add("circ_csv_dev_name", "")
    
    sys_table.add("rect_csv_dev_res", (None, None))
    sys_table.add("rect_csv_dev_dpi", None)
    sys_table.add("rect_csv_dev_name", "")
        
    # Add it to the doc
    doc.add("system", sys_table)

    # --- [key] Section ---
    key_table = table()
    
    key_table.add("mouse_wheel_mapping_code", "")
    
    doc.add("key", key_table)

    # --- [mouse] Section ---
    mouse_table = table()

    # Add the block of comments preceding the sensitivity key
    # We attach these comments to the key itself for better formatting
    mouse_table.add("sensitivity", 15.0)
    mouse_table["sensitivity"].comment(
        "The \"Magic Number\" multiplier\n"
        "SENSITIVITY CONSTANT\n"
        "Adjust this multiplier to tune how fast the camera turns\n"
        "roughly: 1.0 means \"1 DP unit = 1 Mouse Mickey\""
    )

    mouse_table.add("invert_y", False)
    mouse_table["invert_y"].comment("Invert Y axis? (True/False)")

    doc.add("mouse", mouse_table)


    # --- [joystick] Section ---
    joy_table = table()

    joy_table.add("deadzone", 0.15)
    joy_table["deadzone"].comment("Deadzone (0.0 - 1.0)")

    joy_table.add("hysteresis", 5.0)
    joy_table["hysteresis"].comment("Hysteresis Angle (Degrees)")

    joy_table.add("fixed_center", False)
    joy_table["fixed_center"].comment("Fixed or Dynamic joystick center? (True/False)")

    doc.add("joystick", joy_table)


    # Write to file
    with open("settings.toml", "w") as f:
        f.write(tomlkit.dumps(doc))

    print("settings.toml created successfully.")