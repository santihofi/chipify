# Copyright (c) 2026 Santiago Hofwimmer
"""
equations_tab.py – Custom scalar / transient equation editor.

Equations are stored **in the active datasheet** (top-level ``equations:``
and ``transient_equations:`` YAML mappings) so they travel with the design.
The panel edits the datasheet editor's in-memory YAML document and persists
through the editor's save path, keeping form, raw view, and file consistent.

Equations still found in ``settings.json`` (the pre-datasheet storage) are
shown as a fallback when the datasheet has none; the first Apply migrates
them into the datasheet and removes them from settings.json.

Applied via the shared :mod:`chipify.uikit.services.equation_service`:
scalar equations re-run through the window's ``reapply_equations`` so derived
columns flow into every tab; transient equations are picked up by waveform
plots on the same ``data_changed`` refresh.
"""
from __future__ import annotations

import logging

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

#: Mode label → (datasheet YAML key, legacy settings.json key)
_MODE_KEYS = {
    "Scalar": ("equations", "custom_equations"),
    "Transient": ("transient_equations", "transient_equations"),
}


def _as_pairs(raw) -> list[tuple[str, str]]:
    """Normalise a YAML equations block (mapping or legacy list) to pairs."""
    if isinstance(raw, dict):
        return [(str(k), str(v)) for k, v in raw.items()]
    if isinstance(raw, list):
        return [(str(e.get("name", "")), str(e.get("expr", "")))
                for e in raw if isinstance(e, dict)]
    return []


class EquationsTab(QWidget):
    """Editable table of ``{name, expr}`` equations with an Apply action."""

    def __init__(self, editor, parent: QWidget | None = None) -> None:
        """*editor* is the hosting DatasheetEditorTab (owns the YAML document)."""
        super().__init__(parent)
        self._editor = editor
        self._build_ui()
        self.reload()

    # ── Layout ────────────────────────────────────────────────────────────────

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(8)

        # Two-row header keeps the panel narrow enough to sit in a column.
        hdr = QHBoxLayout()
        title = QLabel("CUSTOM EQUATIONS")
        title.setObjectName("Heading")  # match SWEEP PARAMETERS / TESTBENCHES
        hdr.addWidget(title)
        self.mode_combo = QComboBox()
        self.mode_combo.addItems(list(_MODE_KEYS))
        self.mode_combo.currentIndexChanged.connect(self.reload)
        hdr.addWidget(self.mode_combo)
        hdr.addStretch(1)
        layout.addLayout(hdr)

        btns = QHBoxLayout()
        self.btn_add = QPushButton("+ Add")
        self.btn_remove = QPushButton("– Remove")
        self.btn_apply = QPushButton("▶ Apply")
        self.btn_apply.setObjectName("Accent")
        btns.addWidget(self.btn_add)
        btns.addWidget(self.btn_remove)
        btns.addWidget(self.btn_apply)
        btns.addStretch(1)
        layout.addLayout(btns)

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

    def reload(self, *_a) -> None:
        """Repopulate from the editor's YAML document (legacy settings fallback)."""
        yaml_key, legacy_key = _MODE_KEYS[self.mode_combo.currentText()]
        data = getattr(self._editor, "current_yaml_data", None) or {}
        if yaml_key in data:
            pairs = _as_pairs(data.get(yaml_key))
        else:
            # Pre-migration state: show what settings.json still carries so
            # the next Apply moves it into the datasheet.
            legacy = app_config.load_config().get(legacy_key, []) or []
            pairs = [(e.get("name", ""), e.get("expr", ""))
                     for e in legacy if isinstance(e, dict)]
        self.table.setRowCount(0)
        for name, expr in pairs:
            self._append_row(name, expr)

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
        yaml_key, legacy_key = _MODE_KEYS[mode]
        editor = self._editor
        if not getattr(editor, "current_yaml_path", None):
            self.log.setPlainText("No datasheet selected — equations are stored "
                                  "in the datasheet YAML.")
            return

        equations = self._collect()
        bad = [eq["name"] for eq in equations if not eq["name"].isidentifier()]
        if bad:
            self.log.setPlainText(
                "Not saved — equation names must be valid identifiers "
                f"(they become result columns): {', '.join(bad)}"
            )
            return

        # Persist through the editor so file, form, and raw view stay
        # consistent (and concurrent edits in either view are kept).
        value = {eq["name"]: eq["expr"] for eq in equations} if equations else None
        if not editor.set_document_key(yaml_key, value):
            self.log.setPlainText("Could not save the datasheet — see error dialog.")
            return

        # Hard migration: the datasheet is the storage now.
        cfg = app_config.load_config()
        if cfg.get(legacy_key):
            cfg.pop(legacy_key, None)
            app_config.save_config(cfg)
            log.info("Migrated %s from settings.json into the datasheet.", legacy_key)

        # Refresh: re-parses the stim (datasheet), reapplies scalar equations,
        # and emits data_changed so waveform tabs pick up transient equations.
        editor.window_reapply_equations()

        if mode == "Transient":
            self.log.setPlainText(
                f"Saved {len(equations)} transient equation(s) to the datasheet. "
                "Waveform plots list them as signals."
            )
            return

        derived = ", ".join(c for c in (self._last_derived or [])) or "—"
        self.log.setPlainText(
            f"Saved {len(equations)} scalar equation(s) to the datasheet. "
            f"Derived columns: {derived}"
        )

    #: Set by the window after a reapply so the log can report derived names.
    _last_derived: list[str] | None = None

    def report_derived(self, derived: list[str]) -> None:
        """Called back by the window with the names produced by the last apply."""
        self._last_derived = derived
