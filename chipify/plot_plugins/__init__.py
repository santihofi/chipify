# Copyright (c) 2026 Santiago Hofwimmer
"""
Built-in plot plugins for Chipify.

This package ships the distribution-analysis plot modes (QQ plot, ECDF
with spec limits, yield-vs-spec curve) that conform to the
:class:`chipify.plugin_loader.PlotPlugin` contract. They register through
the same plugin mechanism that serves user plugins — see PLUGINS.md.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Type

from chipify.plot_plugins.distribution_plots import (
    ECDFSpecLimits,
    QQPlot,
    YieldVsSpecCurve,
)

if TYPE_CHECKING:
    from chipify.plugin_loader import PlotPlugin

#: Plot modes bundled with the application. ``get_plot_plugins()``
#: merges this list with any user plugins discovered at runtime; user
#: plugins with a colliding ``name`` win.
BUILTIN_PLOT_PLUGINS: list[Type["PlotPlugin"]] = [
    QQPlot,
    ECDFSpecLimits,
    YieldVsSpecCurve,
]

__all__ = ["BUILTIN_PLOT_PLUGINS", "QQPlot", "ECDFSpecLimits", "YieldVsSpecCurve"]
