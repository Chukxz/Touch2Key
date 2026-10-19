from __future__ import annotations

import logging
import sys
from pathlib import Path
from typing import TYPE_CHECKING

from PySide6.QtCore import QEvent, QObject, Qt, QCoreApplication
from PySide6.QtGui import QKeyEvent
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from modules.database import store
from modules.database.config_io import (
    export_bundle,
    export_settings_toml,
    import_any,
)
from modules.platforms import get_specific_qt_key
from modules.scripts.list_windows import select_window
from modules.utils import (
    ADB_RATE_CAP_MAX,
    ADB_RATE_CAP_MIN,
    DEADZONE_MAX,
    DEADZONE_MIN,
    EXCLUDED_KEYS,
    HYSTERESIS_MAX,
    HYSTERESIS_MIN,
    MapperEvent,
    PPS_ALERT_MAX,
    PPS_ALERT_MIN,
    PROFILES_FOLDER,
    SENSITIVITY_MAX,
    SENSITIVITY_MIN,
    TOML_PATH,
    TYPEMATIC_DELAY_MAX_MS,
    TYPEMATIC_DELAY_MIN_MS,
    TYPEMATIC_RATE_MAX_HZ,
    TYPEMATIC_RATE_MIN_HZ,
    get_scancode_from_key,
)

if TYPE_CHECKING:
    from modules.utils import MapperEventDispatcher
    from modules.gui.main_window import EngineProcessController

logger = logging.getLogger("modules.gui.settings_page")

# -------------------------------------------------------------------------
# Input Filters
# -------------------------------------------------------------------------


def verify_key(parent: QWidget | None, key_name: str) -> bool:
    if get_scancode_from_key(key_name) is None:
        QMessageBox.warning(parent, "Unsupported Key", f"'{key_name}' can't be mapped.")
        return False
    return True


class KeyCaptureFilter(QObject):
    """Intercepts the next raw keypress (single stroke) without modal dialogs."""

    def __init__(self, callback, parent=None):
        super().__init__(parent)
        self.key_callback = callback

    def eventFilter(self, obj: QObject, event: QEvent) -> bool:
        # Block focus traversal before Qt converts Tab into a navigation event
        if event.type() == QEvent.Type.ShortcutOverride and isinstance(
            event, QKeyEvent
        ):
            if event.key() in (Qt.Key.Key_Tab, Qt.Key.Key_Backtab):
                event.accept()
                return True

        # Capture the actual key stroke
        if event.type() == QEvent.Type.KeyPress:
            if isinstance(event, QKeyEvent) and event.key() == Qt.Key.Key_Escape:
                self.key_callback(None)
                return True

            precise_key = get_specific_qt_key(event)
            self.key_callback(precise_key)
            return True

        return False


class ContinuousSequenceFilter(QObject):
    """Intercepts continuous sequential KeyPress events for exclusion lists."""

    def __init__(self, key_callback, parent=None):
        super().__init__(parent)
        self.key_callback = key_callback

    def eventFilter(self, obj: QObject, event: QEvent) -> bool:
        # Block focus traversal before Qt converts Tab into a navigation event
        if event.type() == QEvent.Type.ShortcutOverride and isinstance(
            event, QKeyEvent
        ):
            if event.key() in (Qt.Key.Key_Tab, Qt.Key.Key_Backtab):
                event.accept()
                return True

        if event.type() == QEvent.Type.KeyPress and isinstance(event, QKeyEvent):
            if event.isAutoRepeat():
                return True

            precise_key = get_specific_qt_key(event)
            self.key_callback(precise_key)
            return True

        return False


# -------------------------------------------------------------------------
# Interactive Multi-Key UI Component
# -------------------------------------------------------------------------


class KeySequenceRow(QWidget):
    """Encapsulates sequence preview, record toggle, pop/clear, and DB persistence."""

    def __init__(self, target_field: str, page: SettingsPage):
        super().__init__(page)
        self.target_field = target_field
        self.page = page
        self.sequence: list[str] = []

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)

        controls = QHBoxLayout()
        controls.setContentsMargins(0, 0, 0, 0)

        self.sequence_label = QLabel("None")
        self.sequence_label.setStyleSheet(
            "font-family: monospace; font-weight: bold; color: palette(highlight);"
        )

        self.record_btn = QPushButton("Record Keys")
        self.record_btn.setCheckable(True)

        self.remove_btn = QPushButton("Remove Last")
        self.clear_btn = QPushButton("Clear")
        self.wasd_preset_btn = QPushButton("+ WASD")
        self.arrows_preset_btn = QPushButton("+ ←↑↓→")

        controls.addWidget(self.sequence_label)
        controls.addSpacing(10)
        controls.addWidget(self.record_btn)
        controls.addWidget(self.remove_btn)
        controls.addWidget(self.clear_btn)
        controls.addWidget(self.wasd_preset_btn)
        controls.addWidget(self.arrows_preset_btn)
        controls.addStretch()

        layout.addLayout(controls)

        self.status_label = QLabel("")
        self.status_label.setStyleSheet("color: #7f8c8d; font-size: 11px;")
        layout.addWidget(self.status_label)

        self.record_btn.toggled.connect(self._on_toggle_recording)
        self.remove_btn.clicked.connect(self._remove_last_key)
        self.clear_btn.clicked.connect(self._clear_sequence)
        self.wasd_preset_btn.clicked.connect(self._apply_wasd_preset)
        self.arrows_preset_btn.clicked.connect(self._apply_arrows_preset)

    def set_sequence(self, sequence: list[str]) -> None:
        self.sequence = [k.strip().lower() for k in sequence if k.strip()]
        self._update_display()

    def add_key(self, db_key):
        if db_key in self.sequence:
            return
        if get_scancode_from_key(db_key) is None:
            self.status_label.setText(f"'{db_key}' can't be mapped.")
            return
        self.sequence.append(db_key)
        self._update_display()
        self.save()

    def stop_recording(self) -> None:
        if self.record_btn.isChecked():
            self.record_btn.setChecked(False)

    def _apply_wasd_preset(self) -> None:
        for k in ["w", "a", "s", "d"]:
            if k not in self.sequence:
                self.sequence.append(k)
        self._update_display()
        self.save()

    def _apply_arrows_preset(self) -> None:
        for k in ["left", "up", "down", "right"]:
            if k not in self.sequence:
                self.sequence.append(k)
        self._update_display()
        self.save()

    def _on_toggle_recording(self, checked: bool) -> None:
        if checked:
            self.record_btn.setText("Stop Recording")
            self.status_label.setText(
                "Recording keypresses (Esc included)... Click Stop Recording when done."
            )
            self.page.begin_sequence_capture(self)
        else:
            self.record_btn.setText("Record Keys")
            self.status_label.setText("")
            self.page.end_sequence_capture(self)

    def _remove_last_key(self) -> None:
        if self.sequence:
            self.sequence.pop()
            self._update_display()
            self.save()

    def _clear_sequence(self) -> None:
        if self.sequence:
            self.sequence.clear()
            self._update_display()
            self.save()

    def _update_display(self) -> None:
        if not self.sequence:
            self.sequence_label.setText("None")
            self.remove_btn.setEnabled(False)
            self.clear_btn.setEnabled(False)
        else:
            self.sequence_label.setText(" + ".join(self.sequence))
            self.remove_btn.setEnabled(True)
            self.clear_btn.setEnabled(True)

    def save(self) -> None:
        serialized = ",".join(self.sequence)
        self.page.persist_binding(self.target_field, serialized)


# -------------------------------------------------------------------------
# Main Page View
# -------------------------------------------------------------------------


class SettingsPage(QWidget):
    """Unified Settings page covering Hardware, Keybindings, Input tuning, Typematic, and DB resets."""

    title = "Settings"

    def __init__(
        self,
        engine_controller: EngineProcessController,
        dispatcher: MapperEventDispatcher | None = None,
        parent: QWidget | None = None,
    ):
        super().__init__(parent)
        self.engine_controller = engine_controller
        self.dispatcher = dispatcher

        self._single_key_filter: KeyCaptureFilter | None = None
        self._sequence_filter: ContinuousSequenceFilter | None = None
        self._active_seq_row: KeySequenceRow | None = None

        self.w_title: str | None = None
        self.w_id: int | None = None
        self.k_id: int | None = None
        self.m_id: int | None = None

        root_layout = QVBoxLayout(self)
        root_layout.setContentsMargins(0, 0, 0, 0)

        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setFrameShape(QFrame.Shape.NoFrame)

        scroll_content = QWidget()
        scroll_layout = QVBoxLayout(scroll_content)
        scroll_layout.setContentsMargins(0, 0, 0, 0)
        scroll_layout.setSpacing(16)

        # 1. Hardware & Device Configuration
        hw_group = QGroupBox("Hardware & Device Configuration")
        hw_layout = QVBoxLayout(hw_group)

        desc = QLabel(
            "Assign target application windows and physical input hardware. "
            "Target window selection works across all platforms. Low-level Interception driver rebinding applies to Windows."
        )
        desc.setWordWrap(True)
        hw_layout.addWidget(desc)

        self.info_frame = QFrame()
        self.info_frame.setFrameShape(QFrame.Shape.StyledPanel)
        frame_layout = QVBoxLayout(self.info_frame)
        self.w_label = QLabel("Target Window: None")
        self.k_label = QLabel("Configured Keyboard: None")
        self.m_label = QLabel("Configured Mouse: None")
        frame_layout.addWidget(self.w_label)
        frame_layout.addWidget(self.k_label)
        frame_layout.addWidget(self.m_label)
        hw_layout.addWidget(self.info_frame)

        hw_btn_layout = QHBoxLayout()
        self.select_window_btn = QPushButton("Select Target Window")
        self.rebind_hw_btn = QPushButton("Detect & Rebind Hardware")
        hw_btn_layout.addWidget(self.select_window_btn)
        hw_btn_layout.addWidget(self.rebind_hw_btn)
        hw_btn_layout.addStretch()
        hw_layout.addLayout(hw_btn_layout)

        scroll_layout.addWidget(hw_group)

        # 2. Key Bindings
        kb_group = QGroupBox("Global Key Bindings")
        kb_form = QFormLayout(kb_group)

        self.toggle_key_label = QLabel("Not set")
        self.toggle_key_btn = QPushButton("Capture")
        self.toggle_key_clear_btn = QPushButton("Clear")
        kb_form.addRow(
            "Toggle Key (Menu Mode):",
            self._paired_row(
                self.toggle_key_label, self.toggle_key_btn, self.toggle_key_clear_btn
            ),
        )

        self.sprint_key_label = QLabel("Not set")
        self.sprint_key_btn = QPushButton("Capture")
        self.sprint_key_clear_btn = QPushButton("Clear")
        kb_form.addRow(
            "Sprint Key:",
            self._paired_row(
                self.sprint_key_label, self.sprint_key_btn, self.sprint_key_clear_btn
            ),
        )

        scroll_layout.addWidget(kb_group)

        # 3. Input & Controls Group
        input_group = QGroupBox("Touch & Input Controls")
        input_layout = QVBoxLayout(input_group)

        self.left_handed_check = QCheckBox("Left-handed mode")
        input_layout.addWidget(self.left_handed_check)

        self.floating_check = QCheckBox("Floating Joystick")
        self.floating_check.setToolTip("Floats dynamically; is overridden by anchored.")
        input_layout.addWidget(self.floating_check)

        self.anchored_check = QCheckBox("Anchored Joystick")
        self.anchored_check.setToolTip(
            "Locks touches near center to anchor, floats dynamically elsewhere. Overrides floating."
        )
        input_layout.addWidget(self.anchored_check)

        input_form = QFormLayout()
        self.sensitivity_spin_x = QDoubleSpinBox()
        self.sensitivity_spin_x.setRange(SENSITIVITY_MIN, SENSITIVITY_MAX)
        self.sensitivity_spin_x.setSingleStep(0.1)
        input_form.addRow("Sensitivity X:", self.sensitivity_spin_x)

        self.sensitivity_spin_y = QDoubleSpinBox()
        self.sensitivity_spin_y.setRange(SENSITIVITY_MIN, SENSITIVITY_MAX)
        self.sensitivity_spin_y.setSingleStep(0.1)
        input_form.addRow("Sensitivity Y:", self.sensitivity_spin_y)

        self.deadzone_spin = QDoubleSpinBox()
        self.deadzone_spin.setRange(DEADZONE_MIN, DEADZONE_MAX)
        self.deadzone_spin.setSingleStep(0.01)
        input_form.addRow("Deadzone:", self.deadzone_spin)

        self.hysteresis_spin = QDoubleSpinBox()
        self.hysteresis_spin.setRange(HYSTERESIS_MIN, HYSTERESIS_MAX)
        self.hysteresis_spin.setSingleStep(1.0)
        self.hysteresis_spin.setSuffix("°")
        input_form.addRow("Hysteresis:", self.hysteresis_spin)
        input_layout.addLayout(input_form)

        input_reset_row = QHBoxLayout()
        self.reset_input_btn = QPushButton("Reset Input Controls to Defaults")
        input_reset_row.addWidget(self.reset_input_btn)
        input_reset_row.addStretch()
        input_layout.addLayout(input_reset_row)

        scroll_layout.addWidget(input_group)

        # 4. Performance & Engine Group
        perf_group = QGroupBox("Performance & Pipeline")
        perf_form = QFormLayout(perf_group)

        self.rate_cap_spin = QDoubleSpinBox()
        self.rate_cap_spin.setRange(ADB_RATE_CAP_MIN, ADB_RATE_CAP_MAX)
        self.rate_cap_spin.setSingleStep(10.0)
        self.rate_cap_spin.setSuffix(" Hz")
        perf_form.addRow("ADB Rate Cap:", self.rate_cap_spin)

        self.pps_alert_spin = QDoubleSpinBox()
        self.pps_alert_spin.setRange(PPS_ALERT_MIN, PPS_ALERT_MAX)
        self.pps_alert_spin.setSingleStep(5.0)
        self.pps_alert_spin.setSuffix(" PPS")
        perf_form.addRow("PPS Alert Threshold:", self.pps_alert_spin)

        scroll_layout.addWidget(perf_group)

        # 5. Typematic & Exclusions Group
        typematic_group = QGroupBox("Typematic (Auto-Repeat)")
        typematic_form = QFormLayout(typematic_group)
        typematic_form.setFieldGrowthPolicy(
            QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow
        )

        self.typematic_enabled_check = QCheckBox(
            "Enable Hardware/Virtual Typematic Repeat"
        )
        typematic_form.addRow(self.typematic_enabled_check)

        self.typematic_delay_spin = QDoubleSpinBox()
        self.typematic_delay_spin.setRange(
            TYPEMATIC_DELAY_MIN_MS, TYPEMATIC_DELAY_MAX_MS
        )
        self.typematic_delay_spin.setSingleStep(10.0)
        self.typematic_delay_spin.setSuffix(" ms")
        typematic_form.addRow("Typematic Delay:", self.typematic_delay_spin)

        self.typematic_rate_spin = QDoubleSpinBox()
        self.typematic_rate_spin.setRange(TYPEMATIC_RATE_MIN_HZ, TYPEMATIC_RATE_MAX_HZ)
        self.typematic_rate_spin.setSingleStep(1.0)
        self.typematic_rate_spin.setSuffix(" Hz")
        typematic_form.addRow("Typematic Rate:", self.typematic_rate_spin)

        self.typematic_excluded_keys = KeySequenceRow("typematic_excluded_keys", self)
        typematic_excluded_keys_scroll_area = QScrollArea()
        typematic_excluded_keys_scroll_area.setWidget(self.typematic_excluded_keys)
        typematic_excluded_keys_scroll_area.setWidgetResizable(True)
        typematic_form.addRow("Excluded Keys:", typematic_excluded_keys_scroll_area)

        typematic_reset_row = QHBoxLayout()
        self.reset_typematic_btn = QPushButton("Reset Typematic to Defaults")
        typematic_reset_row.addWidget(self.reset_typematic_btn)
        typematic_reset_row.addStretch()
        typematic_form.addRow("", typematic_reset_row)

        scroll_layout.addWidget(typematic_group)

        # 6. System Group
        system_group = QGroupBox("System")
        system_form = QFormLayout(system_group)

        self.two_finger_tap_enabled_check = QCheckBox()
        system_form.addRow(
            "Enable Two-Finger-Tap Gesture:", self.two_finger_tap_enabled_check
        )

        self.bezel_toggle_enabled_check = QCheckBox()
        system_form.addRow("Enable Bezel Toggles:", self.bezel_toggle_enabled_check)

        system_reset_row = QHBoxLayout()
        self.reset_system_btn = QPushButton("Reset System Toggles to Defaults")
        system_reset_row.addWidget(self.reset_system_btn)
        system_reset_row.addStretch()
        system_form.addRow("", system_reset_row)

        scroll_layout.addWidget(system_group)

        # 7. Import / Export / Backup
        io_row = QHBoxLayout()
        self.export_toml_btn = QPushButton("Export settings.toml")
        self.import_toml_btn = QPushButton("Import Config (.toml / .json / Bundle)")
        self.export_bundle_btn = QPushButton("Export Full Bundle")

        io_row.addWidget(self.export_toml_btn)
        io_row.addWidget(self.import_toml_btn)
        io_row.addWidget(self.export_bundle_btn)
        scroll_layout.addLayout(io_row)

        # 8. Database Reset Actions
        reset_row = QHBoxLayout()
        self.reset_defaults_btn = QPushButton("Reset Settings to Defaults")
        self.delete_all_btn = QPushButton("Wipe Database (Factory Reset)")
        self.delete_all_btn.setStyleSheet("color: #d9534f;")

        reset_row.addWidget(self.reset_defaults_btn)
        reset_row.addWidget(self.delete_all_btn)
        scroll_layout.addLayout(reset_row)

        scroll_layout.addStretch()
        scroll_area.setWidget(scroll_content)
        root_layout.addWidget(scroll_area)

        self._wire_signals()
        self._refresh_hw_ui()
        self.load_settings()

    def _app(self) -> QCoreApplication:
        app = QApplication.instance()
        assert app is not None  # a widget can't exist without one
        return app

    def on_page_shown(self) -> None:
        self.refresh_state()
        self._refresh_hw_ui()
        self.load_settings()

    def refresh_state(self) -> None:
        with self.engine_controller.lock:
            self.w_title = self.engine_controller.window_title
            self.w_id = self.engine_controller.window_id
            self.k_id = self.engine_controller.k_id
            self.m_id = self.engine_controller.m_id

    def _notify_reload(self) -> None:
        if self.dispatcher:
            self.dispatcher.dispatch(MapperEvent(action="ON_CONFIG_RELOAD"))

    def _wire_signals(self) -> None:
        self.select_window_btn.clicked.connect(self._handle_window_selection)
        self.rebind_hw_btn.clicked.connect(self._handle_hardware_rebind)

        self.toggle_key_btn.clicked.connect(
            lambda: self._begin_single_key_capture("toggle_key")
        )
        self.toggle_key_clear_btn.clicked.connect(
            lambda: self._on_clear_key("toggle_key")
        )
        self.sprint_key_btn.clicked.connect(
            lambda: self._begin_single_key_capture("sprint_key")
        )
        self.sprint_key_clear_btn.clicked.connect(
            lambda: self._on_clear_key("sprint_key")
        )

        self.left_handed_check.toggled.connect(self._on_left_handed_changed)
        self.floating_check.toggled.connect(self._on_floating_joystick_changed)
        self.anchored_check.toggled.connect(self._on_anchored_joystick_changed)
        self.sensitivity_spin_x.valueChanged.connect(self._on_sensitivity_x_changed)
        self.sensitivity_spin_y.valueChanged.connect(self._on_sensitivity_y_changed)
        self.deadzone_spin.valueChanged.connect(self._on_deadzone_changed)
        self.hysteresis_spin.valueChanged.connect(self._on_hysteresis_changed)
        self.reset_input_btn.clicked.connect(self._on_reset_input_defaults)

        self.rate_cap_spin.valueChanged.connect(self._on_rate_cap_changed)
        self.pps_alert_spin.valueChanged.connect(self._on_pps_alert_changed)

        self.typematic_enabled_check.toggled.connect(self._on_typematic_enabled_changed)
        self.typematic_delay_spin.valueChanged.connect(self._on_typematic_delay_changed)
        self.typematic_rate_spin.valueChanged.connect(self._on_typematic_rate_changed)
        self.reset_typematic_btn.clicked.connect(self._on_reset_typematic_defaults)

        self.two_finger_tap_enabled_check.toggled.connect(
            self._on_two_finger_tap_enabled_changed
        )
        self.bezel_toggle_enabled_check.toggled.connect(
            self._on_bezel_toggle_enabled_changed
        )
        self.reset_system_btn.clicked.connect(self._on_reset_system_defaults)

        self.export_toml_btn.clicked.connect(self._on_export_toml)
        self.import_toml_btn.clicked.connect(self._on_import_toml)
        self.export_bundle_btn.clicked.connect(self._on_export_bundle)
        self.reset_defaults_btn.clicked.connect(self._on_reset_defaults)
        self.delete_all_btn.clicked.connect(self._on_delete_all)

    def _refresh_hw_ui(self) -> None:
        w_id = self.w_id if self.w_id is not None else "Unassigned"
        w_title = self.w_title if self.w_title is not None else ""

        self.w_label.setText(f"Target Window ID:       {w_id} ({w_title})")
        self.select_window_btn.setEnabled(True)

        if sys.platform == "win32":
            k_id = self.k_id if self.k_id is not None else "Unassigned"
            m_id = self.m_id if self.m_id is not None else "Unassigned"

            self.k_label.setText(f"Configured Keyboard ID: {k_id}")
            self.m_label.setText(f"Configured Mouse ID:    {m_id}")
            self.rebind_hw_btn.setEnabled(True)
        else:
            self.k_label.setText(
                "Keyboard Subsystem:     Virtual UInput / Evdev (Kernel-managed)"
            )
            self.m_label.setText(
                "Mouse Subsystem:        Evdev Pointer (Kernel-managed)"
            )
            self.rebind_hw_btn.setEnabled(False)
            self.rebind_hw_btn.setToolTip(
                "Interception device filtering is only applicable on Windows."
            )

    def _handle_window_selection(self) -> None:
        window_result = select_window()
        if not window_result:
            return

        self.w_id, self.w_title = window_result
        with self.engine_controller.lock:
            self.engine_controller.window_id = self.w_id
            self.engine_controller.window_title = self.w_title
        self._refresh_hw_ui()

        if self.dispatcher:
            self.dispatcher.dispatch(
                MapperEvent(
                    action="ON_TARGET_WINDOW_CHANGE",
                    target_window_id=self.w_id,
                    target_window_title=self.w_title,
                )
            )
        QMessageBox.information(
            self,
            "Target Window Updated",
            f"Active target window set:\nID: {self.w_id}\nTitle: {self.w_title}",
        )

    def _handle_hardware_rebind(self) -> None:
        if sys.platform != "win32":
            return
        from modules.platforms.windows.query_interception_device import (
            select_keyboard_then_mouse,
        )

        devices = select_keyboard_then_mouse(parent=self)
        if not devices:
            return

        self.k_id, self.m_id = devices
        with self.engine_controller.lock:
            self.engine_controller.k_id = self.k_id
            self.engine_controller.m_id = self.m_id
        self._refresh_hw_ui()

        if self.dispatcher:
            self.dispatcher.dispatch(
                MapperEvent(
                    action="ON_DEVICES_CHANGE",
                    keyboard_device_id=self.k_id,
                    mouse_device_id=self.m_id,
                )
            )
        QMessageBox.information(
            self,
            "Devices Updated",
            f"Hardware reloaded:\nKeyboard ID: {self.k_id}\nMouse ID: {self.m_id}",
        )

    @staticmethod
    def _paired_row(label: QLabel, *buttons: QPushButton) -> QWidget:
        wrapper = QWidget()
        row = QHBoxLayout(wrapper)
        row.setContentsMargins(0, 0, 0, 0)
        row.addWidget(label)
        for button in buttons:
            row.addWidget(button)
        row.addStretch()
        return wrapper

    def _cancel_captures(self) -> None:
        if self._single_key_filter is not None:
            self._app().removeEventFilter(self._single_key_filter)
            self._single_key_filter.deleteLater()
            self._single_key_filter = None

        self.toggle_key_btn.setEnabled(True)
        self.sprint_key_btn.setEnabled(True)
        if self._active_seq_row is not None:
            self._active_seq_row.stop_recording()

    def hideEvent(self, event) -> None:
        self._cancel_captures()
        self.load_settings()
        super().hideEvent(event)

    def _begin_single_key_capture(self, target_field: str) -> None:
        self._cancel_captures()
        self.load_settings()

        btn = (
            self.toggle_key_btn if target_field == "toggle_key" else self.sprint_key_btn
        )
        lbl = (
            self.toggle_key_label
            if target_field == "toggle_key"
            else self.sprint_key_label
        )

        lbl.setText("Press any key (Esc to cancel)...")
        btn.setEnabled(False)

        def on_captured(key_name: str | None):
            if self._single_key_filter is not None:
                self._app().removeEventFilter(self._single_key_filter)
                self._single_key_filter.deleteLater()
                self._single_key_filter = None

            btn.setEnabled(True)

            if key_name and verify_key(self, key_name):
                self.persist_binding(target_field, key_name)
            self.load_settings()

        self._single_key_filter = KeyCaptureFilter(on_captured, self)
        self._app().installEventFilter(self._single_key_filter)
        self.setFocus()

    def _on_clear_key(self, target_field: str) -> None:
        self._cancel_captures()
        self.persist_binding(target_field, None)
        self.load_settings()

    def begin_sequence_capture(self, row: KeySequenceRow) -> None:
        if self._active_seq_row is not None and self._active_seq_row is not row:
            self._active_seq_row.stop_recording()

        self._active_seq_row = row
        if self._sequence_filter is not None:
            self._app().removeEventFilter(self._sequence_filter)

        self._sequence_filter = ContinuousSequenceFilter(
            key_callback=self._on_seq_key_captured, parent=self
        )
        self._app().installEventFilter(self._sequence_filter)
        self.setFocus()

    def end_sequence_capture(self, row: KeySequenceRow) -> None:
        if self._sequence_filter is not None:
            self._app().removeEventFilter(self._sequence_filter)
            self._sequence_filter.deleteLater()
            self._sequence_filter = None

        if self._active_seq_row is row:
            self._active_seq_row = None

    def _on_seq_key_captured(self, db_key: str) -> None:
        if self._active_seq_row is not None:
            self._active_seq_row.add_key(db_key)

    def persist_binding(self, target_field: str, serialized_val: str | None) -> None:
        try:
            store.settings.update(**{target_field: serialized_val})
            self._notify_reload()
            logger.debug("Updated binding for %s", target_field)
        except Exception as exc:
            logger.exception("Failed to update binding for %s", target_field)
            QMessageBox.critical(self, "Error", f"Could not save key binding:\n{exc}")

    def load_settings(self) -> None:
        try:
            settings = store.settings.get()

            self.toggle_key_label.setText(settings.toggle_key or "Not set")
            self.sprint_key_label.setText(settings.sprint_key or "Not set")
            self.toggle_key_clear_btn.setEnabled(bool(settings.toggle_key))
            self.sprint_key_clear_btn.setEnabled(bool(settings.sprint_key))

            def parse_seq(val: str | None) -> list[str]:
                if not val or not val.strip():
                    return []
                return [k.strip().lower() for k in val.split(",") if k.strip()]

            self.left_handed_check.blockSignals(True)
            self.floating_check.blockSignals(True)
            self.anchored_check.blockSignals(True)
            self.sensitivity_spin_x.blockSignals(True)
            self.sensitivity_spin_y.blockSignals(True)
            self.deadzone_spin.blockSignals(True)
            self.hysteresis_spin.blockSignals(True)
            self.rate_cap_spin.blockSignals(True)
            self.pps_alert_spin.blockSignals(True)
            self.typematic_enabled_check.blockSignals(True)
            self.typematic_delay_spin.blockSignals(True)
            self.typematic_rate_spin.blockSignals(True)
            self.two_finger_tap_enabled_check.blockSignals(True)
            self.bezel_toggle_enabled_check.blockSignals(True)

            self.left_handed_check.setChecked(settings.left_handed)
            self.floating_check.setChecked(settings.floating_joystick)
            self.anchored_check.setChecked(settings.anchored_joystick)
            self.sensitivity_spin_x.setValue(settings.sensitivity_x)
            self.sensitivity_spin_y.setValue(settings.sensitivity_y)
            self.deadzone_spin.setValue(settings.deadzone)
            self.hysteresis_spin.setValue(settings.hysteresis)
            self.rate_cap_spin.setValue(settings.adb_rate_cap)
            self.pps_alert_spin.setValue(settings.pps_alert_threshold)
            self.typematic_enabled_check.setChecked(settings.typematic_enabled)
            self.typematic_delay_spin.setValue(settings.typematic_delay_ms)
            self.typematic_rate_spin.setValue(settings.typematic_rate_hz)
            self.two_finger_tap_enabled_check.setChecked(
                settings.two_finger_tap_enabled
            )
            self.bezel_toggle_enabled_check.setChecked(settings.bezel_toggle_enabled)

            self.typematic_excluded_keys.set_sequence(
                parse_seq(settings.typematic_excluded_keys)
            )

            self.left_handed_check.blockSignals(False)
            self.floating_check.blockSignals(False)
            self.anchored_check.blockSignals(False)
            self.sensitivity_spin_x.blockSignals(False)
            self.sensitivity_spin_y.blockSignals(False)
            self.deadzone_spin.blockSignals(False)
            self.hysteresis_spin.blockSignals(False)
            self.rate_cap_spin.blockSignals(False)
            self.pps_alert_spin.blockSignals(False)
            self.typematic_enabled_check.blockSignals(False)
            self.typematic_delay_spin.blockSignals(False)
            self.typematic_rate_spin.blockSignals(False)
            self.two_finger_tap_enabled_check.blockSignals(False)
            self.bezel_toggle_enabled_check.blockSignals(False)

            on = settings.typematic_enabled
            self.typematic_delay_spin.setEnabled(on)
            self.typematic_rate_spin.setEnabled(on)

        except Exception:
            logger.exception("Failed to load settings from database")

    def _on_left_handed_changed(self, checked: bool) -> None:
        try:
            store.settings.update(left_handed=checked)
            self._notify_reload()
        except Exception:
            logger.exception("Failed to update left_handed setting")

    def _on_floating_joystick_changed(self, checked: bool) -> None:
        try:
            store.settings.update(floating_joystick=checked)
            self._notify_reload()
        except Exception:
            logger.exception("Failed to update floating_joystick setting")

    def _on_anchored_joystick_changed(self, checked: bool) -> None:
        try:
            store.settings.update(anchored_joystick=checked)
            self._notify_reload()
        except Exception:
            logger.exception("Failed to update anchored_joystick setting")

    def _on_sensitivity_x_changed(self, value: float) -> None:
        try:
            store.settings.update(sensitivity_x=value)
            self._notify_reload()
        except Exception:
            logger.exception("Failed to update X sensitivity setting")

    def _on_sensitivity_y_changed(self, value: float) -> None:
        try:
            store.settings.update(sensitivity_y=value)
            self._notify_reload()
        except Exception:
            logger.exception("Failed to update Y sensitivity setting")

    def _on_deadzone_changed(self, value: float) -> None:
        try:
            store.settings.update(deadzone=value)
            self._notify_reload()
        except Exception:
            logger.exception("Failed to update deadzone setting")

    def _on_hysteresis_changed(self, value: float) -> None:
        try:
            store.settings.update(hysteresis=value)
            self._notify_reload()
        except Exception:
            logger.exception("Failed to update hysteresis setting")

    def _on_reset_input_defaults(self) -> None:
        try:
            store.settings.update(
                left_handed=False,
                floating_joystick=False,
                anchored_joystick=False,
                sensitivity_x=1.0,
                sensitivity_y=1.0,
                deadzone=0.1,
                hysteresis=5.0,
            )
            self.load_settings()
            self._notify_reload()
            logger.info("Input controls reset to factory defaults")
        except Exception as exc:
            logger.exception("Failed to reset input controls")
            QMessageBox.critical(
                self, "Error", f"Failed to reset input controls:\n{exc}"
            )

    def _on_rate_cap_changed(self, value: float) -> None:
        try:
            store.settings.update(adb_rate_cap=value)
            self._notify_reload()
        except Exception:
            logger.exception("Failed to update adb_rate_cap setting")

    def _on_pps_alert_changed(self, value: float) -> None:
        try:
            store.settings.update(pps_alert_threshold=value)
            self._notify_reload()
        except Exception:
            logger.exception("Failed to update pps_alert_threshold setting")

    def _on_typematic_enabled_changed(self, checked: bool) -> None:
        self.typematic_delay_spin.setEnabled(checked)
        self.typematic_rate_spin.setEnabled(checked)
        try:
            store.settings.update(typematic_enabled=checked)
            self._notify_reload()
        except Exception:
            logger.exception("Failed to update typematic enabled setting")

    def _on_typematic_delay_changed(self, value: float) -> None:
        try:
            store.settings.update(typematic_delay_ms=value)
            self._notify_reload()
        except Exception:
            logger.exception("Failed to update typematic_delay setting")

    def _on_typematic_rate_changed(self, value: float) -> None:
        try:
            store.settings.update(typematic_rate_hz=value)
            self._notify_reload()
        except Exception:
            logger.exception("Failed to update typematic_rate setting")

    def _on_reset_typematic_defaults(self) -> None:
        try:
            store.settings.update(
                typematic_enabled=True,
                typematic_delay_ms=250.0,
                typematic_rate_hz=30.0,
                typematic_excluded_keys=EXCLUDED_KEYS,
            )
            self.load_settings()
            self._notify_reload()
            logger.info("Typematic settings reset to factory defaults")
        except Exception as exc:
            logger.exception("Failed to reset typematic settings")
            QMessageBox.critical(
                self, "Error", f"Failed to reset typematic settings:\n{exc}"
            )

    def _on_two_finger_tap_enabled_changed(self, checked: bool) -> None:
        try:
            store.settings.update(two_finger_tap_enabled=checked)
            self._notify_reload()
        except Exception:
            logger.exception("Failed to update two_finger_tap enabled setting")

    def _on_bezel_toggle_enabled_changed(self, checked: bool) -> None:
        try:
            store.settings.update(bezel_toggle_enabled=checked)
            self._notify_reload()
        except Exception:
            logger.exception("Failed to update bezel_toggle enabled setting")

    def _on_reset_system_defaults(self) -> None:
        try:
            store.settings.update(
                two_finger_tap_enabled=True,
                bezel_toggle_enabled=True,
            )
            self.load_settings()
            self._notify_reload()
            logger.info("System toggle settings reset to factory defaults")
        except Exception as exc:
            logger.exception("Failed to reset system settings")
            QMessageBox.critical(
                self, "Error", f"Failed to reset system settings:\n{exc}"
            )

    def _on_export_toml(self) -> None:
        path_str, _ = QFileDialog.getSaveFileName(
            self,
            "Export Settings",
            str(TOML_PATH),
            "TOML files (*.toml);;All files (*.*)",
        )
        if not path_str:
            return
        try:
            out_path = export_settings_toml(Path(path_str))
            logger.info("Exported settings TOML to '%s'", out_path)
            QMessageBox.information(
                self,
                "Exported",
                f"Settings exported successfully to:\n{out_path.name}",
            )
        except Exception as exc:
            logger.exception("Failed to export settings TOML")
            QMessageBox.critical(self, "Export Error", str(exc))

    def _on_import_toml(self) -> None:
        PROFILES_FOLDER.mkdir(parents=True, exist_ok=True)
        path_str, _ = QFileDialog.getOpenFileName(
            self,
            "Import Settings, Layout or Bundle",
            str(PROFILES_FOLDER),
            "Supported Files (*.toml *.json);;TOML files (*.toml);;JSON files (*.json);;All files (*.*)",
        )
        if not path_str:
            return
        try:
            if import_any(Path(path_str)):
                self.load_settings()
                self._notify_reload()
                if self.dispatcher:
                    self.dispatcher.dispatch(MapperEvent(action="ON_LAYOUT_RELOAD"))
                logger.info("Imported configuration from '%s'", path_str)
                QMessageBox.information(
                    self,
                    "Imported",
                    "Configuration imported and synced to database.",
                )
            else:
                logger.warning("Could not parse or apply settings from '%s'", path_str)
                QMessageBox.warning(
                    self,
                    "Import Failed",
                    "Could not parse or apply settings from file.",
                )
        except Exception as exc:
            logger.exception("Unexpected error importing '%s'", path_str)
            QMessageBox.critical(self, "Import Error", f"Failed to import file:\n{exc}")

    def _on_export_bundle(self) -> None:
        PROFILES_FOLDER.mkdir(parents=True, exist_ok=True)
        folder = QFileDialog.getExistingDirectory(
            self, "Select Target Folder for Bundle", str(PROFILES_FOLDER)
        )
        if not folder:
            return
        try:
            t_file, j_file = export_bundle(Path(folder))
            logger.info(
                "Exported configuration bundle: '%s', '%s'",
                t_file.name,
                j_file.name,
            )
            QMessageBox.information(
                self,
                "Bundle Exported",
                f"Exported configuration bundle:\n- {t_file.name}\n- {j_file.name}",
            )
        except Exception as exc:
            logger.exception("Bundle export failed")
            QMessageBox.critical(self, "Bundle Export Failed", str(exc))

    def _on_reset_defaults(self) -> None:
        reply = QMessageBox.question(
            self,
            "Reset Settings",
            "Reset all tuning knobs and configurations to defaults?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply == QMessageBox.StandardButton.Yes:
            try:
                store.settings.reset_to_defaults()
                self.load_settings()
                self._notify_reload()
                logger.info("Application settings reset to defaults")
                QMessageBox.information(self, "Reset", "Settings reset to defaults.")
            except Exception as exc:
                logger.exception("Failed to reset settings to defaults")
                QMessageBox.critical(self, "Error", f"Failed to reset settings:\n{exc}")

    def _on_delete_all(self) -> None:
        reply = QMessageBox.warning(
            self,
            "Wipe Database",
            "Are you sure you want to delete ALL layouts and reset all settings?\nThis cannot be undone.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply == QMessageBox.StandardButton.Yes:
            try:
                store.settings.wipe_database()

                self.load_settings()
                self._notify_reload()
                if self.dispatcher:
                    self.dispatcher.dispatch(MapperEvent(action="ON_LAYOUT_RELOAD"))

                logger.info("Database wiped and reset to factory defaults")
                QMessageBox.information(
                    self, "Wiped", "All layouts and settings cleared."
                )
            except Exception as exc:
                logger.exception("Failed to wipe database")
                QMessageBox.critical(self, "Error", f"Failed to wipe database:\n{exc}")