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
import threading
import time
from typing import TYPE_CHECKING

import numpy as np

from chipify import app_config, settings, simulator, util
from chipify.gui.services import data_loader as _dl

if TYPE_CHECKING:
    pass  # avoid circular import

log = logging.getLogger("chipify.gui.controllers.simulation")


def _set_btn_start_ready(app: object) -> None:
    """Re-enable the start button after simulation completes or aborts."""
    # Import inside function to avoid early Tk init during import
    import customtkinter as ctk
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

    def start_simulation(self) -> None:
        """Called by the Start button.  Validates selection and spawns the thread."""
        app = self.app  # type: ignore[attr-defined]
        selected = app.yaml_dropdown.get()
        if not selected or selected == "No files found":
            return

        yaml_path = os.path.join(settings.IN_DIR, selected)
        log.info("SimulationController.start_simulation: %s", selected)

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

        threading.Thread(target=self.run_sim_thread, args=(yaml_path,), daemon=True).start()

    def stop_simulation(self) -> None:
        """
        Called by the Stop button.

        Sets the threading stop-event AND calls ``simulator.abort_simulation()``
        to write the file-based abort flag (context.md §3).
        """
        app = self.app  # type: ignore[attr-defined]
        log.info("SimulationController.stop_simulation: abort requested.")
        app.stop_event.set()
        simulator.abort_simulation()  # writes /tmp/sim_work/abort.flag
        app.lbl_status.configure(text="Status: Canceling simulation…", text_color="orange")
        app.btn_stop.configure(state="disabled")

    def progress_callback_wrapper(self, current: int, total: int) -> None:
        """Worker-thread callback; raises InterruptedError if stop requested."""
        app = self.app  # type: ignore[attr-defined]
        if app.stop_event.is_set():
            raise InterruptedError("Simulation canceled!")
        app.after(0, self._set_progress_ui, current, total)

    def _set_progress_ui(self, current: int, total: int) -> None:
        """Must be called from the main thread via ``app.after()``."""
        app = self.app  # type: ignore[attr-defined]
        app.progress_bar.set(current / total)
        app.lbl_status.configure(
            text=f"Simulating… {current}/{total}", text_color="#3484F0"
        )

    def show_error(self, error_msg: str) -> None:
        """Display an error in the status bar and worst-case panel."""
        import customtkinter as ctk
        app = self.app  # type: ignore[attr-defined]
        app.lbl_status.configure(text="Status: Error / Aborted!", text_color="red")
        app.btn_start.configure(state="normal")
        app.btn_stop.configure(state="disabled")
        app.btn_refresh.configure(state="normal")
        for widget in app.wc_scroll.winfo_children():
            widget.destroy()
        ctk.CTkLabel(
            app.wc_scroll, text=f"LOG:\n{error_msg}",
            text_color="red", justify="left"
        ).pack(anchor="w", padx=20, pady=20)

    def run_sim_thread(self, yaml_path: str) -> None:
        """Worker-thread body: runs the simulation and saves results."""
        app = self.app  # type: ignore[attr-defined]
        log.info("run_sim_thread started. Thread: %s", threading.current_thread().name)
        t0 = time.perf_counter()
        try:
            stim = util.Stimuli(yaml_path)
            df = simulator.run_sim(
                stim, progress_callback=self.progress_callback_wrapper
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

                # Write a pointer so the Transient tab can resolve tran_dir on reload.
                tran_dir_val = df.attrs.get("tran_dir", "")
                if tran_dir_val:
                    try:
                        ptr = os.path.join(settings.OUT_DIR, "tran_data", ".latest")
                        os.makedirs(os.path.dirname(ptr), exist_ok=True)
                        with open(ptr, "w", encoding="utf-8") as fh:
                            fh.write(tran_dir_val)
                    except Exception as exc:
                        log.warning("Could not write tran_dir pointer: %s", exc)

                # Archive history run + write meta sidecar
                try:
                    from chipify import run_meta
                    history_dir = os.path.join(settings.OUT_DIR, "history")
                    os.makedirs(history_dir, exist_ok=True)
                    timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
                    history_file = os.path.join(history_dir, f"run_{timestamp}.csv")
                    df.to_csv(history_file, index=False)
                    total = len(df)
                    valid = int(
                        (df.get("sim_error", "None") == "None").sum()
                    ) if "sim_error" in df.columns else total
                    gpass = int(df["global_pass"].sum()) if "global_pass" in df.columns else None
                    gyield = (gpass / total * 100) if (gpass is not None and total > 0) else None
                    run_meta.write_meta(
                        history_file,
                        yaml_name=os.path.basename(yaml_path),
                        duration_s=elapsed,
                        total_runs=total,
                        valid_runs=valid,
                        global_yield=gyield,
                        tran_dir=df.attrs.get("tran_dir", ""),
                    )
                except Exception as exc:
                    log.warning("Could not save history: %s", exc)

                app.after(0, app.refresh_history)
                app.after(0, app.update_ui_results, df, stim, True)
                app.after(
                    0,
                    lambda e=elapsed: app.lbl_status.configure(
                        text=f"Status: Completed in {e:.1f}s", text_color="#2ecc71"
                    ),
                )
            else:
                log.info("run_sim returned None (aborted or error).")

        except Exception as exc:
            log.exception("run_sim_thread raised an exception: %s", exc)
            app.after(0, self.show_error, str(exc))

        finally:
            log.info("run_sim_thread finished. Re-enabling UI.")
            app.after(0, _set_btn_start_ready, app)
