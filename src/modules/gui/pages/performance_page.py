from __future__ import annotations

from typing import TYPE_CHECKING
from PySide6.QtWidgets import QDoubleSpinBox, QFormLayout, QWidget

from modules.database import store
from modules.utils import MapperEvent
from .base_page import BasePage

if TYPE_CHECKING:
    from modules.utils import MapperEventDispatcher


class PerformancePage(BasePage):
    """Dynamic performance and rate-limiting manager backed by SQLite."""

    title = "Performance"

    def __init__(
        self,
        dispatcher: MapperEventDispatcher | None = None,
        parent=None,
    ):
        super().__init__(dispatcher, parent)

        form_widget = QWidget()
        form = QFormLayout(form_widget)

        self.rate_cap_spin = QDoubleSpinBox()
        self.rate_cap_spin.setRange(60.0, 1000.0)
        self.rate_cap_spin.setSingleStep(10.0)
        self.rate_cap_spin.setSuffix(" Hz")
        form.addRow("ADB Rate Cap:", self.rate_cap_spin)

        self.pps_spin = QDoubleSpinBox()
        self.pps_spin.setRange(30.0, 120.0)
        self.pps_spin.setSingleStep(5.0)
        self.pps_spin.setSuffix(" PPS")
        form.addRow("PPS Alert Threshold:", self.pps_spin)

        self.content_layout().addWidget(form_widget)
        self.content_layout().addStretch()

        self.rate_cap_spin.valueChanged.connect(self._on_rate_cap_changed)
        self.pps_spin.valueChanged.connect(self._on_pps_changed)

        self.load_performance_settings()

    def on_page_shown(self) -> None:
        self.load_performance_settings()

    def load_performance_settings(self) -> None:
        settings = store.settings.get()
        self.rate_cap_spin.blockSignals(True)
        self.pps_spin.blockSignals(True)

        self.rate_cap_spin.setValue(settings.adb_rate_cap)
        self.pps_spin.setValue(settings.pps_alert_threshold)

        self.rate_cap_spin.blockSignals(False)
        self.pps_spin.blockSignals(False)

    def _on_rate_cap_changed(self, val: float) -> None:
        store.settings.update(adb_rate_cap=val)
        if self.dispatcher:
            self.dispatcher.dispatch(MapperEvent(action="ON_CONFIG_RELOAD"))

    def _on_pps_changed(self, val: float) -> None:
        store.settings.update(pps_alert_threshold=val)
        if self.dispatcher:
            self.dispatcher.dispatch(MapperEvent(action="ON_CONFIG_RELOAD"))