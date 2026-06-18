# Copyright (c) 2026 Santiago Hofwimmer
"""
settings_dialog.py – Preferences dialog (Qt).

Edits the same ``settings.json`` keys as the legacy CustomTkinter
``SettingsWindow`` (CPU cores, simulator engine + VACASK options, parallelism,
live plotting, theme, folder paths) via :mod:`chipify.app_config`. Folder-path
changes take effect on the next launch (paths are resolved at import); the
theme is applied immediately through the window's ``apply_theme``.
"""
from __future__ import annotations

import logging
import os
from typing import TYPE_CHECKING

from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLineEdit,
    QSpinBox,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from chipify import app_config
from chipify.gui_qt import theme as _theme
from chipify.gui_qt.widgets.helpers import autoclose_combo

if TYPE_CHECKING:
    from chipify.gui_qt.main_window import MainWindow

log = logging.getLogger("chipify.gui_qt.settings")


class SettingsDialog(QDialog):
    """Modal preferences editor backed by ``app_config``."""

    def __init__(self, window: "MainWindow") -> None:
        super().__init__(window)
        self._window = window
        self.setWindowTitle("Settings")
        self.setMinimumWidth(460)
        self._cfg = app_config.load_config()

        tabs = QTabWidget()
        tabs.addTab(self._build_simulation_tab(), "Simulation")
        tabs.addTab(self._build_performance_tab(), "Performance")
        tabs.addTab(self._build_interface_tab(), "Interface")
        tabs.addTab(self._build_paths_tab(), "Paths")
        for cb in self.findChildren(QComboBox):
            autoclose_combo(cb)

        buttons = QDialogButtonBox(
            QDialogButtonBox.Save | QDialogButtonBox.Cancel
        )
        buttons.accepted.connect(self._save)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addWidget(tabs)
        layout.addWidget(buttons)

    # ── Tabs ──────────────────────────────────────────────────────────────────

    def _build_simulation_tab(self) -> QWidget:
        w = QWidget()
        form = QFormLayout(w)

        max_cores = os.cpu_count() or 1
        self.cores_auto = QCheckBox("Auto-detect")
        self.cores_spin = QSpinBox()
        self.cores_spin.setRange(1, max_cores)
        cores = self._cfg.get("num_cores")
        if cores is None:
            self.cores_auto.setChecked(True)
            self.cores_spin.setEnabled(False)
            self.cores_spin.setValue(max_cores)
        else:
            self.cores_spin.setValue(int(cores))
        self.cores_auto.toggled.connect(lambda on: self.cores_spin.setEnabled(not on))
        form.addRow("CPU cores", self.cores_auto)
        form.addRow("", self.cores_spin)

        self.engine_combo = QComboBox()
        self.engine_combo.addItems(["ngspice", "vacask"])
        self.engine_combo.setCurrentText(self._cfg.get("simulator_engine", "ngspice"))
        form.addRow("Simulator engine", self.engine_combo)

        self.vacask_binary = QLineEdit(self._cfg.get("vacask_binary", "vacask"))
        form.addRow("VACASK binary", self.vacask_binary)
        self.vacask_src = QComboBox()
        self.vacask_src.addItems(["xschem", "ng2vc"])
        self.vacask_src.setCurrentText(self._cfg.get("vacask_netlist_source", "xschem"))
        form.addRow("VACASK netlist source", self.vacask_src)
        self.vacask_pdk = QLineEdit(self._cfg.get("vacask_pdk_dir", ""))
        form.addRow("VACASK PDK dir", self.vacask_pdk)
        return w

    def _build_performance_tab(self) -> QWidget:
        w = QWidget()
        form = QFormLayout(w)

        self.start_method = QComboBox()
        self.start_method.addItems(["auto", "forkserver", "spawn"])
        self.start_method.setCurrentText(self._cfg.get("process_start_method", "auto"))
        form.addRow("Process start method", self.start_method)

        self.chunk_spin = QSpinBox()
        self.chunk_spin.setRange(0, 256)
        self.chunk_spin.setSpecialValueText("Auto")  # 0 → "auto"
        chunk = self._cfg.get("chunk_size", "auto")
        self.chunk_spin.setValue(0 if str(chunk) == "auto" else int(chunk))
        form.addRow("Chunk size", self.chunk_spin)

        self.live_check = QCheckBox("Enable live plotting")
        self.live_check.setChecked(bool(self._cfg.get("live_plotting_enabled", False)))
        form.addRow(self.live_check)
        self.throttle_spin = QSpinBox()
        self.throttle_spin.setRange(500, 5000)
        self.throttle_spin.setSingleStep(100)
        self.throttle_spin.setValue(int(self._cfg.get("live_plot_throttle_ms", 1500)))
        form.addRow("Live redraw throttle (ms)", self.throttle_spin)
        self.stride_spin = QSpinBox()
        self.stride_spin.setRange(1, 1000)
        self.stride_spin.setValue(int(self._cfg.get("live_plot_emit_stride", 1)))
        form.addRow("Live emit stride (batches)", self.stride_spin)
        return w

    def _build_interface_tab(self) -> QWidget:
        w = QWidget()
        form = QFormLayout(w)
        self.theme_combo = QComboBox()
        self.theme_combo.addItems(_theme.available_themes())
        self.theme_combo.setCurrentText(self._cfg.get("theme", _theme.DEFAULT_THEME))
        form.addRow("Theme", self.theme_combo)

        self.font_spin = QSpinBox()
        self.font_spin.setRange(8, 20)
        self.font_spin.setSuffix(" px")
        self.font_spin.setValue(int(self._cfg.get("font_size", 13)))
        form.addRow("Font size", self.font_spin)
        return w

    def _build_paths_tab(self) -> QWidget:
        w = QWidget()
        form = QFormLayout(w)
        self.path_edits = {}
        for key, label in (
            ("in_dir", "Input datasheets"),
            ("out_dir", "Output"),
            ("work_dir", "Scratch / temp"),
            ("tb_dir", "Testbenches"),
        ):
            edit = QLineEdit(self._cfg.get(key) or "")
            edit.setPlaceholderText("(default)")
            self.path_edits[key] = edit
            form.addRow(label, edit)
        return w

    # ── Save ──────────────────────────────────────────────────────────────────

    def _save(self) -> None:
        cfg = app_config.load_config()
        cfg["num_cores"] = None if self.cores_auto.isChecked() else self.cores_spin.value()
        cfg["simulator_engine"] = self.engine_combo.currentText()
        cfg["vacask_binary"] = self.vacask_binary.text().strip() or "vacask"
        cfg["vacask_netlist_source"] = self.vacask_src.currentText()
        cfg["vacask_pdk_dir"] = self.vacask_pdk.text().strip()
        cfg["process_start_method"] = self.start_method.currentText()
        cfg["chunk_size"] = "auto" if self.chunk_spin.value() == 0 else str(self.chunk_spin.value())
        cfg["live_plotting_enabled"] = self.live_check.isChecked()
        cfg["live_plot_throttle_ms"] = self.throttle_spin.value()
        cfg["live_plot_emit_stride"] = self.stride_spin.value()
        for key, edit in self.path_edits.items():
            cfg[key] = edit.text().strip()

        cfg["theme"] = self.theme_combo.currentText()
        cfg["font_size"] = self.font_spin.value()

        app_config.save_config(cfg)
        # Re-apply theme + font size live.
        self._window.apply_appearance()
        self.accept()
