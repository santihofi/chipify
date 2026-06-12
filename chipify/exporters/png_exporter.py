# Copyright (c) 2026 Santiago Hofwimmer
"""Built-in PNG exporter."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from chipify.exporters._white_bg import save_with_white_bg
from chipify.plugin_loader import ExporterPlugin

if TYPE_CHECKING:
    from matplotlib.figure import Figure


class PNGExporter(ExporterPlugin):
    name: str = "PNG Image"
    extension: str = "png"
    description: str = "Raster PNG, 200 DPI, white background."

    def export(
        self,
        fig: "Figure",
        out_path: str,
        *,
        theme: dict[str, Any] | None = None,
    ) -> str:
        return save_with_white_bg(
            fig, out_path,
            format="png", dpi=200, bbox_inches="tight",
        )
