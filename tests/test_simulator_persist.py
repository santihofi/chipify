"""Tests for chipify.simulator analysis-capture diagnostics.

Covers _persist_analyses (writes per-run CSVs and, crucially, records a reason on
the result row when an analysis produced no data — the silent Bode/AC "no data"
symptom) and the ngspice-error extraction helper.
"""
from __future__ import annotations

import os

import pytest

# simulator.py imports heavy runtime deps (tqdm, jinja2, …); skip cleanly if the
# environment doesn't have them installed. CI installs the package, so it runs there.
simulator = pytest.importorskip("chipify.simulator")


class _FakeAnalysis:
    """Stand-in for an Analysis: optionally writes the dest CSV on persist."""

    def __init__(self, kind: str, write_csv: bool = True) -> None:
        self.kind = kind
        self.write_csv = write_csv
        self.persisted: tuple[str, str] | None = None

    def persist_to_csv(self, src_tab: str, dest_csv: str) -> None:
        self.persisted = (src_tab, dest_csv)
        if self.write_csv:
            with open(dest_csv, "w", encoding="utf-8") as fh:
                fh.write("frequency,out_mag,out_phase\n1,2,3\n")


def test_note_when_tab_missing(tmp_path) -> None:
    """ngspice produced no tab → reason recorded on the row, persist not called."""
    an = _FakeAnalysis("ac")
    missing_tab = str(tmp_path / "run_ac.tab")          # never created
    dest_dir = str(tmp_path / "out_ac")
    os.makedirs(dest_dir, exist_ok=True)
    sample: dict = {}

    simulator._persist_analyses(
        [an], {"ac": missing_tab}, {"ac": dest_dir},
        run_id=1, tb_safe="tb_x", tb_path="tb_x", sample=sample,
    )

    assert an.persisted is None
    assert "tb_x__ac_capture" in sample
    assert "no data" in sample["tb_x__ac_capture"]


def test_note_when_tab_present_but_no_csv(tmp_path) -> None:
    """Tab exists but persist writes nothing (empty/unreadable) → reason recorded."""
    an = _FakeAnalysis("ac", write_csv=False)
    tab = tmp_path / "run_ac.tab"
    tab.write_text("* comment only\n", encoding="utf-8")  # exists, but yields no CSV
    dest_dir = str(tmp_path / "out_ac")
    os.makedirs(dest_dir, exist_ok=True)
    sample: dict = {}

    simulator._persist_analyses(
        [an], {"ac": str(tab)}, {"ac": dest_dir},
        run_id=1, tb_safe="tb_x", tb_path="tb_x", sample=sample,
    )

    assert an.persisted is not None                      # persist was attempted
    assert "tb_x__ac_capture" in sample                  # but no CSV → reason recorded
    assert "empty" in sample["tb_x__ac_capture"]


def test_writes_csv_when_tab_present(tmp_path) -> None:
    """An existing tab that persists to a real CSV → no failure note."""
    an = _FakeAnalysis("ac", write_csv=True)
    tab = tmp_path / "run_ac.tab"
    tab.write_text("1 2 3\n", encoding="utf-8")
    dest_dir = str(tmp_path / "out_ac")
    os.makedirs(dest_dir, exist_ok=True)
    sample: dict = {}

    simulator._persist_analyses(
        [an], {"ac": str(tab)}, {"ac": dest_dir},
        run_id=7, tb_safe="tb_x", tb_path="tb_x", sample=sample,
    )

    assert an.persisted is not None
    assert os.path.exists(os.path.join(dest_dir, "run_7__tb_x.csv"))
    assert "tb_x__ac_capture" not in sample


def test_skips_analysis_without_output_dir(tmp_path) -> None:
    """If no output dir was set up for the kind, skip silently (no note)."""
    an = _FakeAnalysis("ac")
    sample: dict = {}

    simulator._persist_analyses(
        [an], {}, {},
        run_id=1, tb_safe="tb_x", tb_path="tb_x", sample=sample,
    )

    assert an.persisted is None
    assert sample == {}


def test_extract_ngspice_error() -> None:
    """Picks the error line, else the last non-empty line; '' on empty input."""
    txt = "Doing analysis at TEMP = 27\nError: vector out not available\nrun simulation done"
    assert "out not available" in simulator._extract_ngspice_error(txt)
    assert simulator._extract_ngspice_error("") == ""
    assert simulator._extract_ngspice_error("foo\nbar\n") == "bar"


def test_inject_capture_before_quit() -> None:
    """Capture must be spliced before a terminating `quit` (which exits ngspice)."""
    netlist = (
        ".control\n"
        "ac dec 10 1 1e9\n"
        "echo MY_DATA:1 2\n"
        "quit\n"
        ".endc\n"
    )
    out = simulator._inject_capture(netlist, "WRDATA_HERE")
    assert "WRDATA_HERE" in out
    assert out.index("WRDATA_HERE") < out.index("quit") < out.index(".endc")


def test_inject_capture_handles_exit() -> None:
    netlist = ".control\nrun\nexit\n.endc\n"
    out = simulator._inject_capture(netlist, "CAP")
    assert out.index("CAP") < out.index("exit")


def test_inject_capture_before_endc_when_no_quit() -> None:
    """Without a quit/exit, capture goes before .endc (unchanged behavior)."""
    netlist = ".control\nac dec 10 1 1e9\n.endc\n"
    out = simulator._inject_capture(netlist, "WRDATA_HERE")
    assert out.index("WRDATA_HERE") < out.index(".endc")


def test_log_capture_failures_dedupes(caplog) -> None:
    """Distinct capture notes on rows are surfaced once each from the main process."""
    rows = [
        {"tb_x__ac_capture": "ac produced no data - empty tab"},
        {"tb_x__ac_capture": "ac produced no data - empty tab"},  # dup
        {"other": 1},
    ]
    with caplog.at_level("WARNING"):
        simulator._log_capture_failures(rows)
    hits = [r for r in caplog.records if "capture failed" in r.getMessage()]
    assert len(hits) == 1
    assert "tb_x__ac" in hits[0].getMessage()
