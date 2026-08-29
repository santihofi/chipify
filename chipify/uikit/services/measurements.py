# Copyright (c) 2026 Santiago Hofwimmer
"""
measurements.py – Framework-agnostic per-parameter measurement statistics.

Computes the rows shown in the Measurements table (sim min/typ/max, spec
limits, Cpk, sigma level, PASS/FAIL/ERROR) from a **full** result DataFrame
and a ``util.Stimuli``. The single authoritative implementation: the Qt
Measurements tab, the CLI analyzer, and the Markdown and PDF exporters all
read these helpers, so the four surfaces cannot disagree about a verdict.

Pass the *complete* frame, never one filtered through
``data_loader.valid_rows``. Validity is scoped per testbench here (see
``data_loader.measurement_ok_mask``): one testbench crashing must not hide the
measurements of the testbenches that succeeded, and a measurement with no
usable run at all reports ERROR rather than an empty, vacuously-true PASS.

No GUI-toolkit imports — usable headlessly and unit-testable.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any

import numpy as np
import pandas as pd

from chipify import data_loader as _dl

#: Status of a measurement row. ``ERROR`` outranks both: it means at least one
#: run could not produce a trustworthy value at all (the testbench failed, or
#: the value came back NaN), which is a different problem from a value that was
#: measured correctly and landed out of spec.
STATUS_PASS = "PASS"
STATUS_FAIL = "FAIL"
STATUS_ERROR = "ERROR"


@dataclass
class MeasurementRow:
    """One row of the Measurements table.

    Numeric fields are raw values (format with :func:`fmt_value`); ``cpk_str``
    and ``sigma_str`` are pre-rendered because they carry the special
    ``INF`` / ``0.00`` / ``-`` cases that are not plain numbers. ``cpk`` and
    ``sigma`` carry the same quantities as plain floats so report exporters can
    apply their own formatting.
    """
    name: str
    sim_min: float
    sim_typ: float
    sim_max: float
    spec_min: float | None
    spec_max: float | None
    cpk_str: str
    sigma_str: str
    status: str        # "PASS" | "FAIL" | "ERROR"
    fail_n: int
    unit: str = ""     # optional engineering unit ("" when unspecified)
    cpk: float = float("nan")
    sigma: float = float("nan")
    #: Runs where this measurement produced no trustworthy value.
    error_n: int = 0
    #: Runs attempted (the full sweep, errored runs included).
    total_n: int = 0
    #: Representative error for this measurement ("" when there were none).
    error_msg: str = ""

    @property
    def errored(self) -> bool:
        """True when at least one run failed to produce a value."""
        return self.error_n > 0


def fmt_value(val: Any) -> str:
    """Render a measurement value the way the table expects ('-' for empty)."""
    if val is None or pd.isna(val):
        return "-"
    return f"{val:.4g}"


def fmt_eng(val: Any) -> str:
    """Render a value with an engineering-unit suffix (``373.5 m``, ``2.686 G``).

    Shared by the Markdown and PDF reports so the same measurement does not
    appear as ``373.5 m`` in one and ``0.3735`` in the other. The GUI table
    keeps :func:`fmt_value`'s plain 4-digit form, where column width matters
    more than readability of the magnitude.
    """
    if val is None or (isinstance(val, float) and math.isnan(val)):
        return "—"
    if not isinstance(val, (int, float, np.number)) or isinstance(val, bool):
        return str(val)
    v = float(val)
    for limit, scale, suffix in (
        (1e9, 1e-9, " G"), (1e6, 1e-6, " M"), (1e3, 1e-3, " k"),
        (1.0, 1.0, ""), (1e-3, 1e3, " m"), (1e-6, 1e6, " µ"),
    ):
        if abs(v) >= limit:
            return f"{v * scale:.4g}{suffix}"
    return f"{v:.4g}"


def _tb_path(test: Any) -> str:
    """Testbench identity, tolerating stand-in stim objects without one.

    An empty path resolves to no per-testbench column, so the error masks fall
    back to the row-level ``sim_error`` — the pre-existing behaviour.
    """
    return str(getattr(test, "tb_path", "") or "")


def _spec_bounds(val_obj: Any) -> tuple[float | None, float | None]:
    """The declared ``(min, max)`` of a datasheet value, either attribute name."""
    return (
        getattr(val_obj, "vmin", getattr(val_obj, "min", None)),
        getattr(val_obj, "vmax", getattr(val_obj, "max", None)),
    )


def _representative_error(df: pd.DataFrame, tb_path: str) -> str:
    """The most frequent error recorded against *tb_path* ("" when none)."""
    col = _dl.tb_error_col(tb_path)
    if col not in df.columns:
        col = "sim_error"
        if col not in df.columns:
            return ""
    errors = df[col].astype(str)
    errors = errors[errors != _dl.NO_ERROR]
    if errors.empty:
        return ""
    return str(errors.value_counts().idxmax())


def measurement_rows(df: pd.DataFrame, stim: Any) -> list[MeasurementRow]:
    """Per-parameter statistics for every spec'd value in *stim*.

    Keeps the ``Cpk = min(lower, upper)`` convention and the zero-variance
    INF / 0.00 handling. Parameters not present in *df* are skipped.

    *df* must be the **full** results frame, not one pre-filtered through
    :func:`data_loader.valid_rows`. Errors are scoped per testbench here, so a
    testbench that crashed must not remove the rows of the testbenches that
    succeeded — pre-filtering would discard exactly the data this function
    exists to report. Two consequences of doing it this way:

    * a measurement whose runs all errored reports ``ERROR``, where the old
      row-filtered code computed ``all()`` over an *empty* selection and got
      ``True`` back — reporting a clean ``PASS`` for a run that never produced
      a single value;
    * ``PASS`` now requires at least one usable run, never vacuous truth.
    """
    rows: list[MeasurementRow] = []
    total_n = len(df)
    for test in stim.tests:
        tb_error = None  # resolved lazily, once per testbench that needs it
        for val_obj in test.value_lst:
            name = val_obj.name
            if name not in df.columns:
                continue

            ok = _dl.measurement_ok_mask(df, _tb_path(test), name)
            usable = df[ok]
            error_n = int((~ok).sum())

            data = usable[name].dropna()
            sim_min = float(data.min()) if not data.empty else np.nan
            sim_max = float(data.max()) if not data.empty else np.nan
            sim_typ = float(data.mean()) if not data.empty else np.nan
            sim_std = float(data.std()) if len(data) > 1 else 0.0

            v_min, v_max = _spec_bounds(val_obj)

            cpk_vals: list[float] = []
            z_vals: list[float] = []
            if sim_std > 0:
                if v_min is not None:
                    cpk_vals.append(((sim_typ - v_min) / sim_std) / 3.0)
                    z_vals.append((sim_typ - v_min) / sim_std)
                if v_max is not None:
                    cpk_vals.append(((v_max - sim_typ) / sim_std) / 3.0)
                    z_vals.append((v_max - sim_typ) / sim_std)

            cpk = sigma = float("nan")
            if cpk_vals:
                cpk, sigma = min(cpk_vals), min(z_vals)
                cpk_str = f"{cpk:.2f}"
                sigma_str = f"{sigma:.2f}σ"
            elif sim_std == 0.0 and not data.empty and (
                v_min is not None or v_max is not None
            ):
                within = (v_min is None or sim_typ >= v_min) and (
                    v_max is None or sim_typ <= v_max
                )
                cpk_str = sigma_str = "INF" if within else "0.00"
            else:
                cpk_str = sigma_str = "-"

            # Verdict over the usable runs only. An empty selection is never a
            # pass: `Series([]).all()` is True, which is what let a run where
            # everything crashed report PASS.
            pass_col = f"{name}_pass"
            if pass_col in df.columns:
                verdicts = df.loc[ok, pass_col]
                passed = bool(verdicts.all()) if len(verdicts) else False
                fail_n = int((verdicts == False).sum())  # noqa: E712
            else:
                passed, fail_n = True, 0

            # No usable value is an ERROR, never a verdict: reporting PASS or
            # FAIL would claim a measurement that was never actually taken.
            if error_n or data.empty:
                status = STATUS_ERROR
                if tb_error is None:
                    tb_error = _representative_error(df, _tb_path(test))
                error_msg = tb_error or (
                    f"{name}: no value in {error_n} run(s)" if error_n
                    else f"{name}: no runs"
                )
            else:
                status = STATUS_PASS if passed else STATUS_FAIL
                error_msg = ""

            rows.append(MeasurementRow(
                name=name,
                sim_min=sim_min, sim_typ=sim_typ, sim_max=sim_max,
                spec_min=v_min, spec_max=v_max,
                cpk_str=cpk_str, sigma_str=sigma_str,
                status=status, fail_n=fail_n,
                unit=str(getattr(val_obj, "unit", None) or ""),
                cpk=cpk, sigma=sigma,
                error_n=error_n, total_n=total_n, error_msg=error_msg,
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

    *equations* is the datasheet's scalar-equation list (``{name, expr}``
    dicts, see ``equation_service.scalar_equations``). Only equations whose
    column actually landed in *valid_df* (i.e. evaluated successfully and
    carry numeric data) produce a row.
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
    df: pd.DataFrame, stim: Any, total: int,
) -> list[WorstCase]:
    """For each failing parameter, the single worst run and what triggered it.

    A parameter is reported only if some usable run both fails its ``*_pass``
    flag *and* lands outside a declared bound. When both bounds are violated
    (across different runs) the side with the larger absolute excess is
    reported.

    Takes the **full** results frame (see :func:`measurement_rows`) and scopes
    validity per measurement. A parameter whose status is ``ERROR`` is still
    reported here when its usable runs violate a bound, so partial-data
    information is not lost behind the error badge.
    """
    out: list[WorstCase] = []
    param_cols = list(getattr(stim, "params", {}) or {})
    for test in stim.tests:
        for val_obj in test.value_lst:
            name = val_obj.name
            pass_col = f"{name}_pass"
            if name not in df.columns or pass_col not in df.columns:
                continue
            ok = _dl.measurement_ok_mask(df, _tb_path(test), name)
            failed = df[ok & (df[pass_col] == False)]  # noqa: E712
            if failed.empty:
                continue

            series = failed[name].dropna()
            if series.empty:
                continue
            v_min, v_max = _spec_bounds(val_obj)

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


@dataclass
class ErrorRow:
    """One distinct simulation failure, with the runs it affected.

    Errors are grouped per *(testbench, message)* rather than listed per run: a
    broken schematic fails identically in every corner, and a hundred copies of
    the same line teaches nothing that the count does not.
    """
    tb_path: str
    kind: str                  #: leading token, e.g. "CRASH", "ENGINE_ERROR"
    message: str               #: the full recorded message
    run_n: int                 #: runs affected by this error
    total_n: int               #: runs attempted
    measurements: list[str] = field(default_factory=list)
    #: Sweep point of the first affected run — which corner broke.
    conditions: dict[str, Any] = field(default_factory=dict)


#: Uppercase tokens the engines put in their messages, most specific first.
_ERROR_KINDS = (
    "TEMPLATE_RENDER_ERROR", "NO_MATCHING_SIGNALS", "NO_MY_DATA_FOUND",
    "RAW_PARSE_ERROR", "INVALID_OUTPUT", "MEASURE_ERROR", "ENGINE_ERROR",
    "NO_RAW_FILE", "WORKER_LOST", "TIMEOUT", "ABORTED", "CRASH",
)

#: Failures phrased as prose rather than a token (simulator.generate_templates
#: and the per-testbench guards in _simulate_single_case). Without these the
#: whole netlist-generation family collapses into a bare "ERROR", which is the
#: least useful thing the column could say.
_ERROR_PHRASES = (
    ("netlist generation failed", "NETLIST_ERROR"),
    ("no netlist template", "NO_TEMPLATE"),
    ("engine unavailable", "ENGINE_UNAVAILABLE"),
)


def error_kind(message: str) -> str:
    """Classify a recorded error message into a short kind token."""
    for kind in _ERROR_KINDS:
        if kind in message:
            return kind
    lowered = message.lower()
    for phrase, kind in _ERROR_PHRASES:
        if phrase in lowered:
            return kind
    return "ERROR"


def error_rows(df: pd.DataFrame, stim: Any) -> list[ErrorRow]:
    """Every distinct simulation error in *df*, grouped by testbench + message.

    Reads the per-testbench ``<tb_path>__error`` columns, falling back to the
    row-level ``sim_error`` for result frames written before those existed.
    Takes the **full** results frame.
    """
    out: list[ErrorRow] = []
    total_n = len(df)
    if not total_n:
        return out
    param_cols = list(getattr(stim, "params", {}) or {})

    for test in stim.tests:
        tb = _tb_path(test)
        col = _dl.tb_error_col(tb)
        if col not in df.columns:
            # Pre-per-testbench CSV: sim_error is all we have, and it is not
            # attributable to a single testbench. Report it once, under the
            # testbench named in the message.
            if "sim_error" not in df.columns:
                continue
            col = "sim_error"

        errors = df[col].astype(str)
        affected = df[errors != _dl.NO_ERROR]
        if affected.empty:
            continue
        if col == "sim_error":
            affected = affected[
                affected[col].astype(str).str.startswith(f"{tb}:")
            ]
            if affected.empty:
                continue

        names = [v.name for v in test.value_lst]
        for message, group in affected.groupby(affected[col].astype(str), sort=False):
            first = group.iloc[0]
            out.append(ErrorRow(
                tb_path=tb,
                kind=error_kind(str(message)),
                message=str(message),
                run_n=int(len(group)),
                total_n=total_n,
                measurements=names,
                conditions={k: first[k] for k in param_cols if k in first},
            ))
    return out
