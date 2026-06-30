# Project Briefing: Chipify

## 1. Project Overview
*   **Project Name:** `Chipify` (Core CLI/Engine & PySide6 (Qt) Desktop GUI).
*   **Purpose:** A high-performance EDA (Electronic Design Automation) tool for mismatch simulations, parameter sweeping, and yield analysis wrapping around Xschem and Ngspice.
*   **Core Tech Stack:** Python 3.11+, `PySide6` (Qt GUI), `pandas` (Data Crunching), `matplotlib` & `scipy` (Visualization & Stats), `multiprocessing` (Parallel execution), `jinja2` (Netlist templating), `asteval` (sandboxed expression evaluation).

---

## 2. File Architecture & Modules (v0.2 — post-Phase-1 refactor)

### Engine (no Tk deps)

| Module | Purpose |
|---|---|
| `settings.py` | Project paths (`IN_DIR`, `OUT_DIR`, `WORK_DIR`, `TB_DIR`, `FAST_TMP`). The four project folders are configurable via `settings.json` (keys `in_dir/out_dir/work_dir/tb_dir`); missing/blank ⇒ default structure. `FAST_TMP` is fixed. |
| `util.py` | Domain objects: `Stimuli`, `Test`, `Value`. Delegates YAML parsing to `schema.py`. |
| `schema.py` | `validate_datasheet()` — validates `datasheet.yaml` against typed schema; safe `_parse_range_dsl()` for `range/linspace/logspace` strings. |
| `expression.py` | `SafeEvaluator` — sandboxed `asteval`-backed evaluator with `numexpr` fast path. Replaces all `eval()` / `df.eval()` call-sites. |
| `app_config.py` | Persistent user preferences (`settings.json`), application-wide logging setup. |
| `simulator.py` | Multiprocessing simulation engine (`NgspiceSimulator`, `VacaskSimulator`). File-based abort via `/tmp/sim_work/abort.flag`. |
| `plot_manager.py` | All Matplotlib logic. Avoids GUI bloat. |
| `data_loader.py` | Results loading / pass-fail / plot-column classification / history — shared by the engine, exporters, and GUI; headless, no GUI deps. |
| `cli.py` | Entry point for headless execution or launching the GUI (`run_gui()` → Qt app). |

### Toolkit-agnostic GUI-support layer (`chipify/uikit/`)

```
uikit/                      – NO GUI-toolkit imports; unit-testable headlessly
├── state.py                – AppState (single source of truth) + Signal pub/sub
├── services/
│   ├── equation_service.py – apply_scalar_equations, apply_transient_equations (via SafeEvaluator)
│   ├── measurements.py     – measurement_rows / equation_rows / worst_cases (stats for the table)
│   ├── transient_loader.py – resolve_analysis_dir, list_analysis_signals, load_analysis_df
│   ├── scatter_hover.py    – matplotlib scatter hover/click manager
│   ├── netlist_export.py   – per-sample SPICE netlist rendering (pure)
│   ├── yaml_editor_service.py – get_params_dict, get_tests_dict, gui_repr_param, sync_form_to_yaml
│   └── plugin_context.py   – PluginContext facade handed to tab plugins (see PLUGINS.md)
└── widgets/
    └── yaml_dumper.py      – QuotedString + inline-list YAML representers
```

### Qt GUI Package (`chipify/gui_qt/`)

```
gui_qt/
├── app.py                  – QApplication bootstrap + main() (the `chipify` GUI entry point)
├── main_window.py          – QMainWindow shell: left control panel + QTabWidget + status bar
├── theme.py                – night/dark/light palettes → QSS + QPalette; plot_theme()
├── controllers/            – simulation_controller, history_controller (Qt signals, no after())
├── workers/sim_worker.py   – QThread worker emitting queued progress/chunk/finished signals
├── services/               – throttle, canvas_menu (QMenu), figure_export, latex_export
├── tabs/                   – editor / measurements / histogram / analytics / transient / equations
└── widgets/                – settings_dialog, run_annotation_dialog, mpl_canvas, helpers
```

Plugins: the Qt GUI loads `QtTabPlugin`s; legacy Tk `TabPlugin`s are detected and skipped with a warning (`plugin_loader.warn_unsupported_tab_plugins()`).

### Tests (`tests/`)

| File | Covers |
|---|---|
| `test_expression.py` | SafeEvaluator sandbox, helpers, SPICE sanitization, security |
| `test_util_range_dsl.py` | `_parse_range_dsl` whitelist, `validate_parameters` |
| `test_equation_service.py` | apply_scalar/transient equations, NaN propagation |
| `test_yaml_editor_service.py` | get_params_dict, get_tests_dict, gui_repr_param |
| `test_data_loader_history.py` | `data_loader.list_history_runs` |
| `test_netlist_export.py` | per-sample netlist rendering (pure logic) |
| `test_plugin_context.py` | `PluginContext` facade, JSON-serialization |
| `test_gui_qt_smoke.py` | Qt GUI smoke tests (offscreen): window, tabs, themes, worker, plugins |

---

## 3. Critical Technical Constraints (DO NOT REVERT)

### Process Management & Abort System (`simulator.py`)
*   Do **NOT** use `ProcessPoolExecutor`, `Manager().Event()`, or signals to stop simulations. They fail to kill underlying Ngspice C-processes and cause RAM leaks.
*   **The Fix:** File-based abort flag at `FAST_TMP/abort.flag` (`/tmp/sim_work/abort.flag`). The worker loop polls `os.path.exists(flag)` every 0.1 s; if found, it executes a hard `process.kill()`. GUI stop button → `simulation_controller.stop_simulation()` → `simulator.abort_simulation()`.

### Scalar capture: chipify owns the `MY_DATA:` line (`simulator.py`)
*   ngspice scalar measurements come back on a single `MY_DATA:` **stdout** line. **Do not hand-write `echo MY_DATA:` in a testbench** — `NgspiceSimulator.generate_test_template` auto-injects it from the datasheet's `value_lst` (`echo MY_DATA:$&<key0> $&<key1> …`, in order) via `_inject_capture`, and strips any stale hand-written one so only chipify's survives.
*   **The contract:** each scalar key under `tests.<tb>` must name an ngspice vector the testbench defines with `let`/`meas` — `$&<key>` has to resolve. The run side parses the same line positionally back into `value_lst`, so chipify controls both ends and the order can't drift. Waveforms work the same way: declare `transient/dc/ac_signals` and chipify injects the `wrdata`/`setplot` capture (`analyses.py`).
*   Vacask is unaffected — it extracts scalars from the `.raw` file (named `meas` results / `measure:` exprs) or its own `printf "MY_DATA: …"`.

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

1. **The core and the `uikit/` layer** (`uikit/services/`, `uikit/state.py`, `data_loader.py`, `expression.py`, `schema.py`) **never import a GUI toolkit**. This keeps them unit-testable without a display; all Qt code lives under `gui_qt/`.
2. **Tabs never call `simulator.*` directly.** They dispatch through a controller (`SimulationController`).
3. **State is mutated only through `AppState`.** Subscribers receive notifications via `Signal.emit()`; the `QThread` sim worker delivers cross-thread updates as queued Qt signals.

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
python -m mypy chipify/expression.py chipify/schema.py chipify/uikit/state.py \
    chipify/uikit/services/ chipify/uikit/widgets/ chipify/data_loader.py \
    chipify/util.py chipify/app_config.py --strict

# Launch GUI (PySide6/Qt)
chipify
```
