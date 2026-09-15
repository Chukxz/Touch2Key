from __future__ import annotations

from typing import TYPE_CHECKING
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from modules.database import store
from modules.utils import MapperEvent
from .base_page import BasePage

if TYPE_CHECKING:
    from modules.utils import MapperEventDispatcher


class PipelinesPage(BasePage):
    """Configuration GUI for 5-stage touch mapping pipelines backed by SQLite zones."""

    title = "Pipelines"

    def __init__(
        self,
        dispatcher: MapperEventDispatcher | None = None,
        parent: QWidget | None = None,
    ):
        super().__init__(dispatcher, parent)

        body_layout = QHBoxLayout()

        # Left Column: Pipeline List & Presets
        left_panel = QVBoxLayout()

        preset_row = QHBoxLayout()
        self.preset_combo = QComboBox()
        self.preset_combo.addItems(
            [
                "Custom",
                "Button (Tap/Hold)",
                "Toggle Key",
                "Fixed Joystick (HUD)",
                "Floating Joystick",
                "Anchored Floating Joystick",
                "Relative Pointer (Look)",
                "Track Fire (Look + Shoot)",
                "Bezel Return Toggle",
                "Double-Tap Toggle",
            ]
        )
        self.add_preset_btn = QPushButton("Add Preset")
        preset_row.addWidget(self.preset_combo)
        preset_row.addWidget(self.add_preset_btn)
        left_panel.addLayout(preset_row)

        self.pipeline_list = QListWidget()
        left_panel.addWidget(self.pipeline_list)

        list_btn_row = QHBoxLayout()
        self.new_btn = QPushButton("New")
        self.duplicate_btn = QPushButton("Duplicate")
        self.delete_btn = QPushButton("Delete")
        list_btn_row.addWidget(self.new_btn)
        list_btn_row.addWidget(self.duplicate_btn)
        list_btn_row.addWidget(self.delete_btn)
        left_panel.addLayout(list_btn_row)

        body_layout.addLayout(left_panel, stretch=1)

        # Right Column: 5-Stage Pipeline Inspector
        inspector = QVBoxLayout()

        meta_form = QFormLayout()
        self.name_edit = QLineEdit()
        self.priority_spin = QDoubleSpinBox()
        self.priority_spin.setRange(-100, 200)
        self.priority_spin.setDecimals(0)
        self.priority_spin.setValue(0)
        meta_form.addRow("Pipeline Name:", self.name_edit)
        meta_form.addRow("Priority Tier:", self.priority_spin)
        inspector.addLayout(meta_form)

        # Stage 1: Region
        region_box = QGroupBox("1. Region (Activation)")
        region_layout = QVBoxLayout(region_box)
        self.region_type_combo = QComboBox()
        self.region_type_combo.addItems(["Always", "Circular", "Rectangular", "Top Bezel Notch"])
        region_layout.addWidget(self.region_type_combo)

        self.region_stack = QStackedWidget()

        self.region_always_page = QWidget()
        self.region_stack.addWidget(self.region_always_page)

        self.region_circle_page = QWidget()
        circle_form = QFormLayout(self.region_circle_page)
        circle_form.setContentsMargins(0, 0, 0, 0)
        self.reg_center_x = QDoubleSpinBox()
        self.reg_center_x.setRange(0, 10000)
        self.reg_center_y = QDoubleSpinBox()
        self.reg_center_y.setRange(0, 10000)
        self.reg_radius = QDoubleSpinBox()
        self.reg_radius.setRange(1, 2000)
        self.reg_radius.setValue(100)
        circle_form.addRow("Center (X, Y):", self._pair_spins(self.reg_center_x, self.reg_center_y))
        circle_form.addRow("Radius (px):", self.reg_radius)
        self.region_stack.addWidget(self.region_circle_page)

        self.region_rect_page = QWidget()
        rect_form = QFormLayout(self.region_rect_page)
        rect_form.setContentsMargins(0, 0, 0, 0)
        self.reg_x1 = QDoubleSpinBox()
        self.reg_x1.setRange(0, 10000)
        self.reg_y1 = QDoubleSpinBox()
        self.reg_y1.setRange(0, 10000)
        self.reg_x2 = QDoubleSpinBox()
        self.reg_x2.setRange(0, 10000)
        self.reg_y2 = QDoubleSpinBox()
        self.reg_y2.setRange(0, 10000)
        rect_form.addRow("Top-Left (X1, Y1):", self._pair_spins(self.reg_x1, self.reg_y1))
        rect_form.addRow("Bottom-Right (X2, Y2):", self._pair_spins(self.reg_x2, self.reg_y2))
        self.region_stack.addWidget(self.region_rect_page)

        self.region_bezel_page = QWidget()
        bezel_form = QFormLayout(self.region_bezel_page)
        bezel_form.setContentsMargins(0, 0, 0, 0)
        self.reg_bezel_height = QDoubleSpinBox()
        self.reg_bezel_height.setRange(2, 100)
        self.reg_bezel_height.setValue(14)
        self.reg_bezel_height.setSuffix(" px")
        bezel_form.addRow("Bezel Height:", self.reg_bezel_height)
        self.region_stack.addWidget(self.region_bezel_page)

        region_layout.addWidget(self.region_stack)
        inspector.addWidget(region_box)

        # Stage 2: Origin
        origin_box = QGroupBox("2. Origin (Center Point)")
        origin_layout = QFormLayout(origin_box)
        self.origin_type_combo = QComboBox()
        self.origin_type_combo.addItems(
            [
                "Dynamic (Touch Point)",
                "Fixed (HUD Coordinate)",
                "Anchored-Dynamic (Snap to HUD)",
            ]
        )
        origin_layout.addRow("Origin Type:", self.origin_type_combo)

        self.orig_x = QDoubleSpinBox()
        self.orig_x.setRange(0, 10000)
        self.orig_y = QDoubleSpinBox()
        self.orig_y.setRange(0, 10000)
        self.orig_pos_widget = self._pair_spins(self.orig_x, self.orig_y)
        self.orig_pos_widget.setEnabled(False)
        origin_layout.addRow("Anchor Point:", self.orig_pos_widget)

        self.orig_snap_radius = QDoubleSpinBox()
        self.orig_snap_radius.setRange(5, 1000)
        self.orig_snap_radius.setValue(80)
        self.orig_snap_radius.setSuffix(" px")
        self.orig_snap_radius.setEnabled(False)
        origin_layout.addRow("Snap Radius:", self.orig_snap_radius)

        inspector.addWidget(origin_box)

        # Stage 3: Constraint
        constraint_box = QGroupBox("3. Constraint")
        constraint_layout = QVBoxLayout(constraint_box)
        self.constraint_type_combo = QComboBox()
        self.constraint_type_combo.addItems(
            ["None", "Radial (Clamped)", "Rectangular", "Leash (Origin Follow)"]
        )
        constraint_layout.addWidget(self.constraint_type_combo)

        self.constraint_stack = QStackedWidget()

        self.constraint_none_page = QWidget()
        self.constraint_stack.addWidget(self.constraint_none_page)

        self.constraint_radial_page = QWidget()
        rad_form = QFormLayout(self.constraint_radial_page)
        rad_form.setContentsMargins(0, 0, 0, 0)
        self.const_radius_spin = QDoubleSpinBox()
        self.const_radius_spin.setRange(1, 2000)
        self.const_radius_spin.setValue(100)
        rad_form.addRow("Clamp Radius:", self.const_radius_spin)
        self.constraint_stack.addWidget(self.constraint_radial_page)

        self.constraint_rect_page = QWidget()
        rect_const_form = QFormLayout(self.constraint_rect_page)
        rect_const_form.setContentsMargins(0, 0, 0, 0)
        self.const_half_w = QDoubleSpinBox()
        self.const_half_w.setRange(1, 5000)
        self.const_half_h = QDoubleSpinBox()
        self.const_half_h.setRange(1, 5000)
        rect_const_form.addRow(
            "Half Dimensions (W/2, H/2):",
            self._pair_spins(self.const_half_w, self.const_half_h),
        )
        self.constraint_stack.addWidget(self.constraint_rect_page)

        self.constraint_leash_page = QWidget()
        leash_form = QFormLayout(self.constraint_leash_page)
        leash_form.setContentsMargins(0, 0, 0, 0)
        self.const_leash_spin = QDoubleSpinBox()
        self.const_leash_spin.setRange(1, 2000)
        self.const_leash_spin.setValue(150)
        leash_form.addRow("Leash Radius:", self.const_leash_spin)
        self.constraint_stack.addWidget(self.constraint_leash_page)

        constraint_layout.addWidget(self.constraint_stack)
        inspector.addWidget(constraint_box)

        # Stage 4: Transformation
        transform_box = QGroupBox("4. Transformation")
        transform_layout = QVBoxLayout(transform_box)
        self.transform_type_combo = QComboBox()
        self.transform_type_combo.addItems(
            [
                "Identity",
                "Delta (Mouse Movement)",
                "Directional (Threshold)",
                "8-Sector Joystick (WASD)",
                "Double-Tap (Temporal)",
            ]
        )
        transform_layout.addWidget(self.transform_type_combo)

        self.transform_stack = QStackedWidget()

        self.trans_identity_page = QWidget()
        self.transform_stack.addWidget(self.trans_identity_page)

        self.trans_delta_page = QWidget()
        delta_form = QFormLayout(self.trans_delta_page)
        delta_form.setContentsMargins(0, 0, 0, 0)
        self.trans_sens_x = QDoubleSpinBox()
        self.trans_sens_x.setRange(0.01, 10.0)
        self.trans_sens_x.setValue(1.0)
        self.trans_sens_y = QDoubleSpinBox()
        self.trans_sens_y.setRange(0.01, 10.0)
        self.trans_sens_y.setValue(1.0)
        delta_form.addRow(
            "Sensitivity (X, Y):",
            self._pair_spins(self.trans_sens_x, self.trans_sens_y),
        )
        self.transform_stack.addWidget(self.trans_delta_page)

        self.trans_dir_page = QWidget()
        dir_form = QFormLayout(self.trans_dir_page)
        dir_form.setContentsMargins(0, 0, 0, 0)
        self.trans_dir_deadzone = QDoubleSpinBox()
        self.trans_dir_deadzone.setRange(0, 500)
        self.trans_dir_threshold = QDoubleSpinBox()
        self.trans_dir_threshold.setRange(1, 500)
        dir_form.addRow(
            "Deadzone / Threshold:",
            self._pair_spins(self.trans_dir_deadzone, self.trans_dir_threshold),
        )
        self.transform_stack.addWidget(self.trans_dir_page)

        self.trans_joy_page = QWidget()
        joy_form = QFormLayout(self.trans_joy_page)
        joy_form.setContentsMargins(0, 0, 0, 0)
        self.trans_joy_dz = QDoubleSpinBox()
        self.trans_joy_dz.setRange(0, 500)
        self.trans_joy_dz.setValue(10)
        self.trans_joy_walk = QDoubleSpinBox()
        self.trans_joy_walk.setRange(10, 1000)
        self.trans_joy_walk.setValue(80)
        self.trans_joy_sprint = QDoubleSpinBox()
        self.trans_joy_sprint.setRange(0, 1000)
        self.trans_joy_sprint.setValue(120)
        self.trans_joy_hysteresis = QDoubleSpinBox()
        self.trans_joy_hysteresis.setRange(0, 45)
        self.trans_joy_hysteresis.setValue(5.0)
        self.trans_joy_hysteresis.setSuffix("°")

        joy_form.addRow("Deadzone:", self.trans_joy_dz)
        joy_form.addRow("Walk Radius:", self.trans_joy_walk)
        joy_form.addRow("Sprint Radius (0=Off):", self.trans_joy_sprint)
        joy_form.addRow("Hysteresis:", self.trans_joy_hysteresis)
        self.transform_stack.addWidget(self.trans_joy_page)

        self.trans_dt_page = QWidget()
        dt_form = QFormLayout(self.trans_dt_page)
        dt_form.setContentsMargins(0, 0, 0, 0)
        self.trans_dt_interval = QDoubleSpinBox()
        self.trans_dt_interval.setRange(0.05, 1.0)
        self.trans_dt_interval.setSingleStep(0.05)
        self.trans_dt_interval.setValue(0.30)
        self.trans_dt_interval.setSuffix(" s")

        self.trans_dt_dist = QDoubleSpinBox()
        self.trans_dt_dist.setRange(5.0, 200.0)
        self.trans_dt_dist.setSingleStep(5.0)
        self.trans_dt_dist.setValue(35.0)
        self.trans_dt_dist.setSuffix(" px")

        dt_form.addRow("Max Tap Interval:", self.trans_dt_interval)
        dt_form.addRow("Max Tap Drift:", self.trans_dt_dist)
        self.transform_stack.addWidget(self.trans_dt_page)

        transform_layout.addWidget(self.transform_stack)
        inspector.addWidget(transform_box)

        # Stage 5: Semantics / Output
        semantic_box = QGroupBox("5. Semantics & Output")
        semantic_form = QFormLayout(semantic_box)
        self.semantic_type_combo = QComboBox()
        self.semantic_type_combo.addItems(
            [
                "Button Press",
                "Toggle Key",
                "Toggle Mode (Game <-> Menu)",
                "WASD Directional Keys",
                "Pointer Move",
                "Track Fire (Button + Move)",
            ]
        )
        semantic_form.addRow("Semantic Mode:", self.semantic_type_combo)

        self.output_key_edit = QLineEdit("space")
        semantic_form.addRow("Target Key / Button:", self.output_key_edit)

        self.is_mouse_btn_check = QCheckBox("Output is Mouse Button")
        semantic_form.addRow("", self.is_mouse_btn_check)

        inspector.addWidget(semantic_box)

        self.save_pipeline_btn = QPushButton("Save Pipeline to Active Layout")
        inspector.addWidget(self.save_pipeline_btn)
        inspector.addStretch()

        body_layout.addLayout(inspector, stretch=2)
        self.content_layout().addLayout(body_layout)

        self._wire_internal_signals()
        self.load_active_layout_zones()

    def on_page_shown(self) -> None:
        self.load_active_layout_zones()

    def _wire_internal_signals(self) -> None:
        self.region_type_combo.currentIndexChanged.connect(self.region_stack.setCurrentIndex)
        self.origin_type_combo.currentIndexChanged.connect(self._on_origin_type_changed)
        self.constraint_type_combo.currentIndexChanged.connect(self.constraint_stack.setCurrentIndex)
        self.transform_type_combo.currentIndexChanged.connect(self.transform_stack.setCurrentIndex)
        self.semantic_type_combo.currentIndexChanged.connect(self._on_semantic_type_changed)
        self.preset_combo.currentIndexChanged.connect(self._apply_preset_fields)

        self.add_preset_btn.clicked.connect(self._apply_preset_fields_button)
        self.save_pipeline_btn.clicked.connect(self._on_save_pipeline)
        self.delete_btn.clicked.connect(self._on_delete_zone)
        self.pipeline_list.itemSelectionChanged.connect(self._on_zone_selected)

    def load_active_layout_zones(self) -> None:
        self.pipeline_list.clear()
        zones = store.get_active_layout_zones()
        for zone in zones:
            item = QListWidgetItem(f"{zone.name or 'Zone'} [{zone.scancode}] (Prio: {zone.priority})")
            item.setData(Qt.ItemDataRole.UserRole, zone.id)
            self.pipeline_list.addItem(item)

    def _on_zone_selected(self) -> None:
        items = self.pipeline_list.selectedItems()
        if not items:
            return
        zone_id = items[0].data(Qt.ItemDataRole.UserRole)
        zone = store.zones.get(zone_id)
        if not zone:
            return

        self.name_edit.setText(zone.name)
        self.priority_spin.setValue(zone.priority)
        self.output_key_edit.setText(zone.scancode)

        if zone.zone_type == "CIRCLE":
            self.region_type_combo.setCurrentIndex(1)
            self.reg_center_x.setValue(zone.cx or 0.0)
            self.reg_center_y.setValue(zone.cy or 0.0)
            self.reg_radius.setValue(zone.r or 50.0)
        else:
            self.region_type_combo.setCurrentIndex(2)
            self.reg_x1.setValue(zone.x1 or 0.0)
            self.reg_y1.setValue(zone.y1 or 0.0)
            self.reg_x2.setValue(zone.x2 or 0.0)
            self.reg_y2.setValue(zone.y2 or 0.0)

    def _on_save_pipeline(self) -> None:
        active_layout = store.get_active_layout()
        if not active_layout:
            QMessageBox.warning(self, "No Active Layout", "Please set an active layout before saving pipelines.")
            return

        reg_idx = self.region_type_combo.currentIndex()
        z_type = "CIRCLE" if reg_idx == 1 else "RECTANGLE"

        zone_fields = {
            "layout_id": active_layout.id,
            "name": self.name_edit.text().strip(),
            "scancode": self.output_key_edit.text().strip() or "space",
            "zone_type": z_type,
            "priority": int(self.priority_spin.value()),
            "move_camera": int(self.semantic_type_combo.currentIndex() == 5),
            "cx": self.reg_center_x.value() if z_type == "CIRCLE" else None,
            "cy": self.reg_center_y.value() if z_type == "CIRCLE" else None,
            "r": self.reg_radius.value() if z_type == "CIRCLE" else None,
            "x1": self.reg_x1.value() if z_type == "RECTANGLE" else None,
            "y1": self.reg_y1.value() if z_type == "RECTANGLE" else None,
            "x2": self.reg_x2.value() if z_type == "RECTANGLE" else None,
            "y2": self.reg_y2.value() if z_type == "RECTANGLE" else None,
        }

        selected = self.pipeline_list.selectedItems()
        if selected:
            zone_id = selected[0].data(Qt.ItemDataRole.UserRole)
            store.zones.update(zone_id, **zone_fields)
        else:
            store.zones.create(**zone_fields)

        self.load_active_layout_zones()
        if self.dispatcher:
            self.dispatcher.dispatch(MapperEvent(action="ON_LAYOUT_RELOAD"))
        QMessageBox.information(self, "Saved", "Pipeline saved and synced to engine.")

    def _on_delete_zone(self) -> None:
        selected = self.pipeline_list.selectedItems()
        if not selected:
            return
        zone_id = selected[0].data(Qt.ItemDataRole.UserRole)
        store.zones.delete(zone_id)
        self.load_active_layout_zones()
        if self.dispatcher:
            self.dispatcher.dispatch(MapperEvent(action="ON_LAYOUT_RELOAD"))

    def _on_origin_type_changed(self, idx: int) -> None:
        is_fixed = idx == 1
        is_anchored = idx == 2
        self.orig_pos_widget.setEnabled(is_fixed or is_anchored)
        self.orig_snap_radius.setEnabled(is_anchored)

    def _on_semantic_type_changed(self, idx: int) -> None:
        is_mode_toggle = idx == 2
        self.output_key_edit.setEnabled(not is_mode_toggle)
        self.is_mouse_btn_check.setEnabled(not is_mode_toggle)

    def _apply_preset_fields_button(self) -> None:
        self._apply_preset_fields(self.preset_combo.currentIndex())

    def _apply_preset_fields(self, index: int) -> None:
        if index == 1:  # Button (Tap/Hold)
            self.region_type_combo.setCurrentIndex(1)
            self.origin_type_combo.setCurrentIndex(1)
            self.constraint_type_combo.setCurrentIndex(0)
            self.transform_type_combo.setCurrentIndex(0)
            self.semantic_type_combo.setCurrentIndex(0)
            self.priority_spin.setValue(0)

        elif index == 2:  # Toggle Key
            self.region_type_combo.setCurrentIndex(1)
            self.origin_type_combo.setCurrentIndex(1)
            self.constraint_type_combo.setCurrentIndex(0)
            self.transform_type_combo.setCurrentIndex(0)
            self.semantic_type_combo.setCurrentIndex(1)
            self.priority_spin.setValue(0)

        elif index == 3:  # Fixed Joystick
            self.region_type_combo.setCurrentIndex(1)
            self.origin_type_combo.setCurrentIndex(1)
            self.constraint_type_combo.setCurrentIndex(1)
            self.transform_type_combo.setCurrentIndex(3)
            self.semantic_type_combo.setCurrentIndex(3)
            self.priority_spin.setValue(0)

        elif index == 4:  # Floating Joystick
            self.region_type_combo.setCurrentIndex(2)
            self.origin_type_combo.setCurrentIndex(0)
            self.constraint_type_combo.setCurrentIndex(3)
            self.transform_type_combo.setCurrentIndex(3)
            self.semantic_type_combo.setCurrentIndex(3)
            self.priority_spin.setValue(0)

        elif index == 5:  # Anchored Floating Joystick
            self.region_type_combo.setCurrentIndex(2)
            self.origin_type_combo.setCurrentIndex(2)
            self.constraint_type_combo.setCurrentIndex(3)
            self.transform_type_combo.setCurrentIndex(3)
            self.semantic_type_combo.setCurrentIndex(3)
            self.priority_spin.setValue(0)

        elif index == 6:  # Relative Pointer
            self.region_type_combo.setCurrentIndex(0)
            self.origin_type_combo.setCurrentIndex(0)
            self.constraint_type_combo.setCurrentIndex(0)
            self.transform_type_combo.setCurrentIndex(1)
            self.semantic_type_combo.setCurrentIndex(4)
            self.priority_spin.setValue(-100)

        elif index == 7:  # Track Fire
            self.region_type_combo.setCurrentIndex(1)
            self.origin_type_combo.setCurrentIndex(0)
            self.constraint_type_combo.setCurrentIndex(0)
            self.transform_type_combo.setCurrentIndex(1)
            self.semantic_type_combo.setCurrentIndex(5)
            self.priority_spin.setValue(0)

        elif index == 8:  # Bezel Return Toggle
            self.region_type_combo.setCurrentIndex(3)
            self.origin_type_combo.setCurrentIndex(0)
            self.constraint_type_combo.setCurrentIndex(0)
            self.transform_type_combo.setCurrentIndex(0)
            self.semantic_type_combo.setCurrentIndex(2)
            self.priority_spin.setValue(150)

        elif index == 9:  # Double-Tap Toggle
            self.region_type_combo.setCurrentIndex(0)
            self.origin_type_combo.setCurrentIndex(0)
            self.constraint_type_combo.setCurrentIndex(0)
            self.transform_type_combo.setCurrentIndex(4)
            self.semantic_type_combo.setCurrentIndex(2)
            self.priority_spin.setValue(-50)

    @staticmethod
    def _pair_spins(spin_a: QDoubleSpinBox, spin_b: QDoubleSpinBox) -> QWidget:
        wrapper = QWidget()
        row = QHBoxLayout(wrapper)
        row.setContentsMargins(0, 0, 0, 0)
        row.addWidget(spin_a)
        row.addWidget(spin_b)
        return wrapper