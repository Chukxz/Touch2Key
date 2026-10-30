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

## Prerequisites & Installation

### Prerequisites
* Python 3.10+
* Android device with **USB Debugging** enabled
* **Windows:** Administrator privileges for **initial setup** (Interception driver) and **uninstallation**. Daily use runs as a standard user.
* **Linux:** `sudo` for **initial setup** (`uinput`/`udev` rules) and **uninstallation**. Daily use runs as a standard user.

### Install
Use a virtual environment to avoid package conflicts:

```bash
git clone [https://github.com/Chukxz/Touch2Key.git](https://github.com/Chukxz/Touch2Key.git)
cd Touch2Key
python -m venv .venv
```

Activate the virtual environment:
* **Windows:** `.venv\Scripts\activate`
* **Linux:** `source .venv/bin/activate`

Install the package:
```bash
pip install .
```

## Quick Start

1. On your Android device, enable **Developer Options** and **USB Debugging**, then accept the RSA fingerprint prompt when you connect it.
2. Run setup once (requires Administrator/`sudo`; reboot on Windows afterwards):
   ```bash
   touch2key-setup
   ```
3. Launch the application:
   ```bash
   touch2key-gui     # GUI (also available from the desktop shortcut created by setup)
   touch2key         # CLI
   ```
4. Pick your target game window, draw your layout in **Layout Studio** (GUI), and start the engine.

> **Wireless play:** connect your PC to your phone's hotspot (5GHz WiFi recommended) and plug in the USB cable for the initial handshake. Once the app logs that the device connected wirelessly, you can unplug the cable.

### ⚠️ Known Conflicts (Game Streamers)
If you also use game streamers like **Sunshine/Moonlight** or **Apollo/Artemis**, disable all virtual controller/mouse inputs in the streaming host to avoid mapping conflicts.

## Command Line Interface (CLI) & GUI Commands

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
Comma-separated: `window_id,sprint_key,rate_cap,pps,k_device,m_device`. Use empty values for defaults/database values, e.g. `,,100,50,,`
```bash
touch2key --config
```

### Toggle Hotkeys, Typematic & System Commands (`touch2key-manage`)
Configure toggle hotkeys, auto-repeat, two-finger tap, bezel toggles, and left-handed mode:
```bash
touch2key-manage --show-toggle-hotkeys
touch2key-manage --set-toggle-hotkeys "lctrl, lalt"
touch2key-manage --show-typematic
touch2key-manage --set-typematic on --typematic-delay 200 --typematic-rate 35
touch2key-manage --typematic-excludes "lshift, lctrl, lalt"
touch2key-manage --reset-typematic
touch2key-manage --show-system
touch2key-manage --set-two-finger-tap off
touch2key-manage --set-bezel-toggle on
touch2key-manage --reset-system
touch2key-manage --set-image <layout_id> path/to/hud_screenshot.png
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

## CLI Global Hotkeys

In CLI mode these hotkeys tune the engine live. They only trigger while your terminal is the foreground window, so they never interfere with games, and losing focus counts as releasing every key.

| Hotkey | Action | Step / Bounds | Description |
| :--- | :--- | :--- | :--- |
| `Esc` | Shutdown | — | Gracefully stops the engine and its worker processes. |
| `F5` | Handedness Toggle | `True` / `False` | Switches between left- and right-handed layouts, then reloads. |
| `F6` | Reload | — | Reloads the layout, pipelines, and settings (including typematic) from SQLite. |
| `F8` | Input Curve Cycle | Linear / Cubic / Exponential | Cycles through easing curves for arrow key incrementing speed. |
| `Left` / `Right` | Rate Cap (Hz) | ±10.0 Hz `[30.0 – 1000.0]` | Tunes the mouse flush and touch reader polling rate. Hold to repeat. |
| `Down` / `Up` | PPS Alert Threshold | ±5.0 PPS `[10.0 – 500.0]` | Tunes the touch monitoring threshold. Hold to repeat. |

**Behavior**
- **Arrow keys:** one step on press. After a 400 ms hold, repeat starts at 5 Hz and ramps along a cubic curve to 30 Hz over 1.5 s. OS key repeat is ignored, and releasing resets the ramp.
- **F5 / F6 / F8:** one action per physical press, with a shared 350 ms cooldown.
- **Opposing keys cancel:** Left + Right (or Down + Up) together do nothing. Different axes work simultaneously.
- **Live status line:** while an arrow key is held, one terminal line shows the current `Rate Cap` and `PPS`. Other log output is held and replayed on release.
- **Persistence:** values change in memory on every step. The SQLite write and reload are batched to at most once every 250 ms, and the final value is always saved after release.

In **GUI mode** the arrow keys belong to Qt. Change the same values on the **Settings** page (ADB Rate Cap and PPS Alert Threshold).

## Architecture & Core Features

* **5-Stage Input Pipeline:** every touch contact passes through an isolated, modular pipeline:
  `Region` -> `Origin` -> `Constraint` -> `Transformation` -> `Semantic`
  Separating spatial detection, reference baselines, bounds, math transforms, and driver output prevents state drift and input fighting.

* **Deterministic Dispatching:** contacts are routed by a strict 5-key precedence sort:
  1. **Type Precedence** (`Bezel: 4` > `Button: 2` > `Joystick: 1` > `Mouse: 0`)
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
    * **Top Bezel:** toggles cursor visibility (Game Mode / Menu Mode) by executing the configured toggle hotkeys sequence.
    * **Bottom Bezel:** opens the Virtual Keyboard (direct IPC to the engine for low-latency typing).
    * **Two-Finger Tap:** in Menu Mode, tap two fingers anywhere to hide the cursor and return to Game Mode. Ignored while in-game.

* **Camera & Joysticks:**
  * **Buttons:** `pointer` zones emit keypresses and camera deltas together (e.g. aiming while shooting).
  * **Fixed joysticks** leave the rest of the screen free for camera look. **Anchored** and **Floating** joysticks split the screen by handedness. Anchored joysticks snap (within the snap radius) to the fixed HUD position; Floating joysticks start where you touch.

* **Platform-Native Injection:** Windows via the Interception driver, Linux via `evdev`/`uinput` (X11 supported).

* **Multiprocess by design:** dedicated worker processes and helper threads, with heartbeat monitors and live status logging.

* **Layout Editor (GUI):** PySide6/Matplotlib canvas for placing zones, adjusting priorities (`P`/`O` keys or the inspector), resizing, and saving to SQLite.

* **Live Input Visualizer (`touch2key-visualizer`):** loads your active layout, highlights hitboxes as you trigger them, and respects your configured toggle hotkeys, so you can test mappings outside a game.

* **Anti-Cheat Safe:** humanized dwell times and randomized click durations for user-initiated actions only. No macros, scripts, or game-state tampering.

## Architecture Diagram

A full-stack diagram of Touch2Key (CLI and bootstrap scripts, the PySide6 GUI and plotter, overlays, SQLite and telemetry, and the 3-phase engine down to the OS driver workers) is generated by `assets/touch2key_arch.py`. One run produces every format below, written next to the script in `assets/`:

| Output | File | Best for |
| :--- | :--- | :--- |
| **PDF** (vector) | `touch2key_full_architecture.pdf` | Reading the whole diagram: text stays sharp at any zoom. |
| **SVG** (vector) | `touch2key_full_architecture.svg` | Opening in a browser, or embedding in docs and web pages. |
| **PNG** (full) | `touch2key_full_architecture.png` | A single raster image of the entire diagram (about 24000 px wide). Very large, so some phone galleries and image viewers will downsample it and look blurry. Prefer the PDF/SVG, or the split PNGs below. |
| **PNG** (split) | `PNG/01_…` to `PNG/07_…` | One image per layer or engine phase, each sized to be readable when fit to the screen. Good for slides and docs. |

The split PNGs are:

| File | Section |
| :--- | :--- |
| `01_layer1_cli_bootstrap.png` | Layer 1: bootstrap, CLI scripts, ADB utilities, dual-mode dialogs |
| `02_layer2_gui.png` | Layer 2: PySide6 GUI, debounced settings, Matplotlib plotter |
| `03_layer3_overlays.png` | Layer 3: visualizer and virtual keyboard overlays |
| `04_layer4_storage_telemetry.png` | Layer 4: SQLite store, config I/O, telemetry snapshot |
| `05_engine_phase1_construction.png` | Engine phase 1: reload transaction and 5-key tier sorting |
| `06_engine_phase2_dispatch.png` | Engine phase 2: touch ingestion, two-finger tap FSM, ownership dispatch |
| `07_engine_phase3_execution.png` | Engine phase 3: pipeline execution, mouse flush, hardware bridge workers |

In the split PNGs, only connections between cards in the same section are drawn. Arrows between layers and phases appear only in the full diagram (PDF, SVG, and full PNG).

See [Contributing](#contributing) for how to regenerate the diagram.

## Window Selection & Persistence

* **CLI mode:** on startup the engine shows a window selector (a refreshing terminal list, or a dialog with `--use-gui`) listing active windows with their titles and classes. On Windows you can also choose the Interception keyboard and mouse devices.
* **GUI mode:** configuration is dynamic and not tied to startup. Change the target window and devices any time from **Settings**.
* **Self-healing tracking:** if the target window is lost (crash or restart), the engine uses the saved window class to re-acquire the largest visible matching window automatically.

## Key Customization & Storage

* **Capture:** bind the **Sprint** key and set performance limits (**ADB Rate Cap** and **PPS Alert Threshold**).
* **SQLite is the single source of truth** (`touch2key.db`): layout zones, priorities, hitboxes, and runtime defaults (system gestures, typematic rules), with foreign-key cascade protection.
* **Import/Export bundles:** TOML and JSON are used only to import, export, and share configurations or legacy layouts, never for active runtime state.

## Connectivity & Device Management

* **Auto-adaptive multi-touch:** queries the touchscreen's `ABS_MT_*` capabilities and slot count over ADB on connect.
* **Wired & wireless ADB:** USB by default. For wireless play, connect to the phone's hotspot, plug in USB, and wait for the successful `adb tcpip 5555` handshake log before unplugging.
* **Resilient stream:** cable or Wi-Fi drops pause the input pump and resume when ADB reconnects, with no crashes or stuck keys.

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

## Automated Maintenance & Privacy

* **Application logs:** pruned after **60 days** or beyond **100 files**, whichever comes first.
* **Diagnostic dumps:** kept up to **60 days**, capped at the **20 most recent** files.
* **Local only:** logs and runtime data are stored in the local `data/` directory, separate from application assets.

## Icon Shortcuts

Running setup from the GUI (`touch2key-gui`) or the terminal (`touch2key-setup`) also creates a desktop shortcut that launches the GUI. Uninstalling always removes it.

## Contributing
Use `black` for formatting (recommended), `pytest` for tests, and `snakeviz` to view profiles. Install the Python dev packages with `pip install -e .[dev]` (installs `build`). 

### Regenerating the architecture diagram

To modify and regenerate the architecture diagram, edit `assets/touch2key_arch.py` and run it. This requires the `graphviz` Python package (`pip install graphviz`) **and** the system-level Graphviz binaries:
* **Windows:** `choco install graphviz` or download from [graphviz.org](https://graphviz.org/download/)
* **Linux:** `sudo apt install graphviz` (or your distribution's equivalent)

```bash
python assets/touch2key_arch.py              # writes next to the script (assets/)
python assets/touch2key_arch.py path/to/out  # or into a folder of your choice
```

A single run writes the PDF, SVG, full PNG, and the split `PNG/` folder described in [Architecture Diagram](#architecture-diagram). Notes:
* **PNG size:** the full PNG uses tighter spacing (`nodesep`/`ranksep`) and an automatically chosen DPI, so Graphviz's cairo renderer never has to downscale it ("graph is too large for cairo-renderer bitmaps"). Tune `PNG_MAX_PIXELS` and `PNG_TARGET_DPI` at the top of the script for a lighter or sharper file.
* **Split PNGs:** each section is laid out on its own at `SPLIT_DPI` (default 200). Adjust `SPLIT_NAMES`, `SPLIT_DPI`, `SPLIT_MAX_PIXELS`, or `EXTRA_CHAINS` (which stacks cards into one column) to change the split output.
* **Vector output:** the PDF and SVG keep the original spacing and have no bitmap size limit.

Contributions to the main repository likely require the author's permission.

## License
MIT License.
