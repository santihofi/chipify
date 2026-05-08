"""
equation_service.py – Sandboxed evaluation of custom scalar and transient equations.

No tkinter imports.  Callers pass equation lists; this service applies them
to DataFrames and returns diagnostic log lines.  Backed by SafeEvaluator.
"""
from __future__ import annotations

import logging
from typing import Any

import pandas as pd

from chipify.expression import SafeEvaluator, ExpressionError

log = logging.getLogger("chipify.gui.services.equations")

_evaluator = SafeEvaluator()


def apply_scalar_equations(
    df: pd.DataFrame,
    equations: list[dict[str, str]],
    sim_error_col: str = "sim_error",
) -> tuple[pd.DataFrame, list[str], list[str]]:
    """
    Apply a list of scalar (per-row) equations to *df*.

    Equations from ``ExpressionPlugin`` subclasses in the plugin directory are
    appended automatically after the explicitly supplied *equations* list.

    Parameters
    ----------
    df:
        The simulation result DataFrame.
    equations:
        List of ``{"name": "col_name", "expr": "expression"}`` dicts.
    sim_error_col:
        Column name used to count valid rows in log messages.

    Returns
    -------
    (df_out, derived_names, log_lines)
        ``df_out``        – updated DataFrame with new columns appended.
        ``derived_names`` – names of successfully added columns.
        ``log_lines``     – human-readable per-equation status lines.
    """
    from chipify.plugin_loader import get_expression_plugins
    plugin_equations: list[dict[str, str]] = []
    for cls in get_expression_plugins():
        name = getattr(cls, "name", "").strip()
        expr = getattr(cls, "expression", "").strip()
        if name and expr:
            plugin_equations.append({"name": name, "expr": expr})

    all_equations = list(equations) + plugin_equations

    derived: list[str] = []
    log_lines: list[str] = []

    for eq in all_equations:
        name = eq.get("name", "").strip()
        expr = eq.get("expr", "").strip()
        if not name or not expr:
            continue
        try:
            df = _evaluator.evaluate_dataframe_column(df, name, expr)
            n_valid = int((df[sim_error_col] == "None").sum()) if sim_error_col in df.columns else len(df)
            log_lines.append(f"[✓] {name} = {expr}  →  ok  ({n_valid} rows)")
            log.debug("Applied scalar equation: %s = %s", name, expr)
            derived.append(name)
        except (ExpressionError, ValueError) as exc:
            log_lines.append(f"[✗] {name} = {expr}  →  {exc}")
            log.warning("Scalar equation %r failed: %s", name, exc)
        except Exception as exc:
            log_lines.append(f"[✗] {name} = {expr}  →  {exc}")
            log.warning("Scalar equation %r unexpected error: %s", name, exc)

    return df, derived, log_lines


def apply_transient_equations(
    df_chunk: pd.DataFrame,
    equations: list[dict[str, str]],
) -> pd.DataFrame:
    """
    Apply transient (waveform-level) equations to a single run's DataFrame.

    Equations may reference SPICE-style column names such as ``v(outp)``.
    Non-identifier column names are translated automatically by SafeEvaluator.

    Parameters
    ----------
    df_chunk:
        A single-run waveform DataFrame (time + signal columns).
    equations:
        List of ``{"name": "col_name", "expr": "expression"}`` dicts.

    Returns
    -------
    pd.DataFrame
        The input DataFrame with any successfully computed columns appended.
        Failed equations are silently skipped (the caller logs at DEBUG).
    """
    for eq in equations:
        name = eq.get("name", "").strip()
        expr = eq.get("expr", "").strip()
        if not name or not expr:
            continue
        try:
            df_chunk = _evaluator.evaluate_dataframe_column(df_chunk, name, expr)
        except Exception as exc:
            log.debug("Transient equation %r skipped: %s", name, exc)

    return df_chunk
