from evdev import InputDevice, ecodes, list_devices


def get_lock_states_linux() -> dict[str, bool]:

    result = {"caps_lock": False, "num_lock": False, "scroll_lock": False}
    for path in list_devices():
        try:
            leds = InputDevice(path).leds()
        except Exception:
            continue
        if ecodes.LED_CAPSL in leds:
            result["caps_lock"] = True
        if ecodes.LED_NUML in leds:
            result["num_lock"] = True
        if ecodes.LED_SCROLLL in leds:
            result["scroll_lock"] = True
    return result
