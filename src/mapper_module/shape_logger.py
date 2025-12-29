import math
from pynput import mouse as pynmouse, keyboard as pynkeyboard
from utils import SCANCODES

# --- Pynput Translation Maps ---
# Map Special Key Objects to Scancode Keys
SPECIAL_KEY_MAP = {
    pynkeyboard.Key.space: "SPACE",
    pynkeyboard.Key.enter: "ENTER",
    pynkeyboard.Key.backspace: "BACKSPACE",
    pynkeyboard.Key.tab: "TAB",
    pynkeyboard.Key.esc: "ESC",
    pynkeyboard.Key.caps_lock: "CAPSLOCK",
    pynkeyboard.Key.shift: "LSHIFT",
    pynkeyboard.Key.shift_l: "LSHIFT",
    pynkeyboard.Key.shift_r: "RSHIFT",
    pynkeyboard.Key.ctrl: "LCTRL",
    pynkeyboard.Key.ctrl_l: "LCTRL",
    pynkeyboard.Key.ctrl_r: "RCTRL",
    pynkeyboard.Key.alt: "LALT",
    pynkeyboard.Key.alt_l: "LALT",
    pynkeyboard.Key.alt_r: "RALT",
    # Arrows (Extended)
    pynkeyboard.Key.up: "E0_UP",
    pynkeyboard.Key.down: "E0_DOWN",
    pynkeyboard.Key.left: "E0_LEFT",
    pynkeyboard.Key.right: "E0_RIGHT",
    # F-Keys
    pynkeyboard.Key.f1: "F1", pynkeyboard.Key.f2: "F2", pynkeyboard.Key.f3: "F3", pynkeyboard.Key.f4: "F4",
    pynkeyboard.Key.f5: "F5", pynkeyboard.Key.f6: "F6", pynkeyboard.Key.f7: "F7", pynkeyboard.Key.f8: "F8",
    pynkeyboard.Key.f9: "F9", pynkeyboard.Key.f10: "F10", pynkeyboard.Key.f11: "F11", pynkeyboard.Key.f12: "F12",
    pynkeyboard.Key.delete: "E0_DELETE", pynkeyboard.Key.insert: "E0_INSERT", pynkeyboard.Key.home: "E0_HOME",
    pynkeyboard.Key.end: "E0_END", pynkeyboard.Key.page_up: "E0_PAGEUP", pynkeyboard.Key.page_down: "E0_PAGEDOWN",
    pynkeyboard.Key.up: "E0_UP", pynkeyboard.Key.down: "E0_DOWN", pynkeyboard.Key.left: "E0_LEFT", pynkeyboard.Key.right: "E0_RIGHT",
    pynkeyboard.Key.caps_lock: "CAPSLOCK", pynkeyboard.Key.num_lock: "NUMLOCK", pynkeyboard.Key.scroll_lock: "SCROLLLOCK",
}

# Map Punctuation Characters to Scancode Keys
SYMBOL_CHAR_MAP = {
    "-": "MINUS", "=": "EQUAL", "[": "LEFT_BRACKET", "]": "RIGHT_BRACKET",
    ";": "SEMICOLON", "'": "APOSTROPHE", "`": "GRAVE", "\\": "BACKSLASH",
    ",": "COMMA", ".": "DOT", "/": "SLASH"
}

class GetShapes():
    def __init__(self):
        self.count = 0
        self.shapes = {}
        self.exit_key = pynkeyboard.Key.esc
        self.points = []
        self.mode = None
        
    def is_normal_key(self, key):
        """Returns string representation of the key if valid, else None"""
        if hasattr(key, 'char') and key.char is not None:
            return key.char
        else:
            # Clean up key names like 'Key.space' -> 'Space'
            return str(key).replace('Key.', '').title()
        
    def get_interception_code(self, pynput_key):
        """
        Takes a raw pynput key object and returns the Interception str scancode.
        Returns None if the key is not found.
        """
        scancode_key_name = None

        # Case A: It's a Character (Letters, Numbers, Symbols)
        if hasattr(pynput_key, 'char') and pynput_key.char is not None:
            char = pynput_key.char
            
            # 1. Alphanumeric? (a-z, 0-9) -> Use directly
            if char.isalnum():
                scancode_key_name = char.lower()
            # 2. Symbol? (., [, /) -> Lookup name
            elif char in SYMBOL_CHAR_MAP:
                scancode_key_name = SYMBOL_CHAR_MAP[char]

        # Case B: It's a Special Key (Shift, Enter, F1)
        else:
            if pynput_key in SPECIAL_KEY_MAP:
                scancode_key_name = SPECIAL_KEY_MAP[pynput_key]

        # Final Lookup
        if scancode_key_name and scancode_key_name in SCANCODES:
            return scancode_key_name
        
        print(f"[!] Warning: No mapping found for {pynput_key}")
        return None

    def get_mapping_code(self):
            """
            Blocks and waits for a key, then returns its Interception Scancode (str).
            """
            print("   >>> PRESS A KEY TO BIND (Input Suppressed) <<<")
            
            captured_data = {'scancode_str': None, 'name': None}

            def on_press(key):
                # 1. Convert to Scancode
                scancode_str = self.get_interception_code(key)
                
                if scancode_str is not None:
                    captured_data['scancode_str'] = scancode_str
                    # Just for display purposes:
                    captured_data['name'] = str(key).replace('Key.', '') 
                    return False # Stop listener
                else:
                    print("   [!] Unknown key, try another.")
                    # We return True to keep listening until a valid key is pressed
                    return True 

            with pynkeyboard.Listener(on_press=on_press, suppress=True) as listener:
                listener.join()
                
            print(f"   >>> BOUND TO: {captured_data['name']} (Scancode string: {captured_data['scancode_str']})")
            return captured_data['scancode_str']

    def encode_shape(self, shape_type, cx, cy, r, bb):
        # Get the key binding from user
        mapping_key = self.get_mapping_code()
        
        # Save the data
        entry =  {
            "m_code": mapping_key,
            "type": shape_type,
            "cx": cx,
            "cy": cy,
            "r": r,
            "bb": bb            
        }
        
        self.shapes[self.count] = entry
        self.count += 1
        
        # Reset State
        self.mode = None
        self.points = []
        print(f"   [Saved Shape #{self.count-1}]")
        print("------------------------------")

    # --- Math Functions ---
    def calculate_circle(self, p):
        x1, y1 = p[0]
        x2, y2 = p[1]
        x3, y3 = p[2]
        
        D = 2 * (x1 * (y2 - y3) + x2 * (y3 - y1) + x3 * (y1 - y2))
        
        if D == 0:
            print("\n[!] Error: Points are collinear.")
            return

        h = ((x1**2 + y1**2) * (y2 - y3) + (x2**2 + y2**2) * (y3 - y1) + (x3**2 + y3**2) * (y1 - y2)) / D
        k = ((x1**2 + y1**2) * (x3 - x2) + (x2**2 + y2**2) * (x1 - x3) + (x3**2 + y3**2) * (x2 - x1)) / D
        r = math.sqrt((x1 - h)**2 + (y1 - k)**2)
        
        print(f"\n>>> CIRCLE DETECTED <<<")
        print(f"Center: ({int(h)}, {int(k)}) | Radius: {int(r)}")
        
        # Pass to encoder (Mapping will be requested there)
        self.encode_shape("CIRCLE", int(h), int(k), int(r), None)

    def calculate_rect(self, p):
        xs = [pt[0] for pt in p]
        ys = [pt[1] for pt in p]
        
        x_min, x_max = min(xs), max(xs)
        y_min, y_max = min(ys), max(ys)
        
        center_x = int(sum(xs) / 4)
        center_y = int(sum(ys) / 4)
        
        print(f"\n>>> RECT/POLY DETECTED <<<")
        print(f"Center: ({center_x}, {center_y})")
        
        # Pass to encoder (Mapping will be requested there)
        self.encode_shape("RECT", center_x, center_y, None, ((x_min, y_min), (x_max, y_max)))
        
    def on_click(self, x, y, button, pressed):
        if not pressed and self.mode is not None:
            self.points.append((x, y))
            print(f"Point {len(self.points)} recorded: {x}, {y}")
            
            if self.mode == 'CIRCLE' and len(self.points) == 3:
                self.calculate_circle(self.points)
                
            elif self.mode == 'RECT' and len(self.points) == 4:
                self.calculate_rect(self.points)

    def on_key_release(self, key):        
        if key == pynkeyboard.Key.f6:
            self.mode = 'CIRCLE'
            self.points = []
            print(f"\n[MODE: CIRCLE] Click 3 points...")

        elif key == pynkeyboard.Key.f7:
            self.mode = 'RECT'
            self.points = []
            print(f"\n[MODE: RECTANGLE] Click 4 points...")
            
        elif key == pynkeyboard.Key.f8:
            if self.mode != None:
                self.mode = None
                self.points = []
                print("\n[X] CANCELLED.")
            else: print("\nNothing to cancel.")
        
        elif key == pynkeyboard.Key.f9:
            print("\n--- CURRENT SHAPES ---")
            for k, v in self.shapes.items():
                print(f"ID {k}: {v}")
            print("----------------------")

        elif key == self.exit_key:
            print("\nStopping Mapper...")
            return False 

    # --- Main Logic Function ---
    def run_input_mapper(self, exit_key=pynkeyboard.Key.esc):
        self.exit_key = exit_key
        print(f"--- Mapper Started ---")
        print(f"F6: Circle | F7: Rect | F8: Cancel | F9: Show Data | {self.exit_key.name}: Exit")

        # Start Mouse (Non-blocking)
        m_listener = pynmouse.Listener(on_click=self.on_click)
        m_listener.start()

        # Start Keyboard (Blocking)
        with pynkeyboard.Listener(on_release=self.on_key_release) as k_listener:
            k_listener.join()
        
        # Cleanup
        m_listener.stop()
        print("--- Mapper Stopped ---")

if __name__ == "__main__":    
    get_shapes = GetShapes()
    # Run directly in main thread for testing
    get_shapes.run_input_mapper()