# Copyright (c) 2026 Santiago Hofwimmer
"""
Built-in exporter plugins for Chipify.

This package ships PNG and SVG savers that conform to the
:class:`chipify.plugin_loader.ExporterPlugin` contract. Additional
formats are pulled in via the same plugin-discovery mechanism that
serves PlotPlugin / ReportPlugin / ExpressionPlugin — see PLUGINS.md.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Type

from chipify.exporters.png_exporter import PNGExporter
from chipify.exporters.svg_exporter import SVGExporter

if TYPE_CHECKING:
    from chipify.plugin_loader import ExporterPlugin

#: Exporters bundled with the application. ``get_exporter_plugins()``
#: merges this list with any user plugins discovered at runtime; user
#: plugins with a colliding ``name`` win.
BUILTIN_EXPORTERS: list[Type["ExporterPlugin"]] = [PNGExporter, SVGExporter]

__all__ = ["BUILTIN_EXPORTERS", "PNGExporter", "SVGExporter"]
