# Changelog

All notable changes to this project are documented here. The format is based on
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project
adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

Preparation for the initial public release.

### Added
- `README.md` with project overview, prerequisites, install, and quick-start.
- Apache-2.0 `LICENSE`.
- `CONTRIBUTING.md` and GitHub issue/PR templates.
- GitHub Actions CI running `pytest` and `mypy` on push and pull request.
- Documented example datasheet under `examples/`.
- Configurable project folder paths (`in_dir`, `out_dir`, `work_dir`, `tb_dir`)
  via `settings.json`, falling back to the default structure when unset.

### Removed
- SSH/remote-dispatch feature (not ready for release); preserved on the
  `feature/remote-dispatch` branch for future work.

## [0.2.0]

- Post-refactor baseline: multiprocessing simulation engine, CustomTkinter GUI,
  sandboxed expression evaluation, plugin system, and PDF/Markdown/LaTeX reports.
