import keyboard
import os
import sys
import threading
from mapper_module.utils import DEFAULT_ADB_RATE_CAP, DEFAULT_KEY_DEBOUNCE
from mapper_module import (
    MapperEventDispatcher, 
    TOML_PATH, 
    AppConfig, 
    JSON_Loader, 
    TouchReader, 
    InterceptionBridge, 
    Mapper, 
    MouseMapper, 
    KeyMapper, 
    WASDMapper
)

def main():
    print("[System] Initializing Mapper... Press 'ESC' at any time to Stop.")

    # --- Argument Parsing ---
    # Usage: python main.py [rate_cap] [debounce_time]
    # Example: python main.py 500 0.005
    try:
        # Default to utils.py values if args are missing
        rate_cap = float(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_ADB_RATE_CAP
        debounce = float(sys.argv[2]) if len(sys.argv) > 2 else DEFAULT_KEY_DEBOUNCE
    except ValueError:
        print("[!] Invalid command line arguments. Falling back to defaults.")
        rate_cap, debounce = DEFAULT_ADB_RATE_CAP, DEFAULT_KEY_DEBOUNCE

    print(f"[Config] ADB Rate Cap: {rate_cap}Hz | Key Debounce: {debounce*1000}ms")

    # 1. Initialize Core Systems
    mapper_event_dispatcher = MapperEventDispatcher()
    config = AppConfig(TOML_PATH, mapper_event_dispatcher)

    # 2. Initialize Bridge & Loader
    interception_bridge = InterceptionBridge()
    json_loader = JSON_Loader(config)

    # 3. Initialize Touch Reader
    # Passing the custom rate_cap from sys.argv
    touch_reader = TouchReader(config, mapper_event_dispatcher, adb_rate_cap=rate_cap)

    # 4. Initialize Mappers
    # The 'mapper' object tracks the game window
    mapper_logic = Mapper(json_loader, touch_reader.res_dpi, interception_bridge)

    # Initialize sub-mappers
    MouseMapper(mapper_logic)
    # Passing the custom debounce from sys.argv
    KeyMapper(mapper_logic, debounce_time=debounce)
    WASDMapper(mapper_logic)

    # 5. Shutdown Logic
    def shutdown():
        print("\n[System] ESC detected. Cleaning up...")

        # Stop the window tracking thread in Mapper
        mapper_logic.running = False

        # Stop the ADB stream in TouchReader
        touch_reader.stop()

        # Release all currently held keys to prevent "sticky keys" on exit
        interception_bridge.release_all()

        print("[System] Shutdown complete. Goodbye.")
        os._exit(0) # Force exit all threads

    # Register the escape key
    keyboard.add_hotkey('esc', shutdown)

    # 6. Keep Main Thread Alive
    keyboard.wait('esc')

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        os._exit(0)
