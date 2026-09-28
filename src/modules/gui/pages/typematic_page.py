from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Sequence

from PySide6.QtWidgets import (
    QCheckBox,
    QDoubleSpinBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from modules.database import store
from modules.utils import MapperEvent, EXCLUDED_KEYS
from .base_page import BasePage

if TYPE_CHECKING:
    from modules.utils import MapperEventDispatcher

logger = logging.getLogger("modules.gui.typematic_page")


class TypematicPage(BasePage):
    """Configuration GUI for keyboard repeat (typematic) behavior, rate limiting,

    and non-spamming/excluded key management.
    """

    title = "Typematic"

    def __init__(
        self,
        dispatcher: MapperEventDispatcher | None = None,
        parent: QWidget | None = None,
    ):
        super().__init__(dispatcher, parent)

        main_layout = QVBoxLayout()

        # -------------------------------------------------------------
        # 1. Master Toggle & Timing Parameters
        # -------------------------------------------------------------
        timing_group = QGroupBox("Auto-Repeat (Typematic) Timing")
        timing_form = QFormLayout(timing_group)

        self.enable_check = QCheckBox("Enable Hardware/Virtual Typematic Repeat")
        self.enable_check.setToolTip(
            "When enabled, holding down mapped keys generates repeating strike events."
        )
        timing_form.addRow(self.enable_check)

        self.delay_spin = QSpinBox()
        self.delay_spin.setRange(50, 2000)
        self.delay_spin.setSingleStep(25)
        self.delay_spin.setValue(250)
        self.delay_spin.setSuffix(" ms")
        self.delay_spin.setToolTip(
            "Initial delay between holding a key down and the start of repeat strikes."
        )
        timing_form.addRow("Initial Repeat Delay:", self.delay_spin)

        self.rate_spin = QDoubleSpinBox()
        self.rate_spin.setRange(1.0, 120.0)
        self.rate_spin.setSingleStep(1.0)
        self.rate_spin.setValue(30.0)
        self.rate_spin.setSuffix(" Hz (events/sec)")
        self.rate_spin.setToolTip("Repeat frequency once auto-repeat starts.")
        timing_form.addRow("Typematic Repeat Speed:", self.rate_spin)

        main_layout.addWidget(timing_group)

        # -------------------------------------------------------------
        # 2. Non-Spamming / Excluded Keys Manager
        # -------------------------------------------------------------
        filter_group = QGroupBox("Non-Spamming Keys (Single-Stroke Only)")
        filter_layout = QVBoxLayout(filter_group)

        info_label = QLabel(
            "Keys listed below will NOT auto-repeat when held down. "
            "Essential for directional movement (WASD) and modifier keys (Shift, Ctrl, Alt) "
            "to prevent event buffer saturation."
        )
        info_label.setWordWrap(True)
        info_label.setStyleSheet(
            "color: palette(placeholder-text); margin-bottom: 4px;"
        )
        filter_layout.addWidget(info_label)

        # Token input row
        input_row = QHBoxLayout()
        self.new_key_edit = QLineEdit()
        self.new_key_edit.setPlaceholderText(
            "Enter key token (e.g. w, space, shift, q)..."
        )
        self.add_key_btn = QPushButton("Add Excluded Key")
        self.remove_key_btn = QPushButton("Remove Selected")

        input_row.addWidget(self.new_key_edit)
        input_row.addWidget(self.add_key_btn)
        input_row.addWidget(self.remove_key_btn)
        filter_layout.addLayout(input_row)

        # Quick preset buttons for common exclusions
        preset_row = QHBoxLayout()
        self.add_wasd_preset_btn = QPushButton("+ WASD Movement")
        self.clear_all_btn = QPushButton("Clear List")

        preset_row.addWidget(self.add_wasd_preset_btn)
        preset_row.addStretch()
        preset_row.addWidget(self.clear_all_btn)
        filter_layout.addLayout(preset_row)

        self.exclude_list = QListWidget()
        filter_layout.addWidget(self.exclude_list)

        main_layout.addWidget(filter_group)

        # -------------------------------------------------------------
        # 3. Action Buttons
        # -------------------------------------------------------------
        btn_row = QHBoxLayout()
        self.reset_defaults_btn = QPushButton("Reset Typematic Defaults")
        self.save_btn = QPushButton("Save Settings")
        self.save_btn.setDefault(True)

        btn_row.addWidget(self.reset_defaults_btn)
        btn_row.addStretch()
        btn_row.addWidget(self.save_btn)
        main_layout.addLayout(btn_row)

        self.content_layout().addLayout(main_layout)

        self._wire_signals()
        self.load_settings()

    def on_page_shown(self) -> None:
        self.load_settings()

    def _wire_signals(self) -> None:
        self.enable_check.toggled.connect(self._on_enable_toggled)
        self.add_key_btn.clicked.connect(self._on_add_key)
        self.remove_key_btn.clicked.connect(self._on_remove_selected_key)
        self.new_key_edit.returnPressed.connect(self._on_add_key)

        self.add_wasd_preset_btn.clicked.connect(
            lambda: self._add_tokens(["w", "a", "s", "d"])
        )
        self.clear_all_btn.clicked.connect(self.exclude_list.clear)

        self.reset_defaults_btn.clicked.connect(self._on_reset_defaults)
        self.save_btn.clicked.connect(self._on_save_settings)

    def _on_enable_toggled(self, checked: bool) -> None:
        self.delay_spin.setEnabled(checked)
        self.rate_spin.setEnabled(checked)

    def load_settings(self) -> None:
        try:
            s = store.settings.get()

            enabled = bool(getattr(s, "typematic_enabled", True))
            delay = int(getattr(s, "typematic_delay_ms", 250.0))
            rate = float(getattr(s, "typematic_rate_hz", 30.0))
            raw_excludes = str(
                getattr(s, "typematic_EXCLUDED_KEYS", f"{EXCLUDED_KEYS}")
            )

            self.enable_check.setChecked(enabled)
            self.delay_spin.setValue(delay)
            self.rate_spin.setValue(rate)
            self._on_enable_toggled(enabled)

            self.exclude_list.clear()
            for token in [
                k.strip().lower() for k in raw_excludes.split(",") if k.strip()
            ]:
                self.exclude_list.addItem(QListWidgetItem(token))

        except Exception as exc:
            logger.exception("Failed to load typematic settings")
            QMessageBox.critical(self, "Error", f"Failed to load settings:\n{exc}")

    def _add_tokens(self, tokens: Sequence[str]) -> None:
        existing = {
            self.exclude_list.item(i).text().lower()
            for i in range(self.exclude_list.count())
        }
        for tok in tokens:
            cleaned = tok.strip().lower()
            if cleaned and cleaned not in existing:
                self.exclude_list.addItem(QListWidgetItem(cleaned))
                existing.add(cleaned)

    def _on_add_key(self) -> None:
        raw_text = self.new_key_edit.text().strip()
        if not raw_text:
            return
        tokens = [k.strip() for k in raw_text.split(",") if k.strip()]
        self._add_tokens(tokens)
        self.new_key_edit.clear()

    def _on_remove_selected_key(self) -> None:
        selected_items = self.exclude_list.selectedItems()
        for item in selected_items:
            row = self.exclude_list.row(item)
            self.exclude_list.takeItem(row)

    def _on_reset_defaults(self) -> None:
        self.enable_check.setChecked(True)
        self.delay_spin.setValue(250)
        self.rate_spin.setValue(30.0)
        self._on_enable_toggled(True)
        self.exclude_list.clear()
        self._add_tokens(EXCLUDED_KEYS.split(","))
        QMessageBox.information(
            self,
            "Defaults",
            "Typematic defaults restored. Click 'Save Settings' to apply.",
        )

    def _on_save_settings(self) -> None:
        try:
            tokens = [
                self.exclude_list.item(i).text().strip().lower()
                for i in range(self.exclude_list.count())
            ]
            serialized_keys = ",".join(
                dict.fromkeys(tokens)
            )  # Deduplicate preserving order

            store.settings.update(
                typematic_enabled=int(self.enable_check.isChecked()),
                typematic_delay_ms=float(self.delay_spin.value()),
                typematic_rate_hz=float(self.rate_spin.value()),
                typematic_EXCLUDED_KEYS=serialized_keys,
            )

            if self.dispatcher:
                self.dispatcher.dispatch(MapperEvent(action="ON_CONFIG_RELOAD"))

            logger.info("Typematic settings committed: %d keys excluded", len(tokens))
            QMessageBox.information(
                self, "Saved", "Typematic and repeat settings saved successfully."
            )
        except Exception as exc:
            logger.exception("Failed to save typematic settings")
            QMessageBox.critical(self, "Database Error", str(exc))
