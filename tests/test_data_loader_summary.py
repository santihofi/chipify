# Copyright (c) 2026 Santiago Hofwimmer
"""
tests/test_data_loader_summary.py

Unit tests for chipify.data_loader.result_summary — the single authoritative
run-count / global-yield helper that the CLI, analyzer, report exporters, and
plugin API all delegate to.

Covers:
- a normal frame (total / crashes / valid / passed / yield)
- an empty frame (yield is 0.0, never a ZeroDivisionError)
- frames missing the ``sim_error`` or ``global_pass`` column (presence guards)
"""
from __future__ import annotations

import pandas as pd

from chipify.data_loader import result_summary


def test_result_summary_normal() -> None:
    df = pd.DataFrame({
        "sim_error": ["None", "None", "None", "timeout"],
        "global_pass": [True, True, False, False],
    })
    s = result_summary(df)
    assert (s.total, s.crashes, s.valid, s.passed) == (4, 1, 3, 2)
    assert s.yield_pct == 50.0


def test_result_summary_empty() -> None:
    s = result_summary(pd.DataFrame({"sim_error": [], "global_pass": []}))
    assert (s.total, s.crashes, s.valid, s.passed) == (0, 0, 0, 0)
    assert s.yield_pct == 0.0  # no ZeroDivisionError on an empty frame


def test_result_summary_missing_global_pass() -> None:
    # No global_pass column ⇒ no passes counted, yield 0.0; crashes still tallied.
    df = pd.DataFrame({"sim_error": ["None", "None", "crash"]})
    s = result_summary(df)
    assert (s.total, s.crashes, s.valid, s.passed, s.yield_pct) == (3, 1, 2, 0, 0.0)


def test_result_summary_missing_sim_error() -> None:
    # No sim_error column ⇒ no crashes, every row valid.
    df = pd.DataFrame({"global_pass": [True, True, True, False]})
    s = result_summary(df)
    assert (s.total, s.crashes, s.valid, s.passed) == (4, 0, 4, 3)
    assert s.yield_pct == 75.0


# ── compute_plot_cols: output/input separation ────────────────────────────────

class _Stim:
    def __init__(self, params):
        self.params = params
        self.tests = []


def test_compute_plot_cols_separates_outputs_from_inputs() -> None:
    """output_cols must exclude input-parameter columns (swept or constant)
    and per-run bookkeeping — a histogram of an input is just the sweep grid."""
    from chipify.data_loader import compute_plot_cols

    df = pd.DataFrame({
        "temp": [-40, 27, 85],              # swept input
        "vdd": [1.8, 1.8, 1.8],             # constant input
        "gain": [10.0, 10.1, 9.9],          # measurement
        "gbw": [1e6, 1.1e6, 0.9e6],         # derived measure output
        "gain_pass": [True, True, True],
        "simulation_duration_s_total": [4.2, None, None],
        "sim_error": ["None"] * 3,
    })
    cols = compute_plot_cols(df, _Stim({"temp": [-40, 27, 85], "vdd": [1.8]}))

    assert cols.sweep_params == ["temp"]                    # multi-valued only
    assert set(cols.output_cols) == {"gain", "gbw"}         # no inputs/bookkeeping
    assert "temp" in cols.all_numeric_cols                  # back-compat list intact
    assert "gain_pass" not in cols.all_numeric_cols


def test_compute_plot_cols_without_stim() -> None:
    from chipify.data_loader import compute_plot_cols

    df = pd.DataFrame({"gain": [1.0, 2.0]})
    cols = compute_plot_cols(df, None)
    assert cols.output_cols == ["gain"]
    assert cols.sweep_params == []
