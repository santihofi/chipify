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
