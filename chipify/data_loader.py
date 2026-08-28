# Copyright (c) 2026 Santiago Hofwimmer
"""
data_loader.py – Load simulation result CSVs and compute plot-column metadata.

No tkinter imports.  Functions return DataFrames and metadata dicts that the
history controller or tab views can read from AppState.
"""
from __future__ import annotations

import logging
import os
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

log = logging.getLogger("chipify.data_loader")


# ── PlotColumns ───────────────────────────────────────────────────────────────

@dataclass
class PlotColumns:
    """
    Separates discrete sweep parameters from continuous output columns.

    This enforces the invariant described in context.md §3: the Corner Yield
    Matrix requires discrete inputs and must never receive continuous outputs.
    Conversely, distribution plots (histogram) must only offer *outputs* —
    the histogram of an input parameter is just the sweep grid, so
    ``output_cols`` excludes every datasheet parameter column.
    """
    sweep_params: list[str] = field(default_factory=list)
    all_numeric_cols: list[str] = field(default_factory=list)
    #: ``all_numeric_cols`` minus input-parameter columns (swept or constant)
    #: and per-run bookkeeping — what measurement/distribution dropdowns show.
    output_cols: list[str] = field(default_factory=list)


# ── DataFrame helpers ─────────────────────────────────────────────────────────

#: Suffix of the per-testbench error column (``"<tb_path>__error"``).
#:
#: ``sim_error`` is a single per-row slot, so one failing testbench poisons the
#: whole row — including the measurements of every *other* testbench in the same
#: run. The per-testbench columns keep a failure scoped to the testbench that
#: caused it; ``sim_error`` remains the row-level roll-up used for yield.
TB_ERROR_SUFFIX = "__error"

#: Value meaning "no error" in every error column.
NO_ERROR = "None"


def tb_error_col(tb_path: str) -> str:
    """Name of the per-testbench error column for *tb_path*."""
    return f"{tb_path}{TB_ERROR_SUFFIX}"


def tb_error_cols(df: pd.DataFrame) -> list[str]:
    """Every per-testbench error column present in *df*."""
    return [c for c in df.columns if c.endswith(TB_ERROR_SUFFIX)]


def _clean_error_series(ser: pd.Series) -> pd.Series:
    """Coerce an error column to plain strings with ``'None'`` for 'no error'."""
    out = ser.fillna(NO_ERROR).astype(str)
    out[out.str.lower() == "nan"] = NO_ERROR
    return out


def _is_clean_error_series(ser: pd.Series) -> bool:
    """True when *ser* already satisfies the error-column invariants.

    The dtype guard matters — a CSV whose error column is all-NaN loads as
    float, where ``.str`` would raise.
    """
    return bool(
        ser.dtype == object
        and not ser.isna().any()
        and ser.map(lambda v: isinstance(v, str)).all()
        and not (ser.str.lower() == "nan").any()
    )


def valid_rows(df: pd.DataFrame) -> pd.DataFrame:
    """
    Return only the rows where ``sim_error == 'None'``.

    Row-level filter for plotting and yield statistics: a row is kept only when
    *every* testbench in it succeeded. Never filter ``sim_error`` inline in tab
    code.

    This is deliberately **not** the filter for per-measurement statistics — a
    row dropped here may still hold perfectly good data for the testbenches that
    did succeed. Use :func:`measurement_ok_mask` for those.
    """
    if "sim_error" not in df.columns:
        return df
    return df[df["sim_error"] == NO_ERROR]


def tb_ok_mask(df: pd.DataFrame, tb_path: str) -> pd.Series:
    """Boolean mask of the rows where testbench *tb_path* itself completed.

    Falls back to the row-level ``sim_error`` when the per-testbench column is
    absent, so result CSVs written before per-testbench errors existed keep
    loading with their original semantics.
    """
    col = tb_error_col(tb_path)
    if col in df.columns:
        return _clean_error_series(df[col]) == NO_ERROR
    if "sim_error" in df.columns:
        return _clean_error_series(df["sim_error"]) == NO_ERROR
    return pd.Series(True, index=df.index)


def measurement_ok_mask(df: pd.DataFrame, tb_path: str, name: str) -> pd.Series:
    """Boolean mask of the rows holding usable data for measurement *name*.

    A measurement is usable when its testbench completed **and** the value is
    not NaN. The NaN term matters on its own: an engine that cannot resolve a
    signal records ``nan`` while leaving the error columns clean (see
    ``engines/vacask.py``), which would otherwise be indistinguishable from a
    genuine out-of-spec result.
    """
    ok = tb_ok_mask(df, tb_path)
    if name not in df.columns:
        return pd.Series(False, index=df.index)
    return ok & df[name].notna()


#: Suffix of the per-testbench verdict column (``"<tb_path>_overall_pass"``).
TB_PASS_SUFFIX = "_overall_pass"


def testbench_names(df: pd.DataFrame) -> list[str]:
    """Testbench paths present in *df*, in column order.

    Read from both the verdict and the error columns: a frame can carry one
    family without the other (an older CSV, or a hand-built test frame), and
    either one names the testbench.
    """
    names: list[str] = []
    for col in df.columns:
        if col.endswith(TB_PASS_SUFFIX) and col != "global" + TB_PASS_SUFFIX:
            name = col[: -len(TB_PASS_SUFFIX)]
        elif col.endswith(TB_ERROR_SUFFIX):
            name = col[: -len(TB_ERROR_SUFFIX)]
        else:
            continue
        if name and name not in names:
            names.append(name)
    return names


def errored_testbenches(df: pd.DataFrame) -> list[str]:
    """Testbenches that failed in at least one row of *df*."""
    return [tb for tb in testbench_names(df)
            if tb_error_col(tb) in df.columns and not tb_ok_mask(df, tb).all()]


def measurement_owners(stim: Any) -> dict[str, str]:
    """Map every measurement name in *stim* to the testbench that produces it.

    Covers both the spec'd values and the ``measure:`` expression results — the
    Analytics tab offers the latter as plottable measurements too, so they need
    an owner or they would silently escape error scoping.
    """
    owners: dict[str, str] = {}
    for test in getattr(stim, "tests", None) or []:
        tb = str(getattr(test, "tb_path", "") or "")
        for val_obj in getattr(test, "value_lst", None) or []:
            owners.setdefault(str(val_obj.name), tb)
        for name in (getattr(test, "measure", None) or {}):
            owners.setdefault(str(name), tb)
    return owners


def plot_rows(df: pd.DataFrame, stim: Any,
              columns: Sequence[str] | None = None) -> pd.DataFrame:
    """Rows holding usable data for every measurement in *columns*.

    The filter plots must use. ``valid_rows`` is row-level, so one testbench
    failing in every corner empties it and blanks every chart in the app —
    including the charts of the testbenches that worked perfectly.

    Only names that are actually measurements constrain the result; sweep
    parameters, equation-derived columns and bookkeeping impose nothing, and an
    empty *columns* means "no constraint" (the whole frame). That is what lets a
    single-measurement histogram be scoped while a correlation heatmap or a
    yield matrix still sees every run.
    """
    if not columns:
        return df
    owners = measurement_owners(stim)
    mask: pd.Series | None = None
    for name in columns:
        tb = owners.get(name)
        if tb is None:          # not a measurement — no constraint
            continue
        col_mask = measurement_ok_mask(df, tb, name)
        mask = col_mask if mask is None else (mask & col_mask)
    return df if mask is None else df[mask]


def effective_pass(df: pd.DataFrame) -> pd.Series:
    """Per-row verdict over the testbenches that actually ran.

    ``global_pass`` ANDs *every* testbench, so one permanently broken testbench
    drives it false everywhere — a yield plot then reads a uniform 0 % and says
    nothing about the corners of the testbenches that worked. This ignores the
    testbenches that errored in that row instead.

    Returns floats (``1.0`` / ``0.0`` / ``NaN``), so a row where nothing ran
    drops out of ``pivot_table(aggfunc="mean")`` rather than counting as a fail.
    """
    names = [tb for tb in testbench_names(df)
             if tb + TB_PASS_SUFFIX in df.columns]
    if not names:
        if "global_pass" in df.columns:
            return df["global_pass"].astype(float)
        return pd.Series(1.0, index=df.index)

    ran = pd.Series(False, index=df.index)
    passed = pd.Series(True, index=df.index)
    for tb in names:
        ok = tb_ok_mask(df, tb)
        verdict = df[tb + TB_PASS_SUFFIX].fillna(False).astype(bool)
        ran = ran | ok
        # A testbench that did not run neither passes nor fails this row.
        passed = passed & (~ok | verdict)
    return passed.astype(float).where(ran, other=float("nan"))


def normalise_sim_error(df: pd.DataFrame) -> pd.DataFrame:
    """Ensure ``sim_error`` column exists, is string-typed, and has no NaNs."""
    if "sim_error" not in df.columns:
        df = df.copy()
        df["sim_error"] = NO_ERROR
        return df
    ser = df["sim_error"]
    if _is_clean_error_series(ser):
        return df
    df = df.copy()
    df["sim_error"] = _clean_error_series(ser)
    return df


def normalise_tb_errors(df: pd.DataFrame) -> pd.DataFrame:
    """Apply the error-column invariants to every ``<tb_path>__error`` column."""
    dirty = [c for c in tb_error_cols(df) if not _is_clean_error_series(df[c])]
    if not dirty:
        return df
    df = df.copy()
    for col in dirty:
        df[col] = _clean_error_series(df[col])
    return df


def compute_global_pass(df: pd.DataFrame) -> pd.DataFrame:
    """Add / recompute the ``global_pass`` boolean column."""
    df = df.copy()
    tb_pass_cols = [c for c in df.columns if c.endswith("_overall_pass")]
    df["global_pass"] = True
    for col in tb_pass_cols:
        df["global_pass"] = df["global_pass"] & df[col]
    return df


def prepare_results(df: pd.DataFrame) -> pd.DataFrame:
    """Normalise ``sim_error`` and (re)compute ``global_pass`` in one call.

    This is the single authoritative way to prepare a results DataFrame for
    yield computation — CLI, analyzer, and report exporters all delegate
    here rather than carrying their own copies of the logic. Idempotent.
    """
    return compute_global_pass(normalise_tb_errors(normalise_sim_error(df)))


@dataclass(frozen=True)
class ResultSummary:
    """Run-count + global-yield statistics for a results DataFrame."""
    total: int      #: number of simulation rows
    crashes: int    #: rows whose ``sim_error`` is not ``"None"``
    valid: int      #: ``total - crashes``
    passed: int     #: rows where ``global_pass`` is true
    yield_pct: float  #: ``passed / total * 100`` (``0.0`` for an empty frame)


def result_summary(df: pd.DataFrame) -> ResultSummary:
    """Compute the standard run summary (total / crashes / valid / yield).

    The single authoritative replacement for the count-and-divide block that
    the CLI, analyzer, report exporters, and plugin API each used to inline.
    Reads ``sim_error`` / ``global_pass`` directly with presence guards (a
    missing column contributes no crashes / no passes), so it is safe on both
    raw and :func:`prepare_results`-prepared frames without mutating them.
    """
    total = len(df)
    crashes = int((df["sim_error"] != "None").sum()) if "sim_error" in df.columns else 0
    passed = int(df["global_pass"].sum()) if "global_pass" in df.columns else 0
    yield_pct = passed / total * 100.0 if total else 0.0
    return ResultSummary(total=total, crashes=crashes, valid=total - crashes,
                         passed=passed, yield_pct=yield_pct)


def compute_plot_cols(df: pd.DataFrame, stim: Any) -> PlotColumns:
    """
    Derive the two column lists needed by the GUI dropdowns.

    Parameters
    ----------
    df:
        The (valid-rows-only) simulation result DataFrame.
    stim:
        ``util.Stimuli`` – used to identify discrete sweep parameters.

    Returns
    -------
    PlotColumns
    """
    numeric_cols = df.select_dtypes(include=[np.number]).columns.tolist()
    all_numeric = [c for c in numeric_cols if not c.endswith("_pass")]

    sweep: list[str] = []
    param_names: set[str] = set()
    if stim is not None:
        param_names = set(getattr(stim, "params", {}) or {})
        for p_name, p_values in stim.params.items():
            if p_name not in df.columns:
                continue
            try:
                is_enumerated = hasattr(p_values, "__len__") and not isinstance(p_values, str)
                if is_enumerated and len(p_values) > 1:
                    sweep.append(p_name)
            except Exception:
                continue

    # Outputs = numeric columns that are neither an input parameter (swept or
    # constant) nor per-run bookkeeping.
    bookkeeping = {"simulation_duration_s_total"}
    outputs = [c for c in all_numeric
               if c not in param_names and c not in bookkeeping]

    return PlotColumns(sweep_params=sweep, all_numeric_cols=all_numeric,
                       output_cols=outputs)


# ── History helpers ───────────────────────────────────────────────────────────

def resolve_csv_path(selection: str, out_dir: str | os.PathLike[str]) -> str | None:
    """
    Convert a history dropdown label to an absolute CSV path.

    Returns ``None`` if the path does not exist.
    """
    out = Path(out_dir)
    if selection == "Latest (simulation_results)":
        path = out / "simulation_results.csv"
    else:
        path = out / "history" / selection
    return str(path) if path.exists() else None


def load_csv(csv_path: str) -> pd.DataFrame:
    """Read a simulation result CSV and apply error-column normalisation."""
    return prepare_results(pd.read_csv(csv_path))


def list_history_runs(out_dir: str | os.PathLike[str],
                      yaml_name: str | None = None) -> list[str]:
    """
    Return run labels for the history dropdown, newest first.

    Puts ``'Latest (simulation_results)'`` at position 0 if it exists.

    If *yaml_name* is given, only history runs whose ``.meta.json`` sidecar
    records that datasheet are returned; runs with missing or different
    metadata are hidden. "Latest" is held to the same standard when its
    sidecar attributes it to a datasheet, but stays visible when it has no
    (or pre-sidecar) metadata — it is the live run, not archive clutter.
    """
    from chipify import run_meta

    out = Path(out_dir)
    runs: list[str] = []
    latest = out / "simulation_results.csv"
    if latest.exists():
        latest_yaml = run_meta.read_meta(latest).get("yaml", "") if yaml_name else ""
        if not yaml_name or not latest_yaml or latest_yaml == yaml_name:
            runs.append("Latest (simulation_results)")

    history_dir = out / "history"
    if history_dir.exists():
        hist_files = sorted(history_dir.glob("run_*.csv"),
                            key=lambda p: p.name, reverse=True)
        if yaml_name:
            hist_files = [
                f for f in hist_files
                if run_meta.read_meta(f).get("yaml") == yaml_name
            ]
        runs.extend(f.name for f in hist_files)

    return runs
