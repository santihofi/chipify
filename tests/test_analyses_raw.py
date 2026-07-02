# Copyright (c) 2026 Santiago Hofwimmer
"""Regression tests for analyses.write_tab_from_raw (VACASK .raw path)."""
from __future__ import annotations

import pytest

np = pytest.importorskip("numpy")
analyses = pytest.importorskip("chipify.analyses")


def test_ac_write_tab_freq_fallback_with_numpy_arrays(tmp_path) -> None:
    """A bucket without the __x__ sentinel falls back to the 'frequency' /
    'freq' columns. Regression: the fallback used `or`-chaining, whose truth
    test raises ValueError on numpy arrays longer than one element."""
    an = analyses.ACAnalysis(signals=["v(out)"])
    freq = np.array([1.0, 10.0, 100.0])
    sig = np.array([1 + 1j, 0.5 + 0.5j, 0.1 + 0.1j])

    out = tmp_path / "ac.tab"
    an.write_tab_from_raw({"frequency": freq, "v(out)": sig}, str(out))
    lines = out.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 3          # one row per frequency point
    assert len(lines[0].split()) == 3  # freq, mag, phase

    # And the 'freq' spelling works too.
    out2 = tmp_path / "ac2.tab"
    an.write_tab_from_raw({"freq": freq, "v(out)": sig}, str(out2))
    assert len(out2.read_text(encoding="utf-8").strip().splitlines()) == 3
