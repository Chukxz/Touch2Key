from mapper import TouchMapperEventDispatcher

class MouseMapper(TouchMapperEventDispatcher):
    def __init__(self):
        super().__init__()
    
    def accept_touch_event(self, event):
        dx = event.sx - event.x
        dy = event.sy - event.y

        