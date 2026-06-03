"""Tests for chipify.simulator._persist_analyses.

Covers the analysis-capture persistence helper, in particular the path that
surfaces a declared analysis which ran but produced no output tab (the cause of
the silent "Bode/AC plot has no data" symptom).
"""
from __future__ import annotations

import os

import pytest

# simulator.py imports heavy runtime deps (tqdm, jinja2, …); skip cleanly if the
# environment doesn't have them installed. CI installs the package, so it runs there.
simulator = pytest.importorskip("chipify.simulator")


class _FakeAnalysis:
    """Minimal stand-in for an Analysis: records persist_to_csv calls."""

    def __init__(self, kind: str) -> None:
        self.kind = kind
        self.persisted: tuple[str, str] | None = None

    def persist_to_csv(self, src_tab: str, dest_csv: str) -> None:
        self.persisted = (src_tab, dest_csv)


def test_persist_warns_and_notes_when_tab_missing(tmp_path) -> None:
    """ngspice produced no tab → no persist, a capture note on the row, no crash."""
    an = _FakeAnalysis("ac")
    missing_tab = str(tmp_path / "run_ac.tab")          # never created
    dest_dir = str(tmp_path / "out_ac")
    os.makedirs(dest_dir, exist_ok=True)
    sample: dict = {}

    simulator._persist_analyses(
        [an], {"ac": missing_tab}, {"ac": dest_dir},
        run_id=1, tb_safe="tb_x", tb_path="tb_x", sample=sample,
    )

    assert an.persisted is None                          # nothing to persist
    assert "tb_x_ac_capture" in sample                   # note recorded on the row
    assert "no data" in sample["tb_x_ac_capture"]


def test_persist_writes_csv_when_tab_present(tmp_path) -> None:
    """An existing tab is handed to persist_to_csv with the canonical CSV name."""
    an = _FakeAnalysis("ac")
    tab = tmp_path / "run_ac.tab"
    tab.write_text("1 2 3\n", encoding="utf-8")          # exists
    dest_dir = str(tmp_path / "out_ac")
    os.makedirs(dest_dir, exist_ok=True)
    sample: dict = {}

    simulator._persist_analyses(
        [an], {"ac": str(tab)}, {"ac": dest_dir},
        run_id=7, tb_safe="tb_x", tb_path="tb_x", sample=sample,
    )

    assert an.persisted is not None
    src, dest = an.persisted
    assert src == str(tab)
    assert dest == os.path.join(dest_dir, "run_7__tb_x.csv")
    assert "tb_x_ac_capture" not in sample               # no failure note


def test_persist_skips_analysis_without_output_dir(tmp_path) -> None:
    """If no output dir was set up for the kind, the analysis is skipped silently."""
    an = _FakeAnalysis("ac")
    sample: dict = {}

    simulator._persist_analyses(
        [an], {}, {},                                    # no tab path, no dir
        run_id=1, tb_safe="tb_x", tb_path="tb_x", sample=sample,
    )

    assert an.persisted is None
    assert sample == {}                                  # no note, no warning
