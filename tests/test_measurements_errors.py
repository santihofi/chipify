# Copyright (c) 2026 Santiago Hofwimmer
"""Error scoping and ERROR status in the measurements service.

Regression cover for the reported bug: a datasheet with several testbenches
where one of them fails used to show *no* results and report PASS — because
``sim_error`` is a single per-row slot, so one failing testbench dropped every
row through ``valid_rows``, and ``Series([]).all()`` is vacuously ``True``.
"""
from __future__ import annotations

import pandas as pd
import pytest

from chipify import data_loader as _dl
from chipify import simulator
from chipify.uikit.services import measurements as meas
# util.Test is aliased: pytest would otherwise try to collect it as a
# test class and warn about its constructor.
from chipify.util import Test as _Test, Value


class _Stim:
    def __init__(self, tests, params=None):
        self.tests = tests
        self.params = params or {"corner": ["tt", "ss"]}


ENGINE_ERR = "tb_ac: ENGINE_ERROR: ngspice: Error on line 42"


def _two_tb_stim():
    """One healthy testbench (tb_amp/gain) and one broken one (tb_ac/bw)."""
    return _Stim([
        _Test("tb_amp", [Value("gain", 40.0, 50.0, 45.0, "dB")]),
        _Test("tb_ac", [Value("bw", 1e6, None, 2e6, "Hz")]),
    ])


def _two_tb_df(tb_amp_error="None", tb_ac_error=ENGINE_ERR):
    """Two runs; tb_amp measures fine, tb_ac fails in every run."""
    return pd.DataFrame({
        "corner": ["tt", "ss"],
        "run_id": ["000000", "000001"],
        "sim_error": [tb_ac_error if tb_ac_error != "None" else tb_amp_error] * 2,
        "tb_amp__error": [tb_amp_error] * 2,
        "tb_ac__error": [tb_ac_error] * 2,
        "gain": [44.0, 46.0],
        "gain_pass": [True, True],
        "bw": [float("nan"), float("nan")],
        "bw_pass": [False, False],
    })


def _rows_by_name(df, stim):
    return {r.name: r for r in meas.measurement_rows(df, stim)}


# ── The reported bug ──────────────────────────────────────────────────────────

def test_failing_testbench_does_not_hide_the_healthy_one():
    """The core regression: one broken testbench used to blank out all results."""
    df, stim = _two_tb_df(), _two_tb_stim()

    # Every row is dropped by the row-level filter — this is why the old code
    # computed its statistics over nothing at all.
    assert len(_dl.valid_rows(df)) == 0

    rows = _rows_by_name(df, stim)

    # The healthy testbench keeps real statistics and a real verdict.
    gain = rows["gain"]
    assert gain.status == meas.STATUS_PASS
    assert gain.sim_min == 44.0 and gain.sim_max == 46.0
    assert gain.error_n == 0

    # The broken one is ERROR — never PASS, and never a bare FAIL either.
    bw = rows["bw"]
    assert bw.status == meas.STATUS_ERROR
    assert bw.error_n == 2 and bw.total_n == 2
    assert "ENGINE_ERROR" in bw.error_msg


def test_all_testbenches_failing_is_not_a_pass():
    """Every simulation failing used to report PASS for every parameter."""
    df = _two_tb_df(tb_amp_error="tb_amp: CRASH: no such file")
    df["gain"] = float("nan")
    df["gain_pass"] = False
    rows = _rows_by_name(df, _two_tb_stim())
    assert {r.status for r in rows.values()} == {meas.STATUS_ERROR}


def test_empty_frame_reports_error_not_pass():
    """A results frame with no rows must not report a vacuous PASS."""
    df = _two_tb_df().iloc[0:0]
    rows = _rows_by_name(df, _two_tb_stim())
    assert [r.status for r in rows.values()] == [meas.STATUS_ERROR] * 2


# ── ERROR semantics ───────────────────────────────────────────────────────────

def test_partial_errors_keep_statistics_from_the_good_runs():
    """One flaky run marks the row ERROR but must not discard the other run."""
    df, stim = _two_tb_df(), _two_tb_stim()
    df["tb_amp__error"] = ["None", "tb_amp: TIMEOUT"]
    df["gain"] = [44.0, float("nan")]
    df["gain_pass"] = [True, False]

    gain = _rows_by_name(df, stim)["gain"]
    assert gain.status == meas.STATUS_ERROR
    assert gain.error_n == 1 and gain.total_n == 2
    assert gain.sim_typ == 44.0          # computed from the run that worked


def test_nan_value_without_a_recorded_error_is_still_an_error():
    """An engine that cannot resolve a signal writes NaN and a clean error slot.

    That used to be indistinguishable from a genuine out-of-spec FAIL.
    """
    df, stim = _two_tb_df(tb_ac_error="None"), _two_tb_stim()
    df["sim_error"] = "None"
    bw = _rows_by_name(df, stim)["bw"]
    assert bw.status == meas.STATUS_ERROR
    assert bw.error_n == 2


def test_out_of_spec_value_is_still_a_plain_fail():
    """Errors must not swallow the ordinary out-of-spec verdict."""
    df, stim = _two_tb_df(), _two_tb_stim()
    df["gain"] = [44.0, 60.0]            # second run above vmax=50
    df["gain_pass"] = [True, False]
    gain = _rows_by_name(df, stim)["gain"]
    assert gain.status == meas.STATUS_FAIL
    assert gain.fail_n == 1 and gain.error_n == 0


def test_worst_case_still_reported_for_a_partially_errored_parameter():
    """An ERROR badge must not hide a spec violation in the usable runs."""
    df, stim = _two_tb_df(), _two_tb_stim()
    df["tb_amp__error"] = ["None", "tb_amp: TIMEOUT"]
    df["gain"] = [10.0, float("nan")]    # first run far below vmin=40
    df["gain_pass"] = [False, False]

    worst = {w.name: w for w in meas.worst_cases(df, stim, len(df))}
    assert "gain" in worst
    assert worst["gain"].worst_val == 10.0
    assert worst["gain"].violation.startswith("<")
    assert worst["gain"].conditions["corner"] == "tt"


# ── error_rows ────────────────────────────────────────────────────────────────

def test_error_rows_groups_by_testbench_and_message():
    rows = meas.error_rows(_two_tb_df(), _two_tb_stim())
    assert len(rows) == 1
    e = rows[0]
    assert e.tb_path == "tb_ac"
    assert e.kind == "ENGINE_ERROR"
    assert e.run_n == 2 and e.total_n == 2
    assert e.measurements == ["bw"]
    assert e.conditions == {"corner": "tt"}     # first affected run


def test_error_rows_separates_distinct_messages():
    df, stim = _two_tb_df(), _two_tb_stim()
    df["tb_ac__error"] = [ENGINE_ERR, "tb_ac: TIMEOUT"]
    kinds = sorted(e.kind for e in meas.error_rows(df, stim))
    assert kinds == ["ENGINE_ERROR", "TIMEOUT"]
    assert all(e.run_n == 1 for e in meas.error_rows(df, stim))


def test_error_rows_empty_for_a_clean_run():
    df, stim = _two_tb_df(tb_ac_error="None"), _two_tb_stim()
    df["sim_error"] = "None"
    df["bw"] = [1.5e6, 1.6e6]
    df["bw_pass"] = [True, True]
    assert meas.error_rows(df, stim) == []


@pytest.mark.parametrize("message,kind", [
    ("tb: CRASH: segfault", "CRASH"),
    ("tb: TIMEOUT", "TIMEOUT"),
    ("tb: NO_MY_DATA_FOUND", "NO_MY_DATA_FOUND"),
    ("tb: INVALID_OUTPUT(expected 2 values, got 1)", "INVALID_OUTPUT"),
    ("tb: TEMPLATE_RENDER_ERROR: 'vdd' is undefined", "TEMPLATE_RENDER_ERROR"),
    ("tb: WORKER_LOST: pool died", "WORKER_LOST"),
    ("tb: something unrecognised", "ERROR"),
])
def test_error_kind_classification(message, kind):
    assert meas.error_kind(message) == kind


# ── Backwards compatibility with pre-per-testbench CSVs ───────────────────────

def test_legacy_frame_without_per_testbench_columns():
    """History CSVs written before per-testbench errors must still load.

    Without those columns an error is not attributable to a single testbench,
    so every measurement in the row is conservatively unusable — but the result
    is still ERROR, never the old vacuous PASS.
    """
    df = _two_tb_df().drop(columns=["tb_amp__error", "tb_ac__error"])
    rows = _rows_by_name(df, _two_tb_stim())
    assert {r.status for r in rows.values()} == {meas.STATUS_ERROR}


def test_legacy_clean_frame_behaves_exactly_as_before():
    df = _two_tb_df(tb_ac_error="None").drop(
        columns=["tb_amp__error", "tb_ac__error"])
    df["sim_error"] = "None"
    df["bw"] = [1.5e6, 1.6e6]
    df["bw_pass"] = [True, True]
    rows = _rows_by_name(df, _two_tb_stim())
    assert {r.status for r in rows.values()} == {meas.STATUS_PASS}


# ── data_loader masks ─────────────────────────────────────────────────────────

def test_tb_ok_mask_is_scoped_per_testbench():
    df = _two_tb_df()
    assert _dl.tb_ok_mask(df, "tb_amp").all()
    assert not _dl.tb_ok_mask(df, "tb_ac").any()


def test_tb_ok_mask_falls_back_to_sim_error():
    df = _two_tb_df().drop(columns=["tb_amp__error", "tb_ac__error"])
    assert not _dl.tb_ok_mask(df, "tb_amp").any()


def test_normalise_tb_errors_cleans_nan_columns():
    df = _two_tb_df()
    df["tb_amp__error"] = [float("nan"), "nan"]
    out = _dl.normalise_tb_errors(df)
    assert list(out["tb_amp__error"]) == ["None", "None"]


def test_measure_error_column_is_not_mistaken_for_a_testbench_error():
    """``<tb>__measure_error`` notes must not be picked up as error columns."""
    df = _two_tb_df()
    df["tb_amp__measure_error"] = "measure 'gbw' failed"
    assert "tb_amp__measure_error" not in _dl.tb_error_cols(df)


# ── simulator: error recording and lost batches ───────────────────────────────

def test_record_error_accumulates_across_testbenches():
    """A second failing testbench used to overwrite the first one's message."""
    stim = _two_tb_stim()
    sample = {"sim_error": _dl.NO_ERROR}
    simulator._fail_test(sample, stim.tests[0], "tb_amp: CRASH")
    simulator._fail_test(sample, stim.tests[1], "tb_ac: TIMEOUT")

    assert sample["tb_amp__error"] == "tb_amp: CRASH"
    assert sample["tb_ac__error"] == "tb_ac: TIMEOUT"
    assert "tb_amp: CRASH" in sample["sim_error"]
    assert "tb_ac: TIMEOUT" in sample["sim_error"]
    assert sample["gain_pass"] is False and sample["bw_pass"] is False


def test_lost_batch_rows_accounts_for_every_case():
    """A crashed worker used to drop its whole batch without a trace."""
    stim = _two_tb_stim()
    batch = [({"corner": "tt"}, "000000"), ({"corner": "ss"}, "000001")]
    rows = simulator._lost_batch_rows(batch, stim.tests, RuntimeError("pool died"))

    assert len(rows) == len(batch)
    for row, (params, run_id) in zip(rows, batch):
        assert row["corner"] == params["corner"]
        assert row["run_id"] == run_id
        assert "WORKER_LOST" in row["sim_error"]
        assert "WORKER_LOST" in row["tb_amp__error"]
        assert row["gain_pass"] is False

    # And they surface as errors rather than as a silently shorter sweep.
    df = _dl.prepare_results(pd.DataFrame(rows))
    errors = meas.error_rows(df, stim)
    assert {e.kind for e in errors} == {"WORKER_LOST"}
    assert all(r.status == meas.STATUS_ERROR
               for r in meas.measurement_rows(df, stim))


# ── Plot row scoping ──────────────────────────────────────────────────────────

def test_plot_rows_keeps_the_healthy_testbenchs_runs():
    """The plotting regression: charts went blank when any testbench failed."""
    df, stim = _two_tb_df(), _two_tb_stim()
    assert len(_dl.valid_rows(df)) == 0          # what used to reach the plots

    assert len(_dl.plot_rows(df, stim, ["gain"])) == 2
    assert _dl.plot_rows(df, stim, ["bw"]).empty


def test_plot_rows_without_columns_keeps_everything():
    """Yield matrices and correlation heatmaps must still see every run."""
    df, stim = _two_tb_df(), _two_tb_stim()
    assert len(_dl.plot_rows(df, stim, [])) == 2
    assert len(_dl.plot_rows(df, stim, None)) == 2
    # A sweep parameter is not a measurement and constrains nothing.
    assert len(_dl.plot_rows(df, stim, ["corner"])) == 2


def test_plot_rows_intersects_multiple_measurements():
    """A scatter needs both axes usable in the same run."""
    df, stim = _two_tb_df(), _two_tb_stim()
    df["tb_amp__error"] = ["None", "tb_amp: TIMEOUT"]
    df["gain"] = [44.0, float("nan")]
    df["bw"] = [1.5e6, 1.6e6]
    df["tb_ac__error"] = "None"

    assert len(_dl.plot_rows(df, stim, ["bw"])) == 2
    assert len(_dl.plot_rows(df, stim, ["gain"])) == 1
    assert len(_dl.plot_rows(df, stim, ["gain", "bw"])) == 1


def test_measurement_owners_covers_measure_expressions():
    stim = _two_tb_stim()
    stim.tests[0].measure = {"gbw": "gain * bw"}
    owners = _dl.measurement_owners(stim)
    assert owners["gain"] == "tb_amp"
    assert owners["bw"] == "tb_ac"
    assert owners["gbw"] == "tb_amp"      # measure: results are measurements too


# ── effective_pass ────────────────────────────────────────────────────────────

def _pass_df(**overrides):
    df = _two_tb_df()
    df["tb_amp_overall_pass"] = [True, True]
    df["tb_ac_overall_pass"] = [False, False]
    for k, v in overrides.items():
        df[k] = v
    return df


def test_effective_pass_ignores_errored_testbenches():
    """global_pass would read 0 everywhere and flatten the yield matrix."""
    df = _dl.prepare_results(_pass_df())
    assert list(df["global_pass"].astype(float)) == [0.0, 0.0]
    assert list(_dl.effective_pass(df)) == [1.0, 1.0]


def test_effective_pass_still_reports_a_genuine_failure():
    df = _dl.prepare_results(_pass_df(tb_amp_overall_pass=[True, False]))
    assert list(_dl.effective_pass(df)) == [1.0, 0.0]


def test_effective_pass_is_nan_when_no_testbench_ran():
    """A row where everything crashed must not count as a fail in a mean."""
    df = _pass_df()
    df["tb_amp__error"] = "tb_amp: CRASH"
    df = _dl.prepare_results(df)
    assert _dl.effective_pass(df).isna().all()


def test_errored_testbenches_names_the_broken_one():
    assert _dl.errored_testbenches(_two_tb_df()) == ["tb_ac"]
    clean = _two_tb_df(tb_ac_error="None")
    clean["sim_error"] = "None"
    assert _dl.errored_testbenches(clean) == []


def test_effective_pass_falls_back_on_legacy_frames():
    """Frames with no per-testbench verdict columns keep global_pass."""
    df = _dl.prepare_results(_two_tb_df().drop(
        columns=["tb_amp__error", "tb_ac__error"]))
    assert list(_dl.effective_pass(df)) == list(df["global_pass"].astype(float))
