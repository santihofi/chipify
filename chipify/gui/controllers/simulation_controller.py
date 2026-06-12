# Copyright (c) 2026 Santiago Hofwimmer
"""
simulation_controller.py – Orchestrates simulation start/stop.

Wraps the simulation core methods that formerly lived on SimifyGUI.
All Tk widget access goes through the ``app`` reference.

The abort flag contract (context.md §3):
    ``stop_simulation()`` must call ``simulator.abort_simulation()`` so that
    the file-based abort flag is written before any running sub-processes check
    for it.  This invariant is preserved below; do not remove that call.
"""
from __future__ import annotations

import datetime
import logging
import os
import queue
import threading
import time
from typing import TYPE_CHECKING

import numpy as np

from chipify import app_config, settings, simulator, util
from chipify.gui.services.main_thread_bridge import MainThreadBridge

if TYPE_CHECKING:
    pass  # avoid circular import

log = logging.getLogger("chipify.gui.controllers.simulation")


def _set_btn_start_ready(app: object) -> None:
    """Re-enable the start button after simulation completes or aborts."""
    # Import inside function to avoid early Tk init during import
    app_ = app  # type: ignore[attr-defined]
    if not app_.lbl_status.cget("text").startswith("Status: Completed in"):
        app_.lbl_status.configure(text="Status: Ready", text_color="#2ecc71")
    app_.btn_start.configure(state="normal")
    app_.btn_stop.configure(state="disabled")
    app_.btn_refresh.configure(state="normal")


class SimulationController:
    """
    Controls the full lifecycle of a Monte-Carlo simulation run.

    Parameters
    ----------
    app:
        The ``SimifyGUI`` main-window instance.  All Tk widget mutations
        are performed via ``app.after(0, …)`` to stay on the main thread.
    """

    def __init__(self, app: object) -> None:
        self.app = app
        self._bridge: MainThreadBridge | None = None
        self._live_plot_enabled_this_run: bool = False
        self._progress_queue: queue.Queue = queue.Queue()
        self._sim_running: threading.Event = threading.Event()

    def _chunk_callback(self, chunk_df: object) -> None:
        """Runs on simulation thread; forwards chunks to the UI bridge when live plotting is on."""
        if not self._live_plot_enabled_this_run:
            return
        bridge = self._bridge
        if bridge is not None:
            bridge.enqueue_chunk(chunk_df)

    def _thread_finalize_guard(self) -> None:
        """Main-thread cleanup when the worker thread exits (abort/error paths)."""
        app = self.app  # type: ignore[attr-defined]
        if self._bridge is not None:
            try:
                self._bridge.stop_polling()
            except Exception:
                log.exception("Bridge stop failed during finalize.")
            self._bridge = None
        try:
            if app.app_state.simulation_active:
                app.app_state.simulation_active = False
                app.app_state.clear_partial()
                for t in getattr(app, "_all_throttles", []):
                    t.cancel_pending()
                app.history_dropdown.configure(state="normal")
        except Exception:
            log.exception("Simulation finalize guard failed.")

    def _on_sim_success_main(self, df: object, stim: object, elapsed: float) -> None:
        """Ordered UI finalization after a successful run (main thread)."""
        app = self.app  # type: ignore[attr-defined]
        if self._bridge is not None:
            try:
                self._bridge.stop_polling()
            except Exception:
                log.exception("Bridge stop after simulation failed.")
            self._bridge = None
        for t in getattr(app, "_all_throttles", []):
            try:
                t.force_now()
            except Exception:
                pass
        try:
            app.history_dropdown.configure(state="normal")
        except Exception:
            pass
        app.app_state.current_stim = stim
        app.app_state.promote_partial(final_df=df, emit=False)
        app.update_ui_results(df, stim, True)
        app.lbl_current_run.configure(text="Viewing: Latest (simulation_results)")
        app.history_dropdown.set("Latest (simulation_results)")
        app.lbl_status.configure(
            text=f"Status: Completed in {elapsed:.1f}s",
            text_color="#2ecc71",
        )

    def start_simulation(self) -> None:
        """Called by the Start button.  Validates selection and spawns the thread."""
        app = self.app  # type: ignore[attr-defined]
        selected = app.yaml_dropdown.get()
        if not selected or selected == "No files found":
            return

        yaml_path = os.path.join(settings.IN_DIR, selected)
        log.info("SimulationController.start_simulation: %s", selected)

        try:
            while True:
                self._progress_queue.get_nowait()
        except queue.Empty:
            pass

        app.btn_start.configure(state="disabled")
        app.btn_refresh.configure(state="disabled")
        app.btn_stop.configure(state="normal")
        app.stop_event.clear()
        app.last_sim_duration_sec = None

        app.progress_bar.set(0)
        app.lbl_status.configure(text="Status: Initializing cores…", text_color="yellow")

        for item in app.tree.get_children():
            app.tree.delete(item)
        for widget in app.wc_scroll.winfo_children():
            widget.destroy()

        import customtkinter as ctk

        app.lbl_wc_empty = ctk.CTkLabel(app.wc_scroll, text="Simulating…", text_color="gray")
        app.lbl_wc_empty.pack(pady=50)

        app.app_state.clear_partial()
        app.app_state.simulation_active = True
        try:
            app.app_state.current_stim = util.Stimuli(yaml_path)
        except Exception as exc:
            log.warning("Could not preload Stimuli for live state: %s", exc)

        self._live_plot_enabled_this_run = app_config.is_live_plotting_enabled()
        if self._live_plot_enabled_this_run:
            self._bridge = MainThreadBridge(app, app.app_state)
            self._bridge.start_polling()
        else:
            self._bridge = None

        try:
            app.history_dropdown.configure(state="disabled")
        except Exception:
            pass

        self._sim_running.set()
        app.after(0, self._pump_progress_queue)

        threading.Thread(target=self.run_sim_thread, args=(yaml_path,), daemon=True).start()

    def _pump_progress_queue(self) -> None:
        """Apply latest progress on the Tk main thread (never touch Tk from run_sim thread)."""
        app = self.app  # type: ignore[attr-defined]
        latest = None
        try:
            while True:
                latest = self._progress_queue.get_nowait()
        except queue.Empty:
            pass
        if latest is not None:
            try:
                cur, tot = latest
                self._set_progress_ui(cur, tot)
            except Exception:
                log.exception("Progress UI update failed.")
        if self._sim_running.is_set():
            app.after(50, self._pump_progress_queue)

    def stop_simulation(self) -> None:
        """
        Called by the Stop button.

        Sets the threading stop-event AND calls ``simulator.abort_simulation()``
        to write the file-based abort flag (context.md §3).
        """
        app = self.app  # type: ignore[attr-defined]
        log.info("SimulationController.stop_simulation: abort requested.")
        app.stop_event.set()
        simulator.abort_simulation()  # writes FAST_TMP/abort.flag (per-project)
        app.lbl_status.configure(text="Status: Canceling simulation…", text_color="orange")
        app.btn_stop.configure(state="disabled")

    def progress_callback_wrapper(self, current: int, total: int) -> None:
        """Worker-thread callback; raises InterruptedError if stop requested."""
        app = self.app  # type: ignore[attr-defined]
        if app.stop_event.is_set():
            raise InterruptedError("Simulation canceled!")
        try:
            self._progress_queue.put_nowait((current, total))
        except Exception:
            pass

    def _set_progress_ui(self, current: int, total: int) -> None:
        """Must be called from the main thread via ``app.after()``."""
        app = self.app  # type: ignore[attr-defined]
        app.progress_bar.set(current / total)
        app.lbl_status.configure(
            text=f"Simulating… {current}/{total}", text_color="#3484F0"
        )

    def show_error(self, error_msg: str) -> None:
        """Display an error in the status bar and worst-case panel."""
        self._thread_finalize_guard()
        import customtkinter as ctk

        app = self.app  # type: ignore[attr-defined]
        app.lbl_status.configure(text="Status: Error / Aborted!", text_color="red")
        app.btn_start.configure(state="normal")
        app.btn_stop.configure(state="disabled")
        app.btn_refresh.configure(state="normal")
        for widget in app.wc_scroll.winfo_children():
            widget.destroy()
        ctk.CTkLabel(
            app.wc_scroll,
            text=f"LOG:\n{error_msg}",
            text_color="red",
            justify="left",
        ).pack(anchor="w", padx=20, pady=20)
        # The error panel lives on the Measurements tab — bring it into view.
        try:
            app.tabs.set("Measurements")
        except Exception:
            pass

    def run_sim_thread(self, yaml_path: str) -> None:
        """Worker-thread body: runs the simulation and saves results."""
        app = self.app  # type: ignore[attr-defined]
        log.info("run_sim_thread started. Thread: %s", threading.current_thread().name)
        t0 = time.perf_counter()
        try:
            stim = util.Stimuli(yaml_path)
            chunk_cb = (
                self._chunk_callback if self._live_plot_enabled_this_run else None
            )
            df = simulator.run_sim(
                stim,
                progress_callback=self.progress_callback_wrapper,
                chunk_callback=chunk_cb,
            )

            if df is not None:
                elapsed = max(0.0, time.perf_counter() - t0)
                app.last_sim_duration_sec = elapsed
                if len(df) > 0:
                    df["simulation_duration_s_total"] = np.nan
                    df.at[df.index[0], "simulation_duration_s_total"] = elapsed
                log.info("run_sim returned %d rows. Saving results…", len(df))

                csv_out = os.path.join(settings.OUT_DIR, "simulation_results.csv")
                df.to_csv(csv_out, index=False)

                # Write .latest pointers so the analysis tabs can resolve each
                # kind's data directory after a GUI restart.
                analysis_dirs = df.attrs.get("analysis_dirs", {}) or {}
                simulator.write_analysis_pointers(analysis_dirs)

                # Archive history run + write meta sidecar
                try:
                    from chipify import run_meta
                    from chipify.gui.services import netlist_export

                    history_dir = os.path.join(settings.OUT_DIR, "history")
                    os.makedirs(history_dir, exist_ok=True)
                    timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
                    history_file = os.path.join(history_dir, f"run_{timestamp}.csv")
                    df.to_csv(history_file, index=False)
                    total = len(df)
                    valid = int((df.get("sim_error", "None") == "None").sum()) if "sim_error" in df.columns else total
                    gpass = int(df["global_pass"].sum()) if "global_pass" in df.columns else None
                    gyield = (gpass / total * 100) if (gpass is not None and total > 0) else None
                    # Persist this run's netlist templates so per-sample
                    # exports from history stay faithful to what actually ran.
                    try:
                        templates_dir = netlist_export.persist_templates(
                            stim, os.path.join(history_dir, f"run_{timestamp}_templates"),
                        )
                    except Exception as exc:
                        log.warning("Could not persist netlist templates: %s", exc)
                        templates_dir = ""
                    meta_kwargs = dict(
                        yaml_name=os.path.basename(yaml_path),
                        duration_s=elapsed,
                        total_runs=total,
                        valid_runs=valid,
                        global_yield=gyield,
                        tran_dir=df.attrs.get("tran_dir", ""),
                        analysis_dirs=analysis_dirs,
                        templates_dir=templates_dir,
                    )
                    run_meta.write_meta(history_file, **meta_kwargs)
                    # Sidecar for the live CSV too, so "Latest" can be
                    # attributed to its datasheet (history filter) and keeps
                    # its templates after a restart.
                    run_meta.write_meta(csv_out, **meta_kwargs)
                except Exception as exc:
                    log.warning("Could not save history: %s", exc)

                app.after(0, app.refresh_history)
                app.after(
                    0,
                    lambda d=df, s=stim, e=elapsed: self._on_sim_success_main(d, s, e),
                )
            else:
                log.info("run_sim returned None (aborted or error).")

        except InterruptedError:
            log.info("run_sim_thread stopped (user cancel or interrupt).")
        except Exception as exc:
            log.exception("run_sim_thread raised an exception: %s", exc)
            app.after(0, self.show_error, str(exc))

        finally:
            log.info("run_sim_thread finished. Re-enabling UI.")
            self._sim_running.clear()

            def _finish_sim_ui(ctrl: SimulationController = self) -> None:
                latest = None
                try:
                    while True:
                        latest = ctrl._progress_queue.get_nowait()
                except queue.Empty:
                    pass
                if latest is not None:
                    try:
                        ctrl._set_progress_ui(*latest)
                    except Exception:
                        pass
                ctrl._thread_finalize_guard()
                _set_btn_start_ready(app)

            app.after(0, _finish_sim_ui)
