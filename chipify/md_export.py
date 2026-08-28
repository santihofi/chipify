# Copyright (c) 2026 Santiago Hofwimmer
"""
md_export.py – Plain Markdown report generator for Chipify.

Produces a compact, text-only `.md` suitable for:
- commit messages / pull-request descriptions
- pasting into Confluence / GitHub issues
- CI artefact archives

Usage (CLI):
    chipify --markdown out/report.md

Usage (programmatic):
    from chipify import md_export
    md_export.generate_md_report(df, stim, yaml_path, "report.md")
"""

from __future__ import annotations
import datetime
import math
from pathlib import Path

import pandas as pd

from chipify.uikit.services import measurements as _meas


# ── internal helpers ──────────────────────────────────────────────────────────

def _build_global_pass(df: pd.DataFrame) -> pd.DataFrame:
    # Single source of truth for sim_error normalisation + global_pass.
    from chipify import data_loader as _dl
    return _dl.prepare_results(df)


def _fmt(v) -> str:
    if v is None or (isinstance(v, float) and math.isnan(v)):
        return "—"
    if abs(v) >= 1e6:
        return f"{v/1e6:.4g} M"
    if abs(v) >= 1e3:
        return f"{v/1e3:.4g} k"
    if abs(v) >= 1:
        return f"{v:.4g}"
    if abs(v) >= 1e-3:
        return f"{v*1e3:.4g} m"
    if abs(v) >= 1e-6:
        return f"{v*1e6:.4g} µ"
    return f"{v:.4g}"


def _status_cell(r) -> str:
    """Markdown for one measurement's verdict.

    ERROR is kept distinct from FAIL on purpose: it means the measurement could
    not be taken at all, which the reader has to chase in the simulator log
    rather than in the design.
    """
    if r.status == _meas.STATUS_ERROR:
        return f"**ERROR** ({r.error_n}/{r.total_n})"
    if r.status == _meas.STATUS_FAIL:
        return f"**FAIL** ({r.fail_n})"
    return "PASS"


def _md_table(rows) -> str:
    lines = [
        "| Parameter | Sim Min | Sim Typ | Sim Max | Spec Min | Spec Max | Cpk | Status |",
        "|-----------|---------|---------|---------|----------|----------|-----|--------|",
    ]
    for r in rows:
        cpk_s = f"{r.cpk:.2f}" if not math.isnan(r.cpk) else "—"
        lines.append(
            f"| {r.name} | {_fmt(r.sim_min)} | {_fmt(r.sim_typ)} | {_fmt(r.sim_max)} "
            f"| {_fmt(r.spec_min)} | {_fmt(r.spec_max)} | {cpk_s} | {_status_cell(r)} |"
        )
    return "\n".join(lines)


# ── public API ────────────────────────────────────────────────────────────────

def generate_md_report(
    df: pd.DataFrame,
    stim,
    yaml_path: str,
    output_path: str,
    sim_duration_sec: float | None = None,
) -> str:
    """
    Generate a plain Markdown report and write it to *output_path*.

    Returns *output_path* on success.
    """
    prepared = _build_global_pass(df)
    valid_df  = prepared[prepared["sim_error"] == "None"]
    # The service scopes errors per testbench, so it needs the full frame:
    # a row-filtered one hides the measurements of every testbench that
    # worked, and reports the ones that crashed as a clean PASS.
    rows      = _meas.measurement_rows(prepared, stim)

    from chipify import data_loader as _dl
    s = _dl.result_summary(prepared)
    total, crashes, valid, passed, yield_ = (
        s.total, s.crashes, s.valid, s.passed, s.yield_pct)

    yaml_name = Path(yaml_path).name
    now       = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    yield_badge = "PASS" if yield_ == 100.0 else ("WARN" if yield_ > 0 else "FAIL")

    swept = []
    for name, vals in stim.params.items():
        try:
            if hasattr(vals, "__len__") and not isinstance(vals, str) and len(vals) > 1:
                swept.append(f"`{name}` ({len(vals)} values)")
        except Exception:
            pass

    lines = [
        "# Chipify Simulation Report",
        "",
        "| | |",
        "|---|---|",
        f"| **Datasheet** | `{yaml_name}` |",
        f"| **Date** | {now} |",
        f"| **Total Runs** | {total} |",
        f"| **Crashes** | {crashes} |",
        f"| **Valid Runs** | {valid} |",
        f"| **Passed** | {passed} |",
        f"| **Global Yield** | {yield_:.1f}% [{yield_badge}] |",
    ]
    if sim_duration_sec is not None:
        lines.append(f"| **Duration** | {sim_duration_sec:.1f} s |")
    if swept:
        lines.append(f"| **Swept** | {', '.join(swept)} |")
    lines += [
        "",
        "## Measurement Results",
        "",
        _md_table(rows),
        "",
    ]

    # Per-param fail details
    fails = [r for r in rows if r.status == _meas.STATUS_FAIL]
    if fails:
        lines += ["## Failing Parameters", ""]
        for r in fails:
            # Per-measurement denominator, not the row-level `valid` count:
            # a sibling testbench crashing drives that to zero and would
            # render this as "1 fail(s) out of 0 valid runs".
            usable = r.total_n - r.error_n
            lines.append(
                f"- **{r.name}**: {r.fail_n} fail(s) out of {usable} usable runs. "
                f"Spec [{_fmt(r.spec_min)}, {_fmt(r.spec_max)}], "
                f"simulated [{_fmt(r.sim_min)}, {_fmt(r.sim_max)}]."
            )
        lines.append("")

    # Simulation errors. A testbench that never produced a value used to be
    # absent from this report entirely, with its parameters reported as PASS.
    errors = _meas.error_rows(prepared, stim)
    if errors:
        lines += ["## Simulation Errors", ""]
        for e in errors:
            conds = ", ".join(f"`{k}={v}`" for k, v in e.conditions.items())
            lines.append(
                f"- **{e.tb_path}** [{e.kind}] - {e.run_n}/{e.total_n} run(s)"
                + (f", first at {conds}" if conds else "")
            )
            lines.append(f"  - `{e.message}`")
            if e.measurements:
                lines.append(f"  - affects: {', '.join(e.measurements)}")
        lines.append("")

    # Append any installed ReportPlugin sections
    try:
        from chipify.plugin_loader import get_report_plugins
        for cls in get_report_plugins():
            try:
                lines.append(cls().render_md(valid_df, stim))
            except Exception:
                pass
    except Exception:
        pass

    content = "\n".join(lines)
    out_path = Path(output_path)
    out_path.resolve().parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(content, encoding="utf-8")
    return output_path
