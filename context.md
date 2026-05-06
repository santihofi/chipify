# Project Briefing: Chipify (Simulation Engine) & Silicrunch (GUI)

## 1. Project Overview
*   **Project Name:** `Chipify` (Core CLI/Engine) & `Silicrunch` (CustomTkinter Desktop GUI).
*   **Purpose:** A high-performance EDA (Electronic Design Automation) tool for mismatch simulations, parameter sweeping, and yield analysis wrapping around Xschem and Ngspice.
*   **Core Tech Stack:** Python 3.12+, `customtkinter` (GUI), `pandas` (Data Crunching), `matplotlib` & `scipy` (Visualization & Stats), `multiprocessing` (Parallel execution), `jinja2` (Netlist templating).

## 2. File Architecture & Modules
*   `settings.py`: Defines global paths (`IN_DIR`, `OUT_DIR`, `WORK_DIR`, `TB_DIR`, etc.) and the crucial RAM disk path (`FAST_TMP = "/tmp/sim_work/"`).
*   `util.py`: Parses the `datasheet.yaml` into `Stimuli`, `Test`, and `Value` objects.
*   `cli.py`: The entry point for headless execution or launching the GUI.
*   `simulator.py`: The heavy-lifting engine. Uses `multiprocessing.Pool` with a file-based abort mechanism.
*   `gui_tk.py`: The frontend (Silicrunch). Tabbed interface for configurations, measurements, histograms, and advanced analytics.
*   `plot_manager.py`: Outsourced Matplotlib logic for all plots. Avoids GUI bloat.
*   `pdf_export.py` & `export_latex.py`: Generators for automated report creation.
*   `debug_export.py`: Extracts failing runs and auto-generates `.spice` netlists for manual Xschem debugging.

## 3. Critical Technical Context & "Gotchas" (DO NOT REVERT)
When writing or modifying code for this project, absolutely adhere to these established architectural constraints to prevent regressions:
*   **Process Management & Abort System (`simulator.py`):** 
    *   Do **NOT** use `ProcessPoolExecutor`, `Manager().Event()`, or signals to stop simulations. They fail to kill underlying Ngspice C-processes and cause RAM leaks.
    *   **The Fix:** We use a **File-Based Abort Flag** (`/tmp/sim_work/abort.flag`). The `run_ngspice` loop polls `os.path.exists(flag)` every 0.1s. If found, it executes a hard `process.kill()`. The GUI triggers this via `simulator.abort_simulation()`.
*   **Matplotlib Ghosting (`plot_manager.py`):**
    *   When drawing plots with colorbars (like Heatmaps), Matplotlib creates secondary axes. Calling `ax.clear()` leaves "ghost" colorbars stacking up.
    *   **The Fix:** Always use `fig.clf()` and completely rebuild the `ax = fig.add_subplot(111)` when switching plot modes.
*   **UI Dropdown Filtering (`gui_tk.py`):**
    *   The "Corner Yield Matrix" requires discrete inputs. If a continuous measurement variable (e.g., `gain` with 1000 unique float values) is passed, the pivot table crashes the GUI.
    *   **The Fix:** The GUI strictly separates `self.sweep_params` (discrete inputs) from `self.all_plot_cols` (inputs + continuous outputs) and filters dropdown options accordingly.
*   **Error Handling in DataFrames:**
    *   Failed Ngspice runs write their error message into the `sim_error` column. Successful runs have `sim_error = 'None'`.
    *   Before plotting or metric calculation, ALWAYS filter: `valid_df = df[df['sim_error'] == 'None']`.

### Epic 6: Multi-Plot Dashboard (Secondary Window)
*   **Goal:** Allow users to open a detached, secondary `Toplevel` window to display multiple plots side-by-side for quick visual correlation.
*   **Approach:** Create a new CustomTkinter window class. Provide a grid layout with a "+" button to dynamically spawn new `FigureCanvasTkAgg` instances. Use `plot_manager.py` methods to populate them.