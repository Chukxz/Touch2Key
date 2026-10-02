# Touch2Key

[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![OS: Windows](https://img.shields.io/badge/os-Windows-blue.svg)](https://www.microsoft.com/en-us/windows)
[![OS: Linux](https://img.shields.io/badge/os-Linux-yellow.svg)](https://www.linuxfoundation.org/)
[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](https://opensource.org/licenses/MIT)

**Touch2Key** is a high-performance, cross-platform input mapper designed to seamlessly translate touch interactions (via Android/ADB) into zero-latency keyboard and mouse inputs on your PC.

This is the Second Touch2Key Published Implementation with full GUI, CLI support, and improved functionality. 
The first version with only CLI support and basic GUI windows can be accessed [here](https://github.com/Chukxz/touch2keybare).

Enable **Developer Options** and **Wireless Debugging** (5 GHz Wi-Fi recommended) on your Android device and accept the authorization prompt when connecting.

Touch2Key can be paired with game streamers like **Sunshine/Moonlight** or **Apollo/Artemis** for full visual and audio streaming. Disable all virtual controller/mouse inputs within your streaming host to prevent mapping conflicts.

---

## Architecture & Core Features

* **5-Stage Input Pipeline:** Every touch contact is processed through an isolated, modular 5-stage pipeline:
  `Region` -> `Origin` -> `Constraint` -> `Transformation` -> `Semantic`
  Decoupling spatial detection, reference baselines, mechanical bounds, mathematical transforms, and driver emissions eliminates state drift and input fighting.

* **Prioritized Deterministic Dispatching:** Touch contacts are routed using a strict 4-key precedence sort:
  1. **Explicit Priority** (Custom user tier: `+100` to `-100`)
  2. **Type Precedence** (`Button: 2` > `Joystick: 1` > `Mouse: 0`)
  3. **Hitbox Specificity** (Smaller bounding areas evaluate before broad/full-screen zones)
  4. **Creation Order** (Deterministic tie-breaker)

* **Hardware-Accurate Typematic Engine (Key Auto-Repeat):**
  * **Dedicated Low-Level Repeat Loop:** Hardware-accurate repeat pulses execute directly inside driver worker processes without pipe saturation or IPC latency.
  * **Focus-Stealing for Diagonal WASD:** Pressing a new key steals typematic repeat focus without sending artificial `KEY_UP` releases to currently held keys, allowing diagonal movement to hold cleanly while spamming action keys.
  * **Dynamic IPC Hot-Reloading:** Delay, rate, and exclusion sets can be altered live via the GUI or CLI without restarting the worker processes.

* **Defensive Input Ownership & Multi-Claim:**
  * **Simultaneous Firing:** Overlapping buttons sharing the same priority tier claim contacts concurrently, enabling multi-key combos from a single touch.
  * **Single-Owner Isolation:** Joysticks and camera look enforce strict single-contact ownership, preventing jitter, delta duplication, or direction fluttering.

* **Hybrid Mode Switching (In-Game vs. Menu/Lobby):**
  * **In-Game Mode (Cursor Hidden):** Custom HUD zones capture taps/drags to drive game controls.
  * **Menu Mode (Cursor Visible):** Game buttons deactivate automatically, passing single-touch events through as absolute desktop clicks (`device_to_game_abs`) for clean lobby, map, and inventory navigation.
  * **Hardware-Free Return Gates & Bezel Toggles:** Return to Game Mode or control visibility using configurable **Double-Tap triggers** and dedicated **Bezel Toggle strips** along screen borders.

* **Dynamic Camera & Joystick Integration:**
  * **Buttons:** Configurable `pointer` zones emit simultaneous keypresses and camera deltas (e.g., for aiming while shooting).
  * **Fixed vs. Anchored/Floating Joysticks:** Fixed HUD joysticks free the rest of the display for full-screen camera look. Anchored and Floating joysticks partition screen halves dynamically based on user handedness and subsequently leash. Anchored joysticks initially snap (bounded by the snap radius) to fixed joystick HUD coordinates in the joystick region unlike Floating joysticks that report the initial touch position in the HUD region.

* **Platform-Native Injection:** Low-level Windows NT kernel injection via the Interception driver and Linux `evdev`/`uinput` subsystem (X11 supported).

* **Zero-Latency Processing:** Dedicated multiprocessing workers and helper threads with sub-millisecond heartbeat monitors and real-time status logging.

* **Interactive Plotting GUI & Layout Editor:** Comprehensive PySide6/Matplotlib interface supporting direct visual placement, live priority adjustments (`P`/`O` keys or toolbar spinboxes), dynamic zone sizing, and SQLite database storage.

* **Anti-Cheat Safe:** Humanized dwell times and randomized click durations for strictly user-initiated actions. No macros, automated scripts, or game-state tampering.

---

## Window Selection & Persistence

On startup in CLI mode, the engine launches an interactive Window Selector dialog or refreshing terminal (depends on the `--use-gui` flag), that lists all active desktop windows with their process titles and window classes. In GUI mode, configuration is dynamic and not tied to startup. 
The Interception mouse and keyboard device can also be configured when running on Windows.

* **Initial Binding:** Select your target emulator or native PC game window. The engine binds directly to its process and window ID.
* **Self-Healing Window Tracking:** If the target window is lost due to a crash or restart, the engine uses the captured window class name to automatically re-acquire the largest active visible instance, maintaining your mapping session without manual intervention.

---

## Key Customization & Storage

* **Capture Dialog:** Binds core control keys (such as **Toggle** and **Sprint**) and configures performance limits (Rate Cap and Polls Per Second).
* **SQLite Single Source of Truth:** Layout zones, priorities, hitboxes, and runtime defaults (including system gestures and typematic rules) are stored persistently in SQLite tables (`touch2key.db`) with foreign-key cascade protection. **The database is the single source of truth for the engine.** 
* **Import/Export Bundles:** TOML and JSON formats are used strictly for importing, exporting, and sharing configuration bundles or legacy layouts. They are never used for active runtime state storage.

---

## Connectivity & Device Management

* **Auto-Adaptive Multi-Touch:** Automatically queries Android touchscreen driver configurations (`ABS_MT_*` event capabilities and slot counts) over ADB upon connection.
* **Wired & Wireless ADB:** Supports high-speed direct USB and wireless TCP/IP debugging (`adb tcpip 5555`).
* **Resilient Event Stream:** Cable disconnects or Wi-Fi drops automatically pause the input pump and resume processing once ADB reconnects, avoiding application crashes or hung keys.

---

## Automated Maintenance & Privacy

Touch2Key features built-in housekeeping to ensure logs and diagnostic files never bloat your storage, while still keeping enough history for effective troubleshooting.

* **Application Logs:** Automatically pruned after **60 days (2 months)** or capped at a maximum of **100 files**, whichever comes first.
* **Diagnostic Dumps:** Retained for up to **60 days** and capped at the **20 most recent files**.
* **Local Storage:** All logs and runtime data are securely stored locally inside your centralized `data/` directory and are completely isolated from permanent application assets.

---

## Icon Shortcuts

The app sets up an icon shortcut on your desktop (that launches the GUI directly) when setup is run either from the GUI (GUI script command: `touch2key-gui`) or from the terminal (CLI setup command: `touch2key-setup`), aside from managing essential stuff like binaries, drivers, and rules. Uninstallation also works similarly and always removes the icon shortcut, aside from managing those same essential items and application data.

---

## Installation

### Prerequisites
* Python 3.10+
* Android device with USB/Wireless Debugging enabled
* Linux users: X11 session with `sudo` access for `uinput`/`udev` rules

### Setup
* **Install:** Remember to create a virtual environment on your machine by using the appropriate `venv` command and activating it (depending on your OS) after navigating to the `Touch2Key` directory on your machine before running the `pip install .` command as it is the standard python practice to avoid package conflicts and ensure isolation.

```bash
git clone [https://github.com/Chukxz/Touch2Key.git](https://github.com/Chukxz/Touch2Key.git)
cd Touch2Key
python -m venv .venv

# Windows: .venv\Scripts\activate
# Linux: source .venv/bin/activate

pip install .
```

### Setup Mode

| Action | Command | Description |
| :--- | :--- | :--- |
| **Standard** | `touch2key-setup` | Runs the OS configuration wizard and installs drivers/rules/binaries and shortcuts. |
| **Skip Confirmation** | `touch2key-setup [--yes, -y]` | Skip confirmation prompts / run non-interactively. |
| **Skip Reboot** | `touch2key-setup --no-restart` | Skip reboot prompt after setup (Windows). |

*(Note: Windows requires a system reboot after installation to fully load the driver).*

---

## Uninstallation

Because Touch2Key installs system-level drivers and kernel rules, **simply running `pip uninstall Touch2Key` is not sufficient.** You should first run the included uninstaller before uninstalling via pip to avoid any issues or residual files.

### Uninstallation Commands

| Action | Command | Description |
| :--- | :--- | :--- |
| **Standard** | `touch2key-uninstall` | Removes drivers/rules/binaries/shortcuts; preserves all user data. |
| **Purge** | `touch2key-uninstall --purge` | Removes drivers/rules/binaries/shortcuts **AND** deletes all user data — all saved jsons/images/profiles (bundles) files, settings toml file, and database files. |
| **Purge-All** | `touch2key-uninstall --purge-all` | Removes drivers/rules/binaries/shortcuts **AND** deletes all user and diagnostic data — all saved jsons/images/profiles (bundles) files, settings toml file, database files, **AND** the diagnostics (profiling — .prof) and log files. |
| **Skip Confirmation** | `touch2key-uninstall [--yes, -y]` | Skip confirmation prompt. |
| **Skip Reboot** | `touch2key-uninstall --no-restart` | Skip reboot prompt (Windows). |

*(Note: Windows requires a system reboot after uninstallation to fully release the driver).*

---

## Command Line Interface (CLI)

| Command | Description |
| :--- | :--- |
| `touch2key` | Launches the CLI engine. |
| `touch2key --profile` | Launches the CLI engine and also runs profiling. |
| `touch2key --use-gui` | Launches the CLI engine with a QApplication context (not the same as a full GUI but with some GUI windows). |
| `touch2key-adb` | Displays full ADB executable path if found. |
| `touch2key-capture` | ADB screen capture. |
| `touch2key-gui` | Launches the GUI engine. |
| `touch2key-gui --profile` | Launches the GUI engine and also runs profiling. |
| `touch2key-manage` | Interactive Layout, Profile, Image, and Typematic Manager. |
| `touch2key-plot` | Mapping visualizer. |
| `touch2key-preflight` | Diagnostic checks. |
| `touch2key-setup` | Runs the OS configuration wizard and installs drivers/rules/binaries and shortcuts. |
| `touch2key-uninstall` | Safely removes drivers, rules, binaries, and shortcuts. |
| `touch2key-wireless` | Forces ADB wireless connection. |
| `touch2key-keyboard` | Test the virtual keyboard program output. |
| `touch2key-visualizer` | Visualize the keyboard and mouse events with support for cursor toggling visualization. |

### Typematic & System Commands (via Layout Manager)
You can directly configure hardware auto-repeat behavior, double taps, bezel toggles, and left-handed mode via `touch2key-manage`:
```bash
touch2key-manage --show-typematic
touch2key-manage --set-typematic on --typematic-delay 200 --typematic-rate 35
touch2key-manage --typematic-excludes "w,a,s,d,shift,ctrl,alt"
touch2key-manage --reset-typematic
touch2key-manage --set-image 1 path/to/hud_screenshot.png
touch2key-manage --set-left-handed on
```
*(Alternatively, choose options like `[ss]` inside the interactive terminal menu to configure double-tap and bezel toggle fields interactively, or `[rss]` to reset them).*

---

## Contributing
Please use `black` for formatting (recommended), `pytest` for unit testing (optional), and `snakeviz` for visual view of the profile (optional).

Install these via running `pip install .[dev]` during installation.

To support editable mode, run `pip install -e .[dev]` (add the `-e` flag) during installation, but note that contributions to the Touch2Key's github repository would likely require permissions from the author(s).

---

## License
MIT License.
