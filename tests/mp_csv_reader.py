# --- usage example ---

# 1. Define your source resolution (The phone you took screenshots on)
SOURCE_W = 1612
SOURCE_H = 720
from csv_reader import normalize_csv_data

# 2. Process Rectangles
rect_zones = normalize_csv_data('./configs/mp_rect.csv', SOURCE_W, SOURCE_H)
# Output example: {'SSB': {'type': 'rect', 'x1': 0.008, 'y1': 0.481, ...}}

# 3. Process Circles
circ_zones = normalize_csv_data('/configs/mp_circ.csv', SOURCE_W, SOURCE_H)
# Output example: {'JOY': {'type': 'circ', 'cx': 0.125, 'cy': 0.555, 'r': 0.033}}

# 4. Merge them into one lookup table for your script
master_zones = {**rect_zones, **circ_zones}

print(f"Loaded {len(master_zones)} zones.")
print(master_zones)
# print(master_zones['JOY']) # Test verify