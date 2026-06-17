# Copyright (c) 2026 Santiago Hofwimmer
"""
transient_tab.py – Waveform overlays (Transient / DC sweep / Bode).

Reuses the shared, framework-agnostic
:mod:`chipify.gui.services.transient_loader` (directory resolution + signal
discovery) and the ``PlotManager.draw_transient_plot`` / ``draw_dc_sweep`` /
``draw_bode_plot`` overlay plotters unchanged. This tab supplies the Qt
controls: analysis kind, run-selection mode, and a multi-select signal list.

Unlike the histogram/analytics tabs this one reads per-run CSVs from disk, so it
redraws on completed loads (``data_changed``) only — not on every live chunk.
"""
from __future__ import annotations

import logging
from typing import Callable

from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from chipify import app_config, settings
from chipify.gui.services import transient_loader as _tl
from chipify.gui.state import AppState
from chipify.gui_qt.widgets.helpers import compact_combo, deferred
from chipify.gui_qt.widgets.mpl_canvas import MplCanvas
from chipify.plot_manager import PlotManager

log = logging.getLogger("chipify.gui_qt.tabs.transient")

#: UI label → Analysis.kind (on disk / in df.attrs["analysis_dirs"]).
_KIND_LABELS = {"Transient": "transient", "DC Sweep": "dc", "Bode": "ac"}
_RUN_MODES = ["All Valid", "Failing Only", "First N", "Custom IDs"]
_RUN_CAP = 500


class TransientTab(QWidget):
    """Per-run waveform overlay for the three analysis kinds."""

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
        self.canvas.set_background(self._plot_theme()["bg"])
        self._state.data_changed.connect(self._on_data_changed)

    # ── Layout ────────────────────────────────────────────────────────────────

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(8)

        controls = QHBoxLayout()
        controls.setSpacing(8)

        self.kind_combo = QComboBox()
        self.kind_combo.addItems(list(_KIND_LABELS))
        self.mode_combo = QComboBox()
        self.mode_combo.addItems(_RUN_MODES)
        for _c in (self.kind_combo, self.mode_combo):
            compact_combo(_c, length=12)
        self.n_edit = QLineEdit("10")
        self.n_edit.setFixedWidth(90)
        self.n_edit.setPlaceholderText("N or ids…")
        self.btn_refresh = QPushButton("↺ Refresh")

        controls.addWidget(QLabel("Mode:"))
        controls.addWidget(self.kind_combo)
        controls.addWidget(QLabel("Runs:"))
        controls.addWidget(self.mode_combo)
        controls.addWidget(self.n_edit)
        controls.addStretch(1)
        self.btn_export = QPushButton("Export…")
        self.btn_export.clicked.connect(self._export)
        controls.addWidget(self.btn_export)
        self.btn_latex = QPushButton("TeX Export")
        self.btn_latex.clicked.connect(self._export_latex)
        controls.addWidget(self.btn_latex)
        controls.addWidget(self.btn_refresh)
        layout.addLayout(controls)

        body = QHBoxLayout()
        body.setSpacing(8)

        sig_panel = QVBoxLayout()
        sig_panel.setSpacing(4)
        sig_panel.addWidget(QLabel("Signals"))
        self.signal_list = QListWidget()
        self.signal_list.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.signal_list.setFixedWidth(170)
        sig_panel.addWidget(self.signal_list, stretch=1)
        self.btn_select_all = QPushButton("Select All")
        sig_panel.addWidget(self.btn_select_all)
        body.addLayout(sig_panel)

        self.canvas = MplCanvas(figsize=(8, 5))
        body.addWidget(self.canvas, stretch=1)
        layout.addLayout(body, stretch=1)

        self.kind_combo.currentIndexChanged.connect(deferred(self._on_kind_change))
        self.mode_combo.currentIndexChanged.connect(deferred(self._on_mode_change))
        self.btn_refresh.clicked.connect(self._redraw)
        self.btn_select_all.clicked.connect(self.signal_list.selectAll)
        self._apply_mode_visibility()

    # ── Control handlers ──────────────────────────────────────────────────────

    def _current_kind(self) -> str:
        return _KIND_LABELS.get(self.kind_combo.currentText(), "transient")

    def _apply_mode_visibility(self) -> None:
        self.n_edit.setVisible(self.mode_combo.currentText() in ("First N", "Custom IDs"))

    def _on_mode_change(self, *_a) -> None:
        self._apply_mode_visibility()
        self._redraw()

    def _on_kind_change(self, *_a) -> None:
        self._refresh_signal_list()
        self._redraw()

    def _on_data_changed(self, df=None, stim=None, switch_tab=False, **_kw) -> None:
        self._refresh_signal_list()
        self._redraw()

    # ── Signal list ───────────────────────────────────────────────────────────

    def _refresh_signal_list(self) -> None:
        """Populate the signal list from the stim's analyses for this kind."""
        kind = self._current_kind()
        stim = self._state.current_stim
        seen: list[str] = []
        if stim is not None:
            for test in stim.tests:
                for an in getattr(test, "analyses", []) or []:
                    if an.kind != kind:
                        continue
                    for sig in an.signals:
                        if sig not in seen:
                            seen.append(sig)
        if kind == "transient":
            for eq in app_config.load_config().get("transient_equations", []):
                name = (eq.get("name") or "").strip()
                if name and name not in seen:
                    seen.append(name)

        self.signal_list.clear()
        self.signal_list.addItems(seen)
        self.signal_list.selectAll()

    # ── Rendering ─────────────────────────────────────────────────────────────

    def _resolve_dir(self) -> str:
        df = self._state.active_df
        if df is None:
            import pandas as pd
            df = pd.DataFrame()
        return _tl.resolve_analysis_dir(df, settings.OUT_DIR, self._current_kind())

    def _selected_run_ids(self, df) -> list[str]:
        mode = self.mode_combo.currentText()
        if "run_id" not in df.columns:
            return []
        if mode == "Failing Only":
            if "global_pass" not in df.columns:
                return []
            ids = list(df[df["global_pass"] == False]["run_id"].astype(str))  # noqa: E712
        elif mode == "First N":
            try:
                n = int(self.n_edit.text())
            except ValueError:
                n = 10
            ids = list(df[df["sim_error"] == "None"]["run_id"].astype(str).head(n))
        elif mode == "Custom IDs":
            raw = self.n_edit.text().replace(",", " ")
            ids = [r.strip().zfill(6) for r in raw.split() if r.strip()]
        else:  # All Valid
            ids = list(df[df["sim_error"] == "None"]["run_id"].astype(str))
        return ids[:_RUN_CAP]

    def _export(self) -> None:
        from chipify.gui_qt.services.figure_export import export_figure
        export_figure(
            self, self.canvas.figure,
            self.kind_combo.currentText().lower().replace(" ", "_"), self._plot_theme(),
        )

    def _export_latex(self) -> None:
        """Export the current overlay selection as pgfplots CSV + .tex."""
        from chipify.gui_qt.services.latex_export import export_overlay_latex
        df = self._state.active_df
        kind = self._current_kind()
        adir = self._resolve_dir() if df is not None else ""
        signals = [i.text() for i in self.signal_list.selectedItems()]
        run_ids = self._selected_run_ids(df) if df is not None else []
        equations = (
            app_config.load_config().get("transient_equations", [])
            if kind == "transient" else []
        )
        export_overlay_latex(self, kind, adir, run_ids, signals, equations)

    def _redraw(self, *_args) -> None:
        kind = self._current_kind()
        theme = self._plot_theme()
        self.canvas.set_background(theme["bg"])
        draw_fn = {
            "transient": PlotManager.draw_transient_plot,
            "dc": PlotManager.draw_dc_sweep,
            "ac": PlotManager.draw_bode_plot,
        }[kind]
        fig, canvas = self.canvas.figure, self.canvas.canvas

        df = self._state.active_df
        adir = self._resolve_dir() if df is not None else ""
        signals = [i.text() for i in self.signal_list.selectedItems()]

        if df is None or not adir or not signals:
            draw_fn(fig, canvas, adir, [], [], bg_color=theme["bg"], theme=theme)
            return

        run_ids = self._selected_run_ids(df)
        pass_map: dict[str, bool] = {}
        if "global_pass" in df.columns and "run_id" in df.columns:
            for _, r in df[["run_id", "global_pass"]].dropna(subset=["run_id"]).iterrows():
                pass_map[str(r["run_id"]).zfill(6)] = bool(r["global_pass"])
        equations = (
            app_config.load_config().get("transient_equations", [])
            if kind == "transient" else []
        )
        draw_fn(
            fig, canvas, adir, run_ids, signals,
            pass_map=pass_map, bg_color=theme["bg"],
            equations=equations, theme=theme,
        )
