# Copyright (c) 2026 Santiago Hofwimmer
"""
measurements_tab.py – Results table + outliers/fails summary.

Shows one row per spec'd parameter (sim min/typ/max, spec limits, Cpk, sigma,
pass/fail) using the shared, framework-agnostic
:func:`chipify.gui.services.measurements.measurement_rows`. Subscribes to
``AppState`` so it refreshes on both completed loads (``data_changed``) and
live simulation chunks (``on_data_chunk_added``, coalesced via a Throttle).
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

_COLUMNS = ["Parameter", "Sim Min", "Sim Typ", "Sim Max",
            "Spec Min", "Spec Max", "Cpk", "Sigma", "Status"]

_PASS_COLOR = QColor("#2ecc71")
_FAIL_COLOR = QColor("#e74c3c")


class MeasurementsTab(QWidget):
    """Per-parameter results table with a fails summary underneath."""

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
        layout.setSpacing(8)

        self.tree = QTreeWidget()
        self.tree.setColumnCount(len(_COLUMNS))
        self.tree.setHeaderLabels(_COLUMNS)
        self.tree.setRootIsDecorated(False)
        self.tree.setAlternatingRowColors(True)
        self.tree.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.tree.setEditTriggers(QAbstractItemView.NoEditTriggers)
        header = self.tree.header()
        header.setSectionResizeMode(0, QHeaderView.Stretch)
        for i in range(1, len(_COLUMNS)):
            header.setSectionResizeMode(i, QHeaderView.ResizeToContents)
        layout.addWidget(self.tree, stretch=1)

        self._fails_header = QLabel("OUTLIERS & FAILS")
        self._fails_header.setObjectName("Heading")
        layout.addWidget(self._fails_header)

        self.fails_summary = QLabel("Run a simulation to see outliers…")
        self.fails_summary.setObjectName("Muted")
        self.fails_summary.setWordWrap(True)
        self.fails_summary.setTextInteractionFlags(Qt.TextSelectableByMouse)
        layout.addWidget(self.fails_summary)

    # ── AppState slots ────────────────────────────────────────────────────────

    def _on_data_changed(self, df=None, stim=None, switch_tab=False, **_kw) -> None:
        self._throttle.force_now()

    def _on_chunk_added(self, df=None, stim=None, chunk_len=0, **_kw) -> None:
        self._throttle.request()

    # ── Rendering ─────────────────────────────────────────────────────────────

    def _refresh_from_state(self) -> None:
        self.refresh(self._state.active_df, self._state.current_stim)

    def refresh(self, df, stim) -> None:
        """Rebuild the table and fails summary from *df* / *stim*."""
        self.tree.clear()
        if df is None or stim is None:
            self.fails_summary.setText("Run a simulation to see outliers…")
            return

        valid_df = _dl.valid_rows(df)
        rows = _meas.measurement_rows(valid_df, stim)

        fails: list[str] = []
        for r in rows:
            item = QTreeWidgetItem([
                r.name,
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
            item.setForeground(len(_COLUMNS) - 1, brush)
            for col in range(1, len(_COLUMNS)):
                item.setTextAlignment(col, Qt.AlignCenter)
            self.tree.addTopLevelItem(item)
            if r.status == "FAIL":
                fails.append(f"{r.name} ({r.fail_n} fail{'s' if r.fail_n != 1 else ''})")

        if not rows:
            total = len(df)
            self.fails_summary.setText(
                "No matching parameters in this run."
                if total else "No data."
            )
            return

        total = len(df)
        valid = len(valid_df)
        if fails:
            self.fails_summary.setText(
                f"{len(fails)} failing parameter(s): " + ", ".join(fails)
                + f"   ·   {valid}/{total} valid runs."
            )
        else:
            self.fails_summary.setText(
                f"All parameters pass.   ·   {valid}/{total} valid runs."
            )

    def show_error(self, message: str) -> None:
        """Display a simulation error in the fails area."""
        self.tree.clear()
        self.fails_summary.setText(f"LOG:\n{message}")
