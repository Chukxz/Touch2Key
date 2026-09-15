# Touch2Key

[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![OS: Windows](https://img.shields.io/badge/os-Windows-blue.svg)](https://www.microsoft.com/en-us/windows)
[![OS: Linux](https://img.shields.io/badge/os-Linux-yellow.svg)](https://www.linuxfoundation.org/)
[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](https://opensource.org/licenses/MIT)

**Touch2Key** is a high-performance, cross-platform input mapper designed to seamlessly translate touch interactions (via Android/ADB) into zero-latency keyboard and mouse inputs on your PC.

Enable **Developer Options** and **Wireless Debugging** (5 GHz Wi-Fi recommended) on your Android device and accept the authorization prompt when connecting.

Touch2Key can be paired with game streamers like **Sunshine/Moonlight** or **Apollo/Artemis** for full visual and audio streaming. Disable all virtual controller/mouse inputs within your streaming host to prevent mapping conflicts.

---

## Architecture & Core Features

* **5-Stage Input Pipeline:** Every touch contact is processed through an isolated, modular 5-stage pipeline:
  $$\text{Region} \longrightarrow \text{Origin} \longrightarrow \text{Constraint} \longrightarrow \text{Transformation} \longrightarrow \text{Semantic}$$
  Decoupling spatial detection, reference baselines, mechanical bounds, mathematical transforms, and driver emissions eliminates state drift and input fighting.

* **Prioritized Deterministic Dispatching:** Touch contacts are routed using a strict 4-key precedence sort:
  1. **Explicit Priority** (Custom user tier: `+100` to `-100`)
  2. **Type Precedence** (`Button: 2` > `Joystick: 1` > `Mouse: 0`)
  3. **Hitbox Specificity** (Smaller bounding areas evaluate before broad/full-screen zones)
  4. **Creation Order** (Deterministic tie-breaker)

* **Defensive Input Ownership & Multi-Claim:**
  * **Simultaneous Firing:** Overlapping buttons sharing the same priority tier claim contacts concurrently, enabling multi-key combos from a single touch.
  * **Single-Owner Isolation:** Joysticks and camera look enforce strict single-contact ownership, preventing jitter, delta duplication, or direction fluttering.

* **Hybrid Mode Switching (In-Game vs. Menu/Lobby):**
  * **In-Game Mode (Cursor Hidden):** Custom HUD zones capture taps/drags to drive game controls.
  * **Menu Mode (Cursor Visible):** Game buttons deactivate automatically, passing single-touch events through as absolute desktop clicks (`device_to_game_abs`) for clean lobby, map, and inventory navigation.
  * **Hardware-Free Return Gates:** Return to Game Mode without touching the physical keyboard using a **synchronized two-finger stationary tap** or by tapping the **top bezel notch strip**.

* **Dynamic Camera & Joystick Integration:**
  * **Track-Fire Buttons:** Configurable `move_camera` zones emit simultaneous keypresses and camera deltas (aim while shooting).
  * **Fixed vs. Floating Joysticks:** Fixed HUD joysticks free the rest of the display for full-screen camera look. Floating joysticks partition screen halves dynamically based on user handedness.
  * **Anchored-Floating Joysticks:** Snap to fixed HUD artwork on touch while leashing dynamic origins during extended thumb drift.

* **Platform-Native Injection:** Low-level Windows NT kernel injection via the Interception driver and Linux `evdev`/`uinput` subsystem (X11 supported).

* **Zero-Latency Processing:** Dedicated multiprocessing workers and helper threads with sub-millisecond heartbeat monitors and real-time status logging.

* **Interactive Plotting GUI & Layout Editor:** Comprehensive PySide6/Matplotlib interface supporting direct visual placement, live priority adjustments (`P`/`O` keys or toolbar spinboxes), dynamic zone sizing, and SQLite database storage.

* **Anti-Cheat Safe:** Humanized dwell times and randomized click durations for strictly user-initiated actions. No macros, automated scripts, or game-state tampering.

---

## Window Selection & Persistence

On startup, the engine launches an interactive Window Selector dialog that lists all active desktop windows with their process titles and window classes.

* **Initial Binding:** Select your target emulator or native PC game window. The engine binds directly to its process and window ID.
* **Self-Healing Window Tracking:** If the target window is lost due to a crash or restart, the engine uses the captured window class name to automatically re-acquire the largest active visible instance, maintaining your mapping session without manual intervention.

---

## Key Customization & Storage

* **Startup Capture Dialog:** Binds core control keys (such as **Toggle** and **Sprint**) and configures performance limits (Rate Cap and Polls Per Second).
* **SQLite & TOML Storage:** Layout zones, priorities, and hitbox coordinates are stored persistently in SQLite tables with foreign-key cascade protection, while runtime defaults are managed via `settings.toml`.

---

## Connectivity & Device Management

* **Auto-Adaptive Multi-Touch:** Automatically queries Android touchscreen driver configurations (`ABS_MT_*` event capabilities and slot counts) over ADB upon connection.
* **Wired & Wireless ADB:** Supports high-speed direct USB and wireless TCP/IP debugging (`adb tcpip 5555`).
* **Resilient Event Stream:** Cable disconnects or Wi-Fi drops automatically pause the input pump and resume processing once ADB reconnects, avoiding application crashes or hung keys.

---

## Installation

### Prerequisites
* Python 3.10+
* Android device with USB/Wireless Debugging enabled
* Linux users: X11 session with `sudo` access for `uinput`/`udev` rules

### Setup
* **Install: Remember to create a virtual environment on your machine by using the appropiate `venv` command and activating it (depending on your OS), after navigating to the `Touch2Key` directory on your machine before running the `pip install .` command as it is the standard python practice to avoid package conflicts and ensure isolation.**

   ```bash
   git clone https://github.com/Chukxz/Touch2Key.git
   cd Touch2Key
   pip install .
* **Setup:** Run setup (Usually requires an internet connection).

*(Note: Windows requires a system reboot after installation to fully load the driver).*

## Uninstallation
Because Touch2Key installs system-level drivers and kernel rules, **simply running `pip uninstall Touch2Key` is not sufficient.** You should first run the included uninstaller before uninstalling via pip to avoid any issues or residual files.

*(Note: Windows requires a system reboot after uninstallation to fully release the driver).*

## Contributing
Please use `black` for formatting (recommended), `pytest` for unit testing (optional), and `snakeviz` for visual view of the profile (optional).

Install these via running `pip install .[dev]` during installation.

To support editable mode run `pip install -e .[dev]` (add the `-e` flag) during installation, but note that contributions to the Touch2Key's github repository would likely require permissions from the author(s).

## License
MIT License.