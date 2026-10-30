"""
Full-stack architecture diagram generator for Touch2Key.
Covers CLI/Bootstrap scripts, PySide6 GUI & Matplotlib Plotter, Overlays,
SQLite/Config I/O/Telemetry, and the 3-Phase Core Engine & OS Driver Workers.

Outputs: PDF (vector), SVG (vector), PNG (compact layout, adaptive DPI so
cairo never has to downscale the bitmap).
"""

from __future__ import annotations

import sys
from pathlib import Path

import graphviz

# Cairo bitmap hard limit is ~32767 px per side; stay well under it.
PNG_MAX_PIXELS = 24000
PNG_TARGET_DPI = 300


def _esc(text: str) -> str:
    """Idempotently escapes &, <, and > so raw arrows/generics never break Graphviz's HTML lexer."""
    raw = (
        text.replace("&amp;", "&")
        .replace("&lt;", "<")
        .replace("&gt;", ">")
    )
    return (
        raw.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )


def _card(
    title: str,
    subtitle: str,
    rows: list[tuple[str, str]],
    header_bg: str = "#1e293b",
    header_fg: str = "#ffffff",
    body_bg: str = "#f8fafc",
    border_color: str = "#94a3b8",
) -> str:
    """Builds an XML-safe Graphviz HTML-table node."""
    tr_list = [
        f'<TR><TD COLSPAN="2" BGCOLOR="{header_bg}" ALIGN="LEFT" CELLPADDING="6">'
        f'<FONT COLOR="{header_fg}"><B>{_esc(title)}</B><BR/>'
        f'<FONT POINT-SIZE="8">{_esc(subtitle)}</FONT></FONT></TD></TR>'
    ]
    for k, v in rows:
        tr_list.append(
            f'<TR>'
            f'<TD BGCOLOR="{body_bg}" ALIGN="LEFT" VALIGN="TOP" CELLPADDING="4"><B>{_esc(k)}</B></TD>'
            f'<TD BGCOLOR="#ffffff" ALIGN="LEFT" VALIGN="TOP" CELLPADDING="4">{_esc(v)}</TD>'
            f'</TR>'
        )
    return (
        f'<<TABLE BORDER="1" CELLBORDER="1" CELLSPACING="0" '
        f'CELLPADDING="0" COLOR="{border_color}">{"".join(tr_list)}</TABLE>>'
    )


def _decision(
    title: str, detail: str, bg: str = "#fef3c7", border: str = "#d97706"
) -> str:
    """Builds a distinct decision node."""
    return (
        f'<<TABLE BORDER="2" CELLBORDER="0" CELLSPACING="0" CELLPADDING="6" '
        f'BGCOLOR="{bg}" COLOR="{border}">'
        f'<TR><TD ALIGN="CENTER"><B>{_esc(title)}</B></TD></TR>'
        f'<TR><TD ALIGN="CENTER"><FONT POINT-SIZE="8">{_esc(detail)}</FONT></TD></TR>'
        f'</TABLE>>'
    )


def build_architecture_digraph(
    nodesep: str = "0.40", ranksep: str = "0.55"
) -> graphviz.Digraph:
    dot = graphviz.Digraph(name="Touch2Key_Full_Architecture")

    # splines="polyline" eliminates ortho edge-label warnings and routes 5x faster
    dot.attr(
        rankdir="TB",
        fontname="Helvetica,Arial,sans-serif",
        fontsize="14",
        labelloc="t",
        label=(
            "<<B>TOUCH2KEY FULL-STACK ARCHITECTURE: GUI, CLI SCRIPTS, SQLITE STORE, "
            "TELEMETRY &amp; 3-PHASE ENGINE PIPELINE (ADB -&gt; OS DRIVERS)</B>>"
        ),
        fontcolor="#0f172a",
        bgcolor="#ffffff",
        pad="0.35",
        nodesep=nodesep,
        ranksep=ranksep,
        splines="polyline",
    )
    dot.attr(
        "node",
        shape="plain",
        fontname="Helvetica,Arial,sans-serif",
        fontsize="10",
    )
    dot.attr(
        "edge",
        fontname="Helvetica,Arial,sans-serif",
        fontsize="9",
        color="#334155",
        fontcolor="#0f172a",
        penwidth="1.3",
        arrowsize="0.75",
    )

    # =======================================================================
    # LAYER 1: BOOTSTRAP, CLI SCRIPTS & DEVICE/WINDOW ACQUISITION
    # =======================================================================
    with dot.subgraph(name="cluster_layer1_scripts") as c:
        c.attr(
            label="<<B>LAYER 1: BOOTSTRAP, CLI SCRIPTS, ADB UTILITIES &amp; DUAL-MODE DIALOGS (modules.scripts.* &amp; modules.cli.*)</B>>",
            style="rounded,filled",
            fillcolor="#f1f5f9",
            color="#64748b",
        )
        c.node(
            "PreflightAndAdb",
            _card(
                "1A. Environment Preflight &amp; ADB Discovery",
                "touch2key-preflight (preflight.py) | touch2key-adb (check_adb.py)",
                [
                    ("check_adb()", "Checks BIN_FOLDER/adb (ADB.exists()) -&gt; fallback shutil.which('adb') -&gt; resolves absolute binary path"),
                    ("check_driver()", "Win32: Interception().valid check | Linux: Path('/dev/uinput').exists() verification"),
                    ("Failure Reporting", "Returns bool; logs actionable remediation (touch2key-setup / sudo touch2key-setup / PC reboot)"),
                ],
                header_bg="#334155",
            ),
        )
        c.node(
            "SetupAndUninstall",
            _card(
                "1B. Platform Bootstrap &amp; Uninstaller",
                "touch2key-setup (setup.py) | touch2key-uninstall (uninstall.py) [--gui, -y, --no-restart, --purge, --purge-all]",
                [
                    ("Privilege Elevation", "Win32: IsUserAnAdmin() -&gt; ShellExecuteW('runas', sys.executable, '-m ...') | Linux: pkexec (GUI) or sudo (CLI)"),
                    ("OS Driver Setup", "setup_windows() installs Interception &amp; platform-tools | setup_linux() writes UDEV_RULE_PATH &amp; reloads udevadm"),
                    ("Desktop Shortcuts", "Win32: PowerShell WScript.Shell -&gt; Touch2Key.lnk (pythonw.exe -m modules.gui.app) | Linux: touch2key.desktop (0o755)"),
                    ("Uninstall &amp; Purge", "store.close() -&gt; _kill_adb() (taskkill/pkill) -&gt; install-interception.exe /uninstall or udev rm -&gt; rmtree(BIN/DATA/LOGS/DIAGNOSTICS)"),
                ],
                header_bg="#1e293b",
            ),
        )
        c.node(
            "AdbCaptureAndWireless",
            _card(
                "1C. ADB Screen Capture &amp; Wireless Handshake",
                "touch2key-capture (adb_screen_capture.py) | touch2key-wireless (wireless_connect.py &amp; wireless_connect_dialog.py)",
                [
                    ("Device Metrics", "get_adb_device() -&gt; _get_device_dpi() (get_dpi() or 'adb shell wm density', fallback BASELINE_DPI) + get_rotation() + rotate_resolution()"),
                    ("ADB Screencap", "adb shell screencap -p /data/local/tmp/temp_cap.png (30s timeout) -&gt; adb pull (20s) -&gt; finally: adb shell rm"),
                    ("PIL &amp; Layout Sync", "Image.open() -&gt; img.load() (releases Win32 file lock) -&gt; img.save(dpi=(dpi,dpi)) -&gt; store.layouts.update(id, image_path, w, h, dpi)"),
                    ("Wireless ADB", "CLI: wireless_connect(continuous=True) | GUI: WirelessConnectDialog + WirelessConnectWorker(QThread) polling every 1.0s (10x0.1s)"),
                ],
                header_bg="#0f766e",
            ),
        )
        c.node(
            "WindowAndKeyCapture",
            _card(
                "1D. Dual-Mode Window Selector &amp; Key/Numeric Capture",
                "select_window() (list_windows.py) | capture_sprint_key() &amp; capture_performance_settings() (key_capture.py)",
                [
                    ("Window Enumeration", "_gather_window_rows(WindowManager): find_visible_windows() -&gt; filters width &gt; 0 &amp; height &gt; 0 -&gt; [wid, title, class, l, t, w, h]"),
                    ("CLI Selector", "1.0s auto-refresh table via AppLogManager.console_write; 50ms non-blocking poll (Win32 msvcrt.getch | Unix tty.setcbreak + select)"),
                    ("GUI Selector", "ListApp(QDialog): QTableWidget with 1000ms QTimer diff-sync (added_ids, removed_ids, current_ids) &amp; UserRole wid storage"),
                    ("Capture Dialogs", "KeyCaptureDialog(QDialog) (get_specific_qt_key -&gt; get_scancode_from_key) &amp; NumericCaptureDialog(QDialog) vs CLI input() prompts"),
                ],
                header_bg="#0369a1",
            ),
        )
        c.node(
            "CliManage",
            _card(
                "1E. CLI Layout, Profile &amp; Settings Manager",
                "touch2key-manage (modules/cli/manage.py) — Argparse Flags &amp; Interactive Loop",
                [
                    ("Profile &amp; Zone CRUD", "--list, --filter, --sort, --new [--dims W H DPI], --set-active, --duplicate, --rename, --delete, --clear-zones, --reset-zones"),
                    ("Zone Inspector CLI", "--list-zones, --set-bezels ID TOP BOT, --edit-zone ZID [--zone-priority/pointer/sens-x/sens-y/deadzone/hysteresis], --reset-zone, --delete-zone"),
                    ("Directionals &amp; Image", "--show-directional-keys, --edit-layout-directionals ID --set-key {up,left,down,right}, --set-image ID PATH (calls apply_image_params)"),
                    ("Global Tuning &amp; I/O", "_normalize_key_seq() ('k1,k2' replace, '+k1' append, '+wasd'/'+arrows' presets, 'clear' wipe), --import/export-json/toml/bundle, --wipe-database"),
                ],
                header_bg="#1d4ed8",
            ),
        )

    # =======================================================================
    # LAYER 2: PYSIDE6 GRAPHICAL USER INTERFACE & MATPLOTLIB PLOTTER
    # =======================================================================
    with dot.subgraph(name="cluster_layer2_gui") as c:
        c.attr(
            label="<<B>LAYER 2: PYSIDE6 GRAPHICAL USER INTERFACE, DEBOUNCED SETTINGS &amp; MATPLOTLIB PLOTTER (modules.gui.*)</B>>",
            style="rounded,filled",
            fillcolor="#e0f2fe",
            color="#38bdf8",
        )
        c.node(
            "GuiMainWindow",
            _card(
                "2A. MainWindow &amp; EngineProcessController",
                "touch2key-gui (modules/gui/main_window.py) — Process Lifecycle &amp; Thread-Safe Event Bridge",
                [
                    ("EngineProcessController", "Manages engine multiprocessing.Process, holds lock for (window_id, window_title, k_id, m_id), pipes runtime IPC commands"),
                    ("Page Navigation &amp; Dock", "QStackedWidget hosting DashboardPage, LayoutStudioPage, SettingsPage + collapsible Log Dock fed by QtLogHandler"),
                    ("Close &amp; Action Guards", "save_all_pages(action) invokes LayoutStudioPage.save_state() (Save/Discard/Cancel prompt) &amp; SettingsPage._flush_pending()"),
                ],
                header_bg="#0284c7",
            ),
        )
        c.node(
            "DashboardPageNode",
            _card(
                "2B. DashboardPage (Live Telemetry &amp; Session Summary)",
                "modules/gui/pages/dashboard_page.py — 1000ms QTimer (Active Only While Visible)",
                [
                    ("Dispatcher Hooks", "Registers ON_RELOAD -&gt; _reload_requested Signal &amp; ON_TARGET_WINDOW_CHANGE -&gt; _target_window_changed Signal (queued to GUI thread)"),
                    ("Session Summary", "Displays active Layout name/ID, non-bezel zone count (count_by_layout()), Target Window title/HWND, Toggle Hotkeys, Sprint, k_id/m_id"),
                    ("Snapshot Telemetry", "read_snapshot(expected_pid) -&gt; checks snapshot_age() &gt; STALE_AFTER_S; renders rate_hz, rate_status, cap/pps drift warnings, DOWN/MOVE/UP/ALL counts"),
                    ("Process Tree Sampler", "labeled_processes(engine, snap) -&gt; cached psutil.Process.oneshot() sampling CPU %, RSS MB, thread count, worker respawns, VKB/Visualizer status"),
                ],
                header_bg="#0369a1",
            ),
        )
        c.node(
            "LayoutStudioPageNode",
            _card(
                "2C. LayoutStudioPage (3-Pane Editor &amp; Pipeline Inspector)",
                "modules/gui/pages/layout_studio_page.py &amp; touch2key-plot (studio.py)",
                [
                    ("Left Sidebar (Profiles)", "Sort QComboBox (synced to profile_sort_order), Ctrl+F filter, QListWidget with ★ Active, ● &lt;24h recency, * dirty badge; Set Active/New/Rename/Duplicate"),
                    ("Center Toolbar", "Select Image / Capture Screenshot (_apply_image -&gt; get_image_params), Toggle Overlays (F4), Add Circle (F6), Add Rect (F7), Cancel (Esc), Save (Ctrl+S / Ctrl+Shift+S)"),
                    ("Right Inspector (Stack)", "Page 0: Top/Bottom Bezel SpinBoxes (MIN..MAX_BEZEL_DP) + Reset All Zones | Page 1: Zone Priority, Ignore AppSettings, Sens X/Y, Deadzone, Hysteresis, Pointer"),
                    ("Unsaved Guards", "_confirm_unsaved() prompts before profile switch, duplicate, import, export, or image change; _on_inspector_value_changed updates PipelineConfig JSON"),
                ],
                header_bg="#1d4ed8",
            ),
        )
        c.node(
            "PlotterWidgetNode",
            _card(
                "2D. LayoutsPlotterWidget (Matplotlib QTAgg Blit Canvas)",
                "modules/gui/widgets/layouts_plotter_widget.py — Interactive Geometry &amp; Artist Manager",
                [
                    ("PlotterState FSM", "IDLE | COLLECTING (3-pt Circle circumcenter / 4-pt Rect bbox) | WAITING_FOR_KEY | WAITING_FOR_WHEEL_INDICATOR | DELETING | CONFIRM_DELETE_ALL"),
                    ("Blit Drag Architecture", "Single mpl_connect per event dispatches to _DraggableLabel, _DraggableCircle (rim resize vs drag), _DraggableRectangle (4 corners + 4 edges + drag)"),
                    ("Wheel &amp; Sprint Coupling", "MouseWheelIndicators (4 directional overlays 0:Up, 1:Left, 2:Down, 3:Right; _MouseWheelDragManager vetoes wheel drag); radially constrains Sprint outside wheel"),
                    ("Atomic DB Save", "save_to_database() -&gt; _build_zone_rows() -&gt; store.layouts.save_with_zones() -&gt; store.settings.update(active_layout_id) -&gt; layout_saved Signal -&gt; ON_RELOAD"),
                ],
                header_bg="#4338ca",
            ),
        )
        c.node(
            "SettingsPageNode",
            _card(
                "2E. SettingsPage (Hardware Rebind, Key Filters &amp; Debounced Writes)",
                "modules/gui/pages/settings_page.py — 250ms Coalesced SpinBox Timer with Exponential Backoff",
                [
                    ("Hardware &amp; Window", "Select Target Window -&gt; ON_TARGET_WINDOW_CHANGE | Win32 Detect &amp; Rebind Hardware (select_keyboard_then_mouse) -&gt; ON_DEVICES_CHANGE"),
                    ("Event Filter Captures", "KeyCaptureFilter (single stroke for sprint_key) &amp; ContinuousSequenceFilter (KeySequenceRow for toggle_hotkeys &amp; typematic_excluded_keys; blocks Tab focus traversal)"),
                    ("Debounced SpinBoxes", "_queue_save() batches sensitivity_x/y, deadzone, hysteresis, adb_rate_cap, pps_alert_threshold, typematic_delay_ms/rate_hz -&gt; _flush_pending() every 250ms"),
                    ("Immediate Toggles", "left_handed, floating_joystick, anchored_joystick, typematic_enabled, two_finger_tap_enabled, bezel_toggle_enabled -&gt; immediate store.settings.update() + ON_RELOAD"),
                ],
                header_bg="#1e40af",
            ),
        )

    # =======================================================================
    # LAYER 3: STANDALONE OVERLAYS (VISUALIZER & VIRTUAL KEYBOARD)
    # =======================================================================
    with dot.subgraph(name="cluster_layer3_overlays") as c:
        c.attr(
            label="<<B>LAYER 3: DIAGNOSTIC &amp; RUNTIME IPC OVERLAYS (modules.gui.overlays.*)</B>>",
            style="rounded,filled",
            fillcolor="#ecfeff",
            color="#06b6d4",
        )
        c.node(
            "VisualizerOverlay",
            _card(
                "3A. Live Touch &amp; Input Curve Visualizer",
                "touch2key-visualizer (visualizer.py) — Single-Instance Fullscreen Translucent QGraphicsView",
                [
                    ("Process Registration", "check_single_instance('Touch2Key_Visualizer') -&gt; register_process(VISUALIZER_RUNTIME_FILE) -&gt; atexit unregister"),
                    ("5ms Poll &amp; InputCurve", "Polls Ctrl+Arrows (trail width/height 1..100) &amp; Ctrl+F6/F7 (max trail 500..5000) via InputCurve (LINEAR/CUBIC/EXPONENTIAL cycled via Ctrl+F8)"),
                    ("Bresenham &amp; Ripples", "mouseMoveEvent draws interpolated bresenham() trail rects; key/mouse press spawns 5000ms expiring ripples + #00FF00/#00FFFF text with QGraphicsDropShadowEffect"),
                    ("Live Engine Secret Sync", "Monitors toggle_hotkeys scancodes to flip ShowCursor/BlankCursor; every 2.0s calls attach() to read live device_width/height and rescale zone coordinates"),
                ],
                header_bg="#0891b2",
            ),
        )
        c.node(
            "VirtualKeyboardOverlay",
            _card(
                "3B. Low-Latency Virtual Keyboard (VKB)",
                "touch2key-keyboard — Spawned via Bottom Bezel (0x9906) or CLI",
                [
                    ("Lifecycle &amp; Tracking", "Managed by Engine.toggle_virtual_keyboard(); PID published in runtime snapshot under workers['vkb']"),
                    ("Direct IPC Stream", "Serializes virtual keystrokes into VKB_STRUCT (&lt;BH: action, scancode) and pipes directly to Engine Mapper for zero-focus-loss injection"),
                ],
                header_bg="#0e7490",
            ),
        )

    # =======================================================================
    # LAYER 4: SQLITE STORAGE, CONFIG I/O & RUNTIME TELEMETRY SNAPSHOT
    # =======================================================================
    with dot.subgraph(name="cluster_layer4_data") as c:
        c.attr(
            label="<<B>LAYER 4: SQLITE SINGLE SOURCE OF TRUTH, CONFIG I/O &amp; TELEMETRY SNAPSHOT (modules.database.* &amp; modules.runtime_info)</B>>",
            style="rounded,filled",
            fillcolor="#ffedd5",
            color="#fb923c",
        )
        c.node(
            "SqliteStore",
            _card(
                "4A. SQLite Relational Store (touch2key.db)",
                "modules/database/ — Foreign-Key Cascaded Repositories (store.settings, store.layouts, store.zones)",
                [
                    ("SettingsRepository", "Singleton AppSettings row: handedness, joystick modes, sens_x/y, deadzone, hysteresis, rate_cap, pps, typematic_*, toggle_hotkeys, active_layout_id"),
                    ("LayoutsRepository", "Layout rows (width, height, dpi, mouse_wheel_radius, sprint_distance, image_path); apply_image_params() atomically rescales all non-bezel zones on resolution change"),
                    ("ZonesRepository", "Zone rows (scancode, zone_type, cx, cy, r, x1..y2, priority, pointer, ignore_app_settings, pipeline_json); auto-heals Top (0x9905) &amp; Bottom (0x9906) Bezels"),
                ],
                header_bg="#ea580c",
            ),
        )
        c.node(
            "ConfigIOAndMigration",
            _card(
                "4B. Config I/O &amp; Legacy Migration Engine",
                "modules/database/config_io.py &amp; legacy_migration.py",
                [
                    ("Import Pipeline", "import_any() auto-detects .json layouts (migrate_json_layout), .toml settings (migrate_toml_config), or bundle directories"),
                    ("Export Pipeline", "export_layout_json(), export_settings_toml(linked_json_path), export_bundle() writing portable TOML + JSON pairs to data/profiles/"),
                ],
                header_bg="#c2410c",
            ),
        )
        c.node(
            "RuntimeSnapshot",
            _card(
                "4C. Runtime Telemetry Snapshot &amp; CLI Stats",
                "modules/runtime_info.py | touch2key-stats (stats.py)",
                [
                    ("Snapshot Payload", "JSON file (.touch2key_runtime): pid, timestamp, rate_hz, rate_status, rate_cap_hz, pps_threshold, menu_mode, downs/moves/ups/all, respawns, workers, device_width/height, window_lost"),
                    ("Consumers", "Read every 1.0s by DashboardPage (_update_telemetry), every 2.0s by Visualizer (attach), and by touch2key-stats (-i, --once, --json, --clear)"),
                ],
                header_bg="#9a3412",
            ),
        )

    # =======================================================================
    # PHASE 1: PIPELINE CONSTRUCTION, RELOAD TRANSACTION & 5-KEY TIER SORTING
    # =======================================================================
    with dot.subgraph(name="cluster_phase1_construction") as c:
        c.attr(
            label="<<B>ENGINE PHASE 1: PIPELINE CONSTRUCTION, RELOAD TRANSACTION &amp; DETERMINISTIC 5-KEY TIER SORTING</B>>",
            style="rounded,filled",
            fillcolor="#f8fafc",
            color="#94a3b8",
        )
        c.node(
            "Triggers",
            _card(
                "5.1 Initialization &amp; Reload Triggers",
                "Engine.start_headless() | MapperEvent(action='ON_RELOAD')",
                [
                    ("Initial Boot", "store.settings.get() -&gt; clamps rate_cap [30..1000Hz], pps [10..500], binds callbacks, starts WindowManager self-healing tracker"),
                    ("ON_RELOAD Sources", "CLI [F5] Handedness | CLI [F6] Reload | CLI Arrow Key 250ms Commit | GUI Settings/Studio MapperEvent | IPC (0x03)"),
                    ("Debouncer", "MapperEventDispatcher._debounce_loop (10ms tick); immediate synchronous delivery if cooldown == 0"),
                ],
                header_bg="#0f172a",
            ),
        )
        c.node(
            "ReloadTx",
            _card(
                "5.2 Atomic Reload Transaction (Engine._on_reload under self.lock)",
                "Layout Snapshot Sync &amp; State Boundary Sanitation",
                [
                    ("LayoutLoader", "load_layout() extracts SQLite snapshot: Layout (width, height, dpi), Settings, Zones, Bezels"),
                    ("Hotkeys Guard", "Under _adjust_lock: syncs rate_cap &amp; pps from DB only if not _settings_dirty"),
                    ("TouchReader", "touch_reader.on_reload() &amp; touch_reader.set_rate_cap(self.rate_cap)"),
                    ("_release_active_inputs()", "_dispatch_generation += 1 | clears _contact_owners &amp; _cursor_contacts | resets all pipelines &amp; releases held keys/buttons"),
                ],
                header_bg="#1d4ed8",
            ),
        )
        c.node(
            "Submappers",
            _card(
                "5.3 Submapper Pipeline Reconstruction",
                "Deterministic Rebuild Sequence",
                [
                    ("Mapper.reload()", "Updates device_width, device_height, dpi, toggle_hotkeys_str, pps"),
                    ("BezelMapper", "TOP_BEZEL (0x9905) -&gt; execute_toggle_hotkeys | BOTTOM_BEZEL (0x9906) -&gt; toggle_virtual_keyboard (Prec: 4)"),
                    ("MouseMapper", "Camera Look Pipeline: Always/Half-Screen Region -&gt; DeltaTransform -&gt; PointerSemantic (Prec: 0)"),
                    ("KeyMapper", "update_bridge_typematics() (&lt;B?IfH) + Button Pipelines (Button + optional PointerSemantic, Prec: 2)"),
                    ("WheelMapper", "Joystick Pipeline: Fixed/Anchored/Dynamic Origin -&gt; JoystickTransform -&gt; DirectionalSemantic (Prec: 1)"),
                ],
                header_bg="#15803d",
            ),
        )
        c.node(
            "PipelineContract",
            _card(
                "5.4 Isolated 5-Stage Pipeline Contract (Pipeline[T])",
                "Region -&gt; Origin -&gt; Constraint -&gt; Transformation[T] -&gt; list[Semantic[T]]",
                [
                    ("Stage 1: Region", "AlwaysRegion (area=inf) | CircularRegion (pi*r^2) | RectangularRegion (w*h)"),
                    ("Stage 2: Origin", "FixedOrigin (static) | DynamicOrigin (touch DOWN) | AnchoredOrigin (snap_radius=80.0 - default)"),
                    ("Stage 3: Constraint", "NoConstraint | RadialConstraint (clamp r) | LeashConstraint (pulls origin if dist &gt; leash_r)"),
                    ("Stage 4: Transform", "IdentityTransform -&gt; UNIT | DeltaTransform -&gt; Vector | JoystickTransform -&gt; frozenset[int]"),
                    ("Stage 5: Semantics", "ButtonSemantic (key/mouse) | DirectionalSemantic (WASD diff) | PointerSemantic (dx,dy) | ToggleSemantic (tap)"),
                ],
                header_bg="#6b21a8",
            ),
        )
        c.node(
            "TierSort",
            _card(
                "5.5 Engine._build_pipeline_tiers()",
                "Strict 5-Key Sort &amp; Equivalence Grouping",
                [
                    ("Key 1: -precedence", "Bezel (4) &gt; Button (2) &gt; Joystick (1) &gt; Mouse/Pointer (0) [is_bezel forces max(4, prec)]"),
                    ("Key 2: -priority", "Custom user priority tier (+200 down to -100)"),
                    ("Key 3: -multi_claim", "allow_multi_claim: True (sorted first) before False (sorted last)"),
                    ("Key 4 &amp; 5", "+region.area (smaller hitboxes first) -&gt; +creation_id (deterministic tie-breaker)"),
                    ("Output: self._tiers", "list[list[Pipeline]] partitioned by identical (precedence, priority, allow_multi_claim)"),
                ],
                header_bg="#b45309",
            ),
        )

        c.edges(
            [
                ("Triggers", "ReloadTx"),
                ("ReloadTx", "Submappers"),
                ("Submappers", "PipelineContract"),
                ("PipelineContract", "TierSort"),
            ]
        )

    # =======================================================================
    # PHASE 2: RUNTIME TOUCH INGESTION, TWO-FINGER TAP FSM & OWNERSHIP DISPATCH
    # =======================================================================
    with dot.subgraph(name="cluster_phase2_dispatch") as c:
        c.attr(
            label="<<B>ENGINE PHASE 2: RUNTIME TOUCH INGESTION, TWO-FINGER TAP FSM &amp; CONTACT OWNERSHIP DISPATCH</B>>",
            style="rounded,filled",
            fillcolor="#f0fdf4",
            color="#86efac",
        )
        c.node(
            "TouchIngest",
            _card(
                "6.1 TouchReader -&gt; Engine._process_touch_event(touch_event)",
                "ADB ABS_MT_* Stream (Synchronized under Engine.lock)",
                [
                    ("ADB Auto-Adapt", "Queries ABS_MT_POSITION_X/Y &amp; slot capabilities on connect; auto-pauses &amp; resumes on USB/Wi-Fi drop"),
                    ("Event Payload", "TouchEvent(contact_id: int, phase: DOWN | MOVE | UP, position: Point(x,y), timestamp: float)"),
                    ("Guard &amp; Telemetry", "Aborts if shutting down | Records TouchEventCount &amp; increments mapper.event_count"),
                ],
                header_bg="#0369a1",
            ),
        )
        c.node(
            "MenuGate",
            _decision(
                "Menu Mode Gesture Gate?",
                "self.is_visible and self.two_finger_tap_enabled",
            ),
        )
        c.node(
            "TFTTracker",
            _card(
                "6.2 TwoFingerTapTracker.observe(touch_event)",
                "Ambiguity Buffer FSM (duration &lt;= 0.25s, drift &lt;= 25px, sync &lt;= 0.12s)",
                [
                    ("PENDING", "Buffers candidate event in _buffer and returns early (prevents single-tap leak)"),
                    ("REJECTED", "Replays all buffered events in decision.replay through _dispatch_normal() in order"),
                    ("RECOGNIZED", "Valid synchronized 2-finger tap -&gt; executes toggle_hotkeys to hide cursor &amp; return to Game Mode"),
                    ("IDLE", "Unbuffered non-DOWN event -&gt; proceeds to _dispatch_normal(touch_event)"),
                ],
                header_bg="#b91c1c",
            ),
        )
        c.node(
            "OwnedCheck",
            _decision(
                "1. Is cid in self._contact_owners?",
                "Ownership is locked at DOWN; MOVE/UP never re-evaluate tiers",
            ),
        )
        c.node(
            "RouteOwned",
            _card(
                "6.3 Route to Owning Pipeline(s)",
                "owners = self._contact_owners[cid]",
                [
                    ("Process", "for pipeline in owners: pipeline.process(event, output_sink)"),
                    ("Generation Fence", "Aborts immediately if generation != self._dispatch_generation"),
                    ("UP Cleanup", "If event.phase is TouchPhase.UP: self._contact_owners.pop(cid, None)"),
                ],
                header_bg="#15803d",
            ),
        )
        c.node(
            "CursorContactCheck",
            _decision(
                "2. Is cid in self._cursor_contacts?",
                "Active Menu Mode Desktop Cursor Contact",
            ),
        )
        c.node(
            "DownPhaseCheck",
            _decision(
                "3. Is event.phase == TouchPhase.DOWN?",
                "Unowned MOVE / UP events are ignored",
            ),
        )
        c.node(
            "IterateTiers",
            _card(
                "6.4 Evaluate Sorted self._tiers (DOWN Phase Only)",
                "Deterministic Tier Claim Loop",
                [
                    ("Mode Filters", "Skip bezel if not bezel_toggle_enabled | Skip non-bezel HUD if self.is_visible (Menu Mode)"),
                    ("Claim Test", "pipeline.claims(event) -&gt; _owned_contact is None and region.activates(event)"),
                    ("Multi-Claim Rule", "If allow_multi_claim: claim all matching in tier | Else: break on first claim in tier"),
                    ("Lock Ownership", "If claimed: self._contact_owners[cid] = tuple(claimed) &amp; return"),
                ],
                header_bg="#166534",
            ),
        )
        c.node(
            "DispatchCursor",
            _card(
                "6.5 Engine._dispatch_cursor(event)",
                "Menu Mode Absolute Cursor Fallback (self.is_visible and cid == 0)",
                [
                    ("Coordinate Map", "gx, gy = mapper.device_to_game_abs(x, y) (rotation-aware window/screen normalization)"),
                    ("Driver Output", "bridge.mouse_move_abs(round(gx), round(gy)) | DOWN: left_click_down() | UP: left_click_up()"),
                ],
                header_bg="#0f766e",
            ),
        )

    # =======================================================================
    # PHASE 3: 5-STAGE PIPELINE EXECUTION, OUTPUT SINK & HARDWARE BRIDGE
    # =======================================================================
    with dot.subgraph(name="cluster_phase3_execution") as c:
        c.attr(
            label="<<B>ENGINE PHASE 3: 5-STAGE PIPELINE EXECUTION, FRACTIONAL MOUSE FLUSH &amp; HARDWARE BRIDGE WORKERS</B>>",
            style="rounded,filled",
            fillcolor="#faf5ff",
            color="#d8b4fe",
        )
        c.node(
            "PipelineProcess",
            _card(
                "7.1 Pipeline.process(event, output_sink)",
                "Isolated 5-Stage Per-Contact Execution",
                [
                    ("Stages 1 &amp; 2", "DOWN: _owned_contact = cid; origin.begin(pos) | All: origin.update(pos, constraint); origin_pt = origin.get()"),
                    ("Stage 3: Constraint", "constrained = constraint.apply(origin_pt, pos) | Computes delta &amp; frame_delta in PipelineContext"),
                    ("Stage 4: Transform", "value = transformation.apply(context) -&gt; UNIT | Vector(dx,dy) | frozenset[scancodes]"),
                    ("Stage 5: Semantics", "For semantic in semantics: semantic.process(context, value, output_sink)"),
                    ("UP Teardown", "If phase is UP: origin.end(), transformation.reset(), clears _owned_contact &amp; _prev_position"),
                ],
                header_bg="#6b21a8",
            ),
        )
        c.node(
            "BridgeOutputSinkNode",
            _card(
                "7.2 BridgeOutputSink &amp; Bezel Callbacks",
                "Sub-Pixel Mouse Accumulator &amp; Action Router",
                [
                    ("Keys &amp; Clicks", "key_down/up(scancode) | mouse_down/up(0x9900..0x9904) -&gt; immediate Bridge call"),
                    ("Fractional Move", "mouse_move(dx, dy) -&gt; under _lock: accumulates _acc_x += dx, _acc_y += dy"),
                    ("Top Bezel Callback", "Mapper.execute_toggle_hotkeys(): parse_seq -&gt; key_down stack -&gt; 15-35ms sleep -&gt; LIFO key_up"),
                    ("Bottom Bezel Callback", "Engine.toggle_virtual_keyboard(): spawns/stops VKB process -&gt; VKB_STRUCT (&lt;BH) pipe to Mapper"),
                ],
                header_bg="#1d4ed8",
            ),
        )
        c.node(
            "MouseFlushThreadNode",
            _card(
                "7.3 MouseFlushThread (Engine._mouse_flush_loop)",
                "Rate-Capped Whole-Pixel Dispatcher (1.0 / max(rate_cap, 30.0) s)",
                [
                    ("flush_mouse_move()", "idx, idy = clamp(round(_acc_x), -32767, 32767) -&gt; bridge.mouse_move_rel(idx, idy)"),
                    ("Remainder &amp; Reset", "Retains fractional _acc_x -= idx, _acc_y -= idy | Resets to 0.0 when active_touches == 0"),
                ],
                header_bg="#1e40af",
            ),
        )
        c.node(
            "HardwareBridge",
            _card(
                "7.4 AbstractBridge -&gt; OS Driver Worker Processes (k_proc &amp; m_proc)",
                "3 Dedicated IPC Pipes + 2 Threads Per Worker Process + Watchdog Respawner",
                [
                    (
                        "Platform Signatures",
                        "Win32: keyboard_worker(k_pipe, log_q, k_handle), mouse_worker(m_pipe, mb_pipe, log_q, m_handle), NtSetTimerResolution | Linux: UInput(KEYBOARD_CAP / MOUSE_CAP)",
                    ),
                    (
                        "k_proc Main Thread",
                        "Polls k_pipe (15s timeout -&gt; _release_all_keys): unpacks PACK_KEY (&lt;HB, maps E0/LINUX_KEY_MAP) -&gt; key_queue | unpacks KEY_CONFIG (&lt;B?IfH)",
                    ),
                    (
                        "k_proc Injector Thread",
                        "Drains key_queue: DOWN sleeps 40-70ms dwell, UP sleeps 1ms (stretches fast taps) | Outer loop fires typematic repeat_key after delay_ns at repeat_rate",
                    ),
                    (
                        "m_proc Main Thread",
                        "Polls m_pipe: coalesces up to MAX_COALESCE=20 TASK_REL (&lt;Bhh, 0.8-1.2ms dwell) or TASK_WHEEL (&lt;Bhh, 1ms dwell) + TASK_ABS (&lt;Bii, MOUSE_VIRTUAL_DESKTOP) via send_lock",
                    ),
                    (
                        "m_proc Button Thread",
                        "Polls mb_pipe (15s timeout -&gt; _release_all_buttons): injects PACK_BUTTON (&lt;Bi) under send_lock, then sleeps 25-40ms DOWN / 1ms UP outside lock (never blocks moves)",
                    ),
                ],
                header_bg="#713f12",
            ),
        )

    # =======================================================================
    # CROSS-LAYER & INTER-PHASE EDGES
    # =======================================================================
    dot.edge("AdbCaptureAndWireless", "SqliteStore", label=" Updates layout image_path, w, h, dpi")
    dot.edge("WindowAndKeyCapture", "SqliteStore", label=" Persists sprint_key, rate_cap, pps")
    dot.edge("CliManage", "SqliteStore", label=" Direct CRUD on layouts, zones, settings")
    dot.edge("CliManage", "ConfigIOAndMigration", label=" Import / Export JSON, TOML, Bundles")
    dot.edge("LayoutStudioPageNode", "PlotterWidgetNode", label=" Hosts canvas &amp; syncs Inspector")
    dot.edge("PlotterWidgetNode", "SqliteStore", label=" save_with_zones() + apply_image_params()")
    dot.edge("LayoutStudioPageNode", "ConfigIOAndMigration", label=" GUI Import / Export")
    dot.edge("SettingsPageNode", "SqliteStore", label=" 250ms debounced &amp; immediate updates")
    dot.edge("ConfigIOAndMigration", "SqliteStore", label=" Transactional migration / read")

    dot.edge("GuiMainWindow", "DashboardPageNode", style="dotted")
    dot.edge("GuiMainWindow", "LayoutStudioPageNode", style="dotted")
    dot.edge("GuiMainWindow", "SettingsPageNode", style="dotted")
    dot.edge("GuiMainWindow", "Triggers", label=" Spawns Engine &amp; dispatches IPC (0x03)")
    dot.edge("PlotterWidgetNode", "Triggers", label=" layout_saved -&gt; ON_RELOAD", style="dashed", color="#1d4ed8")
    dot.edge("SettingsPageNode", "Triggers", label=" _notify_reload() -&gt; ON_RELOAD", style="dashed", color="#1d4ed8")
    dot.edge("WindowAndKeyCapture", "GuiMainWindow", label=" Target Window ID / Devices")

    dot.edge("SqliteStore", "ReloadTx", label=" Reads active Layout, Zones, Bezels, Settings", color="#ea580c")

    dot.edge("ReloadTx", "RuntimeSnapshot", label=" Publishes .touch2key_runtime (1Hz)", style="dashed", color="#9a3412")
    dot.edge("RuntimeSnapshot", "DashboardPageNode", label=" 1000ms telemetry &amp; psutil tree poll", color="#9a3412")
    dot.edge("RuntimeSnapshot", "VisualizerOverlay", label=" 2.0s live device_width/height sync", color="#0891b2")
    dot.edge("BridgeOutputSinkNode", "VirtualKeyboardOverlay", label=" Spawns VKB (0x9906)")
    dot.edge("VirtualKeyboardOverlay", "Submappers", label=" VKB_STRUCT (&lt;BH) pipe")

    dot.edge("TierSort", "IterateTiers", label=" Feeds sorted self._tiers", style="dashed", color="#b45309")

    dot.edge("TouchIngest", "MenuGate")
    dot.edge("MenuGate", "TFTTracker", label=" True (Menu Mode)")
    dot.edge("MenuGate", "OwnedCheck", label=" False (In-Game)")
    dot.edge("TFTTracker", "OwnedCheck", label=" IDLE / REJECTED (Replay)")

    dot.edge("OwnedCheck", "RouteOwned", label=" Yes (MOVE/UP)")
    dot.edge("OwnedCheck", "CursorContactCheck", label=" No")
    dot.edge("CursorContactCheck", "DispatchCursor", label=" Yes")
    dot.edge("CursorContactCheck", "DownPhaseCheck", label=" No")
    dot.edge("DownPhaseCheck", "IterateTiers", label=" Yes (DOWN)")
    dot.edge("IterateTiers", "PipelineProcess", label=" Claimed on DOWN")
    dot.edge("IterateTiers", "DispatchCursor", label=" Unclaimed (Menu &amp; cid==0)")

    dot.edge("RouteOwned", "PipelineProcess", label=" pipeline.process()")
    dot.edge("PipelineProcess", "BridgeOutputSinkNode")
    dot.edge("BridgeOutputSinkNode", "MouseFlushThreadNode", label=" _acc_x, _acc_y")
    dot.edge("BridgeOutputSinkNode", "HardwareBridge", label=" Keys / Clicks / Hotkeys")
    dot.edge("MouseFlushThreadNode", "HardwareBridge", label=" mouse_move_rel(idx, idy)")
    dot.edge("DispatchCursor", "HardwareBridge", label=" mouse_move_abs &amp; left_click")

    return dot


def _png_dpi(dot: graphviz.Digraph) -> int:
    """Pick a DPI so the longest bitmap side stays under PNG_MAX_PIXELS."""
    plain = dot.pipe(format="plain").decode("utf-8", "replace").splitlines()[0].split()
    w_in, h_in = float(plain[2]), float(plain[3])
    longest = max(w_in, h_in)
    dpi = min(PNG_TARGET_DPI, int(PNG_MAX_PIXELS / longest))
    print(f"[..] Layout {w_in:.1f} x {h_in:.1f} in -> PNG dpi {dpi} "
          f"(~{int(w_in * dpi)} x {int(h_in * dpi)} px)")
    return max(dpi, 50)


def generate_all(
    output_name: str = "touch2key_full_architecture",
    out_dir: Path | None = None,
) -> dict[str, Path]:
    out_dir = out_dir or Path(__file__).resolve().parent
    out_dir.mkdir(parents=True, exist_ok=True)
    base = out_dir / output_name
    results: dict[str, Path] = {}

    # Vector formats: original spacing, no bitmap limits apply.
    dot = build_architecture_digraph()
    for fmt in ("pdf", "svg"):
        results[fmt] = Path(dot.render(filename=str(base), format=fmt, cleanup=False))
        print(f"[OK] Generated {fmt.upper()}: {results[fmt]}")

    # PNG: tighter spacing + adaptive DPI so cairo never downscales.
    png_dot = build_architecture_digraph(nodesep="0.20", ranksep="0.30")
    png_dot.graph_attr["dpi"] = str(_png_dpi(png_dot))
    results["png"] = Path(png_dot.render(filename=str(base), format="png", cleanup=False))
    print(f"[OK] Generated PNG: {results['png']}")

    # Remove the intermediate .gv source
    Path(str(base)).unlink(missing_ok=True)
    return results


import re

SPLIT_NAMES = {
    "cluster_layer1_scripts": "01_layer1_cli_bootstrap",
    "cluster_layer2_gui": "02_layer2_gui",
    "cluster_layer3_overlays": "03_layer3_overlays",
    "cluster_layer4_data": "04_layer4_storage_telemetry",
    "cluster_phase1_construction": "05_engine_phase1_construction",
    "cluster_phase2_dispatch": "06_engine_phase2_dispatch",
    "cluster_phase3_execution": "07_engine_phase3_execution",
}
SPLIT_DPI = 200
SPLIT_MAX_PIXELS = 14000
GRID_COLS = 1  # column count for clusters that have no internal edges
# Extra invisible chains to stack cards in one column (keeps each PNG narrow).
EXTRA_CHAINS = {
    "cluster_layer4_data": ["ConfigIOAndMigration", "SqliteStore", "RuntimeSnapshot"],
    "cluster_layer2_gui": [
        "DashboardPageNode", "LayoutStudioPageNode",
        "PlotterWidgetNode", "SettingsPageNode",
    ],
}


def generate_split_pngs(out_dir: Path | None = None) -> list[Path]:
    """Render every cluster as its own PNG (own layout, readable at fit-to-screen)."""
    out_dir = (out_dir or Path(__file__).resolve().parent) / "PNG"
    out_dir.mkdir(parents=True, exist_ok=True)

    full = build_architecture_digraph(nodesep="0.30", ranksep="0.40")
    body = full.body

    # Locate each cluster block [start, end] in the top-level body.
    blocks: dict[str, list[str]] = {}
    top_edges: list[str] = []
    k = 0
    while k < len(body):
        m = re.match(r"\tsubgraph (cluster_\w+) \{", body[k])
        if m:
            end = k
            while body[end] != "\t}\n":
                end += 1
            blocks[m.group(1)] = body[k : end + 1]
            k = end + 1
            continue
        if re.match(r"\t\w+ -> \w+", body[k]):
            top_edges.append(body[k])
        k += 1

    header = body[:3]  # graph / node / edge default attributes
    paths: list[Path] = []
    for cname, fname in SPLIT_NAMES.items():
        block = blocks[cname]
        nodes = [
            m.group(1)
            for line in block
            if (m := re.match(r"\t\t(\w+) \[label=", line))
        ]
        sub = graphviz.Digraph(name=cname)
        sub.body = list(header) + list(block)
        sub.attr(label="")  # drop the global title; the cluster has its own

        inner = [
            e for e in top_edges
            if (m := re.match(r"\t(\w+) -> (\w+)", e))
            and m.group(1) in nodes and m.group(2) in nodes
        ]
        sub.body += inner
        chain = EXTRA_CHAINS.get(cname, [])
        for a, b in zip(chain, chain[1:]):
            sub.edge(a, b, style="invis")
        if not inner and not any("->" in line for line in block):
            for i in range(len(nodes) - GRID_COLS):
                sub.edge(nodes[i], nodes[i + GRID_COLS], style="invis")

        plain = sub.pipe(format="plain").decode("utf-8", "replace").splitlines()[0].split()
        w_in, h_in = float(plain[2]), float(plain[3])
        dpi = max(50, min(SPLIT_DPI, int(SPLIT_MAX_PIXELS / max(w_in, h_in))))
        sub.graph_attr["dpi"] = str(dpi)

        base = out_dir / fname
        png = Path(sub.render(filename=str(base), format="png", cleanup=True))
        paths.append(png)
        print(f"[OK] {png.name}: {w_in:.1f} x {h_in:.1f} in @ {dpi} dpi "
              f"(~{int(w_in * dpi)} x {int(h_in * dpi)} px)")
    return paths


if __name__ == "__main__":
    _out = Path(sys.argv[1]) if len(sys.argv) > 1 else None
    generate_all(out_dir=_out)
    generate_split_pngs(out_dir=_out)
