# Copyright (c) 2026 Santiago Hofwimmer
"""
canvas_menu.py – Right-click "export netlist for this sample" menu (Qt).

The Qt replacement for the CustomTkinter popup in
``chipify.uikit.services.netlist_export.show_export_menu``. The netlist rendering
itself is reused unchanged from that module's pure functions
(:func:`render_netlist_for_row`); only the menu UI is rebuilt as a ``QMenu``.
"""
from __future__ import annotations

import logging
import os

from PySide6.QtGui import QCursor
from PySide6.QtWidgets import QFileDialog, QMenu, QMessageBox, QWidget

from chipify import app_config
from chipify.uikit.services import netlist_export

log = logging.getLogger("chipify.gui_qt.canvas_menu")


def show_netlist_export_menu(
    parent: QWidget,
    stim,
    row,
    templates_dir: str = "",
) -> None:
    """Pop a context menu offering a per-testbench netlist export for *row*.

    *row* is the clicked sample's DataFrame row (a ``pandas.Series``); *stim*
    supplies the testbenches. No-op if there are no testbenches.
    """
    tests = list(getattr(stim, "tests", []) or []) if stim is not None else []
    if not tests:
        return
    run_id = str(row.get("run_id", row.name)).zfill(6)

    menu = QMenu(parent)
    for test in tests:
        action = menu.addAction(
            f"Export netlist {test.tb_path} (run #{run_id})…"
        )
        action.triggered.connect(
            lambda _checked=False, t=test: _export(parent, t, row, run_id, templates_dir)
        )
    menu.exec(QCursor.pos())


def _export(parent: QWidget, test, row, run_id: str, templates_dir: str) -> None:
    try:
        rendering = netlist_export.render_netlist_for_row(
            test, dict(row), run_id, templates_dir,
        )
    except Exception as exc:  # noqa: BLE001
        QMessageBox.critical(parent, "Netlist Export", str(exc))
        return

    engine = app_config.load_config().get("simulator_engine", "ngspice")
    ext = ".sim" if engine == "vacask" else ".spice"
    stem = os.path.splitext(os.path.basename(test.tb_path))[0]
    path, _ = QFileDialog.getSaveFileName(
        parent,
        f"Export netlist for run #{run_id}",
        f"run_{run_id}_{stem}{ext}",
        f"SPICE netlist (*{ext});;All files (*)",
    )
    if not path:
        return
    try:
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(rendering)
        log.info("Exported netlist for run %s to %s", run_id, path)
    except OSError as exc:
        QMessageBox.critical(parent, "Netlist Export", f"Could not write file:\n{exc}")
