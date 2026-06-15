# Copyright (c) 2026 Santiago Hofwimmer
"""
history_controller.py – Qt run-history dropdown + CSV loading.

Delegates all data I/O to the shared, framework-agnostic
``chipify.gui.services.data_loader`` (reused unchanged) and pushes loaded runs
into the window via ``show_results``.
"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from PySide6.QtCore import QObject

from chipify import settings, util
from chipify.gui.services import data_loader as _dl

if TYPE_CHECKING:
    from chipify.gui_qt.main_window import MainWindow

log = logging.getLogger("chipify.gui_qt.controllers.history")

NO_RUNS = "No runs found"


class HistoryController(QObject):
    """Controls the run-history combo box and CSV loading."""

    def __init__(self, window: "MainWindow") -> None:
        super().__init__(window)
        self.window = window

    def refresh(self, select_latest: bool = False) -> None:
        """Repopulate the history combo for the currently selected datasheet."""
        combo = self.window.history_combo
        yaml_path = self.window.current_yaml_path
        yaml_name = None
        if yaml_path:
            import os
            yaml_name = os.path.basename(yaml_path)

        runs = _dl.list_history_runs(settings.OUT_DIR, yaml_name=yaml_name)

        combo.blockSignals(True)
        combo.clear()
        combo.addItems(runs if runs else [NO_RUNS])
        if runs and select_latest:
            combo.setCurrentIndex(0)
        combo.blockSignals(False)

    def auto_load_latest(self) -> None:
        """Load the newest run on startup if a datasheet is selected."""
        combo = self.window.history_combo
        if combo.count() and combo.itemText(0) != NO_RUNS and self.window.current_yaml_path:
            self.on_select(combo.itemText(0), switch_tab=False)
            self.window.set_status("Auto-loaded last run.", "#3484F0")

    def on_select(self, label: str, switch_tab: bool = True) -> None:
        """Load the CSV for *label* and refresh the UI."""
        if not label or label == NO_RUNS or not self.window.current_yaml_path:
            return
        csv_path = _dl.resolve_csv_path(label, settings.OUT_DIR)
        if csv_path is None:
            return
        try:
            df = _dl.load_csv(csv_path)
            stim = util.Stimuli(self.window.current_yaml_path)
        except Exception as exc:  # noqa: BLE001
            log.warning("Could not load run %s: %s", label, exc)
            self.window.set_status(f"Could not load {label}", "#e74c3c")
            return
        self.window.show_results(df, stim, switch_tab=switch_tab)
        self.window.set_status(f"Loaded {label}", "#2ecc71")
