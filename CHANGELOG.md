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

### Fixed
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
