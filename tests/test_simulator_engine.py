# Copyright (c) 2026 Santiago Hofwimmer
"""Tests for chipify.simulator case-evaluation and raw-file parsing.

Covers:
- _simulate_single_case_with_engine: measure: expressions on the MY_DATA
  path (works for ngspice now, not just VACASK), and the INVALID_OUTPUT
  count-mismatch guard.
- _parse_ascii_raw: indexed ASCII Values sections (the standard SPICE
  layout) and complex AC values.
- _staged_copy_is_stale: re-staging of edited model files.
"""
from __future__ import annotations

import math
import os

import pytest

simulator = pytest.importorskip("chipify.simulator")

# Alias: pytest must not try to collect chipify's Test domain class.
from chipify.util import Test as TbTest, Value  # noqa: E402


class _FakeEngine(simulator.BaseSimulator):
    """Engine stub returning a canned MY_DATA line (no subprocess)."""

    name = "fake"

    def __init__(self, output_line: str) -> None:
        self._output = output_line

    def generate_test_template(self, test) -> str:
        return ""

    def run(self, netlist, timeout_sec=10, test=None, analysis_tab_paths=None):
        return self._output, None


def _make_test(tb: str, value_names: list[str], measure: dict | None = None) -> TbTest:
    t = TbTest(tb, [Value(n, None, None, None) for n in value_names])
    t.template_str = "fake netlist"
    t.measure = measure or {}
    return t


# ── measure: expressions on the MY_DATA path ─────────────────────────────────

def test_measure_expressions_evaluated_from_scalars() -> None:
    test = _make_test("tb_gain", ["gain", "bandwidth"],
                      measure={"gbw": "gain * bandwidth"})
    engine = _FakeEngine("MY_DATA: 60.0 1e7")
    sample = simulator._simulate_single_case_with_engine(
        {"temp": 27}, [test], engine,
    )
    assert sample["gain"] == pytest.approx(60.0)
    assert sample["gbw"] == pytest.approx(6e8)
    assert sample["sim_error"] == "None"


def test_measure_can_reference_numeric_params() -> None:
    test = _make_test("tb_x", ["vout"], measure={"vratio": "vout / vdd"})
    engine = _FakeEngine("MY_DATA: 0.9")
    sample = simulator._simulate_single_case_with_engine(
        {"vdd": 1.8}, [test], engine,
    )
    assert sample["vratio"] == pytest.approx(0.5)


def test_measure_failure_records_nan_and_note() -> None:
    test = _make_test("tb_x", ["gain"], measure={"bad": "nonexistent + 1"})
    engine = _FakeEngine("MY_DATA: 42")
    sample = simulator._simulate_single_case_with_engine({}, [test], engine)
    assert math.isnan(sample["bad"])
    assert "bad" in sample["tb_x__measure_error"]
    # A broken derived measure must not fail the run itself.
    assert sample["sim_error"] == "None"


# ── INVALID_OUTPUT on value-count mismatch ────────────────────────────────────

def test_fewer_my_data_values_than_declared_is_an_error() -> None:
    test = _make_test("tb_x", ["gain", "bandwidth", "pm"])
    engine = _FakeEngine("MY_DATA: 60.0")
    sample = simulator._simulate_single_case_with_engine({}, [test], engine)
    assert "INVALID_OUTPUT" in sample["sim_error"]
    assert sample["tb_x_overall_pass"] is False
    assert math.isnan(sample["bandwidth"])
    assert sample["bandwidth_pass"] is False
    assert math.isnan(sample["pm"])


def test_exact_my_data_count_is_clean() -> None:
    test = _make_test("tb_x", ["a", "b"])
    engine = _FakeEngine("MY_DATA: 1 2")
    sample = simulator._simulate_single_case_with_engine({}, [test], engine)
    assert sample["sim_error"] == "None"
    assert sample["tb_x_overall_pass"] is True


# ── ASCII .raw parsing ────────────────────────────────────────────────────────

def _write_ascii_raw(path, *, flags: str, varlines: list[str], values: str,
                     n_points: int) -> None:
    n_vars = len(varlines)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write("Title: t\nDate: now\nPlotname: Transient Analysis\n")
        fh.write(f"Flags: {flags}\n")
        fh.write(f"No. Variables: {n_vars}\nNo. Points: {n_points}\n")
        fh.write("Variables:\n")
        for line in varlines:
            fh.write(line + "\n")
        fh.write("Values:\n")
        fh.write(values)


def test_parse_ascii_raw_with_point_indices(tmp_path) -> None:
    """Standard SPICE ASCII layout: each point starts with its index token."""
    raw = tmp_path / "t.raw"
    _write_ascii_raw(
        raw, flags="real", n_points=3,
        varlines=["\t0\ttime\ttime", "\t1\tv(out)\tvoltage"],
        values=(
            " 0\t0.0\n\t1.0\n"
            " 1\t0.5\n\t2.0\n"
            " 2\t1.0\n\t3.0\n"
        ),
    )
    parsed = simulator._parse_ascii_raw(str(raw))
    assert list(parsed["time"]) == pytest.approx([0.0, 0.5, 1.0])
    assert list(parsed["v(out)"]) == pytest.approx([1.0, 2.0, 3.0])


def test_parse_ascii_raw_without_indices(tmp_path) -> None:
    """Writers that omit the per-point index still parse correctly."""
    raw = tmp_path / "t.raw"
    _write_ascii_raw(
        raw, flags="real", n_points=2,
        varlines=["\t0\ttime\ttime", "\t1\tv(out)\tvoltage"],
        values="0.0 1.0\n0.5 2.0\n",
    )
    parsed = simulator._parse_ascii_raw(str(raw))
    assert list(parsed["time"]) == pytest.approx([0.0, 0.5])
    assert list(parsed["v(out)"]) == pytest.approx([1.0, 2.0])


def test_parse_ascii_raw_complex_values(tmp_path) -> None:
    """AC analyses write complex values as 're,im' pairs."""
    raw = tmp_path / "t.raw"
    _write_ascii_raw(
        raw, flags="complex", n_points=2,
        varlines=["\t0\tfrequency\tfrequency", "\t1\tv(out)\tvoltage"],
        values=(
            " 0\t1.0,0.0\n\t0.5,0.5\n"
            " 1\t10.0,0.0\n\t0.1,0.2\n"
        ),
    )
    parsed = simulator._parse_ascii_raw(str(raw))
    assert parsed["v(out)"][0] == pytest.approx(0.5 + 0.5j)
    assert parsed["v(out)"][1] == pytest.approx(0.1 + 0.2j)
    assert parsed["frequency"][1] == pytest.approx(10.0 + 0.0j)


# ── stage_files_to_ram freshness check ───────────────────────────────────────

def test_staged_copy_is_stale(tmp_path) -> None:
    src = tmp_path / "models.lib"
    dest = tmp_path / "staged.lib"
    src.write_text("v1", encoding="utf-8")

    assert simulator._staged_copy_is_stale(str(src), str(dest))  # missing dest

    import shutil
    shutil.copy2(str(src), str(dest))
    assert not simulator._staged_copy_is_stale(str(src), str(dest))

    # Edit the source: newer mtime + different size → stale again.
    src.write_text("v2 edited", encoding="utf-8")
    os.utime(str(src), (os.path.getmtime(str(dest)) + 5,) * 2)
    assert simulator._staged_copy_is_stale(str(src), str(dest))
