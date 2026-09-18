from __future__ import annotations

import json
import logging
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

from modules.database import reset_layout_zones_to_app_settings, store
from modules.utils import MapperEvent
from .base_page import BasePage

if TYPE_CHECKING:
    from modules.utils import MapperEventDispatcher

logger = logging.getLogger("modules.gui.pipelines_page")


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

        # -------------------------------------------------------------
        # Left Column: Pipeline List, Presets & Global Actions
        # -------------------------------------------------------------
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

        self.reset_all_btn = QPushButton("Reset All Zones to App Defaults")
        left_panel.addWidget(self.reset_all_btn)

        body_layout.addLayout(left_panel, stretch=1)

        # -------------------------------------------------------------
        # Right Column: 5-Stage Pipeline Inspector
        # -------------------------------------------------------------
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
        self.region_type_combo.addItems(
            ["Always", "Circular", "Rectangular", "Top Bezel Notch"]
        )
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
        circle_form.addRow(
            "Center (X, Y):", self._pair_spins(self.reg_center_x, self.reg_center_y)
        )
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
        rect_form.addRow(
            "Top-Left (X1, Y1):", self._pair_spins(self.reg_x1, self.reg_y1)
        )
        rect_form.addRow(
            "Bottom-Right (X2, Y2):", self._pair_spins(self.reg_x2, self.reg_y2)
        )
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

        # Action Buttons
        btn_action_row = QHBoxLayout()
        self.reset_defaults_btn = QPushButton("Reset Zone to App Defaults")
        self.save_pipeline_btn = QPushButton("Save Pipeline to Active Layout")
        btn_action_row.addWidget(self.reset_defaults_btn)
        btn_action_row.addWidget(self.save_pipeline_btn)
        inspector.addLayout(btn_action_row)

        inspector.addStretch()
        body_layout.addLayout(inspector, stretch=2)
        self.content_layout().addLayout(body_layout)

        self._wire_internal_signals()
        self.load_active_layout_zones()

    def on_page_shown(self) -> None:
        self.load_active_layout_zones()

    def _wire_internal_signals(self) -> None:
        self.region_type_combo.currentIndexChanged.connect(
            self.region_stack.setCurrentIndex
        )
        self.origin_type_combo.currentIndexChanged.connect(self._on_origin_type_changed)
        self.constraint_type_combo.currentIndexChanged.connect(
            self.constraint_stack.setCurrentIndex
        )
        self.transform_type_combo.currentIndexChanged.connect(
            self.transform_stack.setCurrentIndex
        )
        self.semantic_type_combo.currentIndexChanged.connect(
            self._on_semantic_type_changed
        )
        self.preset_combo.currentIndexChanged.connect(self._apply_preset_fields)

        self.new_btn.clicked.connect(self._clear_inspector_for_new)
        self.duplicate_btn.clicked.connect(self._on_duplicate_zone)
        self.add_preset_btn.clicked.connect(self._apply_preset_fields_button)
        self.save_pipeline_btn.clicked.connect(self._on_save_pipeline)
        self.reset_defaults_btn.clicked.connect(
            self._reset_current_zone_to_app_settings
        )
        self.reset_all_btn.clicked.connect(self._on_reset_all_zones)
        self.delete_btn.clicked.connect(self._on_delete_zone)
        self.pipeline_list.itemSelectionChanged.connect(self._on_zone_selected)

    def load_active_layout_zones(self) -> None:
        self.pipeline_list.clear()
        try:
            zones = store.get_active_layout_zones()
            for zone in zones:
                item = QListWidgetItem(
                    f"{zone.name or 'Zone'} [{zone.scancode}] (Prio: {zone.priority})"
                )
                item.setData(Qt.ItemDataRole.UserRole, zone.id)
                self.pipeline_list.addItem(item)
        except Exception:
            logger.exception("Failed to load active layout zones from database")

    def _get_existing_singleton_zone_id(self, mode: str) -> int | None:
        """Finds if a singleton zone already exists in the active layout,

        checking semantics, transformations, and fallback codes.
        """
        for zone in store.get_active_layout_zones():
            try:
                cfg = json.loads(zone.pipeline_config or "{}")
                if cfg.get("semantics", {}).get("mode") == mode:
                    return zone.id
                if (
                    mode == "WASD"
                    and cfg.get("transform", {}).get("type") == "JOYSTICK"
                ):
                    return zone.id
            except Exception:
                pass

            if mode == "WASD" and (
                zone.name == "MOUSE_WHEEL" or zone.scancode == "MOUSE_WHEEL"
            ):
                return zone.id
            if mode == "POINTER" and (
                zone.name in ("LOOK_AREA", "Relative Pointer")
                or zone.scancode == "MOUSE_LOOK"
            ):
                return zone.id

        return None

    def _get_pipeline_dict(self) -> dict:
        reg_idx = self.region_type_combo.currentIndex()
        origin_idx = self.origin_type_combo.currentIndex()
        const_idx = self.constraint_type_combo.currentIndex()
        trans_idx = self.transform_type_combo.currentIndex()
        sem_idx = self.semantic_type_combo.currentIndex()

        return {
            "priority": int(self.priority_spin.value()),
            "region": {
                "type_idx": reg_idx,
                "type": ["ALWAYS", "CIRCLE", "RECTANGLE", "BEZEL"][reg_idx],
                "bezel_height": self.reg_bezel_height.value(),
            },
            "origin": {
                "type_idx": origin_idx,
                "type": ["DYNAMIC", "FIXED", "ANCHORED"][origin_idx],
                "anchor_x": self.orig_x.value(),
                "anchor_y": self.orig_y.value(),
                "snap_radius": self.orig_snap_radius.value(),
            },
            "constraint": {
                "type_idx": const_idx,
                "type": ["NONE", "RADIAL", "RECTANGULAR", "LEASH"][const_idx],
                "radius": self.const_radius_spin.value(),
                "half_w": self.const_half_w.value(),
                "half_h": self.const_half_h.value(),
                "leash_radius": self.const_leash_spin.value(),
            },
            "transform": {
                "type_idx": trans_idx,
                "type": ["IDENTITY", "DELTA", "DIRECTIONAL", "JOYSTICK", "DOUBLE_TAP"][
                    trans_idx
                ],
                "sens_x": self.trans_sens_x.value(),
                "sens_y": self.trans_sens_y.value(),
                "deadzone": self.trans_dir_deadzone.value(),
                "threshold": self.trans_dir_threshold.value(),
                "joy_dz": self.trans_joy_dz.value(),
                "joy_walk": self.trans_joy_walk.value(),
                "joy_sprint": self.trans_joy_sprint.value(),
                "joy_hysteresis": self.trans_joy_hysteresis.value(),
                "dt_interval": self.trans_dt_interval.value(),
                "dt_dist": self.trans_dt_dist.value(),
            },
            "semantics": {
                "type_idx": sem_idx,
                "mode": [
                    "BUTTON",
                    "TOGGLE_KEY",
                    "TOGGLE_MODE",
                    "WASD",
                    "POINTER",
                    "TRACK_FIRE",
                ][sem_idx],
                "is_mouse_button": self.is_mouse_btn_check.isChecked(),
            },
        }

    def _reset_current_zone_to_app_settings(self) -> None:
        settings = store.settings.get()
        active = store.get_active_layout()
        inner_r = active.mouse_wheel_radius if active else 50.0
        outer_r = active.sprint_distance if active else 100.0

        sem_idx = self.semantic_type_combo.currentIndex()
        if sem_idx == 3:  # WASD
            self.origin_type_combo.setCurrentIndex(
                2 if settings.anchored_floating_joystick else 1
            )
            self.orig_snap_radius.setValue(settings.joystick_snap_radius)
            self.trans_joy_dz.setValue(settings.deadzone * inner_r)
            self.trans_joy_walk.setValue(inner_r)
            self.trans_joy_sprint.setValue(outer_r)
            self.trans_joy_hysteresis.setValue(settings.hysteresis)
        elif sem_idx in (4, 5):  # POINTER / TRACK_FIRE
            self.trans_sens_x.setValue(settings.sensitivity)
            self.trans_sens_y.setValue(settings.sensitivity)

        QMessageBox.information(
            self,
            "Reset Applied",
            "Inspector fields repopulated with active AppSettings. Click 'Save Pipeline' to commit.",
        )

    def _on_reset_all_zones(self) -> None:
        active = store.get_active_layout()
        if not active:
            return
        reply = QMessageBox.question(
            self,
            "Reset All Zones",
            f"Reset all zones in layout '{active.name}' to default AppSettings?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply == QMessageBox.StandardButton.Yes:
            count = reset_layout_zones_to_app_settings(active.id)
            self.load_active_layout_zones()
            if self.dispatcher:
                self.dispatcher.dispatch(MapperEvent(action="ON_LAYOUT_RELOAD"))
            QMessageBox.information(
                self, "Success", f"Reset {count} zones to default AppSettings."
            )

    def _clear_inspector_for_new(self) -> None:
        self.pipeline_list.clearSelection()
        self.name_edit.setText("New Pipeline")
        self.priority_spin.setValue(0)
        self.output_key_edit.setText("space")
        self.region_type_combo.setCurrentIndex(1)
        self.origin_type_combo.setCurrentIndex(1)
        self.constraint_type_combo.setCurrentIndex(0)
        self.transform_type_combo.setCurrentIndex(0)
        self.semantic_type_combo.setCurrentIndex(0)

    def _on_duplicate_zone(self) -> None:
        selected = self.pipeline_list.selectedItems()
        if not selected:
            return
        zone_id = selected[0].data(Qt.ItemDataRole.UserRole)
        zone = store.zones.get(zone_id)
        if not zone:
            return

        try:
            cfg = json.loads(zone.pipeline_config or "{}")
            target_mode = cfg.get("semantics", {}).get("mode")
            if target_mode in ("WASD", "POINTER"):
                QMessageBox.warning(
                    self,
                    "Cannot Duplicate Singleton",
                    f"Duplicating a {target_mode} singleton zone is forbidden.",
                )
                return
        except Exception:
            pass

        if zone.name in ("MOUSE_WHEEL", "LOOK_AREA") or zone.scancode in (
            "MOUSE_WHEEL",
            "MOUSE_LOOK",
        ):
            QMessageBox.warning(
                self,
                "Cannot Duplicate Singleton",
                "Duplicating a movement joystick or look area is forbidden.",
            )
            return

        active_layout = store.get_active_layout()
        if not active_layout:
            return

        store.zones.create(
            layout_id=active_layout.id,
            name=f"{zone.name or 'Zone'} (Copy)",
            scancode=zone.scancode,
            zone_type=zone.zone_type,
            cx=zone.cx,
            cy=zone.cy,
            r=zone.r,
            x1=zone.x1,
            y1=zone.y1,
            x2=zone.x2,
            y2=zone.y2,
            pipeline_config=zone.pipeline_config,
        )
        self.load_active_layout_zones()
        if self.dispatcher:
            self.dispatcher.dispatch(MapperEvent(action="ON_LAYOUT_RELOAD"))

    def _on_zone_selected(self) -> None:
        items = self.pipeline_list.selectedItems()
        if not items:
            return
        zone_id = items[0].data(Qt.ItemDataRole.UserRole)
        try:
            zone = store.zones.get(zone_id)
            if not zone:
                return

            cfg_raw = zone.pipeline_config or "{}"
            try:
                cfg = json.loads(cfg_raw)
            except Exception:
                cfg = {}

            self.name_edit.setText(zone.name or "")
            self.output_key_edit.setText(zone.scancode or "")
            self.priority_spin.setValue(cfg.get("priority", 0))

            # Geometry defaults
            self.reg_center_x.setValue(zone.cx or 0.0)
            self.reg_center_y.setValue(zone.cy or 0.0)
            self.reg_radius.setValue(zone.r or 50.0)
            self.reg_x1.setValue(zone.x1 or 0.0)
            self.reg_y1.setValue(zone.y1 or 0.0)
            self.reg_x2.setValue(zone.x2 or 0.0)
            self.reg_y2.setValue(zone.y2 or 0.0)

            # Block internal handler to avoid trigger loops while loading inspector
            self.semantic_type_combo.blockSignals(True)

            # Unpack JSON pipeline config
            reg = cfg.get("region", {})
            default_reg_idx = 1 if zone.zone_type == "CIRCLE" else 2
            self.region_type_combo.setCurrentIndex(reg.get("type_idx", default_reg_idx))
            self.reg_bezel_height.setValue(reg.get("bezel_height", 14.0))

            orig = cfg.get("origin", {})
            self.origin_type_combo.setCurrentIndex(orig.get("type_idx", 1))
            self.orig_x.setValue(orig.get("anchor_x", zone.cx or 0.0))
            self.orig_y.setValue(orig.get("anchor_y", zone.cy or 0.0))
            self.orig_snap_radius.setValue(orig.get("snap_radius", 80.0))

            const = cfg.get("constraint", {})
            self.constraint_type_combo.setCurrentIndex(const.get("type_idx", 0))
            self.const_radius_spin.setValue(const.get("radius", 100.0))
            self.const_half_w.setValue(const.get("half_w", 50.0))
            self.const_half_h.setValue(const.get("half_h", 50.0))
            self.const_leash_spin.setValue(const.get("leash_radius", 150.0))

            trans = cfg.get("transform", {})
            self.transform_type_combo.setCurrentIndex(trans.get("type_idx", 0))
            self.trans_sens_x.setValue(trans.get("sens_x", 1.0))
            self.trans_sens_y.setValue(trans.get("sens_y", 1.0))
            self.trans_dir_deadzone.setValue(trans.get("deadzone", 0.0))
            self.trans_dir_threshold.setValue(trans.get("threshold", 50.0))
            self.trans_joy_dz.setValue(trans.get("joy_dz", 10.0))
            self.trans_joy_walk.setValue(trans.get("joy_walk", 80.0))
            self.trans_joy_sprint.setValue(trans.get("joy_sprint", 120.0))
            self.trans_joy_hysteresis.setValue(trans.get("joy_hysteresis", 5.0))
            self.trans_dt_interval.setValue(trans.get("dt_interval", 0.30))
            self.trans_dt_dist.setValue(trans.get("dt_dist", 35.0))

            sem = cfg.get("semantics", {})
            default_sem_idx = 5 if zone.move_camera else 0
            self.semantic_type_combo.setCurrentIndex(
                sem.get("type_idx", default_sem_idx)
            )
            self.is_mouse_btn_check.setChecked(sem.get("is_mouse_button", False))

            self.semantic_type_combo.blockSignals(False)

            is_mode_toggle = self.semantic_type_combo.currentIndex() == 2
            self.output_key_edit.setEnabled(not is_mode_toggle)
            self.is_mouse_btn_check.setEnabled(not is_mode_toggle)

        except Exception:
            logger.exception("Failed to retrieve zone ID %s metadata", zone_id)

    def _on_save_pipeline(self) -> None:
        try:
            active_layout = store.get_active_layout()
            if not active_layout:
                QMessageBox.warning(
                    self,
                    "No Active Layout",
                    "Please set an active layout before saving pipelines.",
                )
                return

            sem_idx = self.semantic_type_combo.currentIndex()
            target_mode = [
                "BUTTON",
                "TOGGLE_KEY",
                "TOGGLE_MODE",
                "WASD",
                "POINTER",
                "TRACK_FIRE",
            ][sem_idx]

            selected = self.pipeline_list.selectedItems()
            current_zone_id = (
                selected[0].data(Qt.ItemDataRole.UserRole) if selected else None
            )

            # Enforce single movement joystick and single mouse look zone
            if target_mode in ("WASD", "POINTER"):
                existing_id = self._get_existing_singleton_zone_id(target_mode)
                if existing_id is not None and existing_id != current_zone_id:
                    entity = (
                        "directional joystick (WASD)"
                        if target_mode == "WASD"
                        else "look area (Mouse Pointer)"
                    )
                    QMessageBox.warning(
                        self,
                        "Singleton Rule Violation",
                        f"A {entity} already exists in this layout.\nYou cannot create a second one.",
                    )
                    return

            reg_idx = self.region_type_combo.currentIndex()
            if reg_idx == 1:
                z_type = "CIRCLE"
            elif reg_idx == 3:
                z_type = "BEZEL"
            else:
                z_type = "RECTANGLE"

            serialized_config = json.dumps(self._get_pipeline_dict())

            zone_fields = {
                "layout_id": active_layout.id,
                "name": self.name_edit.text().strip() or "Custom Pipeline",
                "scancode": self.output_key_edit.text().strip() or "space",
                "zone_type": z_type,
                "cx": self.reg_center_x.value() if z_type == "CIRCLE" else None,
                "cy": self.reg_center_y.value() if z_type == "CIRCLE" else None,
                "r": self.reg_radius.value() if z_type == "CIRCLE" else None,
                "x1": self.reg_x1.value() if z_type == "RECTANGLE" else None,
                "y1": self.reg_y1.value() if z_type == "RECTANGLE" else None,
                "x2": self.reg_x2.value() if z_type == "RECTANGLE" else None,
                "y2": self.reg_y2.value() if z_type == "RECTANGLE" else None,
                "pipeline_config": serialized_config,
            }

            if current_zone_id:
                store.zones.update(current_zone_id, **zone_fields)
                logger.info(
                    "Updated pipeline zone ID %s ('%s')",
                    current_zone_id,
                    zone_fields["name"],
                )
            else:
                new_zone = store.zones.create(**zone_fields)
                logger.info(
                    "Created new pipeline zone ID %s ('%s')",
                    new_zone.id,
                    zone_fields["name"],
                )

            self.load_active_layout_zones()
            if self.dispatcher:
                self.dispatcher.dispatch(MapperEvent(action="ON_LAYOUT_RELOAD"))
            QMessageBox.information(
                self, "Saved", "Pipeline saved and synced to active layout."
            )
        except Exception as exc:
            logger.exception("Failed to save pipeline zone")
            QMessageBox.critical(self, "Error", f"Could not save pipeline:\n{exc}")

    def _on_delete_zone(self) -> None:
        selected = self.pipeline_list.selectedItems()
        if not selected:
            return
        zone_id = selected[0].data(Qt.ItemDataRole.UserRole)
        try:
            store.zones.delete(zone_id)
            logger.info("Deleted pipeline zone ID %s", zone_id)
            self.load_active_layout_zones()
            if self.dispatcher:
                self.dispatcher.dispatch(MapperEvent(action="ON_LAYOUT_RELOAD"))
        except Exception as exc:
            logger.exception("Failed to delete zone ID %s", zone_id)
            QMessageBox.critical(
                self, "Database Error", f"Could not delete zone:\n{exc}"
            )

    def _on_origin_type_changed(self, idx: int) -> None:
        is_fixed = idx == 1
        is_anchored = idx == 2
        self.orig_pos_widget.setEnabled(is_fixed or is_anchored)
        self.orig_snap_radius.setEnabled(is_anchored)

    def _on_semantic_type_changed(self, idx: int) -> None:
        target_mode = [
            "BUTTON",
            "TOGGLE_KEY",
            "TOGGLE_MODE",
            "WASD",
            "POINTER",
            "TRACK_FIRE",
        ][idx]

        is_mode_toggle = idx == 2
        is_track_fire = idx == 5

        # Enable/disable output key editing
        self.output_key_edit.setEnabled(not is_mode_toggle)

        # TrackFire exclusively drags the HUD button/reticle on the touch layer.
        # It suppresses camera movement, so auxiliary camera/mouse toggles are disabled.
        if is_track_fire:
            self.is_mouse_btn_check.setChecked(False)
            self.is_mouse_btn_check.setEnabled(False)
        else:
            self.is_mouse_btn_check.setEnabled(not is_mode_toggle)

        # Intercept manual configuration if another zone holds the singleton
        if target_mode in ("WASD", "POINTER"):
            existing_id = self._get_existing_singleton_zone_id(target_mode)
            selected = self.pipeline_list.selectedItems()
            current_id = (
                selected[0].data(Qt.ItemDataRole.UserRole) if selected else None
            )

            if existing_id is not None and existing_id != current_id:
                entity = (
                    "directional joystick (WASD)"
                    if target_mode == "WASD"
                    else "look area (Mouse Pointer)"
                )
                QMessageBox.warning(
                    self,
                    "Singleton Conflict",
                    f"A {entity} already exists in this layout.\nRedirecting you to the existing zone.",
                )
                self._select_zone_by_id(existing_id)
                self._on_zone_selected()
                return

    def _apply_preset_fields_button(self) -> None:
        self._apply_preset_fields(self.preset_combo.currentIndex())

    def _select_zone_by_id(self, zone_id: int) -> None:
        """Selects the list item matching zone_id without triggering premature reload loops."""
        for i in range(self.pipeline_list.count()):
            item = self.pipeline_list.item(i)
            if item.data(Qt.ItemDataRole.UserRole) == zone_id:
                self.pipeline_list.blockSignals(True)
                self.pipeline_list.setCurrentItem(item)
                self.pipeline_list.blockSignals(False)
                return

    def _apply_preset_fields(self, index: int) -> None:
        if index == 0:  # Custom
            return

        settings = store.settings.get()
        active = store.get_active_layout()
        inner_r = active.mouse_wheel_radius if active else 50.0
        outer_r = active.sprint_distance if active else 100.0

        # Singleton enforcement: Redirect to existing zone instead of drafting a duplicate
        if index in (3, 4, 5):  # Joysticks (WASD)
            existing_id = self._get_existing_singleton_zone_id("WASD")
            selected = self.pipeline_list.selectedItems()
            current_id = (
                selected[0].data(Qt.ItemDataRole.UserRole) if selected else None
            )

            if existing_id is not None and existing_id != current_id:
                self._select_zone_by_id(existing_id)
                QMessageBox.information(
                    self,
                    "Selected Existing Joystick",
                    "A movement joystick already exists in this layout. Switched to editing the existing zone.",
                )

        elif index == 6:  # Relative Pointer (Look Area)
            existing_id = self._get_existing_singleton_zone_id("POINTER")
            selected = self.pipeline_list.selectedItems()
            current_id = (
                selected[0].data(Qt.ItemDataRole.UserRole) if selected else None
            )

            if existing_id is not None and existing_id != current_id:
                self._select_zone_by_id(existing_id)
                QMessageBox.information(
                    self,
                    "Selected Existing Look Area",
                    "A Look Area already exists in this layout. Switched to editing the existing zone.",
                )

        # -------------------------------------------------------------
        # Apply Preset Inspector Values
        # -------------------------------------------------------------
        if index == 1:  # Button (Tap/Hold)
            self.name_edit.setText("Button Zone")
            self.region_type_combo.setCurrentIndex(1)
            self.origin_type_combo.setCurrentIndex(1)
            self.constraint_type_combo.setCurrentIndex(0)
            self.transform_type_combo.setCurrentIndex(0)
            self.semantic_type_combo.setCurrentIndex(0)
            self.priority_spin.setValue(0)

        elif index == 2:  # Toggle Key
            self.name_edit.setText("Toggle Key Zone")
            self.region_type_combo.setCurrentIndex(1)
            self.origin_type_combo.setCurrentIndex(1)
            self.constraint_type_combo.setCurrentIndex(0)
            self.transform_type_combo.setCurrentIndex(0)
            self.semantic_type_combo.setCurrentIndex(1)
            self.priority_spin.setValue(0)

        elif index == 3:  # Fixed Joystick
            self.name_edit.setText("Fixed Joystick")
            self.output_key_edit.setText("WASD")
            self.region_type_combo.setCurrentIndex(1)
            self.origin_type_combo.setCurrentIndex(1)
            self.constraint_type_combo.setCurrentIndex(1)
            self.transform_type_combo.setCurrentIndex(3)
            self.semantic_type_combo.setCurrentIndex(3)
            self.trans_joy_dz.setValue(settings.deadzone * inner_r)
            self.trans_joy_walk.setValue(inner_r)
            self.trans_joy_sprint.setValue(outer_r)
            self.trans_joy_hysteresis.setValue(settings.hysteresis)
            self.priority_spin.setValue(0)

        elif index in (4, 5):  # Floating / Anchored Joystick
            is_anchored = index == 5
            self.name_edit.setText(
                "Anchored Floating Joystick" if is_anchored else "Floating Joystick"
            )
            self.output_key_edit.setText("WASD")
            self.region_type_combo.setCurrentIndex(2)
            self.origin_type_combo.setCurrentIndex(2 if is_anchored else 0)
            self.orig_snap_radius.setValue(settings.joystick_snap_radius)
            self.constraint_type_combo.setCurrentIndex(3)
            self.transform_type_combo.setCurrentIndex(3)
            self.semantic_type_combo.setCurrentIndex(3)
            self.trans_joy_dz.setValue(settings.deadzone * inner_r)
            self.trans_joy_walk.setValue(inner_r)
            self.trans_joy_sprint.setValue(outer_r)
            self.trans_joy_hysteresis.setValue(settings.hysteresis)
            self.priority_spin.setValue(0)

        elif index == 6:  # Relative Pointer (Look)
            self.name_edit.setText("Look Area")
            self.output_key_edit.setText("MOUSE_LOOK")
            self.region_type_combo.setCurrentIndex(0)
            self.origin_type_combo.setCurrentIndex(0)
            self.constraint_type_combo.setCurrentIndex(0)
            self.transform_type_combo.setCurrentIndex(1)
            self.trans_sens_x.setValue(settings.sensitivity)
            self.trans_sens_y.setValue(settings.sensitivity)
            self.semantic_type_combo.setCurrentIndex(4)
            self.priority_spin.setValue(-100)

        elif index == 7:  # Track Fire
            self.name_edit.setText("Track Fire Button")
            self.region_type_combo.setCurrentIndex(1)
            self.origin_type_combo.setCurrentIndex(0)
            self.constraint_type_combo.setCurrentIndex(0)
            self.transform_type_combo.setCurrentIndex(1)
            self.trans_sens_x.setValue(settings.sensitivity)
            self.trans_sens_y.setValue(settings.sensitivity)
            self.semantic_type_combo.setCurrentIndex(5)
            self.priority_spin.setValue(0)

        elif index == 8:  # Bezel Return Toggle
            self.name_edit.setText("Top Bezel Notch")
            self.region_type_combo.setCurrentIndex(3)
            self.origin_type_combo.setCurrentIndex(0)
            self.constraint_type_combo.setCurrentIndex(0)
            self.transform_type_combo.setCurrentIndex(0)
            self.semantic_type_combo.setCurrentIndex(2)
            self.priority_spin.setValue(150)

        elif index == 9:  # Double-Tap Toggle
            self.name_edit.setText("Double-Tap Toggle")
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
