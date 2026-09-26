from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QDoubleSpinBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
    QLabel,
)

from modules.database import reset_layout_zones_to_app_settings, store
from modules.utils import (
    BEZEL,
    BEZEL_DP_THICKNESS,
    TOP_BEZEL_ID,
    BOTTOM_BEZEL_ID,
    MapperEvent,
)

from .base_page import BasePage

if TYPE_CHECKING:
    from modules.utils import MapperEventDispatcher
    from modules.database import LayoutZone

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
        self.left_panel = QVBoxLayout()

        self.pipeline_list = QListWidget()
        self.left_panel.addWidget(self.pipeline_list)

        list_btn_row = QHBoxLayout()
        self.left_panel.addLayout(list_btn_row)

        self.reset_all_btn = QPushButton("Reset All Zones to App Defaults")
        self.left_panel.addWidget(self.reset_all_btn)

        self.ignore_app_settings_btn = QCheckBox("Ignore App Settings")
        self.ignore_app_settings_btn.setChecked(False)
        self.left_panel.addWidget(self.ignore_app_settings_btn)

        body_layout.addLayout(self.left_panel, stretch=1)

        # -------------------------------------------------------------
        # Right Column: 5-Stage Pipeline inspector
        # -------------------------------------------------------------
        self.inspector = QVBoxLayout()

        self.name_label = QLabel("Unset")
        self.inspector.addWidget(self.name_label)
        self.zone: LayoutZone | None = None

        # Stage 1: Region
        region_box = QGroupBox("1. Region")
        region_layout = QVBoxLayout(region_box)
        self.region_stack = QStackedWidget()

        self.priority_region_page = QWidget()
        priority_form = QFormLayout(self.priority_region_page)
        priority_form.setContentsMargins(0, 0, 0, 0)
        self.priority_number = QDoubleSpinBox()
        self.priority_number.setRange(-100, 200)
        self.priority_number.setValue(0)
        priority_form.addRow("Priority Value:", self.priority_number)
        self.region_stack.addWidget(self.top_region_bezel_page)

        self.top_region_bezel_page = QWidget()
        top_bezel_form = QFormLayout(self.top_region_bezel_page)
        top_bezel_form.setContentsMargins(0, 0, 0, 0)
        self.top_reg_bezel_dp_thickness = QDoubleSpinBox()
        self.top_reg_bezel_dp_thickness.setValue(BEZEL_DP_THICKNESS)
        self.top_reg_bezel_dp_thickness.setRange(2, 100)
        self.top_reg_bezel_dp_thickness.setSuffix(" dp")
        top_bezel_form.addRow(
            "Top Bezel DP Thickness:", self.top_reg_bezel_dp_thickness
        )
        self.region_stack.addWidget(self.top_region_bezel_page)

        self.bottom_region_bezel_page = QWidget()
        bottom_bezel_form = QFormLayout(self.bottom_region_bezel_page)
        bottom_bezel_form.setContentsMargins(0, 0, 0, 0)
        self.bottom_reg_bezel_dp_thickness = QDoubleSpinBox()
        self.bottom_reg_bezel_dp_thickness.setRange(2, 100)
        self.bottom_reg_bezel_dp_thickness.setValue(BEZEL_DP_THICKNESS)
        self.bottom_reg_bezel_dp_thickness.setSuffix(" dp")
        bottom_bezel_form.addRow(
            "Bottom Bezel DP Thickness:", self.bottom_reg_bezel_dp_thickness
        )
        self.region_stack.addWidget(self.bottom_region_bezel_page)

        region_layout.addWidget(self.region_stack)
        self.inspector.addWidget(region_box)

        # Stage 4: Transformation
        transform_box = QGroupBox("4. Transformation")
        transform_layout = QVBoxLayout(transform_box)
        self.transform_stack = QStackedWidget()

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

        self.trans_joy_page = QWidget()
        joy_form = QFormLayout(self.trans_joy_page)
        joy_form.setContentsMargins(0, 0, 0, 0)
        self.trans_joy_deadzone = QDoubleSpinBox()
        self.trans_joy_deadzone.setRange(0, 1)
        self.trans_joy_deadzone.setValue(0.1)
        self.trans_joy_hysteresis = QDoubleSpinBox()
        self.trans_joy_hysteresis.setRange(0, 45)
        self.trans_joy_hysteresis.setValue(5.0)
        self.trans_joy_hysteresis.setSuffix("°")

        joy_form.addRow("Deadzone:", self.trans_joy_deadzone)
        joy_form.addRow("Hysteresis:", self.trans_joy_hysteresis)
        self.transform_stack.addWidget(self.trans_joy_page)

        transform_layout.addWidget(self.transform_stack)
        self.inspector.addWidget(transform_box)

        # Stage 5: Semantics / Output
        semantic_box = QGroupBox("5. Semantics & Output")
        semantic_form = QFormLayout(semantic_box)
        self.is_pointer_btn_check = QCheckBox("Output is Pointer Button")
        semantic_form.addRow("Pointer enabled", self.is_pointer_btn_check)
        self.inspector.addWidget(semantic_box)

        # Action Buttons
        btn_action_row = QHBoxLayout()
        self.reset_defaults_btn = QPushButton("Reset Zone to App Defaults")
        self.save_pipeline_btn = QPushButton("Save Pipeline to Active Layout")
        btn_action_row.addWidget(self.reset_defaults_btn)
        btn_action_row.addWidget(self.save_pipeline_btn)
        self.inspector.addLayout(btn_action_row)

        self.inspector.addStretch()
        body_layout.addLayout(self.inspector, stretch=2)
        self.content_layout().addLayout(body_layout)

        self._wire_internal_signals()
        self.load_active_layout_zones()

    def on_page_shown(self) -> None:
        self.load_active_layout_zones()

    def _wire_internal_signals(self) -> None:
        self.save_pipeline_btn.clicked.connect(self._on_save_pipeline)
        self.reset_defaults_btn.clicked.connect(
            self._reset_current_zone_to_app_settings
        )
        self.reset_all_btn.clicked.connect(self._on_reset_all_zones)
        self.pipeline_list.itemSelectionChanged.connect(self._on_zone_selected)
        self.ignore_app_settings_btn.toggled.connect(
            self._on_toggle_ignore_app_settings
        )
        self.is_pointer_btn_check.toggled.connect(self._on_toggle_pointer_btn_check)

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

    def _get_existing_singleton_zone_id(self, sem_mode: str) -> int | None:
        """Finds if a singleton zone already exists in the active layout."""

        for zone in store.get_active_layout_zones():
            zone.set_parsed_config_from_json()

            semantic = zone.CONFIG_HELPER.get_semantic_config()
            _, semantic_mode, _ = semantic

            if semantic_mode == sem_mode:
                return zone.id

        return None

    def _get_pipeline_dict(self, zone: LayoutZone) -> dict:
        active = store.get_active_layout()
        inner_r = active.mouse_wheel_radius if active else 50.0

        if zone.scancode == str(TOP_BEZEL_ID):
            bezel_dp_thickness_value = self.top_reg_bezel_dp_thickness.value()
        elif zone.scancode == str(BOTTOM_BEZEL_ID):
            bezel_dp_thickness_value = self.bottom_reg_bezel_dp_thickness.value()
        else:
            bezel_dp_thickness_value = float(BEZEL_DP_THICKNESS)

        zone.CONFIG_HELPER.set_region_config(None, bezel_dp_thickness_value)

        zone.CONFIG_HELPER.set_transform_config(
            None,
            self.trans_sens_x.value(),
            self.trans_sens_y.value(),
            self.trans_joy_deadzone.value() * inner_r,
            self.trans_joy_hysteresis.value(),
        )

        zone.CONFIG_HELPER.set_semantic_config(
            None, self.is_pointer_btn_check.isChecked()
        )

        return zone.CONFIG_HELPER.pipeline_config

    def _reset_current_zone_to_app_settings(self) -> None:
        if self.zone is None:
            return

        settings = store.settings.get()
        self.zone.set_parsed_config_from_json
        sem_idx, _, _ = self.zone.CONFIG_HELPER.get_semantic_config()

        if sem_idx == 1:  # DIRECTIONAL
            self.trans_joy_deadzone.setValue(settings.deadzone)
            self.trans_joy_hysteresis.setValue(settings.hysteresis)

        elif sem_idx in (0, 2):  # BUTTON / POINTER
            self.trans_sens_x.setValue(settings.sensitivity_x)
            self.trans_sens_y.setValue(settings.sensitivity_y)

        QMessageBox.information(
            self,
            "Reset Applied",
            "self.inspector fields repopulated with active AppSettings. Click 'Save Pipeline' to commit.",
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

    def _on_zone_selected(self) -> None:
        items = self.pipeline_list.selectedItems()
        if not items:
            return
        zone_id = items[0].data(Qt.ItemDataRole.UserRole)

        zone = store.zones.get(zone_id)
        self.zone = zone
        if not zone:
            return

        self.name_label.setText(zone.name)
        self.ignore_app_settings_btn.setChecked(zone.ignore_app_settings)

        zone.set_parsed_config_from_json()

        _, _, bezel_dp_thickness, priority = zone.CONFIG_HELPER.get_region_config()
        self.priority_number.setValue(priority)

        if zone.zone_type == BEZEL:
            if zone.scancode == str(TOP_BEZEL_ID):
                self.top_reg_bezel_dp_thickness.setValue(bezel_dp_thickness)
            elif zone.scancode == str(BOTTOM_BEZEL_ID):
                self.bottom_reg_bezel_dp_thickness.setValue(bezel_dp_thickness)

        _, _, sens_x, sens_y, dz, hys = zone.CONFIG_HELPER.get_transform_config()
        self.trans_sens_x.setValue(sens_x)
        self.trans_sens_y.setValue(sens_y)
        self.trans_joy_deadzone.setValue(dz)
        self.trans_joy_hysteresis.setValue(hys)

        _, sem_mode, pointer = zone.CONFIG_HELPER.get_semantic_config()

        if sem_mode == "BUTTON":
            self.is_pointer_btn_check.setEnabled(True)
            self.is_pointer_btn_check.setChecked(pointer)
        else:
            self.is_pointer_btn_check.setEnabled(False)

    def _on_save_pipeline(self) -> None:
        active_layout = store.get_active_layout()
        if not active_layout:
            QMessageBox.warning(
                self,
                "No Active Layout",
                "Please set an active layout before saving pipelines.",
            )
            return

        selected = self.pipeline_list.selectedItems()
        current_zone_id = (
            selected[0].data(Qt.ItemDataRole.UserRole) if selected else None
        )

        if current_zone_id is None:
            return

        zone = store.zones.get(current_zone_id)
        self.zone = zone

        if zone is None:
            return

        zone.set_parsed_config_from_json()

        _, sem_mode, _ = zone.CONFIG_HELPER.get_semantic_config()
        # Enforce single movement joystick and single mouse look zone
        if sem_mode in ("DIRECTIONAL", "POINTER"):
            existing_id = self._get_existing_singleton_zone_id(sem_mode)
            if existing_id is not None and existing_id != current_zone_id:
                entity = (
                    "directional joystick"
                    if sem_mode == "DIRECTIONAL"
                    else "look area mouse pointer"
                )
                QMessageBox.warning(
                    self,
                    "Singleton Rule Violation",
                    f"A {entity} already exists in this layout.\nYou cannot create a second one.",
                )
                return

        serialized_json = zone.CONFIG_HELPER.get_pipeline_json_from_config(
            self._get_pipeline_dict(zone)
        )

        store.zones.update(
            current_zone_id,
            pipeline_json=serialized_json,
        )
        logger.info(
            "Updated pipeline zone ID %s ('%s')",
            current_zone_id,
            zone.name,
        )

        self.load_active_layout_zones()
        if self.dispatcher:
            self.dispatcher.dispatch(MapperEvent(action="ON_LAYOUT_RELOAD"))

        QMessageBox.information(
            self, "Saved", "Pipeline saved and synced to active layout."
        )

        self.zone = None

    def _on_toggle_ignore_app_settings(self, checked: bool) -> None:
        if self.zone is None:
            return

        if checked:
            self.inspector.setEnabled(False)

        else:
            self.inspector.setEnabled(True)

        store.zones.update(
            self.zone.id,
            ignore_app_settings=checked,
        )

        logger.info(
            "Updated pipeline zone ID %s ('%s')",
            self.zone.id,
            self.zone.name,
        )

        if self.dispatcher:
            self.dispatcher.dispatch(MapperEvent(action="ON_LAYOUT_RELOAD"))

        QMessageBox.information(
            self,
            "Toggled",
            f"Ignore app settings for selected zone set to {checked} and synced.",
        )

    def _on_toggle_pointer_btn_check(self, checked: bool) -> None:
        if self.zone is None:
            return

        self.zone.CONFIG_HELPER.set_semantic_config(None, checked)

        logger.info(
            "Updated pipeline zone ID %s ('%s')",
            self.zone.id,
            self.zone.name,
        )

        if self.dispatcher:
            self.dispatcher.dispatch(MapperEvent(action="ON_LAYOUT_RELOAD"))

        QMessageBox.information(
            self,
            "Toggled",
            f"Pointer boolean for zone set to {checked} and synced.",
        )

    @staticmethod
    def _pair_spins(spin_a: QDoubleSpinBox, spin_b: QDoubleSpinBox) -> QWidget:
        wrapper = QWidget()
        row = QHBoxLayout(wrapper)
        row.setContentsMargins(0, 0, 0, 0)
        row.addWidget(spin_a)
        row.addWidget(spin_b)
        return wrapper
