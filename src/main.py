import keyboard
import sys
import os
import win32gui
import threading
import time
from mapper_module.utils import DEFAULT_ADB_RATE_CAP, KEY_DEBOUNCE, PPS, UP, SHORT_DELAY, set_high_priority

from mapper_module import (
    MapperEventDispatcher, 
    AppConfig, 
    JSON_Loader, 
    TouchReader, 
    InterceptionBridge, 
    Mapper, 
    MouseMapper, 
    KeyMapper, 
    WASDMapper,
)

FOREGROUND_WINDOW = win32gui.GetForegroundWindow()

interception_bridge = None
mapper_logic = None
mouse_mapper = None
key_mapper = None
wasd_mapper = None
is_visible = True
lock = threading.Lock()
is_shutting_down = False


def set_is_visible(_is_visible):
    global is_visible

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
    with lock:
        mapper_logic.event_count += 1 # Tick the counter

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
        
    
def main():
    global mouse_mapper, key_mapper, wasd_mapper, interception_bridge, mapper_logic   

    # --- Elevate Main Process (ADB Parsing & Logic) ---
    # We leave this on default cores (usually all but the last)
    set_high_priority(os.getpid(), "Main Loop")

    print("[System] Initializing Dual-Engine Mapper... Press 'ESC' to Stop.")

    try:
        rate_cap = float(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_ADB_RATE_CAP
        pps  = int(sys.argv[2]) if len(sys.argv) > 2 else PPS
    except ValueError:
        rate_cap, pps = DEFAULT_ADB_RATE_CAP, PPS

    mapper_event_dispatcher = MapperEventDispatcher()
    config = AppConfig(mapper_event_dispatcher)

    # Initialize Bridge (This spawns TWO processes: k_proc and m_proc)
    interception_bridge = InterceptionBridge()
    
    if hasattr(interception_bridge, 'm_proc'):
        set_high_priority(interception_bridge.m_proc.pid, "Mouse")
        
    if hasattr(interception_bridge, 'k_proc'):
        set_high_priority(interception_bridge.k_proc.pid, "Keyboard")
    time.sleep(SHORT_DELAY)

    json_loader = JSON_Loader(config, FOREGROUND_WINDOW)
    touch_reader = TouchReader(config, mapper_event_dispatcher, rate_cap)
    mapper_logic = Mapper(json_loader, touch_reader, interception_bridge, pps)

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
        if interception_bridge:
            interception_bridge.release_all()
        os._exit(0)