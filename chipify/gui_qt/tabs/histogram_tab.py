# Copyright (c) 2026 Santiago Hofwimmer
"""
histogram_tab.py – Per-parameter distribution histogram.

Reuses :func:`chipify.plot_manager.PlotManager.draw_histogram` unchanged; this
tab only supplies the Qt controls (parameter, grouping, fit curve, comparison
run, bins, zoom) and a KPI readout (Cpk / σ / μ / std / fail-rate). Option
lists are rebuilt on ``data_changed``; live chunks trigger a throttled redraw.
"""
from __future__ import annotations

import logging
from typing import Callable

from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from chipify import app_config, settings
from chipify.gui.services import data_loader as _dl
from chipify.gui.services import measurements as _meas
from chipify.gui.state import AppState
from chipify.gui_qt.services.throttle import Throttle
from chipify.gui_qt.widgets.helpers import compact_combo, deferred, elide_horizontally
from chipify.gui_qt.widgets.mpl_canvas import MplCanvas
from chipify.plot_manager import PlotManager

log = logging.getLogger("chipify.gui_qt.tabs.histogram")

_FIT_CURVES = ["Gauss (Normal)", "KDE (Smoothed)", "Uniform",
               "Log-Normal", "Exponential", "Chi-Squared", "None"]
_BINS = ["Auto", "10", "20", "50", "100", "200"]


def _eng(v: float) -> str:
    """Compact engineering format (matches the legacy KPI readout)."""
    av = abs(v)
    if av >= 1e3:
        return f"{v / 1e3:.3g}k"
    if av >= 1:
        return f"{v:.4g}"
    if av >= 1e-3:
        return f"{v * 1e3:.3g}m"
    if av >= 1e-6:
        return f"{v * 1e6:.3g}µ"
    return f"{v:.3g}"


class HistogramTab(QWidget):
    """Distribution histogram with fit overlays and a KPI strip."""

    def __init__(
        self,
        app_state: AppState,
        plot_theme: Callable[[], dict],
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._state = app_state
        self._plot_theme = plot_theme

        self._build_ui()
        self.ax = self.canvas.figure.add_subplot(111)
        self.canvas.set_background(self._plot_theme()["bg"])

        self._throttle = Throttle(self._redraw, app_config.get_live_throttle_ms(), self)
        self._state.data_changed.connect(self._on_data_changed)
        self._state.on_data_chunk_added.connect(lambda **_k: self._throttle.request())

    # ── Layout ────────────────────────────────────────────────────────────────

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(8)

        self.param_combo = QComboBox()
        self.group_combo = QComboBox()
        self.fit_combo = QComboBox()
        self.fit_combo.addItems(_FIT_CURVES)
        self.compare_combo = QComboBox()
        self.bins_combo = QComboBox()
        self.bins_combo.addItems(_BINS)
        self.zoom_check = QCheckBox("Zoom to data")
        self.btn_export = QPushButton("Export…")
        self.btn_export.clicked.connect(self._export)
        for _c in (self.param_combo, self.group_combo, self.fit_combo,
                   self.compare_combo, self.bins_combo):
            compact_combo(_c)

        # Two rows: five compact combos each carry a ~170px minimum, so a single
        # row would force the tab (and thus the window) wider than a small
        # screen. Splitting in two keeps the minimum width well under typical
        # displays so the window can size down to fit.
        row1 = QHBoxLayout()
        row1.setSpacing(8)
        for label, w in (
            ("Meas:", self.param_combo),
            ("Group:", self.group_combo),
            ("Fit:", self.fit_combo),
        ):
            row1.addWidget(QLabel(label))
            row1.addWidget(w)
        row1.addStretch(1)

        row2 = QHBoxLayout()
        row2.setSpacing(8)
        for label, w in (
            ("Compare:", self.compare_combo),
            ("Bins:", self.bins_combo),
        ):
            row2.addWidget(QLabel(label))
            row2.addWidget(w)
        row2.addWidget(self.zoom_check)
        row2.addWidget(self.btn_export)
        row2.addStretch(1)

        self.kpi_label = QLabel("")
        self.kpi_label.setObjectName("Muted")
        elide_horizontally(self.kpi_label)
        row2.addWidget(self.kpi_label)

        layout.addLayout(row1)
        layout.addLayout(row2)

        self.canvas = MplCanvas(figsize=(6, 4))
        layout.addWidget(self.canvas, stretch=1)

        for combo in (self.param_combo, self.group_combo, self.fit_combo,
                      self.compare_combo, self.bins_combo):
            combo.currentIndexChanged.connect(deferred(self._redraw))
        self.zoom_check.toggled.connect(self._redraw)

    # ── Option population ─────────────────────────────────────────────────────

    def _on_data_changed(self, df=None, stim=None, switch_tab=False, **_kw) -> None:
        self._repopulate_options(df, stim)
        self._redraw()

    def _repopulate_options(self, df, stim) -> None:
        if df is None or stim is None:
            return
        valid_df = _dl.valid_rows(df)
        cols = _dl.compute_plot_cols(valid_df, stim)

        meas_names: list[str] = []
        for test in stim.tests:
            for v in test.value_lst:
                if v.name in df.columns and v.name not in meas_names:
                    meas_names.append(v.name)
        params = list(dict.fromkeys(meas_names + cols.all_numeric_cols))

        runs = ["None"] + _dl.list_history_runs(settings.OUT_DIR)

        self._set_items(self.param_combo, params)
        self._set_items(self.group_combo, ["None"] + cols.sweep_params)
        self._set_items(self.compare_combo, runs)

    @staticmethod
    def _set_items(combo: QComboBox, items: list[str]) -> None:
        """Replace items, preserving the current selection where possible."""
        current = combo.currentText()
        combo.blockSignals(True)
        combo.clear()
        combo.addItems(items or ["-"])
        if current in items:
            combo.setCurrentText(current)
        combo.blockSignals(False)

    # ── Rendering ─────────────────────────────────────────────────────────────

    def _redraw(self, *_args) -> None:
        df = self._state.active_df
        stim = self._state.current_stim
        param = self.param_combo.currentText()
        if df is None or stim is None or not param or param == "-":
            return
        valid_df = _dl.valid_rows(df)
        if param not in valid_df.columns:
            return

        self._update_kpis(valid_df, stim, param)
        theme = self._plot_theme()
        self.canvas.set_background(theme["bg"])
        PlotManager.draw_histogram(
            self.canvas.figure, self.ax, self.canvas.canvas, valid_df, stim,
            param,
            self.fit_combo.currentText(),
            self.group_combo.currentText(),
            self.bins_combo.currentText(),
            self.zoom_check.isChecked(),
            self.compare_combo.currentText(),
            theme=theme,
        )

    def _export(self) -> None:
        from chipify.gui_qt.services.figure_export import export_figure
        export_figure(
            self, self.canvas.figure,
            f"histogram_{self.param_combo.currentText()}", self._plot_theme(),
        )

    def _update_kpis(self, valid_df, stim, param: str) -> None:
        data = valid_df[param].dropna()
        if data.empty:
            self.kpi_label.setText("")
            return
        rows = {r.name: r for r in _meas.measurement_rows(valid_df, stim)}
        r = rows.get(param)
        cpk = r.cpk_str if r else "—"
        sigma = r.sigma_str if r else "—"
        fail = f"{r.fail_n} fail" if (r and r.fail_n) else "0 fail"
        self.kpi_label.setText(
            f"Cpk: {cpk}   σ: {sigma}   μ: {_eng(data.mean())}   "
            f"std: {_eng(data.std() if len(data) > 1 else 0.0)}   {fail}"
        )
