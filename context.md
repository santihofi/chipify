# Project Briefing: Chipify (Simulation Engine) & Silicrunch (GUI)

## 1. Project Overview
*   **Project Name:** `Chipify` (Core CLI/Engine) & `Silicrunch` (CustomTkinter Desktop GUI).
*   **Purpose:** A high-performance EDA (Electronic Design Automation) tool for mismatch simulations, parameter sweeping, and yield analysis wrapping around Xschem and Ngspice.
*   **Core Tech Stack:** Python 3.11+, `customtkinter` (GUI), `pandas` (Data Crunching), `matplotlib` & `scipy` (Visualization & Stats), `multiprocessing` (Parallel execution), `jinja2` (Netlist templating), `asteval` (sandboxed expression evaluation).

---

## 2. File Architecture & Modules (v0.2 — post-Phase-1 refactor)

### Engine (no Tk deps)

| Module | Purpose |
|---|---|
| `settings.py` | Global paths (`IN_DIR`, `OUT_DIR`, `WORK_DIR`, `TB_DIR`, `FAST_TMP`). |
| `util.py` | Domain objects: `Stimuli`, `Test`, `Value`. Delegates YAML parsing to `schema.py`. |
| `schema.py` | `validate_datasheet()` — validates `datasheet.yaml` against typed schema; safe `_parse_range_dsl()` for `range/linspace/logspace` strings. |
| `expression.py` | `SafeEvaluator` — sandboxed `asteval`-backed evaluator with `numexpr` fast path. Replaces all `eval()` / `df.eval()` call-sites. |
| `app_config.py` | Persistent user preferences (`settings.json`), application-wide logging setup. |
| `simulator.py` | Multiprocessing simulation engine (`NgspiceSimulator`, `VacaskSimulator`). File-based abort via `/tmp/sim_work/abort.flag`. |
| `plot_manager.py` | All Matplotlib logic. Avoids GUI bloat. |
| `cli.py` | Entry point for headless execution or launching the GUI. |

### GUI Package (`chipify/gui/`)

```
gui/
├── __init__.py
├── theme.py                – CTk appearance mode + BACKGROUND_COLOR / PANEL_COLOR constants
├── state.py                – AppState (single source of truth) + Signal pub/sub
├── main_window.py          – SimifyGUI shell + main() entry point
├── controllers/
│   ├── simulation_controller.py  – start/stop simulation, progress callbacks, abort flag
│   └── history_controller.py     – refresh_history, auto_load_latest_run, on_history_select
├── services/               – pure logic; NO tkinter imports
│   ├── data_loader.py      – load_csv, list_history_runs, compute_plot_cols, valid_rows
│   ├── equation_service.py – apply_scalar_equations, apply_transient_equations (via SafeEvaluator)
│   ├── yaml_editor_service.py – get_params_dict, get_tests_dict, gui_repr_param, sync_form_to_yaml
│   └── transient_loader.py – resolve_tran_dir, list_available_signals, load_tran_df
├── tabs/
│   └── base.py             – TabFrame ABC (.build() / .on_state_change())
└── widgets/
    ├── settings_window.py  – Modal settings dialog (CTkToplevel)
    ├── treeview_styling.py – apply_dark_style(tree) for ttk.Treeview
    └── yaml_dumper.py      – QuotedString + inline-list YAML representers
```

**`gui_tk.py`** — backward-compatibility shim (`from chipify.gui.main_window import main, SimifyGUI`).

### Tests (`tests/`)

| File | Covers |
|---|---|
| `test_expression.py` | SafeEvaluator sandbox, helpers, SPICE sanitization, security |
| `test_util_range_dsl.py` | `_parse_range_dsl` whitelist, `validate_parameters` |
| `test_equation_service.py` | apply_scalar/transient equations, NaN propagation |
| `test_yaml_editor_service.py` | get_params_dict, get_tests_dict, gui_repr_param |

---

## 3. Critical Technical Constraints (DO NOT REVERT)

### Process Management & Abort System (`simulator.py`)
*   Do **NOT** use `ProcessPoolExecutor`, `Manager().Event()`, or signals to stop simulations. They fail to kill underlying Ngspice C-processes and cause RAM leaks.
*   **The Fix:** File-based abort flag at `FAST_TMP/abort.flag` (`/tmp/sim_work/abort.flag`). The worker loop polls `os.path.exists(flag)` every 0.1 s; if found, it executes a hard `process.kill()`. GUI stop button → `simulation_controller.stop_simulation()` → `simulator.abort_simulation()`.

### Safe Expression Evaluation (`expression.py`)
*   **Never** call Python `eval()`, `exec()`, or `df.eval(engine='python')` directly in user-facing code.
*   **The Fix:** Route all expression evaluation through `SafeEvaluator` (module-level singleton: `from chipify.expression import default_evaluator`). It blocks `__import__`, `open`, `exec`, and dunder attribute access via `asteval`.

### YAML Range Parsing (`schema.py`)
*   **Never** use `str.replace("range(","")` or raw `eval()` to expand YAML range strings.
*   **The Fix:** `_parse_range_dsl(value)` uses `ast.parse` + an allowlist (`range`, `linspace`, `logspace`) with constant-only arguments. Any other node raises `SchemaError`.

### Matplotlib Ghosting (`plot_manager.py`)
*   When drawing plots with colorbars, calling `ax.clear()` leaves ghost colorbars stacking up.
*   **The Fix:** Always use `fig.clf()` then `ax = fig.add_subplot(111)` when switching plot modes.

### Sweep vs Output Column Separation
*   The "Corner Yield Matrix" requires discrete inputs. Mixing continuous output columns causes a pivot table crash.
*   **The Fix:** `data_loader.compute_plot_cols()` returns a typed `PlotColumns` dataclass separating `sweep_params` from numeric output columns. `data_loader.valid_rows(df)` is the single filter for `sim_error == 'None'`.

### Error Handling in DataFrames
*   Failed Ngspice runs write their error into the `sim_error` column; successful runs have `sim_error = 'None'`.
*   Always filter before plotting or metric computation: use `data_loader.valid_rows(df)` — never inline the filter.

---

## 4. Architecture Rules (Phase 1 invariants)

1. **Services and model modules** (`services/`, `state.py`, `expression.py`, `schema.py`) **never import `tkinter` / `customtkinter`**. This keeps them unit-testable without a display.
2. **Tabs never call `simulator.*` directly.** They dispatch through a controller (`SimulationController`).
3. **State is mutated only through `AppState`.** Subscribers receive notifications via `Signal.emit()`.

---

## 5. Development Commands

```bash
# Install (engine only)
pip install -e .

# Install with optional fast vectorised evaluation
pip install -e ".[fast]"

# Run tests
pytest

# mypy strict check on typed modules
python -m mypy chipify/expression.py chipify/schema.py chipify/gui/state.py \
    chipify/gui/services/ chipify/gui/tabs/base.py chipify/gui/widgets/ \
    chipify/util.py chipify/app_config.py --strict

# Launch GUI
chipify gui
```
