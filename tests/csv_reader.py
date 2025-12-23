import csv
import os

def normalize_csv_data(file_path, screen_width, screen_height):
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
        print(f"Error: File {file_path} not found.")
        return {}

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
