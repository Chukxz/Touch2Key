import keyboard
import os
import sys
import psutil
from mapper_module.utils import DEFAULT_ADB_RATE_CAP, DEFAULT_KEY_DEBOUNCE, DEFAULT_LATENCY_THRESHOLD
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

mouse_mapper = None
key_mapper = None
wasd_mapper = None

def set_high_priority(pid, label, priority_level=psutil.HIGH_PRIORITY_CLASS):
    try:
        p = psutil.Process(pid)
        p.nice(priority_level)
        p.cpu_affinity(list(range(psutil.cpu_count())))
        
        print(f"[Priority] {label} set to HIGH (Floating Affinity)")
    except Exception as e:
        print(f"[Priority] Warning: {e}")


def process_touch_event(action, event):
    global mouse_mapper, key_mapper, wasd_mapper
    
    if event.is_mouse and mouse_mapper is not None:
        mouse_mapper.process_touch(action, event)
           
    if event.is_key and key_mapper is not None:
        key_mapper.process_touch(action, event)

    if event.is_wasd and wasd_mapper is not None:
        wasd_mapper.process_touch(action, event)
        
            
def main():
    global mouse_mapper, key_mapper, wasd_mapper    

    # --- Elevate Main Process (ADB Parsing & Logic) ---
    # We leave this on default cores (usually all but the last)
    set_high_priority(os.getpid(), "Main Loop")

    print("[System] Initializing Dual-Engine Mapper... Press 'ESC' to Stop.")

    try:
        rate_cap = float(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_ADB_RATE_CAP
        debounce = float(sys.argv[2]) if len(sys.argv) > 2 else DEFAULT_KEY_DEBOUNCE
        latency  = float(sys.argv[3]) if len(sys.argv) > 3 else DEFAULT_LATENCY_THRESHOLD
    except ValueError:
        rate_cap, debounce, latency = DEFAULT_ADB_RATE_CAP, DEFAULT_KEY_DEBOUNCE, DEFAULT_LATENCY_THRESHOLD

    mapper_event_dispatcher = MapperEventDispatcher()
    config = AppConfig(mapper_event_dispatcher)

    # Initialize Bridge (This spawns TWO processes: k_proc and m_proc)
    interception_bridge = InterceptionBridge()
    
    if hasattr(interception_bridge, 'm_proc'):
        set_high_priority(interception_bridge.m_proc.pid, "Mouse")
        
    if hasattr(interception_bridge, 'k_proc'):
        set_high_priority(interception_bridge.k_proc.pid, "Keyboard")

    json_loader = JSON_Loader(config)
    touch_reader = TouchReader(config, mapper_event_dispatcher, rate_cap, latency)

    mapper_logic = Mapper(json_loader, touch_reader.res_dpi, interception_bridge)

    mouse_mapper = MouseMapper(mapper_logic)
    key_mapper = KeyMapper(mapper_logic, debounce_time=debounce)
    wasd_mapper = WASDMapper(mapper_logic)
    
    touch_reader.bind_touch_event(process_touch_event)

    def shutdown():
        print("\n[System] 'ESC' detected. Cleaning up...")
        mapper_logic.running = False
        touch_reader.stop()
        
        # Clean up keys on both processes through the bridge
        try:
            interception_bridge.release_all()
        except: pass

        print("[System] Shutdown complete. Goodbye.")
        os._exit(0)

    keyboard.add_hotkey('esc', shutdown)
    keyboard.wait('esc')

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        os._exit(0)