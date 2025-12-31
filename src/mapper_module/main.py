import threading
import keyboard
from utils import MapperEventDispatcher, TOML_PATH
from config import AppConfig
from mapper_module.json_loader import JSON_Loader
from touch_reader import TouchReader
from bridge import InterceptionBridge
from mapper import Mapper
from mouse_mapper import MouseMapper
from key_mapper import KeyMapper
from wasd_mapper import WASDMapper

mapper_event_dispatcher = MapperEventDispatcher()
config = AppConfig(TOML_PATH, mapper_event_dispatcher)
touch_reader = TouchReader(config)

threading.Thread(target=touch_reader.update_rotation, daemon=True).start()

json_loader = JSON_Loader(config)
keyboard.add_hotkey('f5', json_loader.reload, suppress=True)

interception_bridge = InterceptionBridge()

mapper = Mapper(json_loader, touch_reader.res_dpi, interception_bridge)
MouseMapper(mapper)
KeyMapper(mapper)
# Register WASD Mapper after registering KeyMapper to ensure we check for WASD blocking by HUD buttons
WASDMapper(mapper)

