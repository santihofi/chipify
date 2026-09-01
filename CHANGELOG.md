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
- `PluginContext.specs()` exposes the datasheet's `equations` /
  `transient_equations` blocks; `netlists()` resolves plugin-engine netlist
  extensions.
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
- Histogram TeX export: measurement names with SPICE syntax (`v(out)`, …) are
  sanitised for the output filenames, the success dialog shows the paths that
  were actually written, and an all-NaN series reports "nothing exported"
  instead of a false success message.

### Removed
- SSH/remote-dispatch feature (not ready for release); preserved on the
  `feature/remote-dispatch` branch for future work.

## [0.2.0]

- Post-refactor baseline: multiprocessing simulation engine, CustomTkinter GUI,
  sandboxed expression evaluation, plugin system, and PDF/Markdown/LaTeX reports.

## [0.2.1]

- improve stability, fix bugs

## [0.2.2]

- switch to PySide6-Essentials

## [0.2.3]

- Errors are now scoped per testbench (`<tb_path>__error`) instead of a single
  per-row `sim_error`. A testbench that fails no longer hides the results of the
  testbenches that succeeded, and a measurement with no usable run reports
  ERROR rather than a vacuously-true PASS.
- Measurements tab: Errors column, amber ERROR status, and a SIMULATION ERRORS
  section naming the testbench, failing corner and simulator message, plus a
  scrollable log panel and an "Open Log" button.
- The CLI analyzer and the Markdown/PDF reports read the shared measurements
  service, so all four surfaces agree on a verdict and report errors.
- Crashed worker batches are recorded as WORKER_LOST rows instead of silently
  vanishing from the results; `run_sim` raises on unexpected failure and returns
  None only on user abort, so a failed run can no longer end in silence.
- Logging is enabled for CLI runs and the log banner records the running
  chipify version and install path.
- Waveform overlays (Transient / DC sweep / Bode) can be grouped by a swept
  input parameter: curves are coloured by the parameter's value (`temp=-40`,
  `temp=27`, …) with the signal carried by line style. Available in the Plots
  tab and in the Multi-plot dashboard.
- Fixed: waveform overlays matched no files for any run loaded from a results
  CSV. `run_id` parses back as an integer, so the lookup asked for `run_4`
  while the file is `run_000004__<tb>.csv`; only a run still in memory from a
  live simulation ever drew.
- New optional `reports:` block in the datasheet declares figures and reports to
  generate: plot type, axes/signals, grouping and output formats (any
  `ExporterPlugin` extension such as `png`/`svg`, plus `latex` where a pgfplots
  generator exists). Produced by `chipify-cli --reports` or the GUI's
  *Generate Reports* button into `out/reports/<timestamp>/`, with a `.latest`
  pointer. Previously a CLI run produced no figures at all.
- Fixed: the PDF report only ever contained histograms. A configured scatter,
  transient, DC sweep, Bode, correlation or tornado plot was written as an
  image but never reached the report, which instead showed an automatic
  histogram per measurement plus a correlation page nobody asked for. When a
  datasheet declares `reports: plots:`, the report's figure pages are now
  exactly those plots, in order, rendered through the same call that writes the
  standalone image. Datasheets without a `plots:` list keep the automatic
  sections.
- Fixed: figures embedded in the PDF kept the dark on-screen palette, while the
  same plot exported as a PNG came out light — the report path bypassed the
  exporters' white-paper re-skin.
- Fixed: custom equations could not be deleted. Removing a row without then
  pressing Apply was silently undone by the next table reload (a mode switch or
  datasheet reload put the equation straight back), and clicking Remove with no
  row selected did nothing and said nothing. Removing now saves immediately,
  falls back to the focused row, reports when there is nothing to remove, and an
  unsaved edit discarded by a reload is announced instead of vanishing.
- Fixed: a measurement rendered differently in different formats. The PDF report
  had its own histogram implementation that ignored the datasheet's `reports:`
  spec, so a plot configured `group: temp` came out grouped as a PNG and
  ungrouped in the PDF. Both now use one renderer and one set of options.
- Report histograms zoom to their data by default. With spec limits far outside
  the spread the bars previously collapsed into slivers against a spec-width
  axis; `zoom: false` restores the wide view.
- The `reports:` block is now editable in the GUI: **Reports…** in the Datasheet
  Editor opens a dialog for the plots, formats and documents, saved into the
  datasheet through the same writer the equations panel uses.
- `Export PDF Report` and `Generate Reports` are unified into one button and one
  code path. PDF output moves from the `out/reports/` root into the run's
  `out/reports/<timestamp>/` folder with everything else; when a datasheet
  declares no `reports:` block the button still offers a one-click PDF.
- Markdown and PDF reports now use the same engineering-unit formatting
  (`373.5 m`, `2.686 G`); they previously disagreed on the same numbers.
  Dimensionless values such as Cpk keep the plain form.
- Internal: run selection for waveform overlays lives once in
  `transient_loader.select_run_ids` instead of three copies with two different
  vocabularies, and a datasheet's `runs:` key now takes the same tokens as the
  GUI (`all_valid`, `failing`, `first:N`).
- The `Transient` tab is now `Plots`, since it has long covered DC sweep and
  Bode as well; the dashboard's waveform cell gained the same analysis-kind
  selector. Dashboards saved with the old `Transient` cell still open.
