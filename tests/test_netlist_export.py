"""
tests/test_netlist_export.py

Unit tests for chipify.gui.services.netlist_export (pure rendering logic —
the menu/dialog functions need a Tk display and are not covered here).

Covers:
- render_netlist_for_row: parameter substitution + analysis output paths
- ValueError when no template is available
- resolve_template_text: in-memory template preferred, FAST_TMP fallback
"""
from __future__ import annotations

import os

import pytest

from chipify import settings
from chipify.gui.services import netlist_export


class _FakeAnalysis:
    kind = "transient"

    def jinja_var(self) -> str:
        return "tran_out_path"


class _FakeTest:
    def __init__(self, template_str: str = "", tb_path: str = "tb_amp") -> None:
        self.template_str = template_str
        self.tb_path = tb_path
        self.analyses = [_FakeAnalysis()]


def test_render_substitutes_params_and_tab_paths() -> None:
    test = _FakeTest("Vdd vdd 0 {{ vdd }}\nwrdata {{ tran_out_path }} out\n")
    row = {"vdd": 1.8, "temp": 27, "gain": 42.0}
    rendering = netlist_export.render_netlist_for_row(test, row, "000007")
    assert "Vdd vdd 0 1.8" in rendering
    assert "wrdata run_000007_transient.tab out" in rendering


def test_render_without_template_raises() -> None:
    test = _FakeTest("")
    with pytest.raises(ValueError, match="No netlist template"):
        netlist_export.render_netlist_for_row(test, {"vdd": 1.8}, "000001")


def test_resolve_prefers_in_memory_template() -> None:
    test = _FakeTest("in-memory {{ vdd }}")
    assert netlist_export.resolve_template_text(test) == "in-memory {{ vdd }}"


def test_resolve_falls_back_to_fast_tmp(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(settings, "FAST_TMP", str(tmp_path))
    test = _FakeTest("", tb_path="dir/tb_amp")
    fp = os.path.join(str(tmp_path), "tb_amp.spice")
    with open(fp, "w", encoding="utf-8") as f:
        f.write("from-disk {{ vdd }}")
    assert netlist_export.resolve_template_text(test) == "from-disk {{ vdd }}"


def test_resolve_missing_everywhere_is_empty(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(settings, "FAST_TMP", str(tmp_path))
    assert netlist_export.resolve_template_text(_FakeTest("")) == ""
