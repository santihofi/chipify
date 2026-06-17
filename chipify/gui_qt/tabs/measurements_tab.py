# Copyright (c) 2026 Santiago Hofwimmer
"""
measurements_tab.py – Results overview in three stacked sections.

1. **Parameter results** – one row per spec'd parameter (sim min/typ/max, spec
   limits, Cpk, sigma, pass/fail).
2. **Equation results** – one row per applied scalar (custom) equation
   (expression + min/typ/max of the derived column).
3. **Worst cases** – for each failing parameter, the single worst run, the spec
   it violated, and the sweep conditions that triggered it.

All three are computed by the shared, framework-agnostic
:mod:`chipify.gui.services.measurements` helpers. The tab subscribes to
``AppState`` so it refreshes on completed loads (``data_changed``) and live
chunks (``on_data_chunk_added``, coalesced via a Throttle).
"""
from __future__ import annotations

import logging

from PySide6.QtCore import Qt
from PySide6.QtGui import QBrush, QColor
from PySide6.QtWidgets import (
    QAbstractItemView,
    QHeaderView,
    QLabel,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from chipify import app_config
from chipify.gui.services import data_loader as _dl
from chipify.gui.services import measurements as _meas
from chipify.gui.state import AppState
from chipify.gui_qt.services.throttle import Throttle

log = logging.getLogger("chipify.gui_qt.tabs.measurements")

_PARAM_COLUMNS = ["Parameter", "Unit", "Sim Min", "Sim Typ", "Sim Max",
                  "Spec Min", "Spec Max", "Cpk", "Sigma", "Status"]
_EQ_COLUMNS = ["Equation", "Expression", "Min", "Typ", "Max"]
_WORST_COLUMNS = ["Parameter", "Worst", "Spec", "Fails", "Conditions"]

_PASS_COLOR = QColor("#2ecc71")
_FAIL_COLOR = QColor("#e74c3c")
_MUTED_COLOR = QColor("#888888")


def _fmt_conditions(conditions: dict) -> str:
    """Compact 'name=value, …' rendering of a worst-case run's sweep point."""
    parts = []
    for key, val in conditions.items():
        txt = f"{val:g}" if isinstance(val, float) else str(val)
        parts.append(f"{key}={txt}")
    return ", ".join(parts)


class MeasurementsTab(QWidget):
    """Parameter results, equation results, and worst-case outliers."""

    def __init__(self, app_state: AppState, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._state = app_state
        self._build_ui()

        # Live chunks can arrive rapidly; coalesce table rebuilds.
        self._throttle = Throttle(
            self._refresh_from_state, app_config.get_live_throttle_ms(), self,
        )
        self._state.data_changed.connect(self._on_data_changed)
        self._state.on_data_chunk_added.connect(self._on_chunk_added)

    # ── Layout ────────────────────────────────────────────────────────────────

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(6)

        layout.addWidget(self._heading("PARAMETER RESULTS"))
        self.tree = self._make_tree(_PARAM_COLUMNS)
        layout.addWidget(self.tree, stretch=3)

        layout.addWidget(self._heading("EQUATION RESULTS"))
        self.eq_tree = self._make_tree(_EQ_COLUMNS, stretch_col=1)
        layout.addWidget(self.eq_tree, stretch=1)

        layout.addWidget(self._heading("WORST CASES"))
        self.worst_tree = self._make_tree(_WORST_COLUMNS, stretch_col=4)
        layout.addWidget(self.worst_tree, stretch=2)

        self.status_label = QLabel("Run a simulation to see results…")
        self.status_label.setObjectName("Muted")
        self.status_label.setWordWrap(True)
        self.status_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        layout.addWidget(self.status_label)

    @staticmethod
    def _heading(text: str) -> QLabel:
        lbl = QLabel(text)
        lbl.setObjectName("Heading")
        return lbl

    @staticmethod
    def _make_tree(columns: list[str], stretch_col: int = 0) -> QTreeWidget:
        tree = QTreeWidget()
        tree.setColumnCount(len(columns))
        tree.setHeaderLabels(columns)
        tree.setRootIsDecorated(False)
        tree.setAlternatingRowColors(True)
        tree.setSelectionBehavior(QAbstractItemView.SelectRows)
        tree.setEditTriggers(QAbstractItemView.NoEditTriggers)
        header = tree.header()
        for i in range(len(columns)):
            header.setSectionResizeMode(
                i, QHeaderView.Stretch if i == stretch_col else QHeaderView.ResizeToContents
            )
        return tree

    # ── AppState slots ──────────────────────────────────────────────────────────

    def _on_data_changed(self, df=None, stim=None, switch_tab=False, **_kw) -> None:
        self._throttle.force_now()

    def _on_chunk_added(self, df=None, stim=None, chunk_len=0, **_kw) -> None:
        self._throttle.request()

    # ── Rendering ─────────────────────────────────────────────────────────────

    def _refresh_from_state(self) -> None:
        self.refresh(self._state.active_df, self._state.current_stim)

    def refresh(self, df, stim) -> None:
        """Rebuild all three sections from *df* / *stim*."""
        self.tree.clear()
        self.eq_tree.clear()
        self.worst_tree.clear()
        if df is None or stim is None:
            self.status_label.setText("Run a simulation to see results…")
            return

        valid_df = _dl.valid_rows(df)
        total = len(df)
        valid = len(valid_df)

        rows = _meas.measurement_rows(valid_df, stim)
        self._fill_parameter_rows(rows)

        equations = app_config.load_config().get("custom_equations", []) or []
        eq_rows = _meas.equation_rows(valid_df, equations)
        self._fill_equation_rows(eq_rows)

        worst = _meas.worst_cases(valid_df, stim, total)
        self._fill_worst_rows(worst)

        self._update_status(rows, worst, valid, total)

    def _fill_parameter_rows(self, rows) -> None:
        if not rows:
            self._placeholder(self.tree, "No matching parameters in this run.")
            return
        for r in rows:
            item = QTreeWidgetItem([
                r.name,
                r.unit or "-",
                _meas.fmt_value(r.sim_min),
                _meas.fmt_value(r.sim_typ),
                _meas.fmt_value(r.sim_max),
                _meas.fmt_value(r.spec_min),
                _meas.fmt_value(r.spec_max),
                r.cpk_str,
                r.sigma_str,
                r.status,
            ])
            brush = QBrush(_PASS_COLOR if r.status == "PASS" else _FAIL_COLOR)
            item.setForeground(len(_PARAM_COLUMNS) - 1, brush)
            for col in range(1, len(_PARAM_COLUMNS)):
                item.setTextAlignment(col, Qt.AlignCenter)
            self.tree.addTopLevelItem(item)

    def _fill_equation_rows(self, eq_rows) -> None:
        if not eq_rows:
            self._placeholder(self.eq_tree, "No scalar equations applied.")
            return
        for e in eq_rows:
            item = QTreeWidgetItem([
                e.name, e.expr,
                _meas.fmt_value(e.sim_min),
                _meas.fmt_value(e.sim_typ),
                _meas.fmt_value(e.sim_max),
            ])
            for col in range(2, len(_EQ_COLUMNS)):
                item.setTextAlignment(col, Qt.AlignCenter)
            self.eq_tree.addTopLevelItem(item)

    def _fill_worst_rows(self, worst) -> None:
        if not worst:
            self._placeholder(self.worst_tree, "No outliers — all failing rows are within spec.")
            return
        for w in worst:
            item = QTreeWidgetItem([
                w.name,
                _meas.fmt_value(w.worst_val),
                w.violation,
                f"{w.fail_n} / {w.total}",
                _fmt_conditions(w.conditions),
            ])
            for col in (1, 2, 3):
                item.setTextAlignment(col, Qt.AlignCenter)
            item.setForeground(1, QBrush(_FAIL_COLOR))
            self.worst_tree.addTopLevelItem(item)

    @staticmethod
    def _placeholder(tree: QTreeWidget, text: str) -> None:
        item = QTreeWidgetItem([text] + [""] * (tree.columnCount() - 1))
        item.setForeground(0, QBrush(_MUTED_COLOR))
        tree.addTopLevelItem(item)

    def _update_status(self, rows, worst, valid: int, total: int) -> None:
        if not rows:
            self.status_label.setText(
                "Loaded data does not match the current datasheet specifications."
                if total else "No data."
            )
            return
        fails = [r for r in rows if r.status == "FAIL"]
        if fails:
            names = ", ".join(r.name for r in fails)
            self.status_label.setText(
                f"{len(fails)} failing parameter(s): {names}   ·   "
                f"{len(worst)} with out-of-spec outliers   ·   {valid}/{total} valid runs."
            )
        else:
            self.status_label.setText(
                f"All parameters pass.   ·   {valid}/{total} valid runs."
            )

    def show_error(self, message: str) -> None:
        """Display a simulation error in the status area."""
        self.tree.clear()
        self.eq_tree.clear()
        self.worst_tree.clear()
        self.status_label.setText(f"LOG:\n{message}")
