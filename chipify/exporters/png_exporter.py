"""Built-in PNG exporter."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from chipify.plugin_loader import ExporterPlugin

if TYPE_CHECKING:
    from matplotlib.figure import Figure


class PNGExporter(ExporterPlugin):
    name: str = "PNG Image"
    extension: str = "png"
    description: str = "Raster PNG, 200 DPI, preserves the plot's background colour."

    def export(
        self,
        fig: "Figure",
        out_path: str,
        *,
        theme: dict[str, Any] | None = None,
    ) -> str:
        fig.savefig(
            out_path,
            format="png",
            dpi=200,
            bbox_inches="tight",
            facecolor=fig.get_facecolor(),
        )
        return out_path
