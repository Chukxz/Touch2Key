import csv
import os
import time
from utils import MapperEvent

RELOAD_DELAY = 0.01

class CSV_Loader():
    def __init__(self, mapper_event_dispatcher, config):
        self.last_loaded_path = None
        self.last_loaded_timestamp = 0
        self.master_zones = {}
        self.mapper_event_dispatcher = mapper_event_dispatcher
        self.config = config
        self.last_loaded_circ_path = None
        self.last_loaded_circ_timestamp = None
        self.last_loaded_rect_path = None
        self.last_loaded_rect_timestamp = None
        self.width = None
        self.height = None
        self.dpi = None
        self.csv_data = self.load_csv()
        
    def load_csv(self):
        self.csv_data = self.process_csv(self.last_loaded_circ_path, self.last_loaded_rect_path)
        self.last_loaded_circ_path = self.config['system']['circ_csv_path']
        self.last_loaded_circ_timestamp = os.path.getmtime(self.last_loaded_circ_path)
        self.last_loaded_rect_path = self.config['system']['rect_csv_path']
        self.last_loaded_rect_timestamp = os.path.getmtime(self.last_loaded_rect_path)

        circ_res = self.config['system']['circ_csv_dev_res']
        rect_res = self.config['system']['rect_csv_dev_res']
        
        if all([circ_res, rect_res]) and circ_res == rect_res:
            res = circ_res
        else:
            raise RuntimeError("Resolution not found or mismatched between circular and rectangular CSV settings.")
        self.width, self.height = res
        
        circ_dpi = self.config['system']['circ_csv_dev_dpi']
        rect_dpi = self.config['system']['rect_csv_dev_dpi']
        
        if all([circ_dpi, rect_dpi]) and circ_dpi == rect_dpi:
            self.dpi = circ_dpi
        else:
            raise RuntimeError("Mismatch found between circular and rectangular CSV setting")
        
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
        
        # Check CIRC CSV
        need_csv_reload_circ = self.should_reload(self.last_loaded_circ_path, self.config['system']['circ_csv_path'], self.last_loaded_circ_timestamp)
        # Check RECT CSV
        need_csv_reload_rect = self.should_reload(self.last_loaded_rect_path, self.config['system']['rect_csv_path'], self.last_loaded_rect_timestamp)
                    
        # HARD RELOAD: Only run this block if any CSV actually changed
        if need_csv_reload_circ or need_csv_reload_rect:
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
            
        Returns:
            dict: { "ZONE_NAME": { "x1": 0.5, "y1": ... } }
        """
        normalized_zones = {}
        
        # Check if file exists
        if not os.path.exists(file_path):
            raise RuntimeError(f"Error: File {file_path} not found.")

        with open(file_path, mode='r', encoding='utf-8-sig') as f:
            # DictReader automatically handles the header row
            reader = csv.DictReader(f)
            headers = reader.fieldnames
            
            # Detect CSV Type
            is_rect = 'x1' in headers and 'y1' in headers
            is_circ = 'Center X' in headers or 'Radius' in headers

            for row in reader:
                name = row['Name']
                
                # Skip empty rows or bad data
                if not name:
                    continue
                    
                zone_data = {}
                
                try:
                    if is_rect:
                        # Normalization Formula: Value / Resolution
                        zone_data['type'] = 'rect'
                        zone_data['x1'] = float(row['x1']) / screen_width
                        zone_data['y1'] = float(row['y1']) / screen_height
                        zone_data['x2'] = float(row['x2']) / screen_width
                        zone_data['y2'] = float(row['y2']) / screen_height
                        
                    elif is_circ:
                        zone_data['type'] = 'circ'
                        # Normalize Center
                        zone_data['cx'] = float(row['Center X']) / screen_width
                        zone_data['cy'] = float(row['Center Y']) / screen_height
                        
                        # Normalize Radius
                        # NOTE: We normally normalize radius by WIDTH to keep the circle proportional
                        # to the horizontal field of view.
                        zone_data['r'] = float(row['Radius']) / screen_width

                    # Add to master dict
                    normalized_zones[name] = zone_data
                    
                except ValueError:
                    print(f"Skipping invalid row for {name}")
                    continue

        return normalized_zones

    def process_csv(self, circ_path, rect_path):
        # Leave like this for now will still change
        SOURCE_W = 1612
        SOURCE_H = 720

        circ_zones = self.normalize_csv_data(circ_path, SOURCE_W, SOURCE_H)
        rect_zones = self.normalize_csv_data(rect_path, SOURCE_W, SOURCE_H)
        master_zones = {**circ_zones , **rect_zones}
        
        return master_zones
