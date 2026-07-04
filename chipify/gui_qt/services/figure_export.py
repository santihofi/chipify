# Copyright (c) 2026 Santiago Hofwimmer
"""
figure_export.py – Export a matplotlib figure via the exporter plugins (Qt).

Surfaces the built-in PNG/SVG exporters (and any user ``ExporterPlugin``) as a
save dialog, mirroring the legacy ``attach_export_button`` flow. The exporter
classes and their ``export(fig, out_path, *, theme=None)`` contract are reused
from :func:`chipify.plugin_loader.get_exporter_plugins`.
"""
from __future__ import annotations

import logging
from pathlib import Path

from PySide6.QtWidgets import QFileDialog, QMessageBox, QWidget

log = logging.getLogger("chipify.gui_qt.figure_export")


def export_figure(
    parent: QWidget,
    figure,
    suggested_name: str,
    theme: dict | None = None,
) -> None:
    """Prompt for a path and write *figure* with the chosen exporter plugin."""
    from chipify.plugin_loader import get_exporter_plugins

    exporters = list(get_exporter_plugins())
    if not exporters:
        QMessageBox.warning(parent, "Export", "No exporters available.")
        return

    by_ext = {e.extension.lstrip("."): e for e in exporters}
    filters = ";;".join(f"{e.name} (*.{e.extension.lstrip('.')})" for e in exporters)
    default = f"{suggested_name}.{exporters[0].extension.lstrip('.')}"

    path, selected = QFileDialog.getSaveFileName(parent, "Export figure", default, filters)
    if not path:
        return

    ext = Path(path).suffix.lstrip(".").lower()
    exporter_cls = by_ext.get(ext)
    if exporter_cls is None:
        exporter_cls = next((e for e in exporters if e.name in selected), exporters[0])

    try:
        try:
            written = exporter_cls().export(figure, path, theme=theme)
        except TypeError:
            written = exporter_cls().export(figure, path)  # exporter without theme kwarg
        log.info("Exported figure to %s", written or path)
    except Exception as exc:  # noqa: BLE001
        QMessageBox.critical(parent, "Export", f"Export failed:\n{exc}")
