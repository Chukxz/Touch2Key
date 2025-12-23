from mapper import TouchMapperEventDispatcher

class WASDMapper(TouchMapperEventDispatcher):
    def __init__(self):
        super().__init__()

    def accept_touch_event(self, event):...