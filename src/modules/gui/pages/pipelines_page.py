from __future__ import annotations

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
    QPushButton,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from .base_page import BasePage


class PipelinesPage(BasePage):
    """Configuration GUI for the 5-stage touch mapping pipeline:
    Region -> Origin -> Constraint -> Transformation -> Semantics
    """

    title = "Pipelines"

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)

        body_layout = QHBoxLayout()

        # Left Column: Pipeline List & Presets
        left_panel = QVBoxLayout()

        preset_row = QHBoxLayout()
        self.preset_combo = QComboBox()
        self.preset_combo.addItems(
            [
                "Custom",
                "Button (Tap/Hold)",
                "Toggle",
                "Fixed Joystick (HUD)",
                "Floating Joystick",
                "Relative Pointer (Look)",
                "Track Fire (Look + Shoot)",
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

        # General Name
        name_form = QFormLayout()
        self.name_edit = QLineEdit()
        name_form.addRow("Pipeline Name:", self.name_edit)
        inspector.addLayout(name_form)

        # Stage 1: Region
        region_box = QGroupBox("1. Region (Activation)")
        region_layout = QVBoxLayout(region_box)
        self.region_type_combo = QComboBox()
        self.region_type_combo.addItems(["Always", "Circular", "Rectangular"])
        region_layout.addWidget(self.region_type_combo)

        self.region_stack = QStackedWidget()

        # Region: Always
        self.region_always_page = QWidget()
        self.region_stack.addWidget(self.region_always_page)

        # Region: Circular
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
        circle_form.addRow("Center X:", self.reg_center_x)
        circle_form.addRow("Center Y:", self.reg_center_y)
        circle_form.addRow("Radius (px):", self.reg_radius)
        self.region_stack.addWidget(self.region_circle_page)

        # Region: Rectangular
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
        rect_form.addRow(
            "Top-Left (X1, Y1):", self._pair_spins(self.reg_x1, self.reg_y1)
        )
        rect_form.addRow(
            "Bottom-Right (X2, Y2):", self._pair_spins(self.reg_x2, self.reg_y2)
        )
        self.region_stack.addWidget(self.region_rect_page)

        region_layout.addWidget(self.region_stack)
        inspector.addWidget(region_box)

        # Stage 2: Origin
        origin_box = QGroupBox("2. Origin (Center Point)")
        origin_layout = QFormLayout(origin_box)
        self.origin_type_combo = QComboBox()
        self.origin_type_combo.addItems(
            ["Dynamic (Touch Point)", "Fixed (HUD Coordinate)"]
        )
        origin_layout.addRow("Origin Type:", self.origin_type_combo)

        self.orig_fixed_x = QDoubleSpinBox()
        self.orig_fixed_x.setRange(0, 10000)
        self.orig_fixed_y = QDoubleSpinBox()
        self.orig_fixed_y.setRange(0, 10000)
        self.orig_pos_widget = self._pair_spins(self.orig_fixed_x, self.orig_fixed_y)
        self.orig_pos_widget.setEnabled(False)
        origin_layout.addRow("Fixed Point:", self.orig_pos_widget)
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

        # Constraint: None
        self.constraint_none_page = QWidget()
        self.constraint_stack.addWidget(self.constraint_none_page)

        # Constraint: Radial
        self.constraint_radial_page = QWidget()
        rad_form = QFormLayout(self.constraint_radial_page)
        rad_form.setContentsMargins(0, 0, 0, 0)
        self.const_radius_spin = QDoubleSpinBox()
        self.const_radius_spin.setRange(1, 2000)
        self.const_radius_spin.setValue(100)
        rad_form.addRow("Clamp Radius:", self.const_radius_spin)
        self.constraint_stack.addWidget(self.constraint_radial_page)

        # Constraint: Rectangular
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

        # Constraint: Leash
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
            ]
        )
        transform_layout.addWidget(self.transform_type_combo)

        self.transform_stack = QStackedWidget()

        # Transform: Identity
        self.trans_identity_page = QWidget()
        self.transform_stack.addWidget(self.trans_identity_page)

        # Transform: Delta
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

        # Transform: Directional
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

        # Transform: Joystick Sector
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

        # Save Button
        self.save_pipeline_btn = QPushButton("Save Pipeline")
        inspector.addWidget(self.save_pipeline_btn)
        inspector.addStretch()

        body_layout.addLayout(inspector, stretch=2)
        self.content_layout().addLayout(body_layout)

        self._wire_internal_signals()

    def _wire_internal_signals(self) -> None:
        self.region_type_combo.currentIndexChanged.connect(
            self.region_stack.setCurrentIndex
        )
        self.origin_type_combo.currentIndexChanged.connect(
            lambda idx: self.orig_pos_widget.setEnabled(idx == 1)
        )
        self.constraint_type_combo.currentIndexChanged.connect(
            self.constraint_stack.setCurrentIndex
        )
        self.transform_type_combo.currentIndexChanged.connect(
            self.transform_stack.setCurrentIndex
        )
        self.preset_combo.currentIndexChanged.connect(self._apply_preset_fields)

    def _apply_preset_fields(self, index: int) -> None:
        if index == 1:  # Button (Tap/Hold)
            self.region_type_combo.setCurrentIndex(1)  # Circular
            self.origin_type_combo.setCurrentIndex(1)  # Fixed
            self.constraint_type_combo.setCurrentIndex(0)  # None
            self.transform_type_combo.setCurrentIndex(0)  # Identity
            self.semantic_type_combo.setCurrentIndex(0)  # Button
        elif index == 2:  # Toggle
            self.region_type_combo.setCurrentIndex(1)
            self.origin_type_combo.setCurrentIndex(1)
            self.constraint_type_combo.setCurrentIndex(0)
            self.transform_type_combo.setCurrentIndex(0)
            self.semantic_type_combo.setCurrentIndex(1)
        elif index == 3:  # Fixed Joystick
            self.region_type_combo.setCurrentIndex(1)
            self.origin_type_combo.setCurrentIndex(1)
            self.constraint_type_combo.setCurrentIndex(1)  # Radial clamp
            self.transform_type_combo.setCurrentIndex(3)  # 8-Sector
            self.semantic_type_combo.setCurrentIndex(2)  # WASD
        elif index == 4:  # Floating Joystick
            self.region_type_combo.setCurrentIndex(2)  # Rectangular zone
            self.origin_type_combo.setCurrentIndex(0)  # Dynamic
            self.constraint_type_combo.setCurrentIndex(3)  # Leash
            self.transform_type_combo.setCurrentIndex(3)
            self.semantic_type_combo.setCurrentIndex(2)
        elif index == 5:  # Relative Pointer
            self.region_type_combo.setCurrentIndex(0)  # Always
            self.origin_type_combo.setCurrentIndex(0)  # Dynamic
            self.constraint_type_combo.setCurrentIndex(0)  # None
            self.transform_type_combo.setCurrentIndex(1)  # Delta
            self.semantic_type_combo.setCurrentIndex(3)  # Pointer Move
        elif index == 6:  # Track Fire
            self.region_type_combo.setCurrentIndex(1)  # Circular
            self.origin_type_combo.setCurrentIndex(0)  # Dynamic
            self.constraint_type_combo.setCurrentIndex(0)
            self.transform_type_combo.setCurrentIndex(1)  # Delta
            self.semantic_type_combo.setCurrentIndex(4)  # Track Fire

    @staticmethod
    def _pair_spins(spin_a: QDoubleSpinBox, spin_b: QDoubleSpinBox) -> QWidget:
        wrapper = QWidget()
        row = QHBoxLayout(wrapper)
        row.setContentsMargins(0, 0, 0, 0)
        row.addWidget(spin_a)
        row.addWidget(spin_b)
        return wrapper
