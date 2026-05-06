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

## 4. Immediate Roadmap & Epics
The baseline is stable. The following features are the immediate next steps. When prompted to work on one of these, use the suggested technical approach:

### Epic 1: Simulator Modularity & Abstraction
*   **Goal:** Refactor `simulator.py` to support multiple simulation engines (currently Ngspice, future: Xyce, Spectre).
*   **Approach:** Implement an Abstract Base Class (e.g., `BaseSimulator`) with required methods like `generate_netlist()`, `run()`, `parse_output()`. Make `NgspiceSimulator` a child class. Update the `multiprocessing` worker to dynamically instantiate the correct engine based on user settings.

### Epic 2: Custom Equations (The "Cadence Calculator")
*   **Goal:** Allow users to define mathematical functions combining one or multiple measurement values to create a new derived signal (e.g., `efficiency = p_out / p_in * 100`), which is appended to the DataFrame and can be plotted.
*   **Approach:** Use `pandas.eval()` for safe and fast vectorized mathematical operations on the DataFrame. Add a UI element in the Editor or Analytics tab to define and save these custom expressions.

### Epic 3: Global Settings Menu
*   **Goal:** A dedicated settings menu/modal for persistent user preferences.
*   **Features:** 
    *   `num_cores`: A slider from 1 to `os.cpu_count()`.
    *   `color_scheme`: Dark/Light/Custom themes for CustomTkinter and Matplotlib.
    *   `enable_logging`: Toggle debug logs on/off.
*   **Approach:** Save preferences in a `config.yaml` or `settings.json` file. The `simulator.py` must dynamically read `num_cores` before launching the `multiprocessing.Pool`.

### Epic 4: Advanced PDF Export
*   **Goal:** Replace the current basic PDF export with a professional, datasheet-like report.
*   **Approach:** Use a robust reporting library (like HTML-to-PDF via `WeasyPrint`/`pdfkit` OR `ReportLab`). The report must include a neatly formatted measurements table (Yield, Cpk, Specs) and iterate over `plot_manager.py` to embed high-quality histograms and correlation heatmaps.

### Epic 5: Fix "Compare Runs" Overlay
*   **Goal:** The GUI currently has a "Compare (Ref)" dropdown in the Histogram tab, but selecting a history run does not properly overlay the data in the plot.
*   **Approach:** Update `plot_manager.py` -> `draw_histogram()`. Ensure that the reference CSV is loaded, filtered for `sim_error == 'None'`, and plotted as a secondary semi-transparent histogram/KDE on the same axes.

### Epic 6: Multi-Plot Dashboard (Secondary Window)
*   **Goal:** Allow users to open a detached, secondary `Toplevel` window to display multiple plots side-by-side for quick visual correlation.
*   **Approach:** Create a new CustomTkinter window class. Provide a grid layout with a "+" button to dynamically spawn new `FigureCanvasTkAgg` instances. Use `plot_manager.py` methods to populate them.

### Epic 7: Comprehensive Logging & Exception Handling
*   **Goal:** Prevent silent crashes and provide a clear trail for debugging.
*   **Approach:** Implement Python's built-in `logging` module. Replace `print()` statements with `logger.info()` or `logger.error()`. Catch unhandled exceptions in the Tkinter mainloop and redirect them to a log file (`chipify.log`), optionally showing a user-friendly error popup instead of freezing the GUI.