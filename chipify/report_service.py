# Copyright (c) 2026 Santiago Hofwimmer
"""
report_service.py – Render the datasheet's ``reports:`` block to files.

Headless and toolkit-agnostic: the CLI (``--reports``) and the GUI's
*Generate Reports* button share this one implementation, so the two can never
produce different output for the same datasheet.

No new plotting code lives here. Figures come from the same
:class:`~chipify.plot_manager.PlotManager` entry points the GUI tabs use, drawn
onto a plain ``FigureCanvasAgg``; image files are written by the
``ExporterPlugin`` registry (so a user's own exporter is a usable format for
free), and the PDF / Markdown / LaTeX writers are the existing generators.

Every plot is rendered independently: a spec naming a measurement this run does
not have, or a waveform directory that was never produced, records a warning
and the remaining plots are still written. A report run must never fail as a
unit — the same reasoning that scoped simulation errors per testbench.
"""
from __future__ import annotations

import datetime
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pandas as pd

from chipify import data_loader as _dl
from chipify.reports import LATEX_FORMAT, PLOT_TYPES, PlotSpec, ReportsConfig
from chipify.uikit.services import transient_loader as _tl

log = logging.getLogger("chipify.report_service")

#: Cap on overlaid runs, matching the Plots tab's own limit.
_RUN_CAP = 500


@dataclass
class ReportResult:
    """What a report run produced, and what it could not."""

    out_dir: Path
    files: list[Path] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return bool(self.files) and not self.warnings


# ── Naming ────────────────────────────────────────────────────────────────────

def _slug(text: Any) -> str:
    """Filesystem-safe fragment of a signal or measurement name."""
    return re.sub(r"[^0-9A-Za-z._-]+", "_", str(text)).strip("_") or "plot"


def default_plot_name(spec: PlotSpec) -> str:
    """Filename stem for a spec that did not name itself.

    Built from the options rather than the index, so a plot keeps its filename
    when the list is reordered and two runs stay diffable.
    """
    if spec.name:
        return _slug(spec.name)
    opts = spec.options
    parts: list[str] = [spec.type]
    if spec.type in ("scatter", "corner_yield"):
        parts += [_slug(opts.get("x")), "vs", _slug(opts.get("y"))]
    elif spec.type == "histogram":
        parts.append(_slug(opts.get("param")))
    elif spec.type == "tornado":
        parts.append(_slug(opts.get("target")))
    else:
        signals = opts.get("signals") or []
        parts += [_slug(s) for s in signals[:3]]
    if opts.get("group"):
        parts += ["by", _slug(opts["group"])]
    return "_".join(p for p in parts if p)


# ── Rendering ─────────────────────────────────────────────────────────────────

def _new_figure():
    """A figure plus an Agg canvas satisfying the PlotManager draw contract."""
    from matplotlib.backends.backend_agg import FigureCanvasAgg
    from matplotlib.figure import Figure

    fig = Figure(figsize=(8, 5), dpi=150)
    canvas = FigureCanvasAgg(fig)
    return fig, canvas


def _selected_run_ids(df: pd.DataFrame, runs: str) -> list[str]:
    """Run ids for a waveform overlay, mirroring the Plots tab's run modes."""
    if df is None or "run_id" not in df.columns:
        return []
    mode = str(runs or "valid").strip().lower()
    if mode == "failing" and "global_pass" in df.columns:
        subset = df[df["global_pass"] == False]  # noqa: E712
    elif mode.startswith("first"):
        try:
            n = int(mode.split(":", 1)[1])
        except (IndexError, ValueError):
            n = 10
        subset = _dl.valid_rows(df).head(n)
    else:
        subset = _dl.valid_rows(df)
    return _tl.padded_run_ids(subset)[:_RUN_CAP]


def _render_waveform(spec: PlotSpec, df, stim, out_dir: Path, theme):
    """Draw one transient / dc / bode overlay. Returns (fig, latex_callable)."""
    from chipify.plot_manager import PlotManager

    ptype = spec.plot_type
    opts = spec.options
    kind = ptype.kind
    adir = _tl.resolve_analysis_dir(df, str(out_dir.parent.parent), kind)
    signals = list(opts.get("signals") or _tl.list_kind_signals(stim, kind))
    if not signals:
        raise ValueError(f"no {kind} signals declared in the datasheet")
    if not adir:
        raise ValueError(f"no {kind} waveform directory for this run")

    run_ids = _selected_run_ids(df, opts.get("runs", "valid"))
    if not run_ids:
        raise ValueError("no runs matched the requested selection")

    group_col = str(opts.get("group") or "")
    equations = (_eq_service().transient_equations(stim)
                 if kind == "transient" else [])
    draw_fn = {
        "transient": PlotManager.draw_transient_plot,
        "dc": PlotManager.draw_dc_sweep,
        "ac": PlotManager.draw_bode_plot,
    }[kind]

    fig, canvas = _new_figure()
    draw_fn(fig, canvas, adir, run_ids, signals,
            pass_map=_tl.run_pass_map(df), equations=equations, theme=theme,
            group_map=_tl.run_group_map(df, group_col), group_label=group_col)

    def _latex(dest: Path, stem: str):
        from chipify import export_latex
        gen = {
            "transient": export_latex.generate_transient_latex_export,
            "dc": export_latex.generate_dc_sweep_latex_export,
            "ac": export_latex.generate_bode_latex_export,
        }[kind]
        return gen(str(dest), stem, adir, run_ids, signals, equations)

    return fig, _latex


def _render_histogram(spec: PlotSpec, df, stim, theme):
    from chipify.plot_manager import PlotManager

    opts = spec.options
    param = str(opts["param"])
    if param not in df.columns:
        raise ValueError(f"measurement {param!r} is not in this run's results")

    fig, canvas = _new_figure()
    ax = fig.add_subplot(111)
    PlotManager.draw_histogram(
        fig, ax, canvas, df, stim, param,
        str(opts.get("fit", "Gauss (Normal)")),
        str(opts.get("group") or "None"),
        str(opts.get("bins", "Auto")),
        bool(opts.get("zoom", False)),
        "None", theme=theme,
    )

    def _latex(dest: Path, stem: str):
        from chipify import export_latex
        data = _dl.plot_rows(df, stim, [param])[param]
        bins_text = str(opts.get("bins", "Auto"))
        bins = "auto" if bins_text == "Auto" else int(bins_text)
        return export_latex.generate_latex_export(
            stem, data, str(opts.get("fit", "Gauss (Normal)")), bins, str(dest))

    return fig, _latex


def _render_advanced(spec: PlotSpec, df, stim, theme):
    from chipify.plot_manager import PlotManager

    opts = spec.options
    fig, canvas = _new_figure()
    PlotManager.draw_adv_plot(
        fig, None, canvas, df, stim, spec.plot_type.adv_mode,
        str(opts.get("x", "")), str(opts.get("y", "")),
        str(opts.get("target", "")), theme=theme,
    )
    return fig, None


def _eq_service():
    from chipify.uikit.services import equation_service
    return equation_service


def _render(spec: PlotSpec, df, stim, out_dir: Path, theme):
    """Dispatch one spec to its renderer. Returns ``(figure, latex_callable)``."""
    if spec.plot_type.is_waveform:
        return _render_waveform(spec, df, stim, out_dir, theme)
    if spec.type == "histogram":
        return _render_histogram(spec, df, stim, theme)
    return _render_advanced(spec, df, stim, theme)


# ── Writing ───────────────────────────────────────────────────────────────────

def _exporters() -> dict[str, Any]:
    from chipify.plugin_loader import get_exporter_plugins
    return {e.extension.lstrip(".").lower(): e for e in get_exporter_plugins()}


def _write_plot(spec: PlotSpec, cfg: ReportsConfig, df, stim,
                out_dir: Path, theme, result: ReportResult) -> None:
    stem = default_plot_name(spec)
    formats = spec.resolved_formats(cfg.formats)
    if not formats:
        result.warnings.append(f"{stem}: no output formats requested; skipped.")
        return

    try:
        fig, latex_fn = _render(spec, df, stim, out_dir, theme)
    except Exception as exc:  # noqa: BLE001 — one bad spec must not stop the rest
        result.warnings.append(f"{stem}: could not render ({exc})")
        log.warning("Report plot %r failed to render: %s", stem, exc)
        return

    try:
        exporters = _exporters()
        for fmt in formats:
            if fmt == LATEX_FORMAT:
                if latex_fn is None:
                    result.warnings.append(
                        f"{stem}: LaTeX export is not available for plot type "
                        f"{spec.type!r}; other formats were still written."
                    )
                    continue
                try:
                    written = latex_fn(out_dir, stem)
                except Exception as exc:  # noqa: BLE001
                    result.warnings.append(f"{stem}: LaTeX export failed ({exc})")
                    continue
                for path in (written or ()):
                    if path:
                        result.files.append(Path(path))
                continue

            exporter = exporters.get(fmt)
            if exporter is None:
                result.warnings.append(f"{stem}: no exporter for format {fmt!r}.")
                continue
            dest = out_dir / f"{stem}.{fmt}"
            try:
                exporter().export(fig, str(dest), theme=theme)
            except TypeError:      # exporter predating the theme kwarg
                exporter().export(fig, str(dest))
            result.files.append(dest)
    finally:
        # Figures are created outside pyplot, so nothing closes them for us.
        fig.clf()


def _write_documents(cfg: ReportsConfig, df, stim, yaml_path: str,
                     out_dir: Path, duration_s, result: ReportResult) -> None:
    if cfg.pdf:
        try:
            from chipify import pdf_export
            result.files.append(Path(pdf_export.generate_pdf_report(
                df, stim, yaml_path, str(out_dir), sim_duration_sec=duration_s)))
        except Exception as exc:  # noqa: BLE001
            result.warnings.append(f"PDF report failed ({exc})")
            log.warning("PDF report failed: %s", exc)
    if cfg.markdown:
        try:
            from chipify import md_export
            result.files.append(Path(md_export.generate_md_report(
                df, stim, yaml_path, str(out_dir / "report.md"),
                sim_duration_sec=duration_s)))
        except Exception as exc:  # noqa: BLE001
            result.warnings.append(f"Markdown report failed ({exc})")
            log.warning("Markdown report failed: %s", exc)


# ── Public API ────────────────────────────────────────────────────────────────

def reports_dir(out_dir: str | Path) -> Path:
    """Root directory holding every report run."""
    return Path(out_dir) / "reports"


def latest_reports(out_dir: str | Path) -> str:
    """Path recorded in ``reports/.latest`` ("" when there is none)."""
    pointer = reports_dir(out_dir) / ".latest"
    try:
        return pointer.read_text(encoding="utf-8").strip()
    except OSError:
        return ""


def generate_reports(df: pd.DataFrame, stim: Any, yaml_path: str,
                     out_dir: str | Path, *, duration_s: float | None = None,
                     theme: dict | None = None) -> ReportResult:
    """Render everything the datasheet's ``reports:`` block asks for.

    Writes into ``<out_dir>/reports/<timestamp>/`` and points
    ``<out_dir>/reports/.latest`` at it — the pointer convention
    ``simulator.write_analysis_pointers`` already uses for analysis data.
    """
    cfg: ReportsConfig = getattr(stim, "reports", None) or ReportsConfig()
    stamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    dest = reports_dir(out_dir) / stamp
    result = ReportResult(out_dir=dest)

    if not cfg:
        result.warnings.append(
            "The datasheet declares no 'reports:' block, so there is nothing "
            "to generate."
        )
        return result

    dest.mkdir(parents=True, exist_ok=True)
    prepared = _dl.prepare_results(df)

    for spec in cfg.plots:
        _write_plot(spec, cfg, prepared, stim, dest, theme, result)
    _write_documents(cfg, prepared, stim, yaml_path, dest, duration_s, result)

    try:
        (reports_dir(out_dir) / ".latest").write_text(str(dest), encoding="utf-8")
    except OSError as exc:
        result.warnings.append(f"Could not write the .latest pointer ({exc})")

    log.info("Reports written to %s (%d file(s), %d warning(s))",
             dest, len(result.files), len(result.warnings))
    return result
