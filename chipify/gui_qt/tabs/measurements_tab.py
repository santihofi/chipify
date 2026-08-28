# Copyright (c) 2026 Santiago Hofwimmer
"""
measurements_tab.py – Results overview in three stacked sections.

1. **Parameter results** – one row per spec'd parameter (sim min/typ/max, spec
   limits, Cpk, sigma, pass/fail).
2. **Equation results** – one row per applied scalar (custom) equation
   (expression + min/typ/max of the derived column).
3. **Worst cases** – for each failing parameter, the single worst run, the spec
   it violated, and the sweep conditions that triggered it.
4. **Simulation errors** – each distinct failure the simulator reported, the
   testbench it came from, how many runs it hit and the corner it first hit.

Errors are scoped per testbench, so a testbench that crashed no longer blanks
out the results of the ones that succeeded: its parameters read ``ERROR`` while
the healthy testbenches keep their real statistics and verdicts.

All three are computed by the shared, framework-agnostic
:mod:`chipify.uikit.services.measurements` helpers. The tab subscribes to
``AppState`` so it refreshes on completed loads (``data_changed``) and live
chunks (``on_data_chunk_added``, coalesced via a Throttle).
"""
from __future__ import annotations

import logging

from pathlib import Path

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QBrush, QColor, QDesktopServices
from PySide6.QtWidgets import (
    QAbstractItemView,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from chipify import app_config
from chipify import data_loader as _dl
from chipify.gui_qt import theme
from chipify.uikit.services import measurements as _meas
from chipify.uikit.state import AppState
from chipify.gui_qt.services.throttle import Throttle

log = logging.getLogger("chipify.gui_qt.tabs.measurements")

_PARAM_COLUMNS = ["Parameter", "Unit", "Sim Min", "Sim Typ", "Sim Max",
                  "Spec Min", "Spec Max", "Cpk", "Sigma", "Errors", "Status"]
_EQ_COLUMNS = ["Equation", "Expression", "Min", "Typ", "Max"]
_WORST_COLUMNS = ["Parameter", "Worst", "Spec", "Fails", "Conditions"]
_ERROR_COLUMNS = ["Testbench", "Error", "Runs", "Conditions", "Message"]

_STATUS_COL = len(_PARAM_COLUMNS) - 1
_ERRORS_COL = len(_PARAM_COLUMNS) - 2

_PASS_COLOR = QColor(theme.STATUS_PASS)
_FAIL_COLOR = QColor(theme.STATUS_FAIL)
_ERROR_COLOR = QColor(theme.STATUS_ERROR)
_MUTED_COLOR = QColor(theme.MUTED)

_STATUS_COLORS = {
    _meas.STATUS_PASS: _PASS_COLOR,
    _meas.STATUS_FAIL: _FAIL_COLOR,
    _meas.STATUS_ERROR: _ERROR_COLOR,
}


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

        layout.addWidget(self._heading("SIMULATION ERRORS"))
        self.error_tree = self._make_tree(_ERROR_COLUMNS, stretch_col=4)
        layout.addWidget(self.error_tree, stretch=2)

        status_row = QHBoxLayout()
        self.status_label = QLabel("Run a simulation to see results…")
        self.status_label.setObjectName("Muted")
        self.status_label.setWordWrap(True)
        self.status_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        status_row.addWidget(self.status_label, stretch=1)

        self.open_log_btn = QPushButton("Open Log")
        self.open_log_btn.setToolTip(f"Open {app_config.LOG_PATH}")
        self.open_log_btn.clicked.connect(self._open_log)
        status_row.addWidget(self.open_log_btn, alignment=Qt.AlignTop)
        layout.addLayout(status_row)

        # Engine log tails run to dozens of lines. A word-wrapped QLabel grew
        # without bound and squeezed the tables; this scrolls instead. Hidden
        # until there is something to show.
        self.log_view = QPlainTextEdit()
        self.log_view.setReadOnly(True)
        self.log_view.setMaximumHeight(120)
        self.log_view.setLineWrapMode(QPlainTextEdit.NoWrap)
        self.log_view.setPlaceholderText("Simulator output appears here on failure.")
        font = self.log_view.font()
        font.setFamily("monospace")
        self.log_view.setFont(font)
        self.log_view.hide()
        layout.addWidget(self.log_view)

    def _open_log(self) -> None:
        """Open chipify.log in the desktop's default viewer."""
        path = Path(app_config.LOG_PATH)
        if not path.exists():
            self.status_label.setText(f"No log file yet at {path}")
            return
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))

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

        # measurement_rows / worst_cases / error_rows scope validity per
        # testbench, so they take the full frame: pre-filtering with valid_rows
        # would drop every row of a run where one testbench crashed, which is
        # precisely the data the other testbenches still have to show.
        rows = _meas.measurement_rows(df, stim)
        self._fill_parameter_rows(rows)

        from chipify.uikit.services import equation_service as _eq_svc
        equations = _eq_svc.scalar_equations(stim)
        eq_rows = _meas.equation_rows(valid_df, equations)
        self._fill_equation_rows(eq_rows)

        worst = _meas.worst_cases(df, stim, total)
        self._fill_worst_rows(worst)

        errors = _meas.error_rows(df, stim)
        self._fill_error_rows(errors)

        self._update_status(rows, worst, errors, valid, total)

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
                f"{r.error_n}/{r.total_n}" if r.error_n else "-",
                r.status,
            ])
            brush = QBrush(_STATUS_COLORS.get(r.status, _FAIL_COLOR))
            item.setForeground(_STATUS_COL, brush)
            if r.error_n:
                item.setForeground(_ERRORS_COL, QBrush(_ERROR_COLOR))
                # The reason is why the row is ERROR — keep it one hover away.
                item.setToolTip(_STATUS_COL, r.error_msg)
                item.setToolTip(_ERRORS_COL, r.error_msg)
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

    def _fill_error_rows(self, errors) -> None:
        if not errors:
            self._placeholder(self.error_tree, "No simulation errors.")
            return
        for e in errors:
            item = QTreeWidgetItem([
                e.tb_path,
                e.kind,
                f"{e.run_n} / {e.total_n}",
                _fmt_conditions(e.conditions),
                e.message,
            ])
            for col in (1, 2):
                item.setTextAlignment(col, Qt.AlignCenter)
            item.setForeground(1, QBrush(_ERROR_COLOR))
            item.setToolTip(4, e.message)
            if e.measurements:
                item.setToolTip(0, "Measurements: " + ", ".join(e.measurements))
            self.error_tree.addTopLevelItem(item)

    @staticmethod
    def _placeholder(tree: QTreeWidget, text: str) -> None:
        item = QTreeWidgetItem([text] + [""] * (tree.columnCount() - 1))
        item.setForeground(0, QBrush(_MUTED_COLOR))
        tree.addTopLevelItem(item)

    def _update_status(self, rows, worst, errors, valid: int, total: int) -> None:
        if not rows:
            self.status_label.setText(
                "Loaded data does not match the current datasheet specifications."
                if total else "No data."
            )
            return

        fails = [r for r in rows if r.status == _meas.STATUS_FAIL]
        errored = [r for r in rows if r.status == _meas.STATUS_ERROR]

        parts: list[str] = []
        if errored:
            parts.append(
                f"{len(errored)} errored parameter(s): "
                + ", ".join(r.name for r in errored)
            )
        if fails:
            parts.append(
                f"{len(fails)} failing parameter(s): "
                + ", ".join(r.name for r in fails)
            )
        if not parts:
            parts.append("All parameters pass.")
        elif worst:
            parts.append(f"{len(worst)} with out-of-spec outliers")
        parts.append(f"{valid}/{total} valid runs")
        self.status_label.setText("   ·   ".join(parts))

        # Surface the distinct failures inline so debugging a broken testbench
        # doesn't start with hunting down the log file.
        if errors:
            self.log_view.setPlainText("\n".join(
                f"[{e.kind}] {e.tb_path} ({e.run_n}/{e.total_n} runs): {e.message}"
                for e in errors
            ))
            self.log_view.show()
        else:
            self.log_view.clear()
            self.log_view.hide()

    def show_error(self, message: str) -> None:
        """Display a simulation failure without discarding existing results.

        Deliberately non-destructive: this used to clear all three tables, so a
        failure late in a run wiped results that had already been computed and
        left the user with nothing to debug from.
        """
        self.status_label.setText("Simulation failed - see below.")
        self.log_view.setPlainText(message)
        self.log_view.show()
