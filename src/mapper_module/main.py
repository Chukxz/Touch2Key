import threading
import keyboard
from utils import MapperEventDispatcher, TOML_PATH
from config import AppConfig
from csv_loader import CSV_Loader
from touch_reader import TouchReader
from mapper import Mapper
from mouse_mapper import MouseMapper
from key_mapper import KeyMapper
from wasd_mapper import WASDMapper

mapper_event_dispatcher = MapperEventDispatcher()
config = AppConfig(TOML_PATH, mapper_event_dispatcher)
touch_reader = TouchReader(config)

threading.Thread(target=touch_reader.update_rotation, daemon=True).start()

csv_loader = CSV_Loader(config)
keyboard.add_hotkey('f5', csv_loader.reload, suppress=True)

mapper = Mapper(csv_loader, touch_reader.res_dpi)
MouseMapper(mapper)
KeyMapper(mapper)
# Register WASD Mapper after registering KeyMapper to ensure we check for WASD blocking by HUD buttons
WASDMapper(mapper)

