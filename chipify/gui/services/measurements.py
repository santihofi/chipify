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

            rows.append(MeasurementRow(
                name=name,
                sim_min=sim_min, sim_typ=sim_typ, sim_max=sim_max,
                spec_min=v_min, spec_max=v_max,
                cpk_str=cpk_str, sigma_str=sigma_str,
                status="PASS" if passed else "FAIL", fail_n=fail_n,
            ))
    return rows
