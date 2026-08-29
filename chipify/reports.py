# Copyright (c) 2026 Santiago Hofwimmer
"""
reports.py – Vocabulary for the datasheet's ``reports:`` block.

Owns the plot-type registry and the typed specs; ``schema.py`` validates raw
YAML into these, and ``report_service.py`` renders them. Same split as
``analyses.py``: the classes live here, the validation lives in the schema.

Adding a plot type is one :data:`PLOT_TYPES` entry — the validator, the
renderer and the tests all read that registry, so a new type cannot be half
wired up.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

#: Format name for the pgfplots/LaTeX exporters, which are not image savers and
#: so do not come from the ``ExporterPlugin`` registry.
LATEX_FORMAT = "latex"


@dataclass(frozen=True)
class PlotType:
    """One renderable plot kind declared in a ``reports:`` block."""

    #: ``type:`` value in the YAML.
    name: str
    #: Option keys that must be present.
    required: tuple[str, ...] = ()
    #: Option keys that may be present.
    optional: tuple[str, ...] = ()
    #: ``PlotManager.draw_adv_plot`` mode this maps to (advanced plots only).
    adv_mode: str = ""
    #: Analysis kind for waveform overlays ("transient" / "dc" / "ac").
    kind: str = ""
    #: True when ``export_latex`` has a pgfplots generator for this type.
    supports_latex: bool = False

    @property
    def is_waveform(self) -> bool:
        return bool(self.kind)


#: Every plot type a ``reports:`` block may declare.
#:
#: ``supports_latex`` is False for most advanced plots on purpose: ``export_latex``
#: only ships pgfplots generators for the distribution and the three waveform
#: overlays. Asking for LaTeX elsewhere warns rather than failing, so the plot's
#: other formats are still written.
PLOT_TYPES: dict[str, PlotType] = {
    "scatter": PlotType(
        "scatter", required=("x", "y"), adv_mode="Scatter Plot",
    ),
    "corner_yield": PlotType(
        "corner_yield", required=("x", "y"), adv_mode="Corner Yield Matrix",
    ),
    "correlation": PlotType(
        "correlation", adv_mode="Correlation Heatmap",
    ),
    "tornado": PlotType(
        "tornado", required=("target",), adv_mode="Sensitivity (Tornado)",
    ),
    "fail_breakdown": PlotType(
        "fail_breakdown", adv_mode="Fail Breakdown (Pie Chart)",
    ),
    "histogram": PlotType(
        "histogram", required=("param",),
        optional=("group", "fit", "bins", "zoom"),
        supports_latex=True,
    ),
    "transient": PlotType(
        "transient", optional=("signals", "group", "runs"),
        kind="transient", supports_latex=True,
    ),
    "dc": PlotType(
        "dc", optional=("signals", "group", "runs"),
        kind="dc", supports_latex=True,
    ),
    "bode": PlotType(
        "bode", optional=("signals", "group", "runs"),
        kind="ac", supports_latex=True,
    ),
}

#: Keys every plot entry accepts regardless of type.
COMMON_KEYS = ("type", "name", "formats")


@dataclass
class PlotSpec:
    """One figure to render, as declared in the datasheet."""

    type: str
    #: Filename stem; derived from the type and its options when not given.
    name: str = ""
    #: Output formats for this plot; empty means "use the block default".
    formats: list[str] = field(default_factory=list)
    #: Type-specific options (``x``/``y``/``param``/``signals``/…).
    options: dict[str, Any] = field(default_factory=dict)

    @property
    def plot_type(self) -> PlotType:
        return PLOT_TYPES[self.type]

    def resolved_formats(self, defaults: list[str]) -> list[str]:
        return list(self.formats) if self.formats else list(defaults)


#: Default histogram settings for a report figure.
#:
#: ``zoom`` is on because a report histogram is fitted to its data: when the
#: spec limits sit far outside the spread — a ±10 mV spec on a 60 µV
#: distribution — an unzoomed view collapses every bar into a sliver. The PDF
#: report has always done this; applying it to every format is what makes a
#: measurement look the same whichever way it is exported.
HISTOGRAM_DEFAULTS: dict[str, Any] = {
    "fit": "Gauss (Normal)",
    "group": "None",
    "bins": "Auto",
    "zoom": True,
}


def histogram_options(spec: "PlotSpec | None") -> dict[str, Any]:
    """Effective ``fit`` / ``group`` / ``bins`` / ``zoom`` for a histogram.

    The single place these defaults live, so the standalone figure and the PDF
    page cannot render the same measurement differently.
    """
    opts = dict(HISTOGRAM_DEFAULTS)
    for key in opts:
        value = (spec.options.get(key) if spec is not None else None)
        if value is not None and value != "":
            opts[key] = value
    opts["group"] = str(opts["group"] or "None")
    opts["zoom"] = bool(opts["zoom"])
    return opts


def histogram_spec_for(stim: Any, param: str) -> PlotSpec | None:
    """The datasheet's histogram spec for *param*, when it declares one.

    Lets the PDF report render a measurement exactly as the standalone figure
    does — same grouping, bins, fit and zoom — instead of ignoring the block.
    """
    cfg = getattr(stim, "reports", None)
    plots: list[PlotSpec] = getattr(cfg, "plots", None) or []
    for spec in plots:
        if spec.type == "histogram" and str(spec.options.get("param", "")) == param:
            return spec
    return None


@dataclass
class ReportsConfig:
    """The datasheet's whole ``reports:`` block."""

    #: Default output formats applied to plots that don't override them.
    formats: list[str] = field(default_factory=list)
    pdf: bool = False
    markdown: bool = False
    plots: list[PlotSpec] = field(default_factory=list)

    def __bool__(self) -> bool:
        """True when the block asks for anything at all."""
        return bool(self.plots or self.pdf or self.markdown)
