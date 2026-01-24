from __future__ import annotations

import keyboard
import os
import win32gui
import threading
import time
from mapper_module.utils import (
    DEFAULT_ADB_RATE_CAP, SHORT_DELAY,
    PPS, EMULATORS, ADB_EXE, UP,
    DEF_EMULATOR_ID, TouchEvent,
    set_high_priority, stop_process,
    maintain_bridge_health
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
        with interception_bridge.bridge_lock:
            maintain_bridge_health(interception_bridge)
        mouse_mapper.touch_up()
        key_mapper.release_all()
        wasd_mapper.touch_up()


def process_touch_event(action, touch_event: TouchEvent):
    local_visible = is_visible
    mapper_logic.event_count += 1
    
    if touch_event.is_mouse:
        mouse_mapper.process_touch(action, touch_event, local_visible)
        
    key_mapper.process_touch(action, touch_event, local_visible)
        
    if touch_event.is_wasd:
        wasd_mapper.process_touch(action, touch_event, is_visible)
        

def select_emulator():
    print("Touch2Key Emulator Selector")
    emulators_list = list(EMULATORS.keys())
    emulators_len = len(emulators_list)
    
    if emulators_len == 0:
        return None

    print("Supported Emulators:")
    for id, name in enumerate(emulators_list):
        print(f"ID: [{id}] Name: {name}")

    try:
        choice = input(f"Select Emulator ID [Default {emulators_list[DEF_EMULATOR_ID]}]: ").strip()
        if not choice:
            emulator_id = DEF_EMULATOR_ID
        else:
            emulator_id = int(choice)
            # Boundary Check
            if not (0 <= emulator_id < emulators_len):
                print(f"[!] ID {emulator_id} out of range. Using default.")
                emulator_id = DEF_EMULATOR_ID
    except ValueError:
        print("[!] Invalid input. Using defaults.")
        emulator_id = DEF_EMULATOR_ID

    emulator_name = emulators_list[emulator_id]
    print(f"[Config] {emulator_name} selected.")
    return EMULATORS[emulator_name]
   
    
def main():
    global mouse_mapper, key_mapper, wasd_mapper, interception_bridge, mapper_logic, touch_reader
    keyboard.add_hotkey('esc', shutdown)

    # Elevate Main Process (ADB Parsing & Logic)
    # We leave this on default cores (usually all but the last)
    set_high_priority(os.getpid(), "Main Loop")

    print("[System] Initializing Dual-Engine Mapper... Press 'ESC' to Stop.")
    print(f"ADB Executable File Path: {ADB_EXE}")
    
    emulator = select_emulator()
    if emulator is None:
        print("No emulators supported. Exiting")
        return
    
    try:
        # Rate Cap (The actual hardware limit)
        rate_input = input(f"Enter ADB rate cap [Default {DEFAULT_ADB_RATE_CAP}, Min 60, Blank for Default]: ").strip()
        rate_cap = max(60.0, float(rate_input)) if rate_input else DEFAULT_ADB_RATE_CAP

        # PPS Threshold (The notification trigger)
        pps_input = input(f"Enter target PPS for health alerts [Default {PPS}, Range 30-120]: ").strip()
        pps = max(30.0, min(120.0, float(pps_input))) if pps_input else PPS

    except ValueError:
        print("[!] Invalid input. Using defaults.")
        rate_cap, pps = DEFAULT_ADB_RATE_CAP, PPS

    print(f"[Config] ADB Cap: {rate_cap}Hz | Alert Threshold: {pps}PPS")

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
    mapper_logic = Mapper(json_loader, touch_reader, interception_bridge, pps, emulator)

    mouse_mapper = MouseMapper(mapper_logic)
    key_mapper = KeyMapper(mapper_logic)
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