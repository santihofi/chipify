# Copyright (c) 2026 Santiago Hofwimmer
"""
equations_tab.py – Custom scalar / transient equation editor.

Edits the ``custom_equations`` (scalar, per-run) and ``transient_equations``
(waveform-level) lists in ``settings.json`` and applies them via the shared
:mod:`chipify.gui.services.equation_service`. Scalar equations are re-applied
to the loaded results through the window's ``reapply_equations`` callback so
derived columns flow into every tab; transient equations are picked up by the
Transient tab on its next redraw.
"""
from __future__ import annotations

import logging
from typing import Callable

from PySide6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from chipify import app_config

log = logging.getLogger("chipify.gui_qt.tabs.equations")

_CONFIG_KEY = {"Scalar": "custom_equations", "Transient": "transient_equations"}


class EquationsTab(QWidget):
    """Editable table of ``{name, expr}`` equations with an Apply action."""

    def __init__(
        self,
        reapply_equations: Callable[[], None],
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._reapply = reapply_equations
        self._build_ui()
        self._load_rows()

    # ── Layout ────────────────────────────────────────────────────────────────

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(8)

        top = QHBoxLayout()
        top.addWidget(QLabel("Custom Equations"))
        self.mode_combo = QComboBox()
        self.mode_combo.addItems(["Scalar", "Transient"])
        self.mode_combo.currentIndexChanged.connect(self._load_rows)
        top.addWidget(self.mode_combo)
        top.addStretch(1)
        self.btn_add = QPushButton("+ Add")
        self.btn_remove = QPushButton("– Remove")
        self.btn_apply = QPushButton("▶ Apply")
        self.btn_apply.setObjectName("Accent")
        top.addWidget(self.btn_add)
        top.addWidget(self.btn_remove)
        top.addWidget(self.btn_apply)
        layout.addLayout(top)

        self.table = QTableWidget(0, 2)
        self.table.setHorizontalHeaderLabels(["Name", "Expression"])
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        layout.addWidget(self.table, stretch=1)

        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setFixedHeight(120)
        layout.addWidget(self.log)

        self.btn_add.clicked.connect(lambda: self._append_row("", ""))
        self.btn_remove.clicked.connect(self._remove_selected)
        self.btn_apply.clicked.connect(self._apply)

    # ── Row helpers ───────────────────────────────────────────────────────────

    def _append_row(self, name: str, expr: str) -> None:
        r = self.table.rowCount()
        self.table.insertRow(r)
        self.table.setItem(r, 0, QTableWidgetItem(name))
        self.table.setItem(r, 1, QTableWidgetItem(expr))

    def _remove_selected(self) -> None:
        rows = sorted({i.row() for i in self.table.selectedIndexes()}, reverse=True)
        for r in rows:
            self.table.removeRow(r)

    def _load_rows(self) -> None:
        key = _CONFIG_KEY[self.mode_combo.currentText()]
        equations = app_config.load_config().get(key, []) or []
        self.table.setRowCount(0)
        for eq in equations:
            self._append_row(eq.get("name", ""), eq.get("expr", ""))

    def _collect(self) -> list[dict[str, str]]:
        out: list[dict[str, str]] = []
        for r in range(self.table.rowCount()):
            name = (self.table.item(r, 0).text() if self.table.item(r, 0) else "").strip()
            expr = (self.table.item(r, 1).text() if self.table.item(r, 1) else "").strip()
            if name and expr:
                out.append({"name": name, "expr": expr})
        return out

    # ── Apply ─────────────────────────────────────────────────────────────────

    def _apply(self) -> None:
        mode = self.mode_combo.currentText()
        equations = self._collect()
        cfg = app_config.load_config()
        cfg[_CONFIG_KEY[mode]] = equations
        app_config.save_config(cfg)

        if mode == "Transient":
            self.log.setPlainText(
                f"Saved {len(equations)} transient equation(s). "
                "They apply on the next Transient redraw."
            )
            return

        # Scalar: re-apply to the loaded results so derived columns propagate.
        self._reapply()
        derived = ", ".join(c for c in (self._last_derived or [])) or "—"
        self.log.setPlainText(
            f"Applied {len(equations)} scalar equation(s). Derived columns: {derived}"
        )

    #: Set by the window after a reapply so the log can report derived names.
    _last_derived: list[str] | None = None

    def report_derived(self, derived: list[str]) -> None:
        """Called back by the window with the names produced by the last apply."""
        self._last_derived = derived
