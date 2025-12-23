import wasd_mapper
from mapper import TouchMapperEventDispatcher

class KeyMapper(TouchMapperEventDispatcher):
    def __init__(self):
        super().__init__()
        self.wasd_mapper = wasd_mapper.WASDMapper()

    def is_in_circle(self, px, py, cx, cy, r):
        return (px - cx)**2 + (py - cy)**2 <= r*r

    def is_in_rect(self, px, py, left, right, top, bottom):
        return (left <= px <= right) and (top <= py <= bottom)
    
    def accept_touch_event(self, event):
        if event.is_wasd:
            # Check if no HUD buttons are overlapping - Placeholder for actual check
            
            self.wasd_mapper.accept_touch_event(event)
        
        else:
            # Handle other key mappings here
            pass