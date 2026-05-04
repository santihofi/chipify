# Project Briefing: Simify & Silicrunch

## 1. Project Overview
*   **Project Names:** `Simify` (The CLI/Simulation Engine Wrapper) & `Silicrunch` (The CustomTkinter Desktop GUI).
*   **Purpose:** A high-performance EDA (Electronic Design Automation) tool for mismatch simulations, parameter sweeping, and yield analysis wrapping around Xschem and Ngspice.
*   **Core Tech Stack:** Python 3.12+, `customtkinter` (GUI), `pandas` (Data Crunching), `matplotlib` & `scipy` (Visualization & Stats), `multiprocessing` (Parallel execution), `jinja2` (Netlist templating).

## 2. File Architecture & Modules
The project has recently undergone a major refactoring to avoid a "God Object" GUI. The current structure is:
*   `settings.py`: Defines global paths (`IN_DIR`, `OUT_DIR`, `WORK_DIR`, `TB_DIR`) and the crucial RAM disk path (`FAST_TMP = "/tmp/sim_work/"`).
*   `util.py`: Parses the `datasheet.yaml` (containing sweep parameters and testbench spec boundaries) into `Stimuli`, `Test`, and `Value` objects.
*   `cli.py`: The entry point. Handles `-c` arguments, runs headless simulations, or launches the GUI via `run_gui()`. All CLI outputs are in English.
*   `simulator.py`: The heavy-lifting engine. Uses `multiprocessing.Pool` to run concurrent Ngspice instances.
*   `gui_tk.py`: The frontend (Silicrunch). A tabbed interface displaying measurements, computing readiness metrics ($C_{pk}$, $\sigma$-level), and managing the workflow.
*   `plot_manager.py`: Outsourced Matplotlib logic for Histograms and Advanced Analytics (Shmoo/Scatter, Corner Yield Matrix, Correlation Heatmap, Sensitivity Tornado, Pie Charts).
*   `pdf_export.py` & `export_latex.py`: Generators for automated report creation and `pgfplots`-ready CSV/TeX files.
*   `debug_export.py`: Extracts the worst-case failing run into a dedicated `.csv` and auto-generates a ready-to-run `.spice` netlist for manual Xschem debugging.

## 3. Critical Technical Context & "Gotchas" (DO NOT REVERT)
When writing or modifying code for this project, absolutely adhere to the following architectural decisions that were made to fix severe bugs:

*   **Process Management & Abort System (`simulator.py`):** 
    *   Do **NOT** use `ProcessPoolExecutor` or `Manager().Event()` to stop simulations. They fail to kill underlying Ngspice C-processes and cause RAM leaks/zombies.
    *   **The Fix:** We use a **File-Based Abort Flag** (`/tmp/sim_work/abort.flag`). The `run_ngspice` loop polls `os.path.exists(flag)` every 0.1s. If found, it executes a hard `process.kill()`. The GUI triggers this via `simulator.abort_simulation()`.
*   **Matplotlib Ghosting (`plot_manager.py`):**
    *   When drawing plots with colorbars (like Heatmaps), Matplotlib creates secondary axes. Simply calling `ax.clear()` leaves "ghost" colorbars stacking up on the screen.
    *   **The Fix:** Always use `fig.clf()` and completely rebuild the `ax = fig.add_subplot(111)` when switching plot modes.
*   **UI Dropdown Filtering (`gui_tk.py`):**
    *   The "Corner Yield Matrix" attempts to draw a grid. If a continuous measurement variable (e.g., `gain` with 1000 unique float values) is passed as an X/Y axis, the pivot table crashes or freezes the GUI.
    *   **The Fix:** The GUI strictly separates `self.sweep_params` (discrete inputs) from `self.all_plot_cols` (inputs + continuous outputs). The dropdowns dynamically update their `values` based on the selected plot mode.
*   **Error Handling in DataFrames:**
    *   Failed Ngspice runs write their error message into the `sim_error` column. Successful runs have `sim_error = 'None'`.
    *   Before plotting or metric calculation, ALWAYS filter: `valid_df = df[df['sim_error'] == 'None']`.

## 4. Current Roadmap / Next Immediate Task
The current baseline is rock-solid. The immediate next feature to implement is the **"Auto-Optimizer" (Sizing Engine)**.
*   **Goal:** Allow the tool to not just sweep parameters, but actively *optimize* design variables (e.g., transistor Width $W$ and Length $L$) to reach 100% yield or $C_{pk} > 1.33$.
*   **Required Changes:** 
    1. Update the `datasheet.yaml` parser to distinguish between `sweep_params` (environmental constraints we can't control like Temp, VDD) and `design_vars` (parameters the optimizer is allowed to change).
    2. Implement an optimization loop (e.g., using `scipy.optimize` with Nelder-Mead or a genetic algorithm) that iteratively feeds new `design_vars` into `simulator.py`, evaluates the Yield/$C_{pk}$ cost function, and converges on the perfect sizing.