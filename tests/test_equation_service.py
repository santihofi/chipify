"""
tests/test_equation_service.py

Unit tests for chipify.gui.services.equation_service.

Covers:
- apply_scalar_equations: valid equations, bad expressions, name validation
- apply_transient_equations: SPICE-style column names, silent skip on error
- NaN propagation in scalar context
"""
from __future__ import annotations

import math
import numpy as np
import pandas as pd
import pytest

from chipify.gui.services.equation_service import (
    apply_scalar_equations,
    apply_transient_equations,
)


# ── apply_scalar_equations ────────────────────────────────────────────────────

@pytest.fixture
def sim_df() -> pd.DataFrame:
    return pd.DataFrame({
        "p_out": [0.5, 1.0, 0.75],
        "p_in": [1.0, 2.0, 1.5],
        "sim_error": ["None", "None", "None"],
    })


def test_scalar_basic(sim_df: pd.DataFrame) -> None:
    eqs = [{"name": "eff", "expr": "p_out / p_in * 100"}]
    df_out, derived, log_lines = apply_scalar_equations(sim_df, eqs)
    assert "eff" in df_out.columns
    assert list(df_out["eff"]) == pytest.approx([50.0, 50.0, 50.0])
    assert "eff" in derived
    assert any("[✓]" in line for line in log_lines)


def test_scalar_failed_expression(sim_df: pd.DataFrame) -> None:
    eqs = [{"name": "bad", "expr": "nonexistent_col + 1"}]
    df_out, derived, log_lines = apply_scalar_equations(sim_df, eqs)
    assert "bad" not in df_out.columns
    assert "bad" not in derived
    assert any("[✗]" in line for line in log_lines)


def test_scalar_invalid_target_name(sim_df: pd.DataFrame) -> None:
    eqs = [{"name": "bad-name!", "expr": "p_out"}]
    df_out, derived, log_lines = apply_scalar_equations(sim_df, eqs)
    assert "bad-name!" not in df_out.columns
    assert "bad-name!" not in derived
    assert any("[✗]" in line for line in log_lines)


def test_scalar_empty_equations(sim_df: pd.DataFrame) -> None:
    df_out, derived, log_lines = apply_scalar_equations(sim_df, [])
    assert list(df_out.columns) == list(sim_df.columns)
    assert derived == []
    assert log_lines == []


def test_scalar_skips_empty_name_or_expr(sim_df: pd.DataFrame) -> None:
    eqs = [{"name": "", "expr": "p_out"}, {"name": "x", "expr": ""}]
    df_out, derived, _ = apply_scalar_equations(sim_df, eqs)
    assert "x" not in df_out.columns
    assert derived == []


def test_scalar_nan_propagation(sim_df: pd.DataFrame) -> None:
    sim_df.loc[1, "p_out"] = float("nan")
    eqs = [{"name": "eff", "expr": "p_out / p_in * 100"}]
    df_out, _, _ = apply_scalar_equations(sim_df, eqs)
    assert math.isnan(df_out["eff"].iloc[1])
    assert df_out["eff"].iloc[0] == pytest.approx(50.0)


def test_scalar_multiple_equations(sim_df: pd.DataFrame) -> None:
    eqs = [
        {"name": "eff", "expr": "p_out / p_in * 100"},
        {"name": "power_diff", "expr": "p_in - p_out"},
    ]
    df_out, derived, _ = apply_scalar_equations(sim_df, eqs)
    assert "eff" in df_out.columns
    assert "power_diff" in df_out.columns
    assert len(derived) == 2


# ── apply_transient_equations ─────────────────────────────────────────────────

@pytest.fixture
def tran_df() -> pd.DataFrame:
    return pd.DataFrame({
        "time": [0.0, 1e-9, 2e-9],
        "v(outp)": [0.0, 0.5, 1.0],
        "v(outn)": [1.0, 0.5, 0.0],
    })


def test_transient_spice_col_names(tran_df: pd.DataFrame) -> None:
    eqs = [{"name": "vdiff", "expr": "v(outp) - v(outn)"}]
    df_out = apply_transient_equations(tran_df, eqs)
    assert "vdiff" in df_out.columns
    assert list(df_out["vdiff"]) == pytest.approx([-1.0, 0.0, 1.0])


def test_transient_silent_skip_on_error(tran_df: pd.DataFrame) -> None:
    eqs = [{"name": "broken", "expr": "no_such_col * 2"}]
    df_out = apply_transient_equations(tran_df, eqs)
    # Should not raise, just skip
    assert "broken" not in df_out.columns


def test_transient_empty_eqs(tran_df: pd.DataFrame) -> None:
    df_out = apply_transient_equations(tran_df, [])
    assert list(df_out.columns) == list(tran_df.columns)


def test_transient_multiple_eqs(tran_df: pd.DataFrame) -> None:
    eqs = [
        {"name": "vdiff", "expr": "v(outp) - v(outn)"},
        {"name": "vcm", "expr": "(v(outp) + v(outn)) / 2"},
    ]
    df_out = apply_transient_equations(tran_df, eqs)
    assert "vdiff" in df_out.columns
    assert "vcm" in df_out.columns
    assert list(df_out["vcm"]) == pytest.approx([0.5, 0.5, 0.5])
