from __future__ import annotations

import keyboard
import sys
import os
import win32gui
import threading
import time
from mapper_module.utils import (
    DEFAULT_ADB_RATE_CAP, KEY_DEBOUNCE, PPS, UP, SHORT_DELAY, GLP,
    EVENT_TYPE, TouchEvent, set_high_priority, stop_process
)

from mapper_module import (
    MapperEventDispatcher, 
    AppConfig, 
    JSONLoader, 
    TouchReader, 
    InterceptionBridge, 
    Mapper, 
    MouseMapper, 
    KeyMapper, 
    WASDMapper,
)


FOREGROUND_WINDOW = win32gui.GetForegroundWindow()

interception_bridge = None
touch_reader = None
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


def process_touch_event(action:EVENT_TYPE, touch_event:TouchEvent):    
    with lock:
        mapper_logic.event_count += 1 # Tick the counter

        try:                   
            if touch_event.is_mouse:
                mouse_mapper.process_touch(action, touch_event, is_visible)
            
            if not is_visible:
                if touch_event.is_key:
                    key_mapper.process_touch(action, touch_event)
                
                    if action == UP:
                        wasd_mapper.touch_up()
                    
                    if touch_event.is_wasd:
                        wasd_mapper.process_touch(action, touch_event) 
        except:
            pass
        
    
def main():
    global mouse_mapper, key_mapper, wasd_mapper, interception_bridge, mapper_logic, touch_reader
    keyboard.add_hotkey('esc', shutdown)

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

    json_loader = JSONLoader(config, FOREGROUND_WINDOW)
    touch_reader = TouchReader(config, mapper_event_dispatcher, interception_bridge, rate_cap)
    mapper_logic = Mapper(json_loader, touch_reader, interception_bridge, pps, GLP)

    mouse_mapper = MouseMapper(mapper_logic)
    key_mapper = KeyMapper(mapper_logic, KEY_DEBOUNCE)
    wasd_mapper = WASDMapper(mapper_logic)
        
    touch_reader.bind_touch_event(process_touch_event)
    mapper_event_dispatcher.register_callback("ON_MENU_MODE_TOGGLE", set_is_visible)
    keyboard.wait()
    

def shutdown():
    global is_shutting_down
    if not win32gui.GetForegroundWindow() == FOREGROUND_WINDOW:
        return
        
    if is_shutting_down:
        return
    is_shutting_down = True        
    
    print("\n[System] 'ESC' detected. Cleaning up...")
    
    # Clean up keys on both processes through the bridge
    try:
        print("Exiting all spawned threads...")
        touch_reader.stop()
        mapper_logic.running = False
        interception_bridge.release_all()
        print("Stopping Mouse and Keyboard child processes...")
        stop_process(interception_bridge.k_proc)
        stop_process(interception_bridge.m_proc)
    except:
        pass

    print("[System] Shutdown complete. Goodbye.")
    os._exit(0)

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        shutdown()