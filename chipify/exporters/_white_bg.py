# Copyright (c) 2026 Santiago Hofwimmer
"""
_white_bg.py – Helper that saves a Matplotlib Figure with a forced
white background, regardless of the active GUI theme.

The figure on screen often uses the dark "night" theme: black canvas,
white text and ticks, blue accents. Such a figure saved as-is is
unreadable in white-paper contexts (PDF reports, slides, papers).
``save_with_white_bg`` re-skins the figure to a publication palette
(white bg, black text and spines, gray grid) just for the duration of
the savefig call, then restores every original colour exactly.

Anything the exporter does not know how to recolour (lines, scatter
markers, image colormaps, plugin-drawn artists…) is left alone — only
chrome (background, spines, ticks, labels, title, legend frame) is
touched.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from matplotlib.axes import Axes
    from matplotlib.figure import Figure


# Publication palette
_WHITE = "#ffffff"
_BLACK = "#000000"
_GRID  = "#cccccc"


def _snapshot_axes(ax: "Axes") -> dict[str, Any]:
    snap: dict[str, Any] = {
        "facecolor": ax.get_facecolor(),
        "title_color": ax.title.get_color(),
        "xlabel_color": ax.xaxis.label.get_color(),
        "ylabel_color": ax.yaxis.label.get_color(),
        "spines": {k: s.get_edgecolor() for k, s in ax.spines.items()},
        "xtick_colors": [t.get_color() for t in ax.get_xticklabels()],
        "ytick_colors": [t.get_color() for t in ax.get_yticklabels()],
        "xtick_line_color": ax.xaxis.get_tick_params().get("color"),
        "ytick_line_color": ax.yaxis.get_tick_params().get("color"),
        "grid_colors": [(line, line.get_color()) for line in ax.get_xgridlines() + ax.get_ygridlines()],
        "legend_frame": None,
        "legend_text": [],
    }
    leg = ax.get_legend()
    if leg is not None:
        frame = leg.get_frame()
        snap["legend_frame"] = (
            frame.get_facecolor(),
            frame.get_edgecolor(),
        )
        snap["legend_text"] = [t.get_color() for t in leg.get_texts()]
    return snap


def _apply_white(ax: "Axes") -> None:
    ax.set_facecolor(_WHITE)
    ax.title.set_color(_BLACK)
    ax.xaxis.label.set_color(_BLACK)
    ax.yaxis.label.set_color(_BLACK)
    for spine in ax.spines.values():
        spine.set_edgecolor(_BLACK)
    ax.tick_params(axis="x", colors=_BLACK)
    ax.tick_params(axis="y", colors=_BLACK)
    for t in ax.get_xticklabels():
        t.set_color(_BLACK)
    for t in ax.get_yticklabels():
        t.set_color(_BLACK)
    for line in ax.get_xgridlines() + ax.get_ygridlines():
        line.set_color(_GRID)
    leg = ax.get_legend()
    if leg is not None:
        frame = leg.get_frame()
        frame.set_facecolor(_WHITE)
        frame.set_edgecolor(_BLACK)
        for t in leg.get_texts():
            t.set_color(_BLACK)


def _restore_axes(ax: "Axes", snap: dict[str, Any]) -> None:
    ax.set_facecolor(snap["facecolor"])
    ax.title.set_color(snap["title_color"])
    ax.xaxis.label.set_color(snap["xlabel_color"])
    ax.yaxis.label.set_color(snap["ylabel_color"])
    for name, color in snap["spines"].items():
        if name in ax.spines:
            ax.spines[name].set_edgecolor(color)
    if snap["xtick_line_color"] is not None:
        ax.tick_params(axis="x", colors=snap["xtick_line_color"])
    if snap["ytick_line_color"] is not None:
        ax.tick_params(axis="y", colors=snap["ytick_line_color"])
    for t, c in zip(ax.get_xticklabels(), snap["xtick_colors"]):
        t.set_color(c)
    for t, c in zip(ax.get_yticklabels(), snap["ytick_colors"]):
        t.set_color(c)
    for line, c in snap["grid_colors"]:
        line.set_color(c)
    leg = ax.get_legend()
    if leg is not None and snap["legend_frame"] is not None:
        fc, ec = snap["legend_frame"]
        leg.get_frame().set_facecolor(fc)
        leg.get_frame().set_edgecolor(ec)
        for t, c in zip(leg.get_texts(), snap["legend_text"]):
            t.set_color(c)


def save_with_white_bg(fig: "Figure", out_path: str, **savefig_kwargs: Any) -> str:
    """
    Save *fig* to *out_path* with a forced white-paper palette.

    All chrome (figure bg, axes bg, spines, ticks, tick labels, axis
    labels, titles, grid lines, legend frame and text) is flipped to a
    white-friendly palette for the duration of the save, then restored
    exactly. Plotted data series (lines, bars, scatter points, image
    colormaps) are left untouched.
    """
    orig_fig_fc = fig.get_facecolor()
    orig_fig_ec = fig.get_edgecolor()
    snapshots = [(ax, _snapshot_axes(ax)) for ax in fig.axes]

    fig.patch.set_facecolor(_WHITE)
    fig.patch.set_edgecolor(_WHITE)
    for ax, _ in snapshots:
        _apply_white(ax)

    # Force facecolor on the save call too — bbox_inches="tight" can
    # otherwise inherit a leftover rcParams value.
    savefig_kwargs.setdefault("facecolor", _WHITE)
    savefig_kwargs.setdefault("edgecolor", _WHITE)

    try:
        fig.savefig(out_path, **savefig_kwargs)
    finally:
        fig.patch.set_facecolor(orig_fig_fc)
        fig.patch.set_edgecolor(orig_fig_ec)
        for ax, snap in snapshots:
            _restore_axes(ax, snap)

    return out_path
