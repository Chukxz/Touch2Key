import keyboard
import os
import sys
import psutil
import win32gui
import threading
import time
from mapper_module.utils import DEFAULT_ADB_RATE_CAP, KEY_DEBOUNCE, DEFAULT_LATENCY_THRESHOLD, UP
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

FOREGROUND_WINDOW = win32gui.GetForegroundWindow()

interception_bridge = None
mouse_mapper = None
key_mapper = None
wasd_mapper = None
is_visible = True
lock = threading.Lock()
is_shutting_down = False

def set_high_priority(pid, label, priority_level=psutil.HIGH_PRIORITY_CLASS):
    try:
        p = psutil.Process(pid)
        p.nice(priority_level)
        p.cpu_affinity(list(range(psutil.cpu_count())))
        
        print(f"[Priority] {label} set to HIGH (Floating Affinity)")
    except Exception as e:
        print(f"[Priority] Warning: {e}")


def set_is_visible(_is_visible):
    global is_visible, lock, interception_bridge, mouse_mapper, key_mapper, wasd_mapper

    with lock:
        is_visible = _is_visible
        # Clean up keys and state
        try:
            interception_bridge.release_all()
            mouse_mapper.touch_up()
            key_mapper.release_all()
            wasd_mapper.release_all()
        except: pass


def process_touch_event(action, event):
    global mouse_mapper, key_mapper, wasd_mapper, is_visible
    
    if lock.acquire(blocking=False):
        try: 
            if event.is_mouse:
                mouse_mapper.process_touch(action, event, is_visible)
           
            if event.is_key:
                key_mapper.process_touch(action, event)
            
                if action == UP:
                    wasd_mapper.touch_up()
                   
                if event.is_wasd:
                    wasd_mapper.process_touch(action, event)

        except:
            pass
        finally:
            lock.release()
        
            
def main():
    global mouse_mapper, key_mapper, wasd_mapper, interception_bridge    

    # --- Elevate Main Process (ADB Parsing & Logic) ---
    # We leave this on default cores (usually all but the last)
    set_high_priority(os.getpid(), "Main Loop")

    print("[System] Initializing Dual-Engine Mapper... Press 'ESC' to Stop.")

    try:
        rate_cap = float(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_ADB_RATE_CAP
        latency  = float(sys.argv[2]) if len(sys.argv) > 2 else DEFAULT_LATENCY_THRESHOLD
    except ValueError:
        rate_cap, latency = DEFAULT_ADB_RATE_CAP, DEFAULT_LATENCY_THRESHOLD

    mapper_event_dispatcher = MapperEventDispatcher()
    config = AppConfig(mapper_event_dispatcher)

    # Initialize Bridge (This spawns TWO processes: k_proc and m_proc)
    interception_bridge = InterceptionBridge()
    
    if hasattr(interception_bridge, 'm_proc'):
        set_high_priority(interception_bridge.m_proc.pid, "Mouse")
        
    if hasattr(interception_bridge, 'k_proc'):
        set_high_priority(interception_bridge.k_proc.pid, "Keyboard")
    time.sleep(1)

    touch_reader = TouchReader(config, mapper_event_dispatcher, rate_cap, latency)
    json_loader = JSON_Loader(config, FOREGROUND_WINDOW)

    mapper_logic = Mapper(json_loader, touch_reader.res_dpi, interception_bridge)

    mouse_mapper = MouseMapper(mapper_logic)
    key_mapper = KeyMapper(mapper_logic, KEY_DEBOUNCE)
    wasd_mapper = WASDMapper(mapper_logic)
        
    touch_reader.bind_touch_event(process_touch_event)
    mapper_event_dispatcher.register_callback("ON_MENU_MODE_TOGGLE", set_is_visible)
    

    def shutdown():
        global is_shutting_down
        if not win32gui.GetForegroundWindow() == FOREGROUND_WINDOW:
            return
        
        if is_shutting_down:
            return
        is_shutting_down = True        
                
        print("\n[System] 'ESC' detected. Cleaning up...")
        mapper_logic.running = False
        touch_reader.stop()
        
        # Clean up keys on both processes through the bridge
        try:
            interception_bridge.release_all()
        except: pass

        print("[System] Shutdown complete. Goodbye.")
        os._exit(0)

    keyboard.add_hotkey('esc', shutdown, trigger_on_release=True)
    keyboard.wait()

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        os._exit(0)