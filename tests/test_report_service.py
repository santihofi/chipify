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
            - {type: bode, signals: [outp], group: temp, runs: all_valid}
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


# ── Config override (the unified PDF path) ────────────────────────────────────

def test_config_override_ignores_the_datasheet_block(tmp_path):
    """How the one-click PDF reuses this path instead of having its own."""
    stim = _stim("""
        reports:
          formats: [png]
          plots: [{type: scatter, x: gain, y: pm}]
    """)
    result = rs.generate_reports(_results(), stim, "d.yaml", tmp_path,
                                 config=rs.pdf_only_config())
    assert [f.suffix for f in result.files] == [".pdf"]
    assert not result.warnings


def test_pdf_only_config_works_without_any_reports_block(tmp_path):
    """A datasheet that declares nothing can still produce a PDF."""
    result = rs.generate_reports(_results(), _stim(), "d.yaml", tmp_path,
                                 config=rs.pdf_only_config())
    assert [f.suffix for f in result.files] == [".pdf"]
    # And it lands in the timestamped folder like everything else, rather than
    # loose in out/reports/ as the old export_pdf path did.
    assert result.out_dir.parent == rs.reports_dir(tmp_path)


# ── runs: shares the GUI's vocabulary ─────────────────────────────────────────

@pytest.mark.parametrize("runs", ["all_valid", "failing", "first:5", "All Valid"])
def test_runs_accepts_the_canonical_tokens(runs):
    cfg = _stim(f"""
        reports:
          plots: [{{type: bode, runs: {runs}}}]
    """).reports
    assert cfg.plots[0].options["runs"] == runs


def test_unknown_runs_value_is_rejected():
    from chipify.schema import SchemaError
    with pytest.raises(SchemaError) as exc:
        _stim("""
            reports:
              plots: [{type: bode, runs: whenever}]
        """)
    assert "all_valid" in str(exc.value)


# ── One histogram, every format ───────────────────────────────────────────────

def test_histogram_options_come_from_one_place():
    """The PNG and the PDF page must resolve identical settings for a spec."""
    from chipify.reports import histogram_options, histogram_spec_for

    stim = _stim("""
        reports:
          plots: [{type: histogram, param: gain, group: temp, bins: '20'}]
    """)
    spec = histogram_spec_for(stim, "gain")
    assert spec is not None
    opts = histogram_options(spec)
    assert opts["group"] == "temp" and opts["bins"] == "20"
    # Unset keys fall back to the shared defaults, not to per-renderer ones.
    assert opts["fit"] == "Gauss (Normal)"
    assert opts["zoom"] is True


def test_report_histograms_zoom_to_the_data_by_default():
    """A spec far wider than the spread must not collapse into slivers.

    A +/-10 mV spec on a 60 uV distribution rendered every bar as a sliver
    because the axis spanned the spec, not the data.
    """
    from chipify.reports import histogram_options

    assert histogram_options(None)["zoom"] is True
    assert histogram_options(
        PlotSpec("histogram", options={"param": "gain", "zoom": False})
    )["zoom"] is False


def test_histogram_spec_for_only_matches_its_own_measurement():
    from chipify.reports import histogram_spec_for

    stim = _stim("""
        reports:
          plots:
            - {type: histogram, param: gain, group: temp}
            - {type: scatter, x: gain, y: pm}
    """)
    assert histogram_spec_for(stim, "gain").options["group"] == "temp"
    assert histogram_spec_for(stim, "pm") is None          # the scatter is not one
    assert histogram_spec_for(_stim(), "gain") is None     # no block at all


def test_pdf_page_and_standalone_png_render_the_same_grouping(tmp_path):
    """The reported bug: the PNG was grouped by temp and the PDF was not."""
    import matplotlib
    matplotlib.use("Agg")
    from chipify import pdf_export
    from chipify.reports import histogram_options, histogram_spec_for
    from chipify.uikit.services import measurements as meas

    stim = _stim("""
        reports:
          pdf: true
          formats: [png]
          plots: [{type: histogram, param: gain, group: temp}]
    """)
    df = _dl_prepared()
    captured = {}

    class _Stub:
        def savefig(self, fig):
            # The page carries header/title axes too; take the one that plotted.
            captured["ax"] = next(a for a in fig.axes if a.get_legend() is not None)

    pdf_export._add_histograms(_Stub(), df, stim, meas.measurement_rows(df, stim))
    labels = [t.get_text() for t in captured["ax"].get_legend().get_texts()]
    # One legend entry per temperature: the PDF honours the datasheet's grouping.
    assert any(l.startswith("temp=") for l in labels), labels

    # And it is zoomed to the data, not to the far-away spec limits.
    lo, hi = captured["ax"].get_xlim()
    assert hi - lo < 5.0, (lo, hi)
    assert histogram_options(histogram_spec_for(stim, "gain"))["group"] == "temp"


def _dl_prepared():
    from chipify import data_loader as _dl
    return _dl.prepare_results(_results())


# ── The PDF contains exactly the configured plots ─────────────────────────────

def _pdf_pages(stim, df, out_root):
    """Render the report's plot pages and return one summary per page."""
    import matplotlib
    matplotlib.use("Agg")
    from chipify import pdf_export

    pages = []

    class _Stub:
        def savefig(self, fig, **_kw):
            # The banner sits at the top of the page; everything below is plot.
            header = [a for a in fig.axes if a.get_position().y0 > 0.9]
            plots = [a for a in fig.axes if a not in header]
            pages.append({
                "titles": [a.get_title() for a in plots if a.get_title()],
                "artists": sum(len(a.lines) + len(a.patches) + len(a.collections)
                               + len(a.images) for a in plots),
                "labels": [t.get_text() for a in header for t in a.texts]
                          + [t.get_text() for t in fig.texts],
                "facecolors": [a.get_facecolor() for a in plots],
                "header_facecolors": [a.get_facecolor() for a in header],
            })

    pdf_export._add_report_plots(_Stub(), df, stim, stim.reports.plots, out_root)
    return pages


def test_pdf_renders_every_configured_plot_type(tmp_path):
    """Only histograms used to reach the PDF; scatter/correlation were dropped."""
    stim = _stim("""
        reports:
          pdf: true
          plots:
            - {type: histogram, param: gain}
            - {type: scatter, x: gain, y: pm}
            - {type: correlation}
            - {type: tornado, target: gain}
    """)
    df = _dl_prepared()
    pages = _pdf_pages(stim, df, tmp_path)

    assert len(pages) == 4, "one page per configured plot"
    for page in pages:
        assert page["artists"] > 0, page          # not a blank page
    joined = " ".join(t for p in pages for t in p["titles"])
    assert "Distribution of" in joined and "Shmoo" in joined
    assert "Correlation" in joined


def test_pdf_plot_pages_are_labelled_in_order(tmp_path):
    stim = _stim("""
        reports:
          pdf: true
          plots:
            - {type: histogram, param: gain}
            - {type: scatter, x: gain, y: pm}
    """)
    pages = _pdf_pages(stim, _dl_prepared(), tmp_path)
    labels = [" ".join(p["labels"]) for p in pages]
    assert "histogram_gain" in labels[0] and "(1 / 2)" in labels[0]
    assert "scatter_gain_vs_pm" in labels[1] and "(2 / 2)" in labels[1]


def test_pdf_plot_pages_use_the_white_paper_palette(tmp_path):
    """Embedded pages must not carry the dark on-screen theme onto paper."""
    stim = _stim("""
        reports:
          pdf: true
          plots: [{type: scatter, x: gain, y: pm}]
    """)
    pages = _pdf_pages(stim, _dl_prepared(), tmp_path)
    # white_background() is active while the page is written.
    for fc in pages[0]["facecolors"]:
        assert tuple(round(c, 3) for c in fc[:3]) == (1.0, 1.0, 1.0), fc
    # ...but the header banner keeps its colour, or it would vanish into
    # white-on-white like it used to.
    for fc in pages[0]["header_facecolors"]:
        assert tuple(round(c, 3) for c in fc[:3]) != (1.0, 1.0, 1.0), fc


def test_configured_plots_replace_the_automatic_sections(tmp_path):
    """"Exactly the plots the datasheet asks for" — no extra auto figures."""
    stim = _stim("""
        reports:
          pdf: true
          plots: [{type: scatter, x: gain, y: pm}]
    """)
    result = rs.generate_reports(_results(), stim, "d.yaml", tmp_path)
    pdf = next(f for f in result.files if f.suffix == ".pdf")
    from pypdf import PdfReader
    pages = PdfReader(str(pdf)).pages
    # cover + measurement table + the single configured plot.
    assert len(pages) == 3, len(pages)


def test_no_plots_configured_keeps_the_default_report(tmp_path):
    """A pdf-only run still gets the automatic histograms and correlation."""
    stim = _stim()
    result = rs.generate_reports(_results(), stim, "d.yaml", tmp_path,
                                 config=rs.pdf_only_config())
    pdf = next(f for f in result.files if f.suffix == ".pdf")
    from pypdf import PdfReader
    assert len(PdfReader(str(pdf)).pages) > 3


def test_pdf_pages_are_portrait(tmp_path):
    """Plot pages must match the rest of the report, not sit sideways."""
    from chipify import pdf_export

    stim = _stim("""
        reports:
          pdf: true
          plots:
            - {type: histogram, param: gain}
            - {type: scatter, x: gain, y: pm}
            - {type: correlation}
    """)
    result = rs.generate_reports(_results(), stim, "d.yaml", tmp_path)
    pdf = next(f for f in result.files if f.suffix == ".pdf")

    from pypdf import PdfReader
    for page in PdfReader(str(pdf)).pages:
        w, h = float(page.mediabox.width), float(page.mediabox.height)
        assert h > w, f"page is landscape: {w} x {h}"
        assert round(w / 72, 1) == round(pdf_export.A4[0], 1)


def test_plot_axes_are_fitted_into_the_page_band(tmp_path):
    """A plot must not stretch down the whole sheet on a portrait page."""
    from chipify import pdf_export

    stim = _stim("""
        reports:
          pdf: true
          plots: [{type: scatter, x: gain, y: pm}]
    """)
    pages = _pdf_pages(stim, _dl_prepared(), tmp_path)
    assert len(pages) == 1
    # Recorded by _pdf_pages below via the axes positions.
    left, bottom, width, height = pdf_export._PLOT_BAND
    assert 0.0 < height < 0.7, "band should leave margins above and below"
    assert left + width <= 0.95, "band must leave room for colorbar labels"


def test_page_header_banner_is_actually_drawn():
    """axis("off") also hides the patch, which left the banner invisible."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from chipify import pdf_export

    fig = plt.figure(figsize=pdf_export.A4, facecolor="white")
    ax = pdf_export._page_header(fig, "Banner")
    try:
        assert ax.get_frame_on()
        assert ax.axison, "the axis must stay on or the background patch is skipped"
        assert not any(s.get_visible() for s in ax.spines.values())
        assert ax.get_xticks().size == 0 and ax.get_yticks().size == 0
    finally:
        plt.close(fig)
