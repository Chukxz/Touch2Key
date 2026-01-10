import keyboard
import os
import sys
import psutil  # Required for priority
from mapper_module.utils import DEFAULT_ADB_RATE_CAP, DEFAULT_KEY_DEBOUNCE
from mapper_module import (
    MapperEventDispatcher, 
    AppConfig, 
    JSON_Loader, 
    TouchReader, 
    InterceptionBridge, 
    Mapper, 
    MouseMapper, 
    KeyMapper, 
    WASDMapper
)

def set_high_priority(pid=None):
    """Sets a process to High Priority and pins it to specific CPU cores."""
    try:
        p = psutil.Process(pid or os.getpid())
        
        # 1. Set Windows Process Priority to HIGH
        p.nice(psutil.HIGH_PRIORITY_CLASS)
        
        # 2. CPU Affinity (Optional but recommended)
        # Pinning the Bridge to the last core and the Main loop to others 
        # prevents 'Context Switching' lag.
        cores = list(range(psutil.cpu_count()))
        if len(cores) > 1:
            if pid: # If this is the Bridge Process
                p.cpu_affinity([cores[-1]]) # Use last core
            else: # If this is the Main Process
                p.cpu_affinity(cores[:-1]) # Use all cores except the last
                
        state = "Main" if pid is None else "Bridge"
        print(f"[Priority] {state} Process (PID: {p.pid}) set to HIGH.")
    except Exception as e:
        print(f"[Priority] Warning: Could not set priority for {pid or 'Main'}: {e}")

def main():
    # --- 1. Elevate Main Process ---
    set_high_priority()

    print("[System] Initializing Mapper... Press 'ESC' at any time to Stop.")

    try:
        rate_cap = float(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_ADB_RATE_CAP
        debounce = float(sys.argv[2]) if len(sys.argv) > 2 else DEFAULT_KEY_DEBOUNCE
    except ValueError:
        rate_cap, debounce = DEFAULT_ADB_RATE_CAP, DEFAULT_KEY_DEBOUNCE

    # 2. Initialize Core Systems
    mapper_event_dispatcher = MapperEventDispatcher()
    config = AppConfig(mapper_event_dispatcher)

    # 3. Initialize Bridge (This spawns the worker process)
    interception_bridge = InterceptionBridge()
    
    # --- 4. Elevate Bridge Process ---
    # We target the .process.pid we created inside InterceptionBridge
    if hasattr(interception_bridge, 'process'):
        set_high_priority(interception_bridge.process.pid)

    json_loader = JSON_Loader(config)
    touch_reader = TouchReader(config, mapper_event_dispatcher, adb_rate_cap=rate_cap)

    mapper_logic = Mapper(json_loader, touch_reader.res_dpi, interception_bridge)

    MouseMapper(mapper_logic)
    KeyMapper(mapper_logic, debounce_time=debounce)
    WASDMapper(mapper_logic)

    def shutdown():
        print("\n[System] ESC detected. Cleaning up...")
        mapper_logic.running = False
        touch_reader.stop()
        
        # Important: Release keys before the bridge process is killed
        try:
            interception_bridge.release_all()
        except: pass

        print("[System] Shutdown complete. Goodbye.")
        os._exit(0)

    keyboard.add_hotkey('esc', shutdown)
    keyboard.wait('esc')

if __name__ == "__main__":
    # Multiprocessing on Windows requires this check to avoid spawn loops
    try:
        main()
    except KeyboardInterrupt:
        os._exit(0)