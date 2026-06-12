# Copyright (c) 2026 Santiago Hofwimmer
"""
data_loader.py – Load simulation result CSVs and compute plot-column metadata.

No tkinter imports.  Functions return DataFrames and metadata dicts that the
history controller or tab views can read from AppState.
"""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from typing import Any

import numpy as np
import pandas as pd

log = logging.getLogger("chipify.gui.services.data_loader")


# ── PlotColumns ───────────────────────────────────────────────────────────────

@dataclass
class PlotColumns:
    """
    Separates discrete sweep parameters from continuous output columns.

    This enforces the invariant described in context.md §3: the Corner Yield
    Matrix requires discrete inputs and must never receive continuous outputs.
    """
    sweep_params: list[str] = field(default_factory=list)
    all_numeric_cols: list[str] = field(default_factory=list)


# ── DataFrame helpers ─────────────────────────────────────────────────────────

def valid_rows(df: pd.DataFrame) -> pd.DataFrame:
    """
    Return only the rows where ``sim_error == 'None'``.

    This is the single authoritative filter that all tabs must use; never
    filter ``sim_error`` inline in tab code.
    """
    if "sim_error" not in df.columns:
        return df
    return df[df["sim_error"] == "None"]


def normalise_sim_error(df: pd.DataFrame) -> pd.DataFrame:
    """Ensure ``sim_error`` column exists, is string-typed, and has no NaNs."""
    if "sim_error" not in df.columns:
        df = df.copy()
        df["sim_error"] = "None"
        return df
    ser = df["sim_error"]
    # Fast path: already clean string data. The dtype guard matters — a CSV
    # whose sim_error column is all-NaN loads as float, where .str would raise.
    if (
        ser.dtype == object
        and not ser.isna().any()
        and ser.map(lambda v: isinstance(v, str)).all()
        and not (ser.str.lower() == "nan").any()
    ):
        return df
    df = df.copy()
    df["sim_error"] = ser.fillna("None").astype(str)
    df.loc[df["sim_error"].str.lower() == "nan", "sim_error"] = "None"
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
    return compute_global_pass(normalise_sim_error(df))


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
    if stim is not None:
        for p_name, p_values in stim.params.items():
            if p_name not in df.columns:
                continue
            try:
                is_enumerated = hasattr(p_values, "__len__") and not isinstance(p_values, str)
                if is_enumerated and len(p_values) > 1:
                    sweep.append(p_name)
            except Exception:
                continue

    return PlotColumns(sweep_params=sweep, all_numeric_cols=all_numeric)


# ── History helpers ───────────────────────────────────────────────────────────

def resolve_csv_path(selection: str, out_dir: str) -> str | None:
    """
    Convert a history dropdown label to an absolute CSV path.

    Returns ``None`` if the path does not exist.
    """
    if selection == "Latest (simulation_results)":
        path = os.path.join(out_dir, "simulation_results.csv")
    else:
        path = os.path.join(out_dir, "history", selection)
    return path if os.path.exists(path) else None


def load_csv(csv_path: str) -> pd.DataFrame:
    """Read a simulation result CSV and apply sim_error normalisation."""
    df = pd.read_csv(csv_path)
    df = normalise_sim_error(df)
    df = compute_global_pass(df)
    return df


def list_history_runs(out_dir: str, yaml_name: str | None = None) -> list[str]:
    """
    Return run labels for the history dropdown, newest first.

    Puts ``'Latest (simulation_results)'`` at position 0 if it exists.

    If *yaml_name* is given, only history runs whose ``.meta.json`` sidecar
    records that datasheet are returned; runs with missing or different
    metadata are hidden. "Latest" is held to the same standard when its
    sidecar attributes it to a datasheet, but stays visible when it has no
    (or pre-sidecar) metadata — it is the live run, not archive clutter.
    """
    import glob as _glob

    from chipify import run_meta

    runs: list[str] = []
    latest = os.path.join(out_dir, "simulation_results.csv")
    if os.path.exists(latest):
        latest_yaml = run_meta.read_meta(latest).get("yaml", "") if yaml_name else ""
        if not yaml_name or not latest_yaml or latest_yaml == yaml_name:
            runs.append("Latest (simulation_results)")

    history_dir = os.path.join(out_dir, "history")
    if os.path.exists(history_dir):
        hist_files = _glob.glob(os.path.join(history_dir, "run_*.csv"))
        hist_files.sort(reverse=True)
        if yaml_name:
            hist_files = [
                f for f in hist_files
                if run_meta.read_meta(f).get("yaml") == yaml_name
            ]
        runs.extend(os.path.basename(f) for f in hist_files)

    return runs
