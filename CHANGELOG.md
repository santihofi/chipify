# Changelog

All notable changes to this project are documented here. The format is based on
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project
adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

Preparation for the initial public release.

### Added
- Modular simulator-engine architecture (`chipify/engines/`): each simulator
  is one `BaseSimulator` class resolved through a registry, mirroring the GUI
  plugin system. New engines can be added as a single built-in module, a
  drop-in plugin file in `~/.chipify/plugins/` (see PLUGINS.md, "Simulator
  engine plugin"), or via `register_engine()`. The datasheet schema, the CLI
  `--simulator` choices, the Settings dialog, and the editor's per-testbench
  engine dropdown all read the registry instead of hardcoded name lists.
  `chipify.simulator` keeps re-exporting the engine API for compatibility.
- `sim_timeout_sec` setting (Settings → Simulation → "Per-run timeout"):
  the per-simulation wall-clock limit was previously hardcoded to 10 s.
- QQ plot, ECDF + Spec Limits, and Yield vs Spec Curve now render like the
  histogram: a measurement selector plots the single chosen output full-size,
  with an "All measurements" checkbox restoring the previous panel grid.
  Plot plugins can opt into the selector via `supports_param = True`
  (see PLUGINS.md → PlotPlugin).
- Custom equations (scalar and transient) are stored **in the datasheet**
  (top-level `equations:` / `transient_equations:` YAML blocks) so they travel
  with the design. The CUSTOM EQUATIONS panel edits the active datasheet;
  equations still in `settings.json` are used as a fallback and migrated out
  on the panel's next Apply.
- Transient-equation results appear as selectable signals in the Multi-Plot
  Dashboard's Transient cells (the main Transient tab already listed them);
  signal lists now refresh immediately when equations change, preserving the
  current selection.
- Built-in distribution plot modes registered via the PlotPlugin interface
  (`chipify/plot_plugins/`): QQ plot (normality check), ECDF with spec
  limits, and yield-vs-spec curve. User plugins with the same name override
  the built-ins.
- `README.md` with project overview, prerequisites, install, and quick-start.
- Apache-2.0 `LICENSE`.
- `CONTRIBUTING.md` and GitHub issue/PR templates.
- GitHub Actions CI running `pytest` and `mypy` on push and pull request.
- Documented example datasheet under `examples/`.
- Configurable project folder paths (`in_dir`, `out_dir`, `work_dir`, `tb_dir`)
  via `settings.json`, falling back to the default structure when unset.

### Changed
- The `work_dir` project folder default was renamed `tmp/` → `work/`: it never
  held temporary data (the RAM-backed scratch dir does) — it is the input
  folder for `*.lib`/`*.mod`/`*.inc` model files staged next to the netlists.
  An explicit `work_dir` in `settings.json` keeps working unchanged.

### Fixed
- Correlation matrix: `run_id` (an index, not data) and the per-run duration
  bookkeeping column no longer appear as correlated parameters (GUI and PDF
  report), and the axis labels are anchored so long names stay visible.
- The correlation matrix in the PDF report now greys out the self-correlation
  diagonal like the GUI, instead of rendering it as deep-red 1.00 cells.
- Multi-Plot Dashboard: a dashboard opened before the first data load lost its
  saved cell selections (and persisted the degraded config on close); saved
  selections are now restored when the data arrives.
- Multi-Plot Dashboard: cells in the right-hand grid columns were cut off at
  the window edge. The per-cell controls row forced an ~830 px minimum cell
  width; controls now wrap onto two rows, combos may shrink (popups still
  show full text), and grid columns share the viewport width evenly.
- Histogram selectors (main tab and dashboard cells) no longer offer input
  parameters as "measurements" — a distribution of an input is just the sweep
  grid. Inputs remain available for grouping and as scatter X/Y axes.
- A Jinja2 template-rendering error (e.g. a parameter-name typo in a
  testbench) now fails only that testbench's row with
  `TEMPLATE_RENDER_ERROR`; previously the exception silently discarded the
  whole worker batch of cases from the results. Engines that raise from
  `run()` are contained the same way (`ENGINE_ERROR`).
- AC waveform extraction from VACASK `.raw` files no longer crashes when the
  parsed bucket lacks the X-axis sentinel (`or`-chaining evaluated numpy
  arrays whose truth value is ambiguous).
- Analysis-capture failure notes now quote the *actual* engine's name and
  log tail; on VACASK runs they previously quoted a stale ngspice log.
- A non-numeric `MY_DATA` token now records NaN plus a failed flag for that
  measurement instead of silently omitting the column.
- An unknown engine name (e.g. a typo'd `simulator_engine` in settings.json)
  now logs a warning before falling back to ngspice.
- Stale *copies* of staged VACASK `.osdi` files are refreshed when the PDK
  changes (symlinked ones always tracked the source already).

### Removed
- SSH/remote-dispatch feature (not ready for release); preserved on the
  `feature/remote-dispatch` branch for future work.

## [0.2.0]

- Post-refactor baseline: multiprocessing simulation engine, CustomTkinter GUI,
  sandboxed expression evaluation, plugin system, and PDF/Markdown/LaTeX reports.
