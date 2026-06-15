# Copyright (c) 2026 Santiago Hofwimmer
"""
sim_worker.py – Background simulation worker (runs on a QThread).

A :class:`SimWorker` is moved onto a :class:`~PySide6.QtCore.QThread`; its
``run`` slot executes the full sweep via :func:`chipify.simulator.run_sim`,
persists the results / history / metadata (off the GUI thread), and reports
back purely through Qt signals. Because the signals are delivered with a
queued connection across the thread boundary, the controller's slots run on
the main thread automatically — this is what replaces the legacy
``MainThreadBridge`` queue+``after()`` plumbing.

Cancellation keeps the original abort contract: the GUI thread calls
``request_stop()``, which both trips a local flag (so the next progress tick
raises ``InterruptedError`` and unwinds ``run_sim``) and writes the file-based
abort flag via :func:`chipify.simulator.abort_simulation`.
"""
from __future__ import annotations

import datetime
import logging
import os
import threading
import time

import numpy as np
from PySide6.QtCore import QObject, Signal, Slot

from chipify import run_meta, settings, simulator, util
from chipify.gui.services import netlist_export

log = logging.getLogger("chipify.gui_qt.sim_worker")


class SimWorker(QObject):
    """Runs one Monte-Carlo / corner sweep and emits progress + results."""

    #: ``(current, total)`` progress ticks (worker thread → queued to GUI).
    progress = Signal(int, int)
    #: A partial results DataFrame for live plotting (only when enabled).
    chunk_ready = Signal(object)
    #: Successful completion: ``(df, stim, elapsed_seconds)``.
    finished = Signal(object, object, float)
    #: Unhandled error: human-readable message.
    failed = Signal(str)
    #: Always emitted last, on every exit path, so the thread can be torn down.
    done = Signal()

    def __init__(self, yaml_path: str, live_plotting: bool) -> None:
        super().__init__()
        self._yaml_path = yaml_path
        self._live = live_plotting
        self._stop = threading.Event()

    # ── Called from the GUI thread ────────────────────────────────────────────

    def request_stop(self) -> None:
        """Cancel the run (abort flag + cooperative progress-tick interrupt)."""
        log.info("SimWorker.request_stop: abort requested.")
        self._stop.set()
        simulator.abort_simulation()  # writes FAST_TMP/abort.flag (per-project)

    # ── Worker-thread callbacks passed into run_sim ───────────────────────────

    def _progress_cb(self, current: int, total: int) -> None:
        if self._stop.is_set():
            raise InterruptedError("Simulation canceled!")
        self.progress.emit(current, total)

    def _chunk_cb(self, chunk_df: object) -> None:
        self.chunk_ready.emit(chunk_df)

    # ── Thread body ───────────────────────────────────────────────────────────

    @Slot()
    def run(self) -> None:
        """Execute the sweep; emit ``finished`` / ``failed`` then ``done``."""
        log.info("SimWorker.run on thread %s", threading.current_thread().name)
        t0 = time.perf_counter()
        try:
            stim = util.Stimuli(self._yaml_path)
            df = simulator.run_sim(
                stim,
                progress_callback=self._progress_cb,
                chunk_callback=self._chunk_cb if self._live else None,
            )
            if df is None:
                log.info("run_sim returned None (aborted or error).")
                return

            elapsed = max(0.0, time.perf_counter() - t0)
            if len(df) > 0:
                df["simulation_duration_s_total"] = np.nan
                df.at[df.index[0], "simulation_duration_s_total"] = elapsed
            log.info("run_sim returned %d rows. Saving results…", len(df))
            self._persist(df, stim, elapsed)
            self.finished.emit(df, stim, elapsed)

        except InterruptedError:
            log.info("SimWorker.run stopped (user cancel).")
        except Exception as exc:  # noqa: BLE001 — report any failure to the GUI
            log.exception("SimWorker.run failed: %s", exc)
            self.failed.emit(str(exc))
        finally:
            self.done.emit()

    # ── Persistence (off the GUI thread) ──────────────────────────────────────

    def _persist(self, df, stim, elapsed: float) -> None:
        """Write the live CSV, archive a history copy, and emit meta sidecars."""
        csv_out = os.path.join(settings.OUT_DIR, "simulation_results.csv")
        df.to_csv(csv_out, index=False)

        analysis_dirs = df.attrs.get("analysis_dirs", {}) or {}
        simulator.write_analysis_pointers(analysis_dirs)

        try:
            history_dir = os.path.join(settings.OUT_DIR, "history")
            os.makedirs(history_dir, exist_ok=True)
            timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
            history_file = os.path.join(history_dir, f"run_{timestamp}.csv")
            df.to_csv(history_file, index=False)

            total = len(df)
            valid = (
                int((df.get("sim_error", "None") == "None").sum())
                if "sim_error" in df.columns else total
            )
            gpass = int(df["global_pass"].sum()) if "global_pass" in df.columns else None
            gyield = (gpass / total * 100) if (gpass is not None and total > 0) else None

            try:
                templates_dir = netlist_export.persist_templates(
                    stim, os.path.join(history_dir, f"run_{timestamp}_templates"),
                )
            except Exception as exc:  # noqa: BLE001
                log.warning("Could not persist netlist templates: %s", exc)
                templates_dir = ""

            meta_kwargs = dict(
                yaml_name=os.path.basename(self._yaml_path),
                duration_s=elapsed,
                total_runs=total,
                valid_runs=valid,
                global_yield=gyield,
                tran_dir=df.attrs.get("tran_dir", ""),
                analysis_dirs=analysis_dirs,
                templates_dir=templates_dir,
            )
            run_meta.write_meta(history_file, **meta_kwargs)
            run_meta.write_meta(csv_out, **meta_kwargs)
        except Exception as exc:  # noqa: BLE001
            log.warning("Could not save history: %s", exc)
