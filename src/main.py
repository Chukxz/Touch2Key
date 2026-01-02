import keyboard
import os
import sys
import threading
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
    
    # 1. Initialize Core Systems
    mapper_event_dispatcher = MapperEventDispatcher()
    config = AppConfig(TOML_PATH, mapper_event_dispatcher)
    
    # 2. Initialize Bridge & Loader
    interception_bridge = InterceptionBridge()
    json_loader = JSON_Loader(config)
    
    # 3. Initialize Touch Reader
    # We pass the config so it knows the resolution/DPI
    touch_reader = TouchReader(config)

    # 4. Initialize Mappers
    # The 'mapper' object tracks the game window
    mapper_logic = Mapper(json_loader, touch_reader.res_dpi, interception_bridge)
    
    # Initialize sub-mappers (they register themselves to the dispatcher)
    MouseMapper(mapper_logic)
    KeyMapper(mapper_logic)
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
    # Since TouchReader and Mapper run in daemon threads, 
    # we need the main thread to wait here.
    keyboard.wait('esc')

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        os._exit(0)