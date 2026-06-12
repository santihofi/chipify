# Copyright (c) 2026 Santiago Hofwimmer
"""Built-in SVG exporter."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from chipify.exporters._white_bg import save_with_white_bg
from chipify.plugin_loader import ExporterPlugin

if TYPE_CHECKING:
    from matplotlib.figure import Figure


class SVGExporter(ExporterPlugin):
    name: str = "SVG Vector"
    extension: str = "svg"
    description: str = "Scalable vector SVG, white background; ideal for slides and papers."

    def export(
        self,
        fig: "Figure",
        out_path: str,
        *,
        theme: dict[str, Any] | None = None,
    ) -> str:
        return save_with_white_bg(
            fig, out_path,
            format="svg", bbox_inches="tight",
        )
