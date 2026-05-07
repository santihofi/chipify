"""
history_controller.py – Manages run-history loading and CSV selection.

Wraps the history-management methods formerly on SimifyGUI, delegating
all data I/O to ``data_loader`` and all UI updates to ``app``.
"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from chipify import settings, util
from chipify.gui.services import data_loader as _dl

if TYPE_CHECKING:
    pass

log = logging.getLogger("chipify.gui.controllers.history")


class HistoryController:
    """
    Controls the run-history dropdown and CSV loading.

    Parameters
    ----------
    app:
        The ``SimifyGUI`` main-window instance.
    """

    def __init__(self, app: object) -> None:
        self.app = app

    def refresh_history(self) -> None:
        """Re-populate the history dropdown from the output directory."""
        app = self.app  # type: ignore[attr-defined]
        runs = _dl.list_history_runs(settings.OUT_DIR)
        if not runs:
            app.history_dropdown.configure(values=["No runs found"])
            app.history_dropdown.set("No runs found")
            app.compare_dropdown.configure(values=["None"])
            app.compare_dropdown.set("None")
        else:
            app.history_dropdown.configure(values=runs)
            app.history_dropdown.set(runs[0])
            comp_runs = ["None"] + runs
            app.compare_dropdown.configure(values=comp_runs)
            app.compare_dropdown.set("None")

    def auto_load_latest_run(self) -> None:
        """Load the newest run automatically on startup if a YAML is selected."""
        app = self.app  # type: ignore[attr-defined]
        runs = app.history_dropdown.cget("values")
        if runs and runs[0] != "No runs found" and app.current_yaml_path:
            self.on_history_select(runs[0], switch_tab=False)
            app.lbl_status.configure(
                text="Status: Auto-loaded last run.", text_color="#3484F0"
            )

    def on_history_select(self, selection: str, switch_tab: bool = True) -> None:
        """Load a CSV from the history dropdown and refresh the UI."""
        app = self.app  # type: ignore[attr-defined]
        if not selection or selection == "No runs found" or not app.current_yaml_path:
            return
        csv_path = _dl.resolve_csv_path(selection, settings.OUT_DIR)
        if csv_path is None:
            return
        try:
            df = _dl.load_csv(csv_path)
            stim = util.Stimuli(app.current_yaml_path)
            app.lbl_current_run.configure(text=f"Viewing: {selection}")
            app.update_ui_results(df, stim, switch_tab=switch_tab)
            app.lbl_status.configure(
                text=f"Status: Loaded {selection}", text_color="#2ecc71"
            )
        except Exception as exc:
            from tkinter import messagebox
            messagebox.showwarning(
                "Load Error",
                f"Could not parse run data. Ensure the current Datasheet fits the old run.\n\n{exc}",
            )
