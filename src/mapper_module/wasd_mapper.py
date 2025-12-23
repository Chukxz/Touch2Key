from mapper import TouchMapperEventDispatcher

class WASDMapper(TouchMapperEventDispatcher):
    def __init__(self, interception_bridge):
        super().__init__()
        self.interception_bridge = interception_bridge

    def accept_touch_event(self, event):...