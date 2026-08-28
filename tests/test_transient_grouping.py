# Copyright (c) 2026 Santiago Hofwimmer
"""Grouping waveform overlays by a swept input parameter.

Covers the shared run maps in ``transient_loader`` and the colour / line-style /
legend policy in ``plot_manager._OverlayStyle`` that the Transient, DC sweep and
Bode plotters all share.
"""
from __future__ import annotations

from types import SimpleNamespace

import pandas as pd

from chipify.uikit.services import transient_loader as tl


# ── Run maps ──────────────────────────────────────────────────────────────────

def _run_df():
    return pd.DataFrame({
        "run_id": ["0", "1", "2"],          # unpadded, as read back from CSV
        "temp": [-40, 27, 100],
        "global_pass": [True, False, True],
        "sim_error": ["None"] * 3,
    })


def test_run_group_map_pads_ids_to_match_csv_filenames():
    """Keys must match the ``run_<id>__<tb>.csv`` names the plotters parse."""
    assert tl.run_group_map(_run_df(), "temp") == {
        "000000": -40, "000001": 27, "000002": 100,
    }


def test_run_group_map_is_empty_when_there_is_nothing_to_group_by():
    df = _run_df()
    assert tl.run_group_map(df, "") == {}
    assert tl.run_group_map(df, "None") == {}      # the combo's placeholder
    assert tl.run_group_map(df, "nonexistent") == {}
    assert tl.run_group_map(df.drop(columns=["run_id"]), "temp") == {}
    assert tl.run_group_map(None, "temp") == {}


def test_run_pass_map_matches_the_loops_it_replaces():
    assert tl.run_pass_map(_run_df()) == {
        "000000": True, "000001": False, "000002": True,
    }
    assert tl.run_pass_map(_run_df().drop(columns=["global_pass"])) == {}
    assert tl.run_pass_map(None) == {}


def test_padded_run_ids_survive_a_csv_round_trip():
    """A results CSV parses run_id as int, so "4" would match no waveform file.

    ``run_<id>__<tb>.csv`` is always six digits; before this, every overlay
    drawn from a *loaded* run silently matched nothing (only a run still in
    memory from a live simulation worked, where run_id is still a padded str).
    """
    df = pd.DataFrame({"run_id": [4, 8, 12]})       # int64, as read_csv gives
    assert tl.padded_run_ids(df) == ["000004", "000008", "000012"]
    assert tl.pad_run_id(4) == "000004"
    assert tl.pad_run_id(" 7 ") == "000007"
    assert tl.pad_run_id("000009") == "000009"      # already padded, unchanged
    assert tl.padded_run_ids(pd.DataFrame({"x": [1]})) == []


# ── Signal discovery ──────────────────────────────────────────────────────────

def _stim_with_analyses():
    tran = SimpleNamespace(kind="transient", signals=["v(out)", "v(in)"])
    ac = SimpleNamespace(kind="ac", signals=["outp", "outn"])
    test = SimpleNamespace(analyses=[tran, ac])
    # transient_equations is a list of {name, expr} dicts; a non-empty list also
    # keeps equation_service from falling back to the machine's settings.json.
    return SimpleNamespace(tests=[test], equations=[],
                           transient_equations=[{"name": "_none", "expr": "0"}])


def test_list_kind_signals_is_per_kind():
    stim = _stim_with_analyses()
    assert tl.list_kind_signals(stim, "transient")[:2] == ["v(out)", "v(in)"]
    assert tl.list_kind_signals(stim, "ac") == ["outp", "outn"]
    assert tl.list_kind_signals(stim, "dc") == []


def test_list_kind_signals_appends_transient_equations_only_for_transient():
    stim = _stim_with_analyses()
    stim.transient_equations = [{"name": "out_d", "expr": "outp-outn"}]
    assert "out_d" in tl.list_kind_signals(stim, "transient")
    assert "out_d" not in tl.list_kind_signals(stim, "ac")


def test_kind_labels_round_trip():
    assert tl.kind_for_label("Bode") == "ac"
    assert tl.kind_for_label("DC Sweep") == "dc"
    assert tl.kind_for_label("nonsense") == "transient"     # safe default


# ── Overlay style ─────────────────────────────────────────────────────────────

RUNS = ["000000", "000001", "000002"]
GROUP = {"000000": -40, "000001": 27, "000002": 100}


def _style(signals, **kw):
    from chipify.plot_manager import _OverlayStyle
    return _OverlayStyle(signals, RUNS, **kw)


def test_ungrouped_single_signal_colours_by_run_index():
    """Unchanged legacy behaviour: one signal, viridis across runs."""
    st = _style(["v(out)"])
    assert not st.grouped
    colors = {tuple(st.color(r, "v(out)")) for r in RUNS}
    assert len(colors) == 3
    assert all(st.linestyle(s) == "-" for s in ["v(out)"])


def test_ungrouped_multi_signal_colours_by_signal():
    st = _style(["a", "b"])
    assert tuple(st.color("000000", "a")) != tuple(st.color("000000", "b"))
    # Same signal keeps its colour across runs.
    assert tuple(st.color("000000", "a")) == tuple(st.color("000002", "a"))


def test_ungrouped_failing_run_is_red():
    from chipify.plot_manager import _FAIL_COLOR
    st = _style(["a", "b"], pass_map={"000001": False})
    assert st.color("000001", "a") == _FAIL_COLOR
    # A passing run keeps its palette colour (an RGBA array, not the hex string).
    assert not isinstance(st.color("000000", "a"), str)


def test_grouped_colours_by_group_value_not_run():
    st = _style(["v(out)"], group_map=GROUP, group_label="temp")
    assert st.grouped
    # Three distinct temperatures -> three distinct colours.
    assert len({tuple(st.color(r, "v(out)")) for r in RUNS}) == 3
    # Two runs at the same temperature share a colour.
    st2 = _style(["v(out)"],
                 group_map={"000000": 27, "000001": 27, "000002": 100},
                 group_label="temp")
    assert tuple(st2.color("000000", "v(out)")) == tuple(st2.color("000001", "v(out)"))
    assert tuple(st2.color("000002", "v(out)")) != tuple(st2.color("000000", "v(out)"))


def test_grouped_uses_line_style_for_signals():
    st = _style(["a", "b"], group_map=GROUP, group_label="temp")
    assert st.linestyle("a") != st.linestyle("b")
    # Colour stays the group's regardless of signal.
    assert tuple(st.color("000000", "a")) == tuple(st.color("000000", "b"))


def test_grouped_ignores_pass_fail_highlighting():
    """The user's call: red would pull failing curves out of their group."""
    st = _style(["v(out)"], group_map=GROUP, group_label="temp",
                pass_map={"000001": False})
    assert st.pass_map == {}
    assert not st.is_fail("000001")
    plain = _style(["v(out)"], group_map=GROUP, group_label="temp")
    assert tuple(st.color("000001", "v(out)")) == tuple(plain.color("000001", "v(out)"))


def test_grouped_legend_lists_each_group_value_in_numeric_order():
    st = _style(["v(out)"], group_map=GROUP, group_label="temp")
    labels = [h.get_label() for h in st.legend_handles()]
    assert labels == ["temp=-40", "temp=27", "temp=100"]   # not string-sorted


def test_grouped_legend_adds_signal_styles_when_several_are_selected():
    st = _style(["a", "b"], group_map=GROUP, group_label="temp")
    labels = [h.get_label() for h in st.legend_handles()]
    assert labels[:3] == ["temp=-40", "temp=27", "temp=100"]
    assert labels[3:] == ["a", "b"]


def test_non_numeric_group_values_sort_lexically():
    st = _style(["v(out)"],
                group_map={"000000": "tt", "000001": "ff", "000002": "ss"},
                group_label="corner_mos")
    labels = [h.get_label() for h in st.legend_handles()]
    assert labels == ["corner_mos=ff", "corner_mos=ss", "corner_mos=tt"]


def test_ungrouped_legend_is_unchanged():
    st = _style(["a", "b"], pass_map={"000001": False})
    labels = [h.get_label() for h in st.legend_handles()]
    assert labels == ["a", "b", "Failing run"]
