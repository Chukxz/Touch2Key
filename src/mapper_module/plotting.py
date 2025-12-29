import matplotlib.pyplot as plt
import matplotlib.image as mpimg
import math
import csv
import os
import datetime
from utils import SCANCODES, CSV_FOLDER_NAME

# --- Constants ---
IDLE = "IDLE"
COLLECTING = "COLLECTING"
WAITING_FOR_KEY = "WAITING_FOR_KEY"
DELETING = "DELETING"
CONFIRM_EXIT = "CONFIRM_EXIT"
NAMING = "NAMING"  # <--- NEW STATE

CIRCLE = "CIRCLE"
RECT = "RECT"

SPECIAL_MAP = {
    "escape": "ESC", "enter": "ENTER", "backspace": "BACKSPACE", "tab": "TAB",
    "f1": "F1", "f2": "F2", "f3": "F3", "f4": "F4", "f5": "F5",
    "f6": "F6", "f7": "F7", "f8": "F8", "f9": "F9", "f10": "F10",
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
    def __init__(self, image_path):
        # --- 1. Disable Default Matplotlib Shortcuts ---
        # This prevents 's', 'q', 'f', etc. from triggering internal mpl commands
        for key in plt.rcParams:
            if key.startswith('keymap.'):
                plt.rcParams[key] = []
                
        self.image_path = image_path
        self.shapes = {}
        self.count = 0
        
        # Data Storage
        self.points = []          
        self.drawn_artists = []   
        
        # State Machine
        self.mode = None          
        self.state = IDLE         
        self.target_points = 0
        self.input_buffer = ""

        # GUI Setup
        try:
            img = mpimg.imread(image_path)
        except FileNotFoundError:
            print(f"[!] Error: Image not found at {image_path}")
            return

        self.fig, self.ax = plt.subplots()
        self.ax.imshow(img)
        
        self.update_title("IDLE. F6(Circ) | F7(Rect) | F9(List) | F10(Save) | Del(Remove) | Esc(Exit)")

        # Event Listeners
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
        self.update_title("IDLE. F6(Circ) | F7(Rect) | F9(List) | F10(Save) | Del(Remove) | Esc(Exit)")

    def start_mode(self, mode, num_points):
        self.reset_state() 
        self.mode = mode
        self.target_points = num_points
        self.state = COLLECTING
        self.update_title(f"Mode: {mode}. Click {num_points} points on the image (F8 to Cancel).")

    # --- Event Handlers ---

    def on_click(self, event):
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
            self.update_title(f"Shape Defined! Press KEY to bind (or F8 to Cancel).")

    def on_key_press(self, event):
        """
        Main Input Router. 
        Strictly segregates actions based on self.state to prevent conflicts.
        """

        # 1. State: NAMING (Saving)
        if self.state == NAMING:
            self.handle_naming_input(event.key)
            return
        
        # 2. State: DELETING
        #    - Only accepts numbers, Enter, or Esc. 
        #    - F6/F7/Del are ignored.
        if self.state == DELETING:
            self.handle_delete_input(event.key)
            return

        # 3. State: CONFIRM_EXIT
        #    - Only accepts Enter (quit) or others (cancel).
        if self.state == CONFIRM_EXIT:
            if event.key == 'enter':
                print("[-] Closing application.")
                plt.close()
            else:
                self.reset_state()
            return

        # 4. State: DRAWING (COLLECTING or WAITING_FOR_KEY)
        #    - F8 is the ONLY command allowed (Cancel).
        #    - WAITING_FOR_KEY also accepts binding keys.
        #    - F6, F7, Delete, F10 are BLOCKED.
        if self.state in [COLLECTING, WAITING_FOR_KEY]:
            if event.key == 'f8':
                print("[-] Action Cancelled.")
                self.reset_state()
                return
            
            if self.state == WAITING_FOR_KEY:
                # If waiting for a bind, try to finalize
                self.finalize_shape(event.key)
                return
            
            # If we reach here, user pressed a blocked key while drawing
            if event.key in ['f6', 'f7', 'delete', 'f10']:
                print(f"[!] Blocked: Finish or Cancel (F8) current shape first.")
            return

        # 5. State: IDLE
        #    - Only here can we start new actions.
        if self.state == IDLE:
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
        """Switch to DELETING state and clear buffer."""
        if not self.shapes:
            print("[!] No shapes to delete.")
            self.update_title("List empty. Nothing to delete.")
            return

        self.print_data()
        self.state = DELETING
        self.input_buffer = ""
        self.update_title("DELETE MODE: Type ID... (Enter to Confirm | Esc to Cancel)")

    def handle_delete_input(self, key):
        """Processes keystrokes while in DELETE mode."""
        
        # CANCEL
        if key == 'escape':
            self.reset_state()
            return
        
        # CONFIRM
        elif key == 'enter':
            if self.input_buffer:
                try:
                    uid = int(self.input_buffer)
                    if uid in self.shapes:
                        del self.shapes[uid]
                        print(f"[+] Deleted ID {uid}")
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

        # TYPE NUMBER
        elif key.isdigit():
            self.input_buffer += key
            self.update_title(f"DELETE MODE: ID [{self.input_buffer}] (Enter to delete)")
        
        # BACKSPACE
        elif key == 'backspace':
            self.input_buffer = self.input_buffer[:-1]
            self.update_title(f"DELETE MODE: ID [{self.input_buffer}] (Enter to delete)")
        
        # BLOCK OTHERS
        elif key in ['f6', 'f7', 'delete', 'f10']:
            print("[!] Blocked: Exit Delete Mode (Esc) first.")

    # --- Core Logic ---

    def finalize_shape(self, key_name):
        # Prevent F-keys/Special keys from being used as bindings if desirable,
        # but here we just check mapping existence.
        hex_code = self.get_interception_code(key_name)
        
        if hex_code is None:
            print(f"[!] Key '{key_name}' not mapped.")
            return

        cx, cy, r, bb = None, None, None, None
        if self.mode == CIRCLE:
            cx, cy, r, bb = self.calculate_circle()
        elif self.mode == RECT:
            cx, cy, r, bb = self.calculate_rect()

        if cx is not None:
            self.save_entry(key_name, hex_code, cx, cy, r, bb)
            print(f"[+] Saved ID {self.count-1}: {self.mode} bound to '{key_name}'")
        
        self.reset_state()

    # --- Naming / Saving Logic ---

    def enter_naming_mode(self):
        """Switch to NAMING state to get filename from user."""
        if not self.shapes:
            self.update_title("Nothing to save!")
            return

        self.state = NAMING
        self.input_buffer = "" # Clear buffer
        self.update_title("SAVE: Type Name... (Enter for Default | Esc to Cancel)")

    def handle_naming_input(self, key):
        """Captures keystrokes for the filename."""
        
        # CANCEL
        if key == 'escape':
            self.reset_state()
            return
        
        # CONFIRM SAVE
        elif key == 'enter':
            final_name = self.input_buffer.strip()
            # If empty, pass None so export_data generates a timestamp
            self.export_data(final_name if final_name else None)
            self.reset_state()
            return

        # EDITING
        elif key == 'backspace':
            self.input_buffer = self.input_buffer[:-1]
        
        elif len(key) == 1 and key.isalnum() or key in ['_', '-']:
            # Allow letters, numbers, underscores, and hyphens
            self.input_buffer += key
        
        # Update Visuals
        display_name = self.input_buffer if self.input_buffer else "[Default Timestamp]"
        self.update_title(f"SAVE: {display_name} (Enter to Save)")

    def export_data(self, user_name=None):
        """
        Saves data to CSV.
        :param user_name: Custom name string. If None, uses timestamp.
        """
        if not user_name:
            user_name = datetime.datetime.now().strftime("map_%Y%m%d_%H%M%S")
        
        base_dir = os.path.join("..", "resources", CSV_FOLDER_NAME)
        os.makedirs(base_dir, exist_ok=True)

        combined_rows = []

        for _, data in self.shapes.items():
            # Common: [code, type, cx, cy]
            common = [data['m_code'], data['type'], data['cx'], data['cy']]
            
            row = []
            if data['type'] == RECT:
                (x_min, y_min), (x_max, y_max) = data['bb']
                # [cx, cy, x_min, y_min, x_max, y_max]
                row = common + [x_min, y_min, x_max, y_max]
                
            elif data['type'] == CIRCLE:
                # [cx, cy, radius, "", "", ""]
                row = common + [data['r'], "", "", ""]
            
            combined_rows.append(row)

        file_path = os.path.join(base_dir, f"{user_name}.csv")
        
        try:
            with open(file_path, 'w', newline='') as f:
                writer = csv.writer(f)
                writer.writerow(['scancode', 'type', 'cx', 'cy', 'val1', 'val2', 'val3', 'val4'])
                writer.writerows(combined_rows)

            msg = f"Saved: ../resources/{CSV_FOLDER_NAME}/{user_name}.csv"
            print(f"[+] {msg}")
            self.update_title(msg)
            # We don't reset state here because handle_naming_input calls reset_state right after this
            
        except Exception as e:
            print(f"[!] Export Error: {e}")
            self.update_title(f"Error saving: {e}")
            
    # --- Helper Functions ---

    def get_interception_code(self, key):
        val = SCANCODES.get(key)
        if val is None:
            mapped_key = SPECIAL_MAP.get(key)
            if mapped_key:
                val = SCANCODES.get(mapped_key)
        return hex(val) if val is not None else None

    def save_entry(self, key_name, hex_code, cx, cy, r, bb):
        entry = {
            "key_name": key_name,
            "m_code": hex_code,
            "type": self.mode,
            "cx": cx, "cy": cy, "r": r, "bb": bb
        }
        self.shapes[self.count] = entry
        self.count += 1

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

Plotter("../resources/mp_hud.jpg")