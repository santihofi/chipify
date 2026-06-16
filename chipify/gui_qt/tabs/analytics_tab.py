# Copyright (c) 2026 Santiago Hofwimmer
"""
analytics_tab.py – Advanced analytics (scatter, corner yield, heatmap,
tornado, fail pie, and plot plugins).

Reuses :func:`chipify.plot_manager.PlotManager.draw_adv_plot` and the shared
:class:`chipify.gui.services.scatter_hover.ScatterHoverManager` unchanged. The
scatter-point context menu is the Qt
:func:`chipify.gui_qt.services.canvas_menu.show_netlist_export_menu`.
"""
from __future__ import annotations

import logging
from typing import Callable

from PySide6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from chipify import app_config
from chipify.gui.services import data_loader as _dl
from chipify.gui.services.scatter_hover import HoverState, ScatterHoverManager
from chipify.gui.state import AppState
from chipify.gui_qt.services import canvas_menu
from chipify.gui_qt.services.throttle import Throttle
from chipify.gui_qt.widgets.helpers import compact_combo, deferred
from chipify.gui_qt.widgets.mpl_canvas import MplCanvas
from chipify.plot_manager import PlotManager

log = logging.getLogger("chipify.gui_qt.tabs.analytics")

_BASE_MODES = [
    "Fail Breakdown (Pie Chart)",
    "Scatter Plot",
    "Corner Yield Matrix",
    "Correlation Heatmap",
    "Sensitivity (Tornado)",
]
_XY_MODES = {"Scatter Plot", "Corner Yield Matrix"}
_TARGET_MODES = {"Sensitivity (Tornado)"}


class AnalyticsTab(QWidget):
    """Mode-driven analytics plots over the results DataFrame."""

    def __init__(
        self,
        app_state: AppState,
        plot_theme: Callable[[], dict],
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._state = app_state
        self._plot_theme = plot_theme
        self._sc_plot = None
        self._scatter_df = None

        self._build_ui()
        self.canvas.figure.add_subplot(111)
        self.canvas.set_background(self._plot_theme()["bg"])

        self._hover = ScatterHoverManager(
            self.canvas.canvas, self.canvas.figure,
            get_state=self._hover_state,
            on_point_click=self._on_point_click,
        )
        self._hover.connect()

        self._throttle = Throttle(self._redraw, app_config.get_live_throttle_ms(), self)
        self._state.data_changed.connect(self._on_data_changed)
        self._state.on_data_chunk_added.connect(lambda **_k: self._throttle.request())

    # ── Layout ────────────────────────────────────────────────────────────────

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(8)

        controls = QHBoxLayout()
        controls.setSpacing(8)

        self.mode_combo = QComboBox()
        self.mode_combo.addItems(self._all_modes())
        compact_combo(self.mode_combo, length=16)
        controls.addWidget(QLabel("Mode:"))
        controls.addWidget(self.mode_combo)

        self.lbl_x = QLabel("X:")
        self.x_combo = QComboBox()
        self.lbl_y = QLabel("Y:")
        self.y_combo = QComboBox()
        self.lbl_target = QLabel("Target:")
        self.target_combo = QComboBox()
        for _c in (self.x_combo, self.y_combo, self.target_combo):
            compact_combo(_c)
        for w in (self.lbl_x, self.x_combo, self.lbl_y, self.y_combo,
                  self.lbl_target, self.target_combo):
            controls.addWidget(w)
        controls.addStretch(1)
        self.btn_export = QPushButton("Export…")
        self.btn_export.clicked.connect(self._export)
        controls.addWidget(self.btn_export)
        layout.addLayout(controls)

        self.canvas = MplCanvas(figsize=(8, 5))
        layout.addWidget(self.canvas, stretch=1)

        self.mode_combo.currentIndexChanged.connect(deferred(self._on_mode_change))
        for combo in (self.x_combo, self.y_combo, self.target_combo):
            combo.currentIndexChanged.connect(deferred(self._redraw))
        self._apply_mode_visibility()

    @staticmethod
    def _all_modes() -> list[str]:
        modes = list(_BASE_MODES)
        try:
            from chipify.plugin_loader import get_plot_plugins
            modes += [cls.name for cls in get_plot_plugins()]
        except Exception:  # noqa: BLE001
            log.debug("Could not enumerate plot plugins.", exc_info=True)
        return modes

    # ── Mode handling ─────────────────────────────────────────────────────────

    def _apply_mode_visibility(self) -> None:
        mode = self.mode_combo.currentText()
        xy = mode in _XY_MODES
        tgt = mode in _TARGET_MODES
        for w in (self.lbl_x, self.x_combo, self.lbl_y, self.y_combo):
            w.setVisible(xy)
        for w in (self.lbl_target, self.target_combo):
            w.setVisible(tgt)

    def _on_mode_change(self, *_a) -> None:
        self._apply_mode_visibility()
        self._repopulate_options(self._state.active_df, self._state.current_stim)
        self._redraw()

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

        mode = self.mode_combo.currentText()
        if mode == "Corner Yield Matrix":
            xy_opts = cols.sweep_params or ["-"]
        else:
            xy_opts = list(dict.fromkeys(cols.sweep_params + meas_names)) or ["-"]
        target_opts = meas_names or ["-"]

        self._set_items(self.x_combo, xy_opts, prefer_index=0)
        self._set_items(self.y_combo, xy_opts, prefer_index=1)
        self._set_items(self.target_combo, target_opts, prefer_index=0)

    @staticmethod
    def _set_items(combo: QComboBox, items: list[str], prefer_index: int = 0) -> None:
        current = combo.currentText()
        combo.blockSignals(True)
        combo.clear()
        combo.addItems(items)
        if current in items:
            combo.setCurrentText(current)
        elif items:
            combo.setCurrentIndex(min(prefer_index, len(items) - 1))
        combo.blockSignals(False)

    # ── Rendering ─────────────────────────────────────────────────────────────

    def _redraw(self, *_args) -> None:
        df = self._state.active_df
        stim = self._state.current_stim
        if df is None or stim is None:
            return
        valid_df = _dl.valid_rows(df)
        if valid_df.empty:
            return

        theme = self._plot_theme()
        self.canvas.set_background(theme["bg"])
        self._sc_plot, self._scatter_df = PlotManager.draw_adv_plot(
            self.canvas.figure, None, self.canvas.canvas, valid_df, stim,
            self.mode_combo.currentText(),
            self.x_combo.currentText(),
            self.y_combo.currentText(),
            self.target_combo.currentText(),
            bg_color=theme["bg"], theme=theme,
        )
        # draw_adv_plot did fig.clf() — drop the stale tooltip annotation.
        self._hover.invalidate()

    # ── Scatter hover / click ─────────────────────────────────────────────────

    def _hover_state(self):
        if self.mode_combo.currentText() != "Scatter Plot":
            return None
        if self._sc_plot is None or self._scatter_df is None:
            return None
        return HoverState(
            self._sc_plot, self._scatter_df,
            self.x_combo.currentText(), self.y_combo.currentText(),
            self._state.current_stim,
        )

    def _on_point_click(self, row, state, _event) -> None:
        canvas_menu.show_netlist_export_menu(self, state.stim, row, templates_dir="")

    def _export(self) -> None:
        from chipify.gui_qt.services.figure_export import export_figure
        export_figure(
            self, self.canvas.figure,
            self.mode_combo.currentText(), self._plot_theme(),
        )
