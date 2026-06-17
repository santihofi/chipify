# Copyright (c) 2026 Santiago Hofwimmer
"""
multiplot_window.py – Multi-Plot Dashboard (Qt).

A separate top-level window holding a reflowing grid of configurable plot
cells. Each :class:`PlotCell` reuses the same ``PlotManager`` dispatch as the
main plot tabs (histogram / adv-plot / transient) and the shared
``ScatterHoverManager``. Cell layouts persist to the ``multiplot_config`` key
in ``settings.json``, in the same shape as the legacy CustomTkinter dashboard,
so saved dashboards survive the GUI migration.
"""
from __future__ import annotations

import logging
from typing import Callable

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from chipify import app_config, settings
from chipify.gui.services import data_loader as _dl
from chipify.gui.services import transient_loader as _tl
from chipify.gui.services.scatter_hover import HoverState, ScatterHoverManager
from chipify.gui.state import AppState
from chipify.gui_qt.services import canvas_menu
from chipify.gui_qt.widgets.helpers import compact_combo, deferred
from chipify.gui_qt.widgets.mpl_canvas import MplCanvas
from chipify.plot_manager import PlotManager

log = logging.getLogger("chipify.gui_qt.multiplot")

_BASE_MODES = [
    "Histogram", "Scatter Plot", "Corner Yield Matrix", "Correlation Heatmap",
    "Sensitivity (Tornado)", "Fail Breakdown (Pie Chart)", "Transient",
]
_FIT_CURVES = ["Gauss (Normal)", "KDE (Smoothed)", "Uniform",
               "Log-Normal", "Exponential", "Chi-Squared", "None"]
_BINS = ["Auto", "10", "20", "50", "100", "200"]
_TRAN_RUN_MODES = ["All Valid", "Failing Only", "First N"]


def _all_modes() -> list[str]:
    modes = list(_BASE_MODES)
    try:
        from chipify.plugin_loader import get_plot_plugins
        modes += [cls.name for cls in get_plot_plugins()]
    except Exception:  # noqa: BLE001
        pass
    return modes


class PlotCell(QFrame):
    """One configurable plot in the dashboard grid."""

    def __init__(
        self,
        app_state: AppState,
        plot_theme: Callable[[], dict],
        remove_cb: Callable[["PlotCell"], None],
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("Card")
        self._state = app_state
        self._plot_theme = plot_theme
        self._remove_cb = remove_cb
        self._sc_plot = None
        self._scatter_df = None

        self._build_ui()
        self.canvas.figure.add_subplot(111)
        self.canvas.set_background(self._plot_theme()["bg"])
        self._hover = ScatterHoverManager(
            self.canvas.canvas, self.canvas.figure,
            get_state=self._hover_state, on_point_click=self._on_point_click,
        )
        self._hover.connect()

    # ── Layout ────────────────────────────────────────────────────────────────

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.setSpacing(4)

        header = QHBoxLayout()
        self.mode_combo = QComboBox()
        self.mode_combo.addItems(_all_modes())
        compact_combo(self.mode_combo, length=16)
        header.addWidget(self.mode_combo, stretch=1)
        btn_remove = QPushButton("✕")
        btn_remove.setFixedWidth(28)
        btn_remove.clicked.connect(lambda: self._remove_cb(self))
        header.addWidget(btn_remove)
        layout.addLayout(header)

        # Context controls (shown/hidden per mode).
        self.controls = QHBoxLayout()
        self.param_combo = QComboBox()
        self.group_combo = QComboBox()
        self.dist_combo = QComboBox(); self.dist_combo.addItems(_FIT_CURVES)
        self.compare_combo = QComboBox()
        self.bins_combo = QComboBox(); self.bins_combo.addItems(_BINS)
        self.zoom_check = QCheckBox("Zoom"); self.zoom_check.setToolTip("Zoom to data")
        self.x_combo = QComboBox()
        self.y_combo = QComboBox()
        self.target_combo = QComboBox()
        self.tran_signal_combo = QComboBox()
        self.tran_mode_combo = QComboBox(); self.tran_mode_combo.addItems(_TRAN_RUN_MODES)
        self.tran_n_edit = QLineEdit("10"); self.tran_n_edit.setFixedWidth(56)
        for combo, tip in (
            (self.param_combo, "Parameter"), (self.group_combo, "Group by"),
            (self.dist_combo, "Fit curve"), (self.compare_combo, "Compare run"),
            (self.bins_combo, "Bins"), (self.x_combo, "X axis"),
            (self.y_combo, "Y axis"), (self.target_combo, "Target"),
            (self.tran_signal_combo, "Signal"), (self.tran_mode_combo, "Runs"),
        ):
            combo.setToolTip(tip)
        self._ctl_widgets = [
            self.param_combo, self.group_combo, self.dist_combo, self.compare_combo,
            self.bins_combo, self.zoom_check, self.x_combo, self.y_combo, self.target_combo,
            self.tran_signal_combo, self.tran_mode_combo, self.tran_n_edit,
        ]
        for w in self._ctl_widgets:
            if isinstance(w, QComboBox):
                compact_combo(w, length=8)
            self.controls.addWidget(w)
        self.controls.addStretch(1)
        layout.addLayout(self.controls)

        self.canvas = MplCanvas(figsize=(4, 3), toolbar=False)
        layout.addWidget(self.canvas, stretch=1)

        self.mode_combo.currentIndexChanged.connect(deferred(self._on_mode_change))
        for w in self._ctl_widgets:
            if isinstance(w, QComboBox):
                w.currentIndexChanged.connect(deferred(self._request_redraw))
        self.tran_n_edit.editingFinished.connect(self._request_redraw)
        self.zoom_check.toggled.connect(self._request_redraw)
        self._apply_mode_visibility()

    def _apply_mode_visibility(self) -> None:
        mode = self.mode_combo.currentText()
        vis = {w: False for w in self._ctl_widgets}
        if mode == "Histogram":
            for w in (self.param_combo, self.group_combo, self.dist_combo,
                      self.compare_combo, self.bins_combo, self.zoom_check):
                vis[w] = True
        elif mode in ("Scatter Plot", "Corner Yield Matrix"):
            vis[self.x_combo] = vis[self.y_combo] = True
        elif mode == "Sensitivity (Tornado)":
            vis[self.target_combo] = True
        elif mode == "Transient":
            vis[self.tran_signal_combo] = vis[self.tran_mode_combo] = True
            vis[self.tran_n_edit] = True
        for w, on in vis.items():
            w.setVisible(on)

    def _on_mode_change(self, *_a) -> None:
        self._apply_mode_visibility()
        self._request_redraw()

    def _request_redraw(self, *_a) -> None:
        snap = self._win_snapshot()
        if snap is not None:
            self.redraw(*snap)

    def _win_snapshot(self):
        win = self.window()
        return win.data_snapshot() if hasattr(win, "data_snapshot") else None

    # ── Option population ─────────────────────────────────────────────────────

    def _populate(self, valid_df, stim, sweep_params, derived_cols) -> None:
        if valid_df is None or stim is None:
            return
        cols = _dl.compute_plot_cols(valid_df, stim)
        meas = []
        for test in stim.tests:
            for v in test.value_lst:
                if v.name in valid_df.columns and v.name not in meas:
                    meas.append(v.name)
        params = list(dict.fromkeys(meas + cols.all_numeric_cols + list(derived_cols or [])))
        xy = list(dict.fromkeys(sweep_params + meas + list(derived_cols or [])))

        signals = ["All Signals"]
        for test in stim.tests:
            for an in getattr(test, "analyses", []) or []:
                if an.kind == "transient":
                    for s in an.signals:
                        if s not in signals:
                            signals.append(s)

        self._set(self.param_combo, params)
        self._set(self.group_combo, ["None"] + sweep_params)
        self._set(self.compare_combo, ["None"] + _dl.list_history_runs(settings.OUT_DIR))
        self._set(self.x_combo, xy)
        self._set(self.y_combo, xy)
        self._set(self.target_combo, meas or ["-"])
        self._set(self.tran_signal_combo, signals)

    @staticmethod
    def _set(combo: QComboBox, items: list[str]) -> None:
        current = combo.currentText()
        combo.blockSignals(True)
        combo.clear()
        combo.addItems(items or ["-"])
        if current and current in items:
            combo.setCurrentText(current)
        combo.blockSignals(False)

    # ── Rendering ─────────────────────────────────────────────────────────────

    def redraw(self, valid_df, stim, sweep_params, derived_cols, tran_dir="") -> None:
        self._populate(valid_df, stim, sweep_params, derived_cols)
        mode = self.mode_combo.currentText()
        theme = self._plot_theme()
        self.canvas.set_background(theme["bg"])
        fig, canvas = self.canvas.figure, self.canvas.canvas
        self._sc_plot = self._scatter_df = None
        self._hover.invalidate()

        try:
            if mode == "Histogram":
                param = self.param_combo.currentText()
                fig.clf()
                ax = fig.add_subplot(111)
                if param in valid_df.columns:
                    PlotManager.draw_histogram(
                        fig, ax, canvas, valid_df, stim, param,
                        self.dist_combo.currentText(), self.group_combo.currentText(),
                        self.bins_combo.currentText(), self.zoom_check.isChecked(),
                        self.compare_combo.currentText(), theme=theme,
                    )
                else:
                    canvas.draw_idle()
            elif mode == "Transient":
                self._draw_transient(valid_df, stim, tran_dir, theme)
            else:
                self._sc_plot, self._scatter_df = PlotManager.draw_adv_plot(
                    fig, None, canvas, valid_df, stim, mode,
                    self.x_combo.currentText(), self.y_combo.currentText(),
                    self.target_combo.currentText(), bg_color=theme["bg"], theme=theme,
                )
        except Exception as exc:  # noqa: BLE001
            log.debug("PlotCell redraw failed: %s", exc)
            fig.clf()
            ax = fig.add_subplot(111)
            ax.text(0.5, 0.5, f"Error:\n{exc}", ha="center", va="center",
                    color="#e74c3c", fontsize=8, wrap=True, transform=ax.transAxes)
            canvas.draw_idle()

    def _draw_transient(self, valid_df, stim, tran_dir, theme) -> None:
        sig = self.tran_signal_combo.currentText().strip()
        if sig in ("", "All Signals"):
            signals = []
            for test in stim.tests:
                for an in getattr(test, "analyses", []) or []:
                    if an.kind == "transient":
                        signals.extend(s for s in an.signals if s not in signals)
        else:
            signals = [sig]

        df = self._state.active_df
        run_ids: list[str] = []
        if df is not None and "run_id" in df.columns:
            run_mode = self.tran_mode_combo.currentText()
            if run_mode == "Failing Only" and "global_pass" in df.columns:
                run_ids = list(df[df["global_pass"] == False]["run_id"].astype(str))  # noqa: E712
            elif run_mode == "All Valid":
                run_ids = list(df[df.get("sim_error", "None") == "None"]["run_id"].astype(str))
            else:
                try:
                    n = int(self.tran_n_edit.text())
                except ValueError:
                    n = 10
                run_ids = list(df[df.get("sim_error", "None") == "None"]["run_id"].astype(str).head(n))
        run_ids = run_ids[:500]

        pass_map: dict[str, bool] = {}
        if df is not None and "global_pass" in df.columns:
            for _, r in df[["run_id", "global_pass"]].dropna(subset=["run_id"]).iterrows():
                pass_map[str(r["run_id"]).zfill(6)] = bool(r["global_pass"])

        equations = app_config.load_config().get("transient_equations", [])
        PlotManager.draw_transient_plot(
            self.canvas.figure, self.canvas.canvas, tran_dir, run_ids, signals,
            pass_map=pass_map, bg_color=theme["bg"], equations=equations, theme=theme,
        )

    # ── Scatter hover ─────────────────────────────────────────────────────────

    def _hover_state(self):
        if self.mode_combo.currentText() != "Scatter Plot":
            return None
        if self._sc_plot is None or self._scatter_df is None:
            return None
        return HoverState(self._sc_plot, self._scatter_df,
                          self.x_combo.currentText(), self.y_combo.currentText(),
                          self._state.current_stim)

    def _on_point_click(self, row, state, _event) -> None:
        canvas_menu.show_netlist_export_menu(self, state.stim, row, templates_dir="")

    # ── Persistence ───────────────────────────────────────────────────────────

    def get_config(self) -> dict:
        return {
            "mode": self.mode_combo.currentText(),
            "param": self.param_combo.currentText(),
            "dist": self.dist_combo.currentText(),
            "bins": self.bins_combo.currentText(),
            "zoom": self.zoom_check.isChecked(),
            "group": self.group_combo.currentText(),
            "compare": self.compare_combo.currentText(),
            "x_col": self.x_combo.currentText(),
            "y_col": self.y_combo.currentText(),
            "target": self.target_combo.currentText(),
            "tran_signals": self.tran_signal_combo.currentText(),
            "tran_run_mode": self.tran_mode_combo.currentText(),
            "tran_n": self.tran_n_edit.text(),
        }

    def apply_config(self, cfg: dict) -> None:
        self.mode_combo.setCurrentText(cfg.get("mode", "Histogram"))
        self.dist_combo.setCurrentText(cfg.get("dist", "Gauss (Normal)"))
        self.bins_combo.setCurrentText(cfg.get("bins", "Auto"))
        self.zoom_check.setChecked(bool(cfg.get("zoom", False)))
        self.tran_mode_combo.setCurrentText(cfg.get("tran_run_mode", "First N"))
        self.tran_n_edit.setText(str(cfg.get("tran_n", "10")))
        # Param/x/y/target selections are restored after options repopulate.
        self._pending_cfg = cfg
        self._apply_mode_visibility()

    def restore_pending(self) -> None:
        """Re-apply remembered selections once option lists are populated."""
        cfg = getattr(self, "_pending_cfg", None)
        if not cfg:
            return
        for combo, key in (
            (self.param_combo, "param"), (self.group_combo, "group"),
            (self.compare_combo, "compare"),
            (self.x_combo, "x_col"), (self.y_combo, "y_col"),
            (self.target_combo, "target"), (self.tran_signal_combo, "tran_signals"),
        ):
            val = cfg.get(key)
            if val and combo.findText(val) >= 0:
                combo.setCurrentText(val)
        self._pending_cfg = None


class MultiPlotWindow(QWidget):
    """Top-level dashboard window with a reflowing grid of plot cells."""

    def __init__(
        self,
        app_state: AppState,
        plot_theme: Callable[[], dict],
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent, Qt.Window)
        self.setWindowTitle("Multi-Plot Dashboard")
        self.resize(1100, 800)
        self._state = app_state
        self._plot_theme = plot_theme
        self._cells: list[PlotCell] = []

        self._build_ui()
        self._restore()

        self._state.data_changed.connect(lambda **_k: self.refresh_all())
        self._state.on_data_chunk_added.connect(lambda **_k: self.refresh_all())

    # ── Layout ────────────────────────────────────────────────────────────────

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)

        toolbar = QHBoxLayout()
        btn_add = QPushButton("+ Add Plot")
        btn_add.setObjectName("Accent")
        btn_add.clicked.connect(lambda: self._add_cell())
        toolbar.addWidget(btn_add)
        toolbar.addWidget(QLabel("Columns:"))
        self.cols_spin = QSpinBox()
        self.cols_spin.setRange(1, 4)
        self.cols_spin.setValue(2)
        self.cols_spin.valueChanged.connect(self._reflow)
        toolbar.addWidget(self.cols_spin)
        toolbar.addStretch(1)
        layout.addLayout(toolbar)

        self._grid_host = QWidget()
        self._grid = QGridLayout(self._grid_host)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(self._grid_host)
        layout.addWidget(scroll, stretch=1)

    # ── Cell management ───────────────────────────────────────────────────────

    def data_snapshot(self):
        """``(valid_df, stim, sweep_params, derived_cols, tran_dir)`` or None."""
        df = self._state.active_df
        stim = self._state.current_stim
        if df is None or stim is None:
            return None
        valid_df = _dl.valid_rows(df)
        cols = _dl.compute_plot_cols(valid_df, stim)
        tran_dir = _tl.resolve_analysis_dir(df, settings.OUT_DIR, "transient")
        return valid_df, stim, cols.sweep_params, self._state.derived_cols, tran_dir

    def _add_cell(self, config: dict | None = None) -> PlotCell:
        cell = PlotCell(self._state, self._plot_theme, self._remove_cell)
        if config:
            cell.apply_config(config)
        self._cells.append(cell)
        self._reflow()
        snap = self.data_snapshot()
        if snap is not None:
            cell.redraw(*snap)
            cell.restore_pending()
        return cell

    def _remove_cell(self, cell: PlotCell) -> None:
        if cell in self._cells:
            self._cells.remove(cell)
            cell.setParent(None)
            cell.deleteLater()
            self._reflow()

    def _reflow(self, *_a) -> None:
        cols = self.cols_spin.value()
        for i, cell in enumerate(self._cells):
            self._grid.addWidget(cell, i // cols, i % cols)

    def refresh_all(self) -> None:
        snap = self.data_snapshot()
        if snap is None:
            return
        for cell in self._cells:
            cell.redraw(*snap)

    # ── Persistence ───────────────────────────────────────────────────────────

    def _restore(self) -> None:
        configs = app_config.load_config().get("multiplot_config", []) or []
        for cfg in configs:
            self._add_cell(cfg)
        if not self._cells:
            self._add_cell()

    def closeEvent(self, event) -> None:  # noqa: N802 (Qt override)
        try:
            cfg = app_config.load_config()
            cfg["multiplot_config"] = [c.get_config() for c in self._cells]
            app_config.save_config(cfg)
        except Exception:  # noqa: BLE001
            log.debug("Could not persist multiplot config.", exc_info=True)
        super().closeEvent(event)
