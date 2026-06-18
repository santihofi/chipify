# Copyright (c) 2026 Santiago Hofwimmer
"""
measurements.py – Framework-agnostic per-parameter measurement statistics.

Computes the rows shown in the Measurements table (sim min/typ/max, spec
limits, Cpk, sigma level, pass/fail) from a *valid-rows-only* result
DataFrame and a ``util.Stimuli``. This is the authoritative version of the
logic that used to live inline in the CustomTkinter ``_measurement_snapshot``;
both GUIs (and, in time, the reports) can share it.

No GUI-toolkit imports — usable headlessly and unit-testable.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd


@dataclass
class MeasurementRow:
    """One row of the Measurements table.

    Numeric fields are raw values (format with :func:`fmt_value`); ``cpk_str``
    and ``sigma_str`` are pre-rendered because they carry the special
    ``INF`` / ``0.00`` / ``-`` cases that are not plain numbers.
    """
    name: str
    sim_min: float
    sim_typ: float
    sim_max: float
    spec_min: float | None
    spec_max: float | None
    cpk_str: str
    sigma_str: str
    status: str        # "PASS" | "FAIL"
    fail_n: int
    unit: str = ""     # optional engineering unit ("" when unspecified)


def fmt_value(val: Any) -> str:
    """Render a measurement value the way the table expects ('-' for empty)."""
    if val is None or pd.isna(val):
        return "-"
    return f"{val:.4g}"


def measurement_rows(valid_df: pd.DataFrame, stim: Any) -> list[MeasurementRow]:
    """Per-parameter statistics for every spec'd value in *stim*.

    Mirrors the legacy ``_measurement_snapshot`` row computation exactly,
    including the ``Cpk = min(lower, upper)`` convention and the zero-variance
    INF / 0.00 handling. Parameters not present in *valid_df* are skipped.
    """
    rows: list[MeasurementRow] = []
    for test in stim.tests:
        for val_obj in test.value_lst:
            name = val_obj.name
            if name not in valid_df.columns:
                continue

            data = valid_df[name].dropna()
            sim_min = float(data.min()) if not data.empty else np.nan
            sim_max = float(data.max()) if not data.empty else np.nan
            sim_typ = float(data.mean()) if not data.empty else np.nan
            sim_std = float(data.std()) if len(data) > 1 else 0.0

            v_min = getattr(val_obj, "vmin", getattr(val_obj, "min", None))
            v_max = getattr(val_obj, "vmax", getattr(val_obj, "max", None))

            cpk_vals: list[float] = []
            z_vals: list[float] = []
            if sim_std > 0:
                if v_min is not None:
                    cpk_vals.append(((sim_typ - v_min) / sim_std) / 3.0)
                    z_vals.append((sim_typ - v_min) / sim_std)
                if v_max is not None:
                    cpk_vals.append(((v_max - sim_typ) / sim_std) / 3.0)
                    z_vals.append((v_max - sim_typ) / sim_std)

            if cpk_vals:
                cpk_str = f"{min(cpk_vals):.2f}"
                sigma_str = f"{min(z_vals):.2f}σ"
            elif sim_std == 0.0 and (v_min is not None or v_max is not None):
                within = (v_min is None or sim_typ >= v_min) and (
                    v_max is None or sim_typ <= v_max
                )
                cpk_str = sigma_str = "INF" if within else "0.00"
            else:
                cpk_str = sigma_str = "-"

            pass_col = f"{name}_pass"
            if pass_col in valid_df.columns:
                passed = bool(valid_df[pass_col].all())
                fail_n = int((valid_df[pass_col] == False).sum())  # noqa: E712
            else:
                passed, fail_n = True, 0

            unit = getattr(val_obj, "unit", None) or ""

            rows.append(MeasurementRow(
                name=name,
                sim_min=sim_min, sim_typ=sim_typ, sim_max=sim_max,
                spec_min=v_min, spec_max=v_max,
                cpk_str=cpk_str, sigma_str=sigma_str,
                status="PASS" if passed else "FAIL", fail_n=fail_n,
                unit=str(unit),
            ))
    return rows


@dataclass
class EquationRow:
    """One row of the Equation-results table (a derived scalar column)."""
    name: str
    expr: str
    sim_min: float
    sim_typ: float
    sim_max: float


def equation_rows(
    valid_df: pd.DataFrame, equations: list[dict[str, str]] | None,
) -> list[EquationRow]:
    """Per-equation min/typ/max for each applied scalar equation column.

    *equations* is the ``custom_equations`` list (``{name, expr}`` dicts). Only
    equations whose column actually landed in *valid_df* (i.e. evaluated
    successfully and carry numeric data) produce a row.
    """
    rows: list[EquationRow] = []
    for eq in equations or []:
        name = (eq.get("name") or "").strip()
        expr = (eq.get("expr") or "").strip()
        if not name or name not in valid_df.columns:
            continue
        data = pd.to_numeric(valid_df[name], errors="coerce").dropna()
        if data.empty:
            continue
        rows.append(EquationRow(
            name=name, expr=expr,
            sim_min=float(data.min()),
            sim_typ=float(data.mean()),
            sim_max=float(data.max()),
        ))
    return rows


@dataclass
class WorstCase:
    """The worst failing run for one out-of-spec parameter.

    ``conditions`` maps each sweep-parameter name to its value in the run that
    produced ``worst_val`` — i.e. the corner/seed combination that triggered the
    worst violation.
    """
    name: str
    worst_val: float
    violation: str        # e.g. "< 0.3" or "> 0.5"
    fail_n: int
    total: int
    conditions: dict[str, Any]


def worst_cases(
    valid_df: pd.DataFrame, stim: Any, total: int,
) -> list[WorstCase]:
    """For each failing parameter, the single worst run and what triggered it.

    Mirrors the legacy Tk "Outliers & Fails" worst-case cards: a parameter is
    reported only if some valid run both fails its ``*_pass`` flag *and* lands
    outside a declared bound. When both bounds are violated (across different
    runs) the side with the larger absolute excess is reported.
    """
    out: list[WorstCase] = []
    param_cols = list(getattr(stim, "params", {}) or {})
    for test in stim.tests:
        for val_obj in test.value_lst:
            name = val_obj.name
            pass_col = f"{name}_pass"
            if name not in valid_df.columns or pass_col not in valid_df.columns:
                continue
            failed = valid_df[valid_df[pass_col] == False]  # noqa: E712
            if failed.empty:
                continue

            series = failed[name].dropna()
            if series.empty:
                continue
            v_min = getattr(val_obj, "vmin", getattr(val_obj, "min", None))
            v_max = getattr(val_obj, "vmax", getattr(val_obj, "max", None))

            candidates: list[tuple[float, float, Any, str]] = []
            if v_min is not None and float(series.min()) < v_min:
                candidates.append((v_min - float(series.min()), float(series.min()),
                                   series.idxmin(), f"< {fmt_value(v_min)}"))
            if v_max is not None and float(series.max()) > v_max:
                candidates.append((float(series.max()) - v_max, float(series.max()),
                                   series.idxmax(), f"> {fmt_value(v_max)}"))
            if not candidates:
                continue
            _, worst_val, worst_idx, violation = max(candidates, key=lambda c: c[0])

            worst_row = failed.loc[worst_idx]
            conditions = {k: worst_row[k] for k in param_cols if k in worst_row}
            out.append(WorstCase(
                name=name, worst_val=float(worst_val), violation=violation,
                fail_n=int(len(failed)), total=int(total), conditions=conditions,
            ))
    return out
