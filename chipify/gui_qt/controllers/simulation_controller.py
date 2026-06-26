# Copyright (c) 2026 Santiago Hofwimmer
"""
simulation_controller.py – Qt simulation lifecycle (start / progress / stop).

Owns the :class:`QThread` + :class:`SimWorker`, translates the worker's Qt
signals into ``AppState`` mutations and status-bar updates, and enforces the
abort-flag contract on Stop. Same responsibilities as the former CustomTkinter
simulation controller; the queue/``after()`` plumbing is gone because
cross-thread Qt signals marshal to the GUI thread on their own.
"""
from __future__ import annotations

import logging
import os
from typing import TYPE_CHECKING

from PySide6.QtCore import QObject, QThread

from chipify import app_config, settings, util
from chipify.gui_qt import theme
from chipify.gui_qt.workers.sim_worker import SimWorker

if TYPE_CHECKING:
    from chipify.gui_qt.main_window import MainWindow

log = logging.getLogger("chipify.gui_qt.controllers.simulation")

_GREEN = "#2ecc71"
_BLUE = theme.ACCENT
_ORANGE = "#e67e22"
_RED = theme.DANGER


class SimulationController(QObject):
    """Drives a Monte-Carlo simulation run from the Qt GUI."""

    def __init__(self, window: "MainWindow") -> None:
        super().__init__(window)
        self.window = window
        self.app_state = window.app_state
        self._thread: QThread | None = None
        self._worker: SimWorker | None = None

    # ── Start ─────────────────────────────────────────────────────────────────

    def start(self) -> None:
        """Validate the selection and launch the worker thread."""
        if self._thread is not None:
            return  # a run is already in flight
        selected = self.window.datasheet_combo.currentText()
        if not selected or selected == self.window.NO_DATASHEETS:
            return
        yaml_path = os.path.join(settings.IN_DIR, selected)
        log.info("SimulationController.start: %s", selected)

        # Persist any unsaved editor edits so the sweep runs against what the
        # user currently sees. Cancel the run if those edits aren't valid YAML.
        editor = getattr(self.window, "editor_tab", None)
        if editor is not None and not editor.autosave_for_run(yaml_path):
            return

        self.app_state.clear_partial()
        self.app_state.simulation_active = True
        try:
            self.app_state.current_stim = util.Stimuli(yaml_path)
        except Exception as exc:  # noqa: BLE001
            log.warning("Could not preload Stimuli for live state: %s", exc)

        live = app_config.is_live_plotting_enabled()
        self.window.set_running_ui(True)
        self.window.progress_bar.setValue(0)
        self.window.set_status("Initializing cores…", "yellow")

        self._thread = QThread(self)
        self._worker = SimWorker(yaml_path, live)
        self._worker.moveToThread(self._thread)

        self._thread.started.connect(self._worker.run)
        self._worker.progress.connect(self._on_progress)
        if live:
            self._worker.chunk_ready.connect(self.app_state.append_results)
        self._worker.finished.connect(self._on_finished)
        self._worker.failed.connect(self._on_failed)
        self._worker.done.connect(self._on_done)

        self._thread.start()

    # ── Stop ──────────────────────────────────────────────────────────────────

    def stop(self) -> None:
        """Request cancellation (writes the abort flag via the worker)."""
        if self._worker is None:
            return
        log.info("SimulationController.stop: abort requested.")
        self._worker.request_stop()
        self.window.set_status("Canceling simulation…", _ORANGE)
        self.window.btn_stop.setEnabled(False)

    # ── Worker signal slots (main thread) ─────────────────────────────────────

    def _on_progress(self, current: int, total: int) -> None:
        pct = int(current / total * 100) if total else 0
        self.window.progress_bar.setValue(pct)
        self.window.set_status(f"Simulating… {current}/{total}", _BLUE)

    def _on_finished(self, df: object, stim: object, elapsed: float) -> None:
        self.app_state.current_stim = stim
        self.app_state.last_sim_duration_sec = elapsed
        self.app_state.promote_partial(final_df=df, emit=False)
        self.window.show_results(df, stim, switch_tab=True)
        self.window.set_status(f"Completed in {elapsed:.1f}s", _GREEN)
        self.window.refresh_history(select_latest=True)

    def _on_failed(self, message: str) -> None:
        self.window.set_status("Error / Aborted!", _RED)
        self.window.show_error(message)

    def _on_done(self) -> None:
        """Final teardown on any exit path (success, abort, or error)."""
        self.app_state.simulation_active = False
        self.app_state.clear_partial()
        self.window.set_running_ui(False)
        self._teardown_thread()

    def _teardown_thread(self) -> None:
        thread, self._thread = self._thread, None
        worker, self._worker = self._worker, None
        if thread is not None:
            thread.quit()
            thread.wait()
            thread.deleteLater()
        if worker is not None:
            worker.deleteLater()
