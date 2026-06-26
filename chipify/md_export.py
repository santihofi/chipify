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
import os

import pandas as pd


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


def _measurement_rows(valid_df: pd.DataFrame, stim) -> list[dict]:
    rows = []
    for test in stim.tests:
        for val_obj in test.value_lst:
            p = val_obj.name
            if p not in valid_df.columns:
                continue
            data = valid_df[p].dropna()
            lo = getattr(val_obj, "vmin", getattr(val_obj, "min", None))
            hi = getattr(val_obj, "vmax", getattr(val_obj, "max", None))

            cpk = float("nan")
            if len(data) >= 2:
                mu, sigma = data.mean(), data.std()
                if sigma > 0:
                    cpks = []
                    if lo is not None: cpks.append((mu - lo) / (3 * sigma))
                    if hi is not None: cpks.append((hi - mu) / (3 * sigma))
                    if cpks: cpk = min(cpks)

            pass_col = f"{p}_pass"
            passed = pass_col in valid_df.columns and bool(valid_df[pass_col].all())
            fail_n = int((valid_df[pass_col] == False).sum()) if pass_col in valid_df.columns else 0

            rows.append({
                "name":    p,
                "min":     data.min()  if not data.empty else float("nan"),
                "typ":     data.mean() if not data.empty else float("nan"),
                "max":     data.max()  if not data.empty else float("nan"),
                "spec_lo": lo,
                "spec_hi": hi,
                "cpk":     cpk,
                "passed":  passed,
                "fail_n":  fail_n,
            })
    return rows


def _md_table(rows: list[dict], n_valid: int) -> str:
    lines = [
        "| Parameter | Sim Min | Sim Typ | Sim Max | Spec Min | Spec Max | Cpk | Status |",
        "|-----------|---------|---------|---------|----------|----------|-----|--------|",
    ]
    for r in rows:
        cpk_s = f"{r['cpk']:.2f}" if not math.isnan(r["cpk"]) else "—"
        status = "PASS" if r["passed"] else f"**FAIL** ({r['fail_n']})"
        lines.append(
            f"| {r['name']} | {_fmt(r['min'])} | {_fmt(r['typ'])} | {_fmt(r['max'])} "
            f"| {_fmt(r['spec_lo'])} | {_fmt(r['spec_hi'])} | {cpk_s} | {status} |"
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
    rows      = _measurement_rows(valid_df, stim)

    from chipify import data_loader as _dl
    s = _dl.result_summary(prepared)
    total, crashes, valid, passed, yield_ = (
        s.total, s.crashes, s.valid, s.passed, s.yield_pct)

    yaml_name = os.path.basename(yaml_path)
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
        _md_table(rows, valid),
        "",
    ]

    # Per-param fail details
    fails = [r for r in rows if not r["passed"]]
    if fails:
        lines += ["## Failing Parameters", ""]
        for r in fails:
            lines.append(
                f"- **{r['name']}**: {r['fail_n']} fail(s) out of {valid} valid runs. "
                f"Spec [{_fmt(r['spec_lo'])}, {_fmt(r['spec_hi'])}], "
                f"simulated [{_fmt(r['min'])}, {_fmt(r['max'])}]."
            )
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
    os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(content)
    return output_path
