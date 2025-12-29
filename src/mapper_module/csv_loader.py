import csv
import os
import time
from utils import MapperEvent, CIRCLE, RECT
from default_toml_helper import create_default_toml

RELOAD_DELAY = 0.01

class CSV_Loader():
    def __init__(self, mapper_event_dispatcher, config):
        self.last_loaded_path = None
        self.last_loaded_timestamp = 0
        self.master_zones = {}
        self.mapper_event_dispatcher = mapper_event_dispatcher
        self.config = config
        self.last_loaded_csv_path = None
        self.last_loaded_csv_timestamp = None
        self.width = None
        self.height = None
        self.dpi = None
        self.dev_name = None
        self.csv_data = self.load_csv()
        
    def load_csv(self):
        self.csv_data = self.process_csv(self.last_loaded_csv_path)
        self.last_loaded_csv_path = self.config['system']['csv_path']
        self.last_loaded_csv_timestamp = os.path.getmtime(self.last_loaded_csv_path)
        
        try:
            w, h = self.config['system']['csv_dev_res']
            self.width = int(w)
            self.height = int(h)     
        except:
            create_default_toml()
            raise RuntimeError("Resolution not found or misconfigured, configuration settings reset to default.")
        
        try:
            self.dpi = int(self.config['system']['csv_dev_dpi'])
        except:
            create_default_toml()
            raise RuntimeError("DPI not found or misconfigured in CSV, configuration settings reset to default.")
        
        try:
            self.dev_name = str(self.config['system']['csv_dev_name'])
        except:
            create_default_toml()
            raise RuntimeError("Device name not found or misconfigured, configuration settings reset to default.")
        
    def should_reload(self, old_path, new_path, last_timestamp):
        # ANALYZE: Do we need a HARD RELOAD (CSV)?
        need_csv_reload = False
        current_file_time = 0
        
        if os.path.exists(new_path):
            current_file_time = os.path.getmtime(new_path)
            
        if new_path != old_path:
            print(f"[Update] Layout path '{old_path}' changed to '{new_path}'.")
            need_csv_reload = True
        elif current_file_time != last_timestamp:
            print(f"[Update] CSV file '{new_path}' modification detected.")
            need_csv_reload = True
        
        return need_csv_reload

    def reload(self):
        print("\n[System] Checking for updates...")
        
        # Check CSV
        need_csv_reload = self.should_reload(self.last_loaded_csv_path, self.config['system']['csv_path'], self.last_loaded_csv_timestamp)
                    
        # HARD RELOAD: Only run this block if any CSV actually changed
        if need_csv_reload:
            # Load data into memory FIRST (Don't stop the game yet)
            print("[System] Parsing new CSV...")
            self.load_csv()
            
            # CRITICAL SECTION (Stop the game briefly)
            with self.config.config_lock:
                print("[System] Applying new layout...")
                self.mapper_event_dispatcher.dispatch(MapperEvent(action="CSV"))
                
            print("[System] Layout swapped safely. Game resumed.")
        else:
            print("[System] No layout changes found.")
        
        # Wait sometime to ensure better time management for soft reloads
        time.sleep(RELOAD_DELAY)

    def normalize_csv_data(self, file_path, screen_width, screen_height):
        """ 
        Reads a CSV file (Rect or Circ), normalizes all coordinates to 0.0-1.0,
        and returns a dictionary of dictionaries.
        
        Args:
            file_path (str): Path to the CSV file.
            screen_width (int/float): The resolution width used when creating the CSV.
            screen_height (int/float): The resolution height used when creating the CSV.
        """
        normalized_zones = {}
        
        # Check if file exists
        if not os.path.exists(file_path):
            raise RuntimeError(f"Error: File {file_path} not found.")

        with open(file_path, mode='r', encoding='utf-8-sig') as f:
            # DictReader automatically handles the header row
            reader = csv.DictReader(f)
            # headers = reader.fieldnames
            
            for row in reader:
                scancode = row["scancode"]
                if not scancode:
                    continue # Skip empty rows or bad data
                
                name = row["name"]

                # Detect CSV Type
                is_circ = row['type'] == CIRCLE
                is_rect = row['type'] == RECT 

                zone_data = {}
                
                try:
                    if is_circ:
                        zone_data['type'] = CIRCLE
                        
                        # Normalize Center
                        zone_data['cx'] = float(row['cx']) / screen_width
                        zone_data['cy'] = float(row['cy']) / screen_height
                        
                        # Normalize Radius
                        # NOTE: We normally normalize radius by WIDTH to keep the circle proportional
                        # to the horizontal field of view.
                        zone_data['r'] = float(row['val1']) / screen_width

                    elif is_rect:
                        zone_data['type'] = RECT
                        
                        # Normalization Formula: Value / Resolution
                        zone_data['x1'] = float(row['val1']) / screen_width
                        zone_data['y1'] = float(row['val2']) / screen_height
                        zone_data['x2'] = float(row['val3']) / screen_width
                        zone_data['y2'] = float(row['val4']) / screen_height
                        
                    # Add to master dict
                    normalized_zones[scancode] = zone_data
                    
                except ValueError:
                    print(f"Skipping invalid row for scancode: {scancode} with name: {name}.")
                    continue

        return normalized_zones

    def process_csv(self, csv_path):
        # Leave like this for now will still change
        SOURCE_W = 1612
        SOURCE_H = 720

        return self.normalize_csv_data(csv_path, SOURCE_W, SOURCE_H)