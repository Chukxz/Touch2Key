from touch_reader import TouchReader
import threading

touch_reader = TouchReader()
threading.Thread(target=touch_reader.update_rotation, daemon=True).start()
