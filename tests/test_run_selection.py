# Copyright (c) 2026 Santiago Hofwimmer
"""One run-selection implementation behind every waveform surface.

The Plots tab, the Multi-plot dashboard cell and a datasheet's ``reports:``
``runs:`` key each used to carry their own copy — with two different
vocabularies between them (``"All Valid"`` vs ``"valid"``), so a datasheet and
the GUI could disagree about which runs a plot covered.
"""
from __future__ import annotations

import pandas as pd
import pytest

from chipify.uikit.services import transient_loader as tl


def _df(n: int = 5) -> pd.DataFrame:
    return pd.DataFrame({
        "run_id": list(range(n)),                       # int64, as read_csv gives
        "sim_error": ["None"] * n,
        "global_pass": [i % 2 == 0 for i in range(n)],
    })


# ── Modes ─────────────────────────────────────────────────────────────────────

def test_all_valid_returns_every_padded_id():
    assert tl.select_run_ids(_df(3), tl.RUN_MODE_ALL) == ["000000", "000001", "000002"]


def test_failing_only_selects_the_failing_runs():
    assert tl.select_run_ids(_df(5), tl.RUN_MODE_FAILING) == ["000001", "000003"]


def test_failing_without_a_verdict_column_selects_nothing():
    assert tl.select_run_ids(_df(3).drop(columns=["global_pass"]),
                             tl.RUN_MODE_FAILING) == []


def test_first_n_honours_both_the_argument_and_the_shorthand():
    assert tl.select_run_ids(_df(5), tl.RUN_MODE_FIRST, n=2) == ["000000", "000001"]
    assert tl.select_run_ids(_df(5), "first:3") == ["000000", "000001", "000002"]


def test_custom_ids_are_padded_and_split_on_commas_or_spaces():
    assert tl.select_run_ids(_df(3), tl.RUN_MODE_CUSTOM,
                             custom="1, 2 07") == ["000001", "000002", "000007"]


def test_errored_rows_are_excluded_from_the_valid_selection():
    df = _df(3)
    df.loc[1, "sim_error"] = "tb: CRASH"
    assert tl.select_run_ids(df, tl.RUN_MODE_ALL) == ["000000", "000002"]


def test_selection_is_capped():
    assert len(tl.select_run_ids(_df(tl.RUN_CAP + 50), tl.RUN_MODE_ALL)) == tl.RUN_CAP


def test_missing_run_id_column_yields_nothing():
    assert tl.select_run_ids(pd.DataFrame({"x": [1]}), tl.RUN_MODE_ALL) == []
    assert tl.select_run_ids(None, tl.RUN_MODE_ALL) == []


# ── One vocabulary ────────────────────────────────────────────────────────────

@pytest.mark.parametrize("label,token", list(tl.RUN_MODE_LABELS.items()))
def test_gui_labels_resolve_to_canonical_tokens(label, token):
    assert tl.parse_run_mode(label)[0] == token


def test_gui_label_and_yaml_token_select_the_same_runs():
    """The point of the change: the datasheet and the GUI cannot disagree."""
    df = _df(5)
    for label, token in tl.RUN_MODE_LABELS.items():
        if token == tl.RUN_MODE_CUSTOM:
            continue           # custom needs an explicit id list
        assert tl.select_run_ids(df, label) == tl.select_run_ids(df, token)


def test_unknown_mode_is_rejected_with_the_options_named():
    with pytest.raises(ValueError) as exc:
        tl.parse_run_mode("whatever")
    assert "all_valid" in str(exc.value)


def test_default_is_all_valid():
    assert tl.parse_run_mode("")[0] == tl.RUN_MODE_ALL
    assert tl.select_run_ids(_df(2)) == ["000000", "000001"]
