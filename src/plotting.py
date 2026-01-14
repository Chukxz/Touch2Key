import matplotlib.pyplot as plt
from PIL import Image
import tomlkit
import math
import json
import os
import datetime
import ctypes
from mapper_module.utils import (
    CIRCLE, RECT, SCANCODES, IMAGES_FOLDER, JSONS_FOLDER, TOML_PATH, 
    MOUSE_WHEEL_CODE, SPRINT_DISTANCE_CODE, select_image_file
)
from mapper_module.default_toml_helper import create_default_toml

# --- Constants ---
IDLE = "IDLE"
COLLECTING = "COLLECTING"
WAITING_FOR_KEY = "WAITING_FOR_KEY"
DELETING = "DELETING"
CONFIRM_EXIT = "CONFIRM_EXIT"
NAMING = "NAMING"

SPECIAL_MAP = {
    "escape": "ESC", "enter": "ENTER", "backspace": "BACKSPACE", "tab": "TAB",
    "f1": "F1", "f2": "F2", "f3": "F3", "f4": "F4", "f5": "F5", "f6": "F6", 
    "f7": "F7", "f8": "F8", "f9": "F9", "f10": "F10", "f11": "F11", "f12": "F12",
    "=": "EQUAL", "-": "MINUS",
    "[": "LEFT_BRACKET", "]": "RIGHT_BRACKET",
    ";": "SEMICOLON", "'": "APOSTROPHE", "`": "GRAVE", "\\": "BACKSLASH",
    ",": "COMMA", ".": "DOT", "/": "SLASH",
    "shift": "LSHIFT", "alt": "LALT", "control": "LCTRL", " ": "SPACE",
    "caps_lock": "CAPSLOCK", "num_lock": "NUMLOCK", "scroll_lock": "SCROLLLOCK",
    "*": "NUM_MULTIPLY",
    "up": "E0_UP", "left": "E0_LEFT", "right": "E0_RIGHT", "down": "E0_DOWN",
    "insert": "E0_INSERT", "delete": "E0_DELETE",
}

class Plotter:
    def __init__(self, image_path=None):
        # 1. DPI Awareness MUST be first to ensure coordinates match the screen      
        try:
            ctypes.windll.shcore.SetProcessDpiAwareness(1) 
        except Exception:
            try: ctypes.windll.user32.SetProcessDPIAware()
            except: pass

        # 2. SMART PATH DETECTION
        if image_path is None:
            if os.path.exists(TOML_PATH):
                try:
                    with open(TOML_PATH, "r", encoding="utf-8") as f:
                        doc = tomlkit.load(f)
                        toml_img = doc.get("system", {}).get("hud_image_path", "")
                        if toml_img and os.path.exists(toml_img):
                            image_path = toml_img
                            print(f"[System] Auto-loading last HUD: {os.path.basename(image_path)}")
                except: pass

            if image_path is None:
                os.makedirs(IMAGES_FOLDER, exist_ok=True)
                print(f"[System] No active HUD found in config. Opening selector...")
                image_path = select_image_file(IMAGES_FOLDER)

        if not image_path:
            print("Exiting: No image selected.")
            return

        self.image_path = image_path

        # 3. GUI Configuration
        for key in plt.rcParams:
            if key.startswith('keymap.'):
                plt.rcParams[key] = []

        self.shapes = {}
        self.count = 0
        self.points = []          
        self.drawn_artists = []   
        self.mode = None          
        self.state = IDLE         
        self.target_points = 0
        self.input_buffer = ""
        self.saved_mouse_wheel = False
        self.saved_sprint_distance = False
        self.mouse_wheel_radius = 0.0
        self.mouse_wheel_cy = 0.0
        self.sprint_distance = 0.0

        try:
            img = Image.open(image_path)
        except Exception as e:
            raise RuntimeError(f"Error loading image: {e}")

        self.fig, self.ax = plt.subplots()
        self.ax.imshow(img)
        self.update_title("IDLE. F5 (Change Image) | F6(Circle) | F7(Rect) | F8(Remove) | F9(List) | F10(Save) | Esc(Exit).")

        self.fig.canvas.mpl_connect("key_press_event", self.on_key_press)
        self.fig.canvas.mpl_connect("button_press_event", self.on_click)

        plt.show()

    
    # --- Visual & State Management ---

    def update_title(self, text):
        self.ax.set_title(text)
        self.fig.canvas.draw()

    def clear_visuals(self):
        for artist in self.drawn_artists:
            artist.remove()
        self.drawn_artists = []
        self.fig.canvas.draw()

    def reset_state(self):
        self.clear_visuals()
        self.state = IDLE
        self.mode = None
        self.points = []
        self.input_buffer = ""
        self.update_title("IDLE. F5 (Change Image) | F6(Circle) | F7(Rect) | F8(Remove) | F9(List) | F10(Save) | F11(Sprint Threshold) | F12(Mouse Wheel) | Delete(Delete) | Esc(Exit).")

    def start_mode(self, mode, num_points):
        self.reset_state() 
        self.mode = mode
        self.target_points = num_points
        self.state = COLLECTING
        self.update_title(f"Mode: {mode}. Click {num_points} points on the image (F8 to Cancel).")

    def refresh_image():
        new_path = select_image_file(IMAGES_FOLDER)
        if new_path:
            self.image_path = new_path
        # Reload the image and refresh the plot
        img = Image.open(new_path)
        self.ax.clear()
        self.ax.imshow(img)
        self.reset_state()
        print(f"[System] Swapped HUD to: {os.path.basename(new_path)}")


    # --- Event Handlers ---

    def on_click(self, event):
        # 1. NEW: Handle Binding via Mouse Click
        if self.state == WAITING_FOR_KEY:
            # Matplotlib button codes: 1=Left, 2=Middle, 3=Right
            mouse_map = {
                1: "MOUSE_LEFT",
                2: "MOUSE_MIDDLE",
                3: "MOUSE_RIGHT"
            }
            
            button_name = mouse_map.get(event.button)
            
            if button_name:
                print(f"[-] Mouse Click Detected: {button_name}")
                self.finalize_shape(button_name)
            return

        # 2. Existing: Handle Drawing Points
        if self.state != COLLECTING:
            return
        
        if event.xdata is None or event.ydata is None:
            return

        self.points.append((int(event.xdata), int(event.ydata)))
        
        dot, = self.ax.plot(event.xdata, event.ydata, 'ro')
        self.drawn_artists.append(dot)
        self.fig.canvas.draw()

        remaining = self.target_points - len(self.points)
        if remaining > 0:
            self.update_title(f"Mode: {self.mode}. {remaining} points remaining.")
        else:
            self.state = WAITING_FOR_KEY
            self.update_title(f"Shape Defined! Press KEY or CLICK MOUSE to bind (F8 to Cancel).")

    def on_key_press(self, event):
        """Main Input Router."""
        
        if self.state == NAMING:
            self.handle_naming_input(event.key)
            return
        
        if self.state == DELETING:
            self.handle_delete_input(event.key)
            return

        if self.state == CONFIRM_EXIT:
            if event.key == 'enter':
                print("[-] Closing application.")
                plt.close()
            else:
                self.reset_state()
            return

        if self.state in [COLLECTING, WAITING_FOR_KEY]:
            if event.key == 'f8':
                print("[-] Action Cancelled.")
                self.reset_state()
                return
            
            if self.state == WAITING_FOR_KEY:
                self.finalize_shape(event.key)
                return
            
            if event.key in ['f6', 'f7', 'delete', 'f10']:
                print(f"[!] Blocked: Finish or Cancel (F8) current shape first.")
            return

        if self.state == IDLE:
            if event.key == 'f5':
                self.refresh_image()
            if event.key == 'f6':
                self.start_mode(CIRCLE, 3)
            elif event.key == 'f7':
                self.start_mode(RECT, 4)
            elif event.key == 'f9':
                self.print_data()
            elif event.key == 'f10':
                self.enter_naming_mode()
            elif event.key == 'delete':
                self.enter_delete_mode()
            elif event.key == 'escape':
                self.state = CONFIRM_EXIT
                self.update_title("[EXIT?] Press ENTER to Quit or Any other key to Cancel.")

    # --- Delete Logic ---

    def enter_delete_mode(self):
        if not self.shapes:
            print("[!] No shapes to delete.")
            self.update_title("List empty. Nothing to delete.")
            return

        self.print_data()
        self.state = DELETING
        self.input_buffer = ""
        self.update_title("DELETE MODE: Type ID... (Enter to Confirm | Esc to Cancel)")

    def handle_delete_input(self, key):
        if key == 'escape':
            self.reset_state()
            return
        
        elif key == 'enter':
            if self.input_buffer:
                try:
                    uid = int(self.input_buffer)
                    if uid in self.shapes:
                        del self.shapes[uid]
                        print(f"[+] Deleted ID {uid}")
                        
                        if self.saved_mouse_wheel and any(v['key_name'] == MOUSE_WHEEL_CODE for v in self.shapes.values()) == False:
                            self.saved_mouse_wheel = False
                        if self.saved_sprint_distance and any(v['key_name'] == SPRINT_DISTANCE_CODE for v in self.shapes.values()) == False:
                            self.saved_sprint_distance = False
                            
                        self.update_title(f"Deleted ID {uid}. Returning to IDLE...")
                        self.reset_state()
                    else:
                        print(f"[!] ID {uid} not found.")
                        self.update_title(f"Error: ID {uid} not found. Try again or Esc.")
                        self.input_buffer = ""
                        
                except ValueError:
                    self.update_title("Error: Invalid Number. Try again or Esc.")
                    self.input_buffer = ""
            return
        
        elif key.isdigit():
            self.input_buffer += key
            self.update_title(f"DELETE MODE: ID [{self.input_buffer}] (Enter to delete)")
        elif key == 'backspace':
            self.input_buffer = self.input_buffer[:-1]
            self.update_title(f"DELETE MODE: ID [{self.input_buffer}] (Enter to delete)")
        elif key in ['f6', 'f7', 'delete', 'f10']:
            print("[!] Blocked: Exit Delete Mode (Esc) first.")

    # --- Core Logic ---

    def finalize_shape(self, key_name):
        # 'key_name' might be a key string ('a', 'f1') OR a mouse string ('MOUSE_LEFT')
        hex_code, interception_key = self.get_interception_code(key_name)
        
        if hex_code is None:
            print(f"[!] Key '{key_name}' not mapped.")
            return

        cx, cy, r, bb = None, None, None, None
        if self.mode == CIRCLE:
            cx, cy, r, bb = self.calculate_circle()
        elif self.mode == RECT:
            cx, cy, r, bb = self.calculate_rect()

        if cx is not None:
            saved = self.save_entry(interception_key, hex_code, cx, cy, r, bb)
            if saved:
                print(f"[+] Saved ID {self.count-1}: {self.mode} bound to key '{key_name}' with interception key: '{interception_key}'")
        
        self.reset_state()

    # --- Naming / Saving Logic ---

    def enter_naming_mode(self):
        if not self.shapes:
            self.update_title("Nothing to save!")
            return

        self.state = NAMING
        self.input_buffer = ""
        self.update_title("SAVE: Type Name... (Enter for Default | Esc to Cancel)")

    def handle_naming_input(self, key):
        if key == 'escape':
            self.reset_state()
            return
        elif key == 'enter':
            final_name = self.input_buffer.strip()
            self.export_data(final_name if final_name else None)
            self.reset_state()
            return
        elif key == 'backspace':
            self.input_buffer = self.input_buffer[:-1]
        elif len(key) == 1 and (key.isalnum() or key in ['_', '-']):
            self.input_buffer += key
        
        display_name = self.input_buffer if self.input_buffer else "[Default Timestamp]"
        self.update_title(f"SAVE: {display_name} (Enter to Save)")

    def export_data(self, user_name=None):
        if not user_name:
            user_name = datetime.datetime.now().strftime("map_%Y%m%d_%H%M%S")
        
        os.makedirs(JSONS_FOLDER, exist_ok=True)
        json_output = []

        for _, data in self.shapes.items():
            entry = {
                "name": data['key_name'], # Interception Key Name
                "scancode": data['m_code'], # Saved as hex string "0x..."
                "type": data['type'],
                "cx": data['cx'],
                "cy": data['cy'],
                # Initialize vals to 0/null
                "val1": 0, "val2": 0, "val3": 0, "val4": 0
            }
            
            if data['type'] == RECT:
                (x_min, y_min), (x_max, y_max) = data['bb']
                entry["val1"] = x_min
                entry["val2"] = y_min
                entry["val3"] = x_max
                entry["val4"] = y_max
                
            elif data['type'] == CIRCLE:
                entry["val1"] = data['r']
                # val2, 3, 4 remain 0
            
            json_output.append(entry)

        file_path = os.path.join(JSONS_FOLDER, f"{user_name}.json")
        
        try:
            with open(file_path, 'w', encoding='utf-8') as f:
                json.dump(json_output, f, indent=4)

            msg = f"{JSONS_FOLDER}/{user_name}.json"
            print(f"[+] {msg}")

        except Exception as e:
            print(f"[!] Export Error: {e}")
            self.update_title(f"Error saving: {e}")
            return
            
        try:
            if not os.path.exists(TOML_PATH):
                create_default_toml()
                
            # Load
            with open(TOML_PATH, "r", encoding="utf-8") as f:
                doc = tomlkit.load(f)

            # Ensure structure exists
            if "system" not in doc: doc.add("system", tomlkit.table())
            if "key" not in doc: doc.add("key", tomlkit.table())

            # Update paths
            doc["system"]["hud_image_path"] = os.path.normpath(self.image_path)
            doc["system"]["json_path"] = os.path.normpath(file_path)
            doc['joystick']['mouse_wheel_radius'] = self.mouse_wheel_radius
            doc['joystick']['sprint_distance'] = self.sprint_distance

            # Save
            with open(TOML_PATH, "w", encoding="utf-8") as f:
                tomlkit.dump(doc, f)

        except (KeyError, Exception) as e:
            create_default_toml()
            _str = f"Config corrupted. Resetting to defaults. Error: {e}"
            raise RuntimeError(_str)
                
        self.update_title(msg)
            
    # --- Helper Functions ---

    def get_interception_code(self, key):
        mapped_key = key
        val = SCANCODES.get(mapped_key)
        if val is None:
            mapped_key = SPECIAL_MAP.get(key)
            if mapped_key:
                val = SCANCODES.get(mapped_key)
        return hex(val) if val is not None else None, mapped_key if val is not None else None

    def save_entry(self, interception_key, hex_code, cx, cy, r, bb):
        id = self.count
        inc_count = True
        saved = False
        
        if interception_key == MOUSE_WHEEL_CODE:
            if self.mode == CIRCLE:
                if self.saved_mouse_wheel:
                    print(f"[!] Mouse Wheel already assigned. Overwriting previous assignment.")
                    for k, v in self.shapes.items():
                        if v['key_name'] == MOUSE_WHEEL_CODE:
                            id = k
                            inc_count = False
                            self.shapes.pop(k)
                            break
                    self.saved_mouse_wheel = True
                self.mouse_wheel_radius = r
                self.mouse_wheel_cy = cy
                
            elif self.mode == RECT:
                print(f"[!] Error: Mouse Wheel can only be assigned to '{CIRCLE}' not '{RECT} shapes.")
                return saved
        
        elif interception_key == SPRINT_DISTANCE_CODE:
            if self.mode == CIRCLE:
                if self.saved_sprint_distance:
                    if not self.saved_mouse_wheel:
                        print(f"[!] Mouse Wheel not assigned yet. Please assign it first.")
                        return saved
                    
                    print(f"[!] Sprint Threshold already assigned. Overwriting previous assignment.")
                    for k, v in self.shapes.items():
                        if v['key_name'] == SPRINT_DISTANCE_CODE:
                            id = k
                            inc_count = False
                            self.shapes.pop(k)
                            break
                    self.saved_sprint_distance = True
                self.sprint_distance = cy - self.mouse_wheel_cy
                
            elif self.mode == RECT:
                print(f"[!] Error: Sprint Button can only be assigned to '{CIRCLE}' not '{RECT} shapes.")
                return saved
        
        entry = {
            "key_name": interception_key,
            "m_code": hex_code,
            "type": self.mode,
            "cx": cx, "cy": cy, "r": r, "bb": bb
        }
        self.shapes[id] = entry
        if inc_count:
            self.count += 1
        
        saved = True
        return saved

    def print_data(self):
        print("\n" + "="*45)
        print(f" {'ID':<5} | {'KEY':<10} | {'TYPE':<8} | {'INFO'}")
        print("="*45)
        for k, v in self.shapes.items():
            print(k, v)
        print("="*45 + "\n")

    # --- Math ---
    def calculate_circle(self):
        x1, y1 = self.points[0]
        x2, y2 = self.points[1]
        x3, y3 = self.points[2]
        D = 2 * (x1 * (y2 - y3) + x2 * (y3 - y1) + x3 * (y1 - y2))
        if D == 0: return None, None, None, None
        h = ((x1**2 + y1**2) * (y2 - y3) + (x2**2 + y2**2) * (y3 - y1) + (x3**2 + y3**2) * (y1 - y2)) / D
        k = ((x1**2 + y1**2) * (x3 - x2) + (x2**2 + y2**2) * (x1 - x3) + (x3**2 + y3**2) * (x2 - x1)) / D
        r = math.sqrt((x1 - h)**2 + (y1 - k)**2)
        return int(h), int(k), int(r), None

    def calculate_rect(self):
        xs = [pt[0] for pt in self.points]
        ys = [pt[1] for pt in self.points]
        return int(sum(xs)/4), int(sum(ys)/4), None, ((min(xs), min(ys)), (max(xs), max(ys)))

if __name__ == "__main__":
    Plotter()