import threading
from parse_config import AppConfig
from touch_reader import TouchReader
from mapper import Mapper
from mouse_mapper import MouseMapper
from key_mapper import KeyMapper
from wasd_mapper import WASDMapper
        
class TouchMapperEventDispatcher:
    def __init__(self):    
        # The Registry
        self.callback_registry = {
            "ON_TOUCH_DOWN": [],
            "ON_TOUCH_UP": [],
            "ON_TOUCH_PRESSED": []
        }

    def register_callback(self, event_type, func):
        self.callback_registry[event_type].append(func)
    
    def unregister_callback(self, event_type, func):
        self.callback_registry[event_type].remove(func)

    def dispatch(self, event_object):
        if event_object.action == "DOWN":
            for func in self.callback_registry["ON_TOUCH_DOWN"]:
                func(event_object) # Execute the callback
        elif event_object.action == "UP":
            for func in self.callback_registry["ON_TOUCH_UP"]:
                func(event_object) # Execute the callback
        elif event_object.action == "PRESSED":
            for func in self.callback_registry["ON_TOUCH_PRESSED"]:
                func(event_object) # Execute the callback

config = AppConfig('config.ini')
touch_event_dispatcher = TouchMapperEventDispatcher()
touch_reader = TouchReader(config, touch_event_dispatcher)
threading.Thread(target=touch_reader.update_rotation, daemon=True).start()


mapper = Mapper(touch_reader.width, touch_reader.height, config)
MouseMapper(mapper, config, touch_event_dispatcher)
KeyMapper(mapper, config, touch_event_dispatcher)
# Register WASD Mapper after registering KeyMapper to ensure we check for WASD blocking by HUD buttons
WASDMapper(mapper, config, touch_event_dispatcher)