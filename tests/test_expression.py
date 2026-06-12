# Copyright (c) 2026 Santiago Hofwimmer
"""
tests/test_expression.py

Unit tests for chipify.expression.SafeEvaluator.

Covers:
- Basic arithmetic
- numpy helpers (db, last, first)
- SPICE-style name sanitisation
- Security: rejects __import__, open, exec, attribute chains
- DataFrame column evaluation (replaces df.eval)
- evaluate_vector numexpr / asteval fallback
- ExpressionError is raised for bad expressions
"""
from __future__ import annotations

import math
import numpy as np
import pandas as pd
import pytest

from chipify.expression import SafeEvaluator, ExpressionError


@pytest.fixture
def ev() -> SafeEvaluator:
    return SafeEvaluator()


# ── Basic arithmetic ──────────────────────────────────────────────────────────

def test_simple_arithmetic(ev: SafeEvaluator) -> None:
    assert ev.evaluate_scalar("2 + 3", {}) == 5
    assert ev.evaluate_scalar("10 / 4", {}) == pytest.approx(2.5)


def test_named_scalars(ev: SafeEvaluator) -> None:
    result = ev.evaluate_scalar("p_out / p_in * 100", {"p_out": 0.5, "p_in": 1.0})
    assert result == pytest.approx(50.0)


# ── numpy helpers ─────────────────────────────────────────────────────────────

def test_db_helper(ev: SafeEvaluator) -> None:
    result = ev.evaluate_scalar("db(x)", {"x": np.array([100.0])})
    assert float(result[0]) == pytest.approx(40.0)  # 20*log10(100) = 40


def test_last_helper(ev: SafeEvaluator) -> None:
    arr = np.array([1.0, 2.0, 3.0])
    assert ev.evaluate_scalar("last(x)", {"x": arr}) == pytest.approx(3.0)


def test_first_helper(ev: SafeEvaluator) -> None:
    arr = np.array([10.0, 20.0])
    assert ev.evaluate_scalar("first(x)", {"x": arr}) == pytest.approx(10.0)


def test_numpy_functions_available(ev: SafeEvaluator) -> None:
    result = ev.evaluate_scalar("sqrt(4.0)", {})
    assert float(result) == pytest.approx(2.0)


# ── SPICE name sanitisation ───────────────────────────────────────────────────

def test_sanitise_key(ev: SafeEvaluator) -> None:
    assert ev.sanitise_key("v(out)") == "v_out_"
    assert ev.sanitise_key("i(R1)") == "i_R1_"
    assert ev.sanitise_key("v(net001)") == "v_net001_"


def test_sanitise_spice_expr(ev: SafeEvaluator) -> None:
    expr = "v(out) - v(in)"
    safe = ev.sanitise_spice_expr(expr)
    assert safe == "v_out_ - v_in_"


def test_sanitise_keeps_helper_calls_with_bare_args(ev: SafeEvaluator) -> None:
    # Helper calls must remain calls — only SPICE accessors get rewritten.
    assert ev.sanitise_spice_expr("last(vout)") == "last(vout)"
    assert ev.sanitise_spice_expr("db(gain)") == "db(gain)"
    assert ev.sanitise_spice_expr("last(v(out))") == "last(v_out_)"
    assert ev.sanitise_spice_expr("gain * bandwidth") == "gain * bandwidth"


def test_spice_measure_with_bare_name_helper(ev: SafeEvaluator) -> None:
    results = {"vout": np.array([0.0, 0.5, 1.0])}
    assert float(ev.evaluate_spice_measure("last(vout)", results)) == pytest.approx(1.0)


def test_evaluate_spice_measure(ev: SafeEvaluator) -> None:
    results = {
        "v(out)": np.array([0.0, 0.5, 1.0]),
        "time": np.array([0.0, 1e-9, 2e-9]),
    }
    # last(v_out_) should return 1.0
    val = ev.evaluate_spice_measure("last(v(out))", results)
    assert float(val) == pytest.approx(1.0)


# ── Security: blocked constructs ──────────────────────────────────────────────

def test_blocks_import(ev: SafeEvaluator) -> None:
    with pytest.raises(ExpressionError):
        ev.evaluate_scalar("__import__('os').system('echo bad')", {})


def test_blocks_open(ev: SafeEvaluator) -> None:
    # `open` must be unavailable regardless of platform (asteval ships it by
    # default in some versions); using a real path would make this OS-dependent.
    with pytest.raises(ExpressionError):
        ev.evaluate_scalar("open('x')", {})


def test_blocks_dunder_attr(ev: SafeEvaluator) -> None:
    with pytest.raises(ExpressionError):
        ev.evaluate_scalar("(1).__class__.__bases__", {})


def test_blocks_exec(ev: SafeEvaluator) -> None:
    with pytest.raises(ExpressionError):
        ev.evaluate_scalar("exec('import os')", {})


def test_blocks_invalid_syntax(ev: SafeEvaluator) -> None:
    with pytest.raises(ExpressionError):
        ev.evaluate_scalar("a[", {"a": 1})  # unclosed bracket → SyntaxError


# ── evaluate_dataframe_column ─────────────────────────────────────────────────

def test_df_column_simple(ev: SafeEvaluator) -> None:
    df = pd.DataFrame({"p_out": [0.5, 1.0], "p_in": [1.0, 2.0]})
    df2 = ev.evaluate_dataframe_column(df, "eff", "p_out / p_in * 100")
    assert list(df2["eff"]) == pytest.approx([50.0, 50.0])


def test_df_column_spice_col_name(ev: SafeEvaluator) -> None:
    df = pd.DataFrame({"v(outp)": [1.0, 2.0], "v(outn)": [0.1, 0.2]})
    df2 = ev.evaluate_dataframe_column(df, "vdiff", "v(outp) - v(outn)")
    assert list(df2["vdiff"]) == pytest.approx([0.9, 1.8])


def test_df_column_rejects_bad_target(ev: SafeEvaluator) -> None:
    df = pd.DataFrame({"a": [1.0]})
    with pytest.raises(ValueError, match="Invalid column name"):
        ev.evaluate_dataframe_column(df, "bad-name!", "a")


def test_df_column_expression_error(ev: SafeEvaluator) -> None:
    df = pd.DataFrame({"a": [1.0]})
    with pytest.raises(ExpressionError):
        ev.evaluate_dataframe_column(df, "b", "nonexistent_column + 1")


def test_df_column_preserves_existing(ev: SafeEvaluator) -> None:
    df = pd.DataFrame({"x": [3.0, 4.0], "y": [1.0, 2.0]})
    df2 = ev.evaluate_dataframe_column(df, "z", "x + y")
    assert "x" in df2.columns and "y" in df2.columns
    assert list(df2["z"]) == pytest.approx([4.0, 6.0])


# ── evaluate_vector ───────────────────────────────────────────────────────────

def test_evaluate_vector_basic(ev: SafeEvaluator) -> None:
    cols = {"a": np.array([1.0, 2.0, 3.0]), "b": np.array([4.0, 5.0, 6.0])}
    result = ev.evaluate_vector("a + b", cols)
    np.testing.assert_array_almost_equal(result, [5.0, 7.0, 9.0])


def test_evaluate_vector_with_helper(ev: SafeEvaluator) -> None:
    # db() is not supported by numexpr → falls back to asteval
    cols = {"x": np.array([10.0, 100.0])}
    result = ev.evaluate_vector("db(x)", cols)
    np.testing.assert_array_almost_equal(result, [20.0, 40.0])


# ── nan propagation ───────────────────────────────────────────────────────────

def test_df_column_nan_propagation(ev: SafeEvaluator) -> None:
    df = pd.DataFrame({"a": [1.0, float("nan"), 3.0]})
    df2 = ev.evaluate_dataframe_column(df, "b", "a * 2")
    assert math.isnan(df2["b"].iloc[1])
    assert df2["b"].iloc[0] == pytest.approx(2.0)
    assert df2["b"].iloc[2] == pytest.approx(6.0)
