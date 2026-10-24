# Touch2Key

[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![OS: Windows](https://img.shields.io/badge/os-Windows-blue.svg)](https://www.microsoft.com/en-us/windows)
[![OS: Linux](https://img.shields.io/badge/os-Linux-yellow.svg)](https://www.linuxfoundation.org/)
[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](https://opensource.org/licenses/MIT)

**Touch2Key** is a high-performance, cross-platform input mapper that translates touches on an Android device (via ADB) into low-latency keyboard and mouse input on your PC.

This is the second published Touch2Key implementation, with a full GUI, CLI support, and improved functionality.
The first version (CLI only, basic GUI windows) is available [here](https://github.com/Chukxz/touch2keybare).

## At a Glance

* **What it does:** Your phone's touchscreen becomes a configurable gamepad/HUD for PC games: buttons, joysticks, camera look, and mouse.
* **Platforms:** Windows (Interception driver) and Linux (`evdev`/`uinput`, X11). Android device required.
* **Two ways to run:** `touch2key-gui` (full GUI, recommended) or `touch2key` (CLI with runtime hotkeys).
* **Admin rights:** needed only for setup and uninstall. Daily use runs as a normal user.
* **Settings live in SQLite.** TOML/JSON are for import/export only.

## Quick Start

1. On your Android device, enable **Developer Options** and **USB Debugging**, then accept the RSA fingerprint prompt when you connect it.
2. Install (inside a virtual environment, see [Installation](#installation)):
   ```bash
   pip install .
   ```
3. Run setup once (requires Administrator/`sudo`; reboot on Windows afterwards):
   ```bash
   touch2key-setup
   ```
4. Launch:
   ```bash
   touch2key-gui     # GUI (also available from the desktop shortcut created by setup)
   touch2key         # CLI
   ```
5. Pick your target game window, draw your layout in **Layout Studio** (GUI), and start the engine.

> **Wireless play:** connect your PC to your phone's hotspot (5GHz WiFi recommended) and plug in the USB cable for the initial handshake. Once the app logs that the device connected wirelessly, you can unplug the cable.
>
> *If you also use game streamers like **Sunshine/Moonlight** or **Apollo/Artemis**, disable all virtual controller/mouse inputs in the streaming host to avoid mapping conflicts.*

---

## Architecture & Core Features

* **5-Stage Input Pipeline:** every touch contact passes through an isolated, modular pipeline:
  `Region` -> `Origin` -> `Constraint` -> `Transformation` -> `Semantic`
  Separating spatial detection, reference baselines, bounds, math transforms, and driver output prevents state drift and input fighting.

* **Deterministic Dispatching:** contacts are routed by a strict 5-key precedence sort:
  1. **Type Precedence** (`SystemToggle: 4` > `Button: 2` > `Joystick: 1` > `Mouse: 0`)
  2. **Explicit Priority** (custom tier: `+200` to `-100`)
  3. **Allow Multi Claim** (splits a tier into `True` (sorted first) and `False` (sorted last))
  4. **Hitbox Specificity** (smaller areas evaluate before broad/full-screen zones)
  5. **Creation Order** (deterministic tie-breaker)

* **Hardware-Accurate Typematic (Key Auto-Repeat):**
  * Repeat pulses run inside the driver worker processes, with no pipe saturation or IPC latency.
  * Pressing a new key steals repeat focus without releasing held keys, so diagonal movement stays held while you spam action keys.
  * Delay, rate, and exclusions can be changed live from the GUI or CLI without restarting workers.

* **Defensive Input Ownership:**
  * **Multi-claim:** overlapping buttons in the same priority tier claim a contact together, enabling multi-key combos from one touch.
  * **Single-owner:** joysticks and camera look own exactly one contact, preventing jitter and duplicated deltas.

* **Hybrid Mode Switching (In-Game vs. Menu):**
  * **In-Game (cursor hidden):** HUD zones capture taps/drags to drive game controls.
  * **Menu (cursor visible):** game buttons deactivate and single touches become absolute desktop clicks, for lobby, map, and inventory navigation.
  * **Touchscreen-only switching:** *both are toggleable in settings, and the bezel zones are seeded in every layout automatically.*
    * **Top Bezel:** toggles cursor visibility (Game Mode / Menu Mode).
    * **Bottom Bezel:** opens the Virtual Keyboard (direct IPC to the engine for low-latency typing).
    * **Two-Finger Tap:** in Menu Mode, tap two fingers anywhere to hide the cursor and return to Game Mode. Ignored while in-game.

* **Camera & Joysticks:**
  * **Buttons:** `pointer` zones emit keypresses and camera deltas together (e.g. aiming while shooting).
  * **Fixed joysticks** leave the rest of the screen free for camera look. **Anchored** and **Floating** joysticks split the screen by handedness. Anchored joysticks snap (within the snap radius) to the fixed HUD position; Floating joysticks start where you touch.

* **Platform-Native Injection:** Windows via the Interception driver, Linux via `evdev`/`uinput` (X11 supported).

* **Multiprocess by design:** dedicated worker processes and helper threads, with heartbeat monitors and live status logging.

* **Layout Editor (GUI):** PySide6/Matplotlib canvas for placing zones, adjusting priorities (`P`/`O` keys or the inspector), resizing, and saving to SQLite.

* **Live Input Visualizer (`touch2key-visualizer`):** loads your active layout, highlights hitboxes as you trigger them, and respects your configured `toggle_key`, so you can test mappings outside a game.

* **Anti-Cheat Safe:** humanized dwell times and randomized click durations for user-initiated actions only. No macros, scripts, or game-state tampering.

---

## Window Selection & Persistence

* **CLI mode:** on startup the engine shows a window selector (a refreshing terminal list, or a dialog with `--use-gui`) listing active windows with their titles and classes. On Windows you can also choose the Interception keyboard and mouse devices.
* **GUI mode:** configuration is dynamic and not tied to startup. Change the target window and devices any time from **Settings**.
* **Self-healing tracking:** if the target window is lost (crash or restart), the engine uses the saved window class to re-acquire the largest visible matching window automatically.

---

## Key Customization & Storage

* **Capture:** bind the core keys (**Toggle** and **Sprint**) and set performance limits (**ADB Rate Cap** and **PPS Alert Threshold**).
* **SQLite is the single source of truth** (`touch2key.db`): layout zones, priorities, hitboxes, and runtime defaults (system gestures, typematic rules), with foreign-key cascade protection.
* **Import/Export bundles:** TOML and JSON are used only to import, export, and share configurations or legacy layouts, never for active runtime state.

---

## Connectivity & Device Management

* **Auto-adaptive multi-touch:** queries the touchscreen's `ABS_MT_*` capabilities and slot count over ADB on connect.
* **Wired & wireless ADB:** USB by default. For wireless play, connect to the phone's hotspot, plug in USB, and wait for the successful `adb tcpip 5555` handshake log before unplugging.
* **Resilient stream:** cable or Wi-Fi drops pause the input pump and resume when ADB reconnects, with no crashes or stuck keys.

---

## Automated Maintenance & Privacy

* **Application logs:** pruned after **60 days** or beyond **100 files**, whichever comes first.
* **Diagnostic dumps:** kept up to **60 days**, capped at the **20 most recent** files.
* **Local only:** logs and runtime data are stored in the local `data/` directory, separate from application assets.

---

## Icon Shortcuts

Running setup from the GUI (`touch2key-gui`) or the terminal (`touch2key-setup`) also creates a desktop shortcut that launches the GUI. Uninstalling always removes it.

---

## Installation

### Prerequisites
* Python 3.10+
* Android device with **USB Debugging** enabled
* **Windows:** Administrator privileges for **initial setup** (Interception driver) and **uninstallation**. Daily use runs as a standard user.
* **Linux:** `sudo` for **initial setup** (`uinput`/`udev` rules) and **uninstallation**. Daily use runs as a standard user.

### Install
Use a virtual environment to avoid package conflicts:

```bash
git clone https://github.com/Chukxz/Touch2Key.git
cd Touch2Key
python -m venv .venv

# Windows: .venv\Scripts\activate
# Linux:   source .venv/bin/activate

pip install .
```

### Setup Commands

| Action | Command | Description |
| :--- | :--- | :--- |
| **Standard** | `touch2key-setup` | Runs the OS configuration wizard: installs drivers, rules, binaries, and shortcuts. |
| **Skip Confirmation** | `touch2key-setup [--yes, -y]` | Runs non-interactively. |
| **Skip Reboot** | `touch2key-setup --no-restart` | Skips the reboot prompt (Windows). |

*(Windows requires a reboot after installation to load the driver.)*

---

## Uninstallation

Touch2Key installs system-level drivers and kernel rules, so **`pip uninstall Touch2Key` alone is not enough.** Run the uninstaller first.

> **Elevation:** requires **Administrator** (Windows) or **sudo** (Linux).

| Action | Command | Description |
| :--- | :--- | :--- |
| **Standard** | `touch2key-uninstall` | Removes drivers, rules, binaries, and shortcuts; keeps all user data. |
| **Purge** | `touch2key-uninstall --purge` | As above, **and** deletes user data: jsons, images, profile bundles, settings TOML, runtime files, and the database. |
| **Purge-All** | `touch2key-uninstall --purge-all` | As Purge, **and** deletes diagnostics (`.prof`) and log files. |
| **Skip Confirmation** | `touch2key-uninstall [--yes, -y]` | Skips the confirmation prompt. |
| **Skip Reboot** | `touch2key-uninstall --no-restart` | Skips the reboot prompt (Windows). |

*(Windows requires a reboot after uninstallation to release the driver.)*

---

## Command Line Interface (CLI)

| Command | Description |
| :--- | :--- |
| `touch2key` | Launches the engine in CLI mode. |
| `touch2key --profile` | CLI mode with profiling. |
| `touch2key --use-gui` | CLI mode with a QApplication context (some GUI windows, not the full GUI). |
| `touch2key-gui` | Launches the full GUI. |
| `touch2key-gui --profile` | GUI mode with profiling. |
| `touch2key-gui --terminal-log {auto,on,off}` | Terminal log output in GUI mode. `auto` (default) prints only if a terminal exists, `on` prints whenever a console stream exists, `off` never prints. Logs are always written to the log file. |
| `touch2key-adb` | Shows the full ADB executable path, if found. |
| `touch2key-capture` | ADB screen capture. |
| `touch2key-manage` | Interactive Layout, Profile, Image, and Typematic manager. |
| `touch2key-plot` | Mapping visualizer. |
| `touch2key-preflight` | Diagnostic checks. |
| `touch2key-setup` | OS configuration wizard (drivers, rules, binaries, shortcuts). |
| `touch2key-stats` | Live telemetry for the running engine. |
| `touch2key-uninstall` | Removes drivers, rules, binaries, and shortcuts. |
| `touch2key-wireless` | Forces an ADB wireless connection. |
| `touch2key-keyboard` | Tests the virtual keyboard output standalone. |
| `touch2key-visualizer` | Live event visualizer with your active layout and toggle key. |

### One-Line Config Flag
Comma-separated: `window_id,toggle_key,sprint_key,rate_cap,pps,k_device,m_device`. Use empty values for defaults/database values, e.g. `,,,100,50,,`

```bash
touch2key --config
```

### Typematic & System Commands (`touch2key-manage`)
Configure auto-repeat, two-finger tap, bezel toggles, and left-handed mode:

```bash
touch2key-manage --show-typematic
touch2key-manage --set-typematic on --typematic-delay 200 --typematic-rate 35
touch2key-manage --typematic-excludes "lshift, lctrl, lalt"
touch2key-manage --reset-typematic
touch2key-manage --show-system
touch2key-manage --set-two-finger-tap off
touch2key-manage --set-bezel-toggle on
touch2key-manage --reset-system
touch2key-manage --set-image <layout_id> path/to/hud_screenshot.png  # e.g. --set-image 1 hud.png
touch2key-manage --set-left-handed on
```

### Telemetry (`touch2key-stats`)
Attaches to a running engine (GUI or CLI):

```bash
touch2key-stats                  # sample every second until Ctrl+C
touch2key-stats -i 5             # every 5 seconds
touch2key-stats --once           # one sample; exit code 1 if no engine
touch2key-stats --json >> t.log  # JSON Lines, one object per sample
touch2key-stats -c, --clear      # clear the terminal between samples (ignored with --json)
```

---

## CLI Global Hotkeys

In CLI mode these hotkeys tune the engine live. They only trigger while your terminal is the foreground window, so they never interfere with games, and losing focus counts as releasing every key.

| Hotkey | Action | Step / Bounds | Description |
| :--- | :--- | :--- | :--- |
| `Esc` | Shutdown | — | Gracefully stops the engine and its worker processes. |
| `F5` | Handedness Toggle | `True` / `False` | Switches between left- and right-handed layouts, then reloads. |
| `F6` | Reload | — | Reloads the layout, pipelines, and settings (including typematic) from SQLite. |
| `Left` / `Right` | Rate Cap (Hz) | ±10.0 Hz `[30.0 – 1000.0]` | Tunes the mouse flush and touch reader polling rate. Hold to repeat. |
| `Down` / `Up` | PPS Alert Threshold | ±5.0 PPS `[10.0 – 500.0]` | Tunes the touch monitoring threshold. Hold to repeat. |

**Behavior**
- **Arrow keys:** one step on press. After a 400 ms hold, repeat starts at 5 Hz and ramps along a cubic curve to 30 Hz over 1.5 s. OS key repeat is ignored, and releasing resets the ramp.
- **F5 / F6:** one action per physical press, with a shared 350 ms cooldown.
- **Opposing keys cancel:** Left + Right (or Down + Up) together do nothing. Different axes work simultaneously.
- **Live status line:** while an arrow key is held, one terminal line shows the current `Rate Cap` and `PPS`. Other log output is held and replayed on release.
- **Persistence:** values change in memory on every step. The SQLite write and reload are batched to at most once every 250 ms, and the final value is always saved after release.

In **GUI mode** the arrow keys belong to Qt. Change the same values on the **Settings** page (ADB Rate Cap and PPS Alert Threshold).

---

## Contributing
Use `black` for formatting (recommended), `pytest` for tests (optional), and `snakeviz` to view profiles (optional). Install them with `pip install .[dev]`, or `pip install -e .[dev]` for editable mode. Contributions to the main repository likely require the author's permission.

---

## License
MIT License.