Touch2Key

""Python 3.10+" (https://img.shields.io/badge/python-3.10+-blue.svg)" (https://www.python.org/downloads/)
""OS: Windows" (https://img.shields.io/badge/os-Windows-blue.svg)" (https://www.microsoft.com/en-us/windows)
""OS: Linux" (https://img.shields.io/badge/os-Linux-yellow.svg)" (https://www.linuxfoundation.org/)
""License: MIT" (https://img.shields.io/badge/License-MIT-green.svg)" (https://opensource.org/licenses/MIT)

Touch2Key is a high-performance, cross-platform input mapper that translates touchscreen input from an Android device into low-latency keyboard and mouse input on your PC through ADB.

This is the second published implementation of Touch2Key, featuring a full GUI, CLI support, and an expanded feature set.

The original implementation, which provides a CLI and basic GUI windows, is available "here" (https://github.com/Chukxz/touch2keybare).

⚡ At a Glance

- Purpose: Turn your phone's touchscreen into a configurable gamepad or HUD for PC games, supporting buttons, joysticks, camera look, and mouse input.
- Platforms: Windows (Interception driver) and Linux ("evdev"/"uinput", with X11 support). An Android device is required.
- Two ways to run: "touch2key-gui" (full GUI, recommended) or "touch2key" (CLI with runtime hotkeys).
- Administrator privileges: Required only for initial setup and uninstallation. Normal operation runs without elevation.
- Storage: SQLite is the single source of truth for runtime settings and layouts. TOML and JSON are used only for importing and exporting configurations.

📦 Prerequisites & Installation

Prerequisites

- Python 3.10+
- An Android device with USB Debugging enabled.
- Windows: Administrator privileges for initial setup (Interception driver installation) and uninstallation. Daily use runs as a standard user.
- Linux: "sudo" privileges for initial setup ("uinput" configuration and "udev" rules) and uninstallation. Daily use runs as a standard user.

Install

Use a virtual environment to avoid package conflicts:

git clone https://github.com/Chukxz/Touch2Key.git
cd Touch2Key
python -m venv .venv

Activate the virtual environment:

- Windows: ".venv\Scripts\activate"
- Linux: "source .venv/bin/activate"

Install the package:

pip install .

🚀 Quick Start

1. On your Android device, enable Developer Options and USB Debugging.

2. Connect your device and accept the RSA fingerprint prompt when it appears.

3. Run the setup wizard once. This requires Administrator privileges on Windows or "sudo" on Linux. A reboot is required after Windows driver installation.
   
   touch2key-setup

4. Launch the application:
   
   touch2key-gui     # Full GUI (recommended)
touch2key         # CLI

5. Select your target game window, create your layout in Layout Studio (GUI), and start the engine.

6. Configure your sprint key and toggle hotkeys where applicable.

«Wireless play: Connect your PC to your phone's hotspot (5 GHz Wi-Fi recommended), then connect the phone through USB for the initial handshake. Once the application confirms that the wireless ADB connection is established, you can unplug the USB cable.»

⚠️ Known Conflicts: Game Streaming Software

If you use game-streaming software such as Sunshine/Moonlight or Apollo/Artemis, disable its virtual controller and mouse inputs where they conflict with Touch2Key's input injection. Otherwise, duplicate or competing inputs may occur.

💻 Command-Line Interface (CLI) & GUI Commands

Command| Description
"touch2key"| Launches the engine in CLI mode.
"touch2key --profile"| Launches CLI mode with profiling enabled.
"touch2key --use-gui"| Runs CLI mode with a "QApplication" context. This supports certain GUI windows but does not launch the full GUI.
"touch2key-gui"| Launches the full GUI.
"touch2key-gui --profile"| Launches GUI mode with profiling enabled.
"touch2key-gui --terminal-log {auto,on,off}"| Controls terminal logging in GUI mode. "auto" (default) prints only when a terminal is available; "on" prints whenever a console stream exists; "off" disables terminal output. Logs are always written to the log file.
"touch2key-adb"| Displays the full path to the ADB executable, if found.
"touch2key-capture"| Captures the Android device's screen through ADB.
"touch2key-manage"| Interactive manager for layouts, profiles, images, and typematic settings.
"touch2key-plot"| Launches the mapping visualizer.
"touch2key-preflight"| Runs diagnostic and preflight checks.
"touch2key-setup"| Launches the OS configuration wizard for drivers, rules, binaries, and shortcuts.
"touch2key-stats"| Displays live telemetry from the running engine.
"touch2key-uninstall"| Removes installed drivers, rules, binaries, and shortcuts.
"touch2key-wireless"| Forces an ADB wireless connection.
"touch2key-keyboard"| Runs the standalone virtual keyboard test.
"touch2key-visualizer"| Launches the live input visualizer with the active layout and toggle hotkeys.

One-Line Configuration Flag

The comma-separated configuration format is:

"window_id,sprint_key,rate_cap,pps,k_device,m_device"

Leave fields empty to use their defaults or database values.

For example:

touch2key --config

An example configuration string is:

,,100,50,,

Toggle Hotkeys, Typematic & System Commands ("touch2key-manage")

Use "touch2key-manage" to configure toggle hotkeys, automatic key repeat, two-finger tap, bezel toggles, and left-handed mode.

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

Telemetry ("touch2key-stats")

"touch2key-stats" attaches to a running engine, whether launched through the GUI or CLI.

touch2key-stats                  # Sample every second until Ctrl+C
touch2key-stats -i 5             # Sample every 5 seconds
touch2key-stats --once           # Take one sample; exit with code 1 if no engine is running
touch2key-stats --json >> t.log  # Append JSON Lines output to a log file
touch2key-stats -c, --clear      # Clear the terminal between samples (ignored with --json)

⌨️ CLI Global Hotkeys

In CLI mode, these hotkeys adjust engine settings at runtime. They are active only while the terminal is the foreground window, preventing them from interfering with games. Losing terminal focus is treated as releasing all held CLI hotkeys.

Hotkey| Action| Step / Bounds| Description
"Esc"| Shutdown| —| Gracefully stops the engine and its worker processes.
"F5"| Handedness Toggle| "True" / "False"| Switches between left- and right-handed layouts, then reloads the configuration.
"F6"| Reload| —| Reloads the layout, pipelines, and settings (including typematic) from SQLite.
"F8"| Input Curve Cycle| Linear / Cubic / Exponential / Logarithmic| Cycles through easing curves used for arrow-key adjustment speed.
"Left" / "Right"| Rate Cap (Hz)| ±10.0 Hz "[30.0–1000.0]"| Adjusts the mouse flush and touch-reader polling rate. Holding a key enables repetition.
"Down" / "Up"| PPS Alert Threshold| ±5.0 PPS "[10.0–500.0]"| Adjusts the touch-monitoring threshold. Holding a key enables repetition.

Behavior

- Arrow keys: Apply one adjustment on press. After a 400 ms hold, repetition starts at 5 Hz and ramps along a cubic curve to 30 Hz over 1.5 seconds. OS-generated key-repeat events are ignored, and releasing the key resets the ramp.
- F5 / F6 / F8: Trigger once per physical press, with a shared 350 ms cooldown.
- Opposing keys cancel: Pressing Left + Right or Down + Up simultaneously produces no adjustment. Different axes can operate simultaneously.
- Live status line: While an arrow key is held, one terminal line displays the current "Rate Cap" and "PPS". Other log output is temporarily held and replayed after release.
- Persistence: Values are updated in memory on every step. SQLite writes and reloads are batched to a maximum frequency of once every 250 ms, and the final value is saved after release.

In GUI mode, Qt handles the arrow keys. The same values can be adjusted through the Settings page using ADB Rate Cap and PPS Alert Threshold.

🏗️ Architecture & Core Features

5-Stage Input Pipeline

Every touch contact passes through an isolated, modular pipeline:

"Region" → "Origin" → "Constraint" → "Transformation" → "Semantic"

Each stage has a distinct responsibility:

- Region: Detects whether a touch falls within a configured zone.
- Origin: Establishes the reference position for subsequent calculations.
- Constraint: Applies spatial or movement boundaries.
- Transformation: Applies mathematical transformations to the input.
- Semantic: Converts the processed input into keyboard or mouse actions.

Separating spatial detection, reference baselines, constraints, mathematical transformations, and driver output helps prevent state drift and conflicting input behavior.

Deterministic Dispatching

Contacts are routed using a strict five-key precedence sort:

1. Type Precedence: Button ("3") > Bezel ("2") > Joystick ("1") > Mouse ("0").
2. Explicit Priority: Custom priority tier, ranging from "+200" to "-100".
3. Allow Multi Claim: "True" entries are sorted before "False", allowing eligible overlapping zones in the same tier to claim a contact together.
4. Hitbox Specificity: Smaller hitboxes are evaluated before broader or full-screen zones.
5. Creation Order: Provides a deterministic tie-breaker.

Hardware-Accurate Typematic (Key Auto-Repeat)

- Repeat pulses run inside the driver worker processes, avoiding pipe saturation and IPC latency during repeated key output.
- Pressing a new key takes over repeat ownership without releasing other held keys. This allows diagonal movement to remain active while action keys are pressed repeatedly.
- Delay, repeat rate, and exclusions can be changed live through the GUI or CLI without restarting the workers.

Defensive Input Ownership

- Multi-claim: Overlapping buttons in the same priority tier can claim a contact together, enabling multiple key outputs from one touch.
- Single-owner: Joysticks and camera-look zones own exactly one contact, preventing duplicated deltas and conflicting movement.

Hybrid Mode Switching (In-Game vs. Menu)

Touch2Key supports two input modes:

- In-Game (cursor hidden): HUD zones capture taps and drags to control game inputs.
- Menu (cursor visible): Game-control buttons are deactivated, and single touches become absolute desktop clicks for navigating lobbies, maps, and inventories.

Touchscreen-only switching: Both bezel zones can be toggled through settings, and bezel zones are automatically seeded into every layout.

- Top Bezel: Toggles cursor visibility (Game Mode / Menu Mode) by executing the configured toggle-hotkey sequence.
- Bottom Bezel: Opens the Virtual Keyboard through direct IPC to the engine for low-latency typing. Typematic is suspended while the virtual keyboard is active.
- Two-Finger Tap: Available only in Menu Mode (cursor visible). Tapping with two fingers anywhere on the screen gracefully shuts down the engine process. The gesture is ignored in Game Mode and uses time-driven polling to avoid requiring movement during stationary holds.

Camera & Joysticks

- Buttons: Pointer zones can emit keypresses and camera deltas together, allowing actions such as aiming while shooting.
- Fixed joysticks: Stay at their configured HUD positions, leaving the remaining screen area available for camera look.
- Anchored joysticks: Snap to the configured HUD position when touched within the default snap radius of "80.0" pixels.
- Floating joysticks: Begin at the initial touch position.

Anchored and floating joystick layouts can be arranged according to the selected handedness.

Platform-Native Injection

- Windows: Uses the Interception driver.
- Linux: Uses "evdev"/"uinput", with X11 support.

Multiprocess Architecture

Touch2Key uses dedicated worker processes and helper threads, with heartbeat monitoring and live status logging.

Layout Editor (GUI)

The PySide6/Matplotlib-based Layout Studio provides tools for placing and configuring zones, adjusting priorities ("P"/"O" keys or the inspector), resizing hitboxes, and saving layouts to SQLite.

Live Input Visualizer ("touch2key-visualizer")

The live visualizer loads your active layout and highlights hitboxes as they are triggered.

It dynamically scales and offsets the layout to match the active target window when the engine is running, or uses fullscreen positioning when running standalone.

It also respects your configured toggle hotkeys, allowing you to test mappings outside a game. Its own hotkeys are displayed in an overlaid diagnostics panel.

Gameplay Automation & Anti-Cheat Considerations

Touch2Key is designed as an input-mapping tool rather than a gameplay automation system.

It does not provide gameplay bots, automated gameplay macros, or game-state manipulation. Its toggle shortcuts operate as system-level mode switches.

Humanized dwell times and randomized click durations are used for user-initiated actions. However, compatibility with individual games and their anti-cheat systems is not guaranteed; users should check the relevant game's rules and policies.

📐 Architecture Diagram

A full-stack architecture diagram of Touch2Key is generated by "assets/touch2key_arch.py". It covers the CLI and bootstrap scripts, PySide6 GUI and plotter, overlays, SQLite and telemetry, and the three engine phases down to the OS driver workers.

Only the PDF is included by default in the repository.

One execution generates all the formats listed below, writing them next to the script in "assets/".

Output| File| Best for
PDF (vector)| "touch2key_full_architecture.pdf"| Reading the complete diagram. Text remains sharp at any zoom level.
SVG (vector)| "touch2key_full_architecture.svg"| Opening in a browser or embedding in documentation and web pages.
PNG (full)| "touch2key_full_architecture.png"| A single raster image of the entire diagram (approximately 24,000 pixels wide). Very large; some phone galleries and image viewers may downsample it and make it appear blurry. Prefer the PDF, SVG, or split PNGs.
PNG (split)| "SPLIT_ARCHITECTURE_PNGS/01_…" to "SPLIT_ARCHITECTURE_PNGS/07_…"| Individual images for each layer or engine phase, sized for readability on screen. Useful for slides and documentation.

The split PNGs are:

File| Section
"01_layer1_cli_bootstrap.png"| Layer 1: Bootstrap, CLI scripts, ADB utilities, and dual-mode dialogs
"02_layer2_gui.png"| Layer 2: PySide6 GUI, debounced settings, and Matplotlib plotter
"03_layer3_overlays.png"| Layer 3: Visualizer and virtual keyboard overlays
"04_layer4_storage_telemetry.png"| Layer 4: SQLite store, configuration I/O, and telemetry snapshot
"05_engine_phase1_construction.png"| Engine phase 1: Reload transaction and five-key tier sorting
"06_engine_phase2_dispatch.png"| Engine phase 2: Touch ingestion, two-finger tap FSM, and ownership dispatch
"07_engine_phase3_execution.png"| Engine phase 3: Pipeline execution, mouse flush, and hardware bridge workers

In the split PNGs, only connections between cards within the same section are drawn. Arrows connecting layers and engine phases appear only in the full diagram (PDF, SVG, and full PNG).

See "Contributing" (#-contributing) for instructions on regenerating the diagram.

🪟 Window Selection & Persistence

- CLI mode: On startup, the engine displays a window selector. Depending on the launch mode, this is either a refreshing terminal list or a dialog opened with "--use-gui". On Windows, you can also select the Interception keyboard and mouse devices.
- GUI mode: Configuration is dynamic and is not restricted to startup. You can change the target window and devices at any time through Settings.
- Self-healing tracking: If the target window is lost (for example, because the game crashes or restarts), the engine uses the saved window class to reacquire the largest visible matching window automatically.

🗄️ Key Customization & Storage

- Capture: Bind the Sprint key and configure performance limits such as the ADB Rate Cap and PPS Alert Threshold.
- SQLite as the single source of truth: The "touch2key.db" database stores layout zones, priorities, hitboxes, and runtime defaults, including bezel settings, gestures, and typematic rules. Foreign-key cascade protection helps maintain database integrity.
- Import/Export bundles: TOML and JSON are used only to import, export, and share configurations or legacy layouts. They are not used as active runtime storage.

📡 Connectivity & Device Management

- Auto-adaptive multi-touch: On connection, Touch2Key queries the touchscreen's "ABS_MT_*" capabilities and slot count through ADB.
- Wired and wireless ADB: USB is used by default. For wireless play, connect the phone to the PC's hotspot, establish the initial USB connection, and wait for the successful "adb tcpip 5555" handshake message before unplugging.
- Resilient input stream: If the USB cable or Wi-Fi connection drops, the input pump pauses and resumes when ADB reconnects, helping prevent crashes and stuck inputs.

🧹 Uninstallation

Touch2Key installs system-level drivers and kernel rules, so running "pip uninstall Touch2Key" alone is not sufficient. Run the Touch2Key uninstaller before removing the Python package.

«Elevation: Administrator privileges are required on Windows; Linux requires "sudo".»

Action| Command| Description
Standard| "touch2key-uninstall"| Removes drivers, rules, binaries, and shortcuts while preserving user data.
Purge| "touch2key-uninstall --purge"| Performs standard uninstallation and deletes user data, including JSON files, images, profile bundles, settings TOML files, runtime files, and the database.
Purge-All| "touch2key-uninstall --purge-all"| Performs Purge and also deletes diagnostic (".prof") and log files.
Skip Confirmation| "touch2key-uninstall --yes" or "touch2key-uninstall -y"| Skips the confirmation prompt.
Skip Reboot| "touch2key-uninstall --no-restart"| Skips the reboot prompt on Windows.

(Windows requires a reboot after uninstallation to release the driver.)

🔒 Automated Maintenance & Privacy

- Application logs: Pruned after 60 days or when the number of files exceeds 100, whichever condition is reached first.
- Diagnostic dumps: Retained for up to 60 days, with a maximum of the 20 most recent files.
- Local storage: Logs and runtime data are stored locally in the "data/" directory, separately from application assets.

🖥️ Desktop Shortcuts

Running setup through either "touch2key-gui" or "touch2key-setup" also creates a desktop shortcut for launching the GUI.

Uninstallation removes the shortcut.

🤝 Contributing

Use "black" for formatting (recommended), "pytest" for testing, and "snakeviz" for viewing profiling results.

Install the development dependencies with:

pip install -e .[dev]

This installs "flake8", "build", and "graphviz".

Regenerating the Architecture Diagram

To modify and regenerate the architecture diagram, edit "assets/touch2key_arch.py" and run it.

Generation requires the Python "graphviz" package:

pip install graphviz

It also requires the system-level Graphviz binaries:

- Windows: "choco install graphviz"
- Linux: "sudo apt install graphviz" (or the equivalent package for your distribution)

Alternatively, download Graphviz from "graphviz.org" (https://graphviz.org/download/).

Run:

python assets/touch2key_arch.py              # Write outputs next to the script (assets/)
python assets/touch2key_arch.py path/to/out  # Write outputs to a specified directory

A single execution generates the PDF, SVG, full PNG, and "SPLIT_ARCHITECTURE_PNGS/" folder described in the "Architecture Diagram" (#-architecture-diagram) section.

Additional notes:

- PNG size: The full PNG uses tighter spacing ("nodesep"/"ranksep") and an automatically selected DPI to avoid Graphviz's cairo-renderer bitmap downscaling error: "graph is too large for cairo-renderer bitmaps". Adjust "PNG_MAX_PIXELS" and "PNG_TARGET_DPI" near the top of the script to control output size and sharpness.
- Split PNGs: Each section is rendered independently at "SPLIT_DPI" (default: 200). Adjust "SPLIT_NAMES", "SPLIT_DPI", "SPLIT_MAX_PIXELS", or "EXTRA_CHAINS" (which stacks cards into a single column) to change the split output.
- Vector output: PDF and SVG retain the original spacing and do not have the bitmap size limitations of raster output.

Contributions to the main repository may require the author's permission.

📄 License

MIT License.