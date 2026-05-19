"""Built-in SVG exporter."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from chipify.plugin_loader import ExporterPlugin

if TYPE_CHECKING:
    from matplotlib.figure import Figure


class SVGExporter(ExporterPlugin):
    name: str = "SVG Vector"
    extension: str = "svg"
    description: str = "Scalable vector SVG; best for slides, papers, and re-styling."

    def export(
        self,
        fig: "Figure",
        out_path: str,
        *,
        theme: dict[str, Any] | None = None,
    ) -> str:
        fig.savefig(
            out_path,
            format="svg",
            bbox_inches="tight",
            facecolor=fig.get_facecolor(),
        )
        return out_path
