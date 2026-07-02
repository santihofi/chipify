# Copyright (c) 2026 Santiago Hofwimmer
"""
latex_export.py – Qt wiring for the pgfplots/LaTeX exporters.

Surfaces the framework-agnostic generators in :mod:`chipify.export_latex` to the
Qt tabs, mirroring the legacy CustomTkinter "TeX Export" buttons. Both the
histogram distribution and the transient/DC/Bode overlays write a ``.csv`` plus
a ``.tex`` into ``OUT_DIR/latex/``; this module owns the directory, the
dispatch, and all user-facing messaging so the tab methods stay thin.
"""
from __future__ import annotations

import logging
import os

from PySide6.QtWidgets import QMessageBox, QWidget

from chipify import settings

log = logging.getLogger("chipify.gui_qt.latex_export")

#: kind → (overlay generator name, output basename).
_OVERLAY = {
    "transient": ("generate_transient_latex_export", "transient"),
    "dc": ("generate_dc_sweep_latex_export", "dc_sweep"),
    "ac": ("generate_bode_latex_export", "bode"),
}


def _latex_dir() -> str:
    return os.path.join(settings.OUT_DIR, "latex")


def export_histogram_latex(
    parent: QWidget,
    param: str,
    data_series,
    dist_type: str,
    bins,
) -> None:
    """Write the current distribution (+ optional fit) as pgfplots CSV + .tex."""
    if not param or param == "-" or data_series is None or len(data_series) == 0:
        QMessageBox.information(
            parent, "TeX Export",
            "Nothing to export — run a simulation and pick a measurement first.",
        )
        return

    from chipify import export_latex

    out_dir = _latex_dir()
    try:
        written = export_latex.generate_latex_export(
            param, data_series, dist_type, bins, out_dir,
        )
    except Exception as exc:  # noqa: BLE001
        log.exception("Histogram LaTeX export failed: %s", exc)
        QMessageBox.critical(parent, "TeX Export", f"LaTeX export failed:\n{exc}")
        return
    if written is None:
        QMessageBox.information(
            parent, "TeX Export",
            f"{param} carries no numeric data in this run — nothing exported.",
        )
        return
    csv_path, tex_path = written
    log.info("Exported %s histogram LaTeX to %s", param, out_dir)
    QMessageBox.information(
        parent, "TeX Export",
        f"Exported {param} to:\n  {tex_path}\n  {csv_path}",
    )


def export_overlay_latex(
    parent: QWidget,
    kind: str,
    analysis_dir: str,
    run_ids: list[str],
    signals: list[str],
    equations: list | None = None,
) -> None:
    """Write a transient / DC / Bode overlay as pgfplots CSV + .tex."""
    if not analysis_dir:
        QMessageBox.information(
            parent, "TeX Export",
            "No analysis data found. Run a simulation first.",
        )
        return
    if not signals:
        QMessageBox.information(parent, "TeX Export", "Select at least one signal first.")
        return

    from chipify import export_latex

    gen_name, name = _OVERLAY.get(kind, _OVERLAY["transient"])
    generate = getattr(export_latex, gen_name)
    out_dir = _latex_dir()
    try:
        csv_path, tex_path = generate(
            out_dir, name, analysis_dir, run_ids, signals, equations=equations,
        )
    except ValueError as exc:
        # Raised when the current selection yields no plottable data.
        QMessageBox.information(parent, "TeX Export", str(exc))
        return
    except Exception as exc:  # noqa: BLE001
        log.exception("Overlay LaTeX export failed: %s", exc)
        QMessageBox.critical(parent, "TeX Export", f"Export failed:\n{exc}")
        return
    log.info("Exported %s overlay LaTeX to %s", kind, out_dir)
    QMessageBox.information(parent, "TeX Export", f"Exported:\n  {tex_path}\n  {csv_path}")
