# Copyright (c) 2026 Santiago Hofwimmer
"""The datasheet's ``reports:`` block: validation and headless rendering."""
from __future__ import annotations

import pickle
import textwrap

import pandas as pd
import pytest

from chipify import report_service as rs
from chipify.reports import PLOT_TYPES, PlotSpec, ReportsConfig
from chipify.schema import SchemaError, validate_datasheet
from chipify.util import Stimuli

_BASE = """
parameters:
  temp: [-40, 27, 100]
  vdd: [1.8]
tests:
  tb:
    gain: {min: 9, max: 11, unit: dB}
    pm: {min: 45, unit: deg}
"""


def _datasheet(reports_block: str = "") -> dict:
    import yaml
    return yaml.safe_load(_BASE + textwrap.dedent(reports_block))


def _stim(reports_block: str = ""):
    return validate_datasheet(_datasheet(reports_block))


def _results() -> pd.DataFrame:
    return pd.DataFrame({
        "temp": [-40, 27, 100, 27],
        "vdd": [1.8] * 4,
        "run_id": ["0", "1", "2", "3"],
        "sim_error": ["None"] * 4,
        "tb__error": ["None"] * 4,
        "tb_overall_pass": [True] * 4,
        "gain": [10.0, 10.2, 9.8, 10.1],
        "gain_pass": [True] * 4,
        "pm": [55.0, 60.0, 52.0, 58.0],
        "pm_pass": [True] * 4,
    })


# ── Validation ────────────────────────────────────────────────────────────────

def test_absent_block_yields_an_empty_falsey_config():
    """Datasheets that declare nothing must be entirely unaffected."""
    cfg = _stim().reports
    assert isinstance(cfg, ReportsConfig)
    assert not cfg and cfg.plots == []


def test_full_block_parses():
    cfg = _stim("""
        reports:
          formats: [png, svg]
          pdf: true
          markdown: true
          plots:
            - {type: scatter, x: gain, y: pm, formats: [svg], name: g_vs_pm}
            - {type: histogram, param: gain, group: temp}
            - {type: bode, signals: [outp], group: temp, runs: valid}
    """).reports
    assert cfg.formats == ["png", "svg"] and cfg.pdf and cfg.markdown
    assert [p.type for p in cfg.plots] == ["scatter", "histogram", "bode"]
    assert cfg.plots[0].formats == ["svg"]           # per-plot override
    assert cfg.plots[1].resolved_formats(cfg.formats) == ["png", "svg"]
    assert cfg.plots[2].options["signals"] == ["outp"]


@pytest.mark.parametrize("block,fragment", [
    ("reports: [1, 2]", "expected a mapping"),
    ("reports:\n  plots: {}", "expected a list"),
    ("reports:\n  plots: [{type: nope}]", "unknown plot type"),
    ("reports:\n  plots: [{param: gain}]", "missing required key 'type'"),
    ("reports:\n  plots: [{type: scatter, y: pm}]", "requires 'x'"),
    ("reports:\n  plots: [{type: histogram, param: gain, bogus: 1}]", "unknown key"),
    ("reports:\n  formats: [tiff_nope]", "unknown format"),
])
def test_invalid_blocks_name_the_offending_path(block, fragment):
    with pytest.raises(SchemaError) as exc:
        _stim("\n" + block)
    assert fragment in str(exc.value)


def test_stimuli_with_reports_still_pickles(tmp_path):
    """Stimuli is sent to worker processes, so it must stay picklable."""
    path = tmp_path / "d.yaml"
    path.write_text(_BASE + textwrap.dedent("""
        reports:
          pdf: true
          plots: [{type: scatter, x: gain, y: pm}]
    """), encoding="utf-8")
    stim = Stimuli(str(path))
    assert pickle.loads(pickle.dumps(stim)).reports.pdf is True


# ── Naming ────────────────────────────────────────────────────────────────────

def test_plot_names_come_from_the_spec_not_its_position():
    """Reordering the list must not rename every file and ruin run-to-run diffs."""
    assert rs.default_plot_name(
        PlotSpec("scatter", options={"x": "gain", "y": "pm"})
    ) == "scatter_gain_vs_pm"
    assert rs.default_plot_name(
        PlotSpec("histogram", options={"param": "gain", "group": "temp"})
    ) == "histogram_gain_by_temp"
    assert rs.default_plot_name(PlotSpec("scatter", name="my plot/name")) == "my_plot_name"


# ── Rendering ─────────────────────────────────────────────────────────────────

_TYPE_OPTIONS = {
    "scatter": {"x": "gain", "y": "pm"},
    "corner_yield": {"x": "temp", "y": "vdd"},
    "correlation": {},
    "tornado": {"target": "gain"},
    "fail_breakdown": {},
    "histogram": {"param": "gain"},
}


@pytest.mark.parametrize("ptype", sorted(_TYPE_OPTIONS))
def test_every_non_waveform_type_renders_headless(ptype, tmp_path):
    """Parametrised over the registry, so a new type cannot land uncovered."""
    stim = _stim()
    stim.reports = ReportsConfig(
        formats=["png", "svg"],
        plots=[PlotSpec(ptype, options=dict(_TYPE_OPTIONS[ptype]))],
    )
    result = rs.generate_reports(_results(), stim, "d.yaml", tmp_path)
    assert not result.warnings, result.warnings
    assert len(result.files) == 2
    for path in result.files:
        assert path.exists() and path.stat().st_size > 0


def test_registry_and_test_matrix_stay_in_step():
    """Every non-waveform plot type must appear in the render matrix above."""
    non_waveform = {n for n, t in PLOT_TYPES.items() if not t.is_waveform}
    assert non_waveform == set(_TYPE_OPTIONS)


def test_latex_on_an_unsupported_type_warns_but_keeps_the_other_formats(tmp_path):
    stim = _stim()
    stim.reports = ReportsConfig(
        plots=[PlotSpec("scatter", formats=["png", "latex"],
                        options={"x": "gain", "y": "pm"})],
    )
    result = rs.generate_reports(_results(), stim, "d.yaml", tmp_path)
    assert [f.suffix for f in result.files] == [".png"]
    assert any("LaTeX" in w and "scatter" in w for w in result.warnings)


def test_histogram_latex_writes_the_pgfplots_pair(tmp_path):
    stim = _stim()
    stim.reports = ReportsConfig(
        plots=[PlotSpec("histogram", formats=["latex"], options={"param": "gain"})],
    )
    result = rs.generate_reports(_results(), stim, "d.yaml", tmp_path)
    assert sorted(f.suffix for f in result.files) == [".csv", ".tex"]
    assert not result.warnings


def test_one_bad_spec_does_not_stop_the_others(tmp_path):
    stim = _stim()
    stim.reports = ReportsConfig(
        formats=["png"],
        plots=[
            PlotSpec("histogram", options={"param": "not_a_measurement"}),
            PlotSpec("scatter", options={"x": "gain", "y": "pm"}),
        ],
    )
    result = rs.generate_reports(_results(), stim, "d.yaml", tmp_path)
    assert [f.name for f in result.files] == ["scatter_gain_vs_pm.png"]
    assert any("not_a_measurement" in w for w in result.warnings)


def test_missing_waveform_directory_warns_rather_than_raising(tmp_path):
    stim = _stim()
    stim.reports = ReportsConfig(
        formats=["png"], plots=[PlotSpec("bode", options={"signals": ["outp"]})])
    result = rs.generate_reports(_results(), stim, "d.yaml", tmp_path)
    assert result.files == []
    assert len(result.warnings) == 1


def test_documents_and_latest_pointer(tmp_path):
    stim = _stim()
    stim.reports = ReportsConfig(pdf=True, markdown=True)
    result = rs.generate_reports(_results(), stim, "d.yaml", tmp_path,
                                 duration_s=1.25)
    assert not result.warnings, result.warnings
    assert {f.suffix for f in result.files} == {".pdf", ".md"}

    # Timestamped directory, with .latest naming it (the analysis_data pattern).
    assert result.out_dir.parent == rs.reports_dir(tmp_path)
    assert rs.latest_reports(tmp_path) == str(result.out_dir)


def test_empty_config_reports_that_there_is_nothing_to_do(tmp_path):
    result = rs.generate_reports(_results(), _stim(), "d.yaml", tmp_path)
    assert result.files == []
    assert "no 'reports:' block" in result.warnings[0]
    # Nothing was created for a datasheet that asked for nothing.
    assert not result.out_dir.exists()
