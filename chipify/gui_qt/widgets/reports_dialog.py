# Copyright (c) 2026 Santiago Hofwimmer
"""
reports_dialog.py – Edit a datasheet's ``reports:`` block.

Chipify's paradigm is that a datasheet is fully buildable from the GUI; this is
the form for the block that declares which figures and reports a run produces.
Opened from the Datasheet Editor, and persisted through
``editor_tab.set_document_key("reports", …)`` — the same call the equations
panel uses, so there is exactly one writer for top-level datasheet keys.

The per-plot form is **generated from** :data:`chipify.reports.PLOT_TYPES`
rather than hand-written per type: the registry already declares each type's
required and optional keys, so a new plot type gets a GUI for free and this
dialog never becomes a second place that knows the plot vocabulary.
"""
from __future__ import annotations

import logging
from typing import Any

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from chipify import data_loader as _dl
from chipify.reports import PLOT_TYPES, PlotSpec, ReportsConfig
from chipify.uikit.services import transient_loader as _tl
from chipify.uikit.services import yaml_editor_service as _ye

log = logging.getLogger("chipify.gui_qt.reports_dialog")

_FIT_CURVES = ["Gauss (Normal)", "KDE (Smoothed)", "Uniform",
               "Log-Normal", "Exponential", "Chi-Squared", "None"]
_BINS = ["Auto", "10", "20", "50", "100", "200"]

#: How each option key is edited. Keyed by option name rather than by plot
#: type, so the nine keys across all types need nine entries, not one per
#: (type, key) pair.
_FIELD_KIND: dict[str, str] = {
    "x": "column", "y": "column",
    "param": "measurement", "target": "measurement",
    "group": "sweep",
    "signals": "signals",
    "runs": "runs",
    "fit": "fit",
    "bins": "bins",
    "zoom": "bool",
}


class _Choices:
    """Names offered by the dialog's dropdowns.

    Prefers the loaded results (so the lists match what a plot can actually
    reference) and falls back to the datasheet itself, because a `reports:`
    block must be buildable before the first simulation has ever run.
    """

    def __init__(self, df, stim) -> None:
        self.stim = stim
        self.measurements: list[str] = []
        for test in getattr(stim, "tests", None) or []:
            for val in getattr(test, "value_lst", None) or []:
                if val.name not in self.measurements:
                    self.measurements.append(val.name)
            for name in (getattr(test, "measure", None) or {}):
                if name not in self.measurements:
                    self.measurements.append(name)

        self.sweeps = [str(p) for p in (getattr(stim, "params", None) or {})]
        if df is not None:
            cols = _dl.compute_plot_cols(df, stim)
            self.sweeps = cols.sweep_params or self.sweeps
            for c in cols.output_cols:
                if c not in self.measurements:
                    self.measurements.append(c)
        self.columns = list(dict.fromkeys(self.sweeps + self.measurements))

    def signals(self, plot_type: str) -> list[str]:
        kind = PLOT_TYPES[plot_type].kind
        return _tl.list_kind_signals(self.stim, kind) if kind else []


def _format_names() -> list[str]:
    from chipify.plugin_loader import get_exporter_plugins
    from chipify.reports import LATEX_FORMAT
    exts = [e.extension.lstrip(".").lower() for e in get_exporter_plugins()]
    return sorted(dict.fromkeys(exts)) + [LATEX_FORMAT]


class ReportsDialog(QDialog):
    """Form for the datasheet's ``reports:`` block."""

    def __init__(self, editor_tab, app_state, parent: QWidget | None = None) -> None:
        super().__init__(parent or editor_tab)
        self._editor = editor_tab
        self._state = app_state
        self._choices = _Choices(app_state.current_df, self._stim_for_choices())
        self._config: ReportsConfig = self._load_config()
        self._fields: dict[str, QWidget] = {}

        self.setWindowTitle("Reports — plots and documents to generate")
        self.setMinimumWidth(720)
        self._build_ui()
        self._refresh_plot_list()

    def _stim_for_choices(self):
        """Where the dropdown names come from.

        The loaded run when there is one, else the datasheet open in the editor
        — a `reports:` block has to be buildable before the first simulation has
        ever run, which is the whole point of configuring it in the GUI. Parsed
        through the schema validator so the names match what a run would see.
        """
        stim = self._state.current_stim
        if stim is not None:
            return stim
        try:
            from chipify.schema import validate_datasheet
            return validate_datasheet(self._editor.current_yaml_data or {})
        except Exception as exc:  # noqa: BLE001 — an invalid draft still opens
            log.debug("Could not derive names from the datasheet: %s", exc)
            return None

    # ── Load / save ───────────────────────────────────────────────────────────

    def _load_config(self) -> ReportsConfig:
        try:
            return _ye.reports_to_config(self._editor.current_yaml_data or {})
        except Exception as exc:  # noqa: BLE001 — a bad block must still open
            log.warning("Could not parse the reports block: %s", exc)
            from PySide6.QtWidgets import QMessageBox
            QMessageBox.warning(
                self, "Reports",
                f"The datasheet's 'reports:' block could not be read and will "
                f"be replaced if you save:\n\n{exc}")
            return ReportsConfig()

    # ── Layout ────────────────────────────────────────────────────────────────

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)

        body = QHBoxLayout()
        left = QVBoxLayout()
        left.addWidget(QLabel("Plots"))
        self.plot_list = QListWidget()
        self.plot_list.setSelectionMode(QAbstractItemView.SingleSelection)
        self.plot_list.setFixedWidth(240)
        self.plot_list.currentRowChanged.connect(self._on_select)
        left.addWidget(self.plot_list, stretch=1)

        btn_row = QHBoxLayout()
        self.btn_add = QPushButton("+ Add")
        self.btn_add.clicked.connect(self._add_plot)
        self.btn_del = QPushButton("✕ Remove")
        self.btn_del.clicked.connect(self._remove_plot)
        btn_row.addWidget(self.btn_add)
        btn_row.addWidget(self.btn_del)
        left.addLayout(btn_row)
        body.addLayout(left)

        self.detail = QGroupBox("Plot settings")
        self.detail_form = QFormLayout(self.detail)
        body.addWidget(self.detail, stretch=1)
        root.addLayout(body, stretch=1)

        # Defaults applied to every plot that does not override them.
        defaults = QGroupBox("Default formats")
        drow = QHBoxLayout(defaults)
        self.format_checks: dict[str, QCheckBox] = {}
        for fmt in _format_names():
            box = QCheckBox(fmt)
            box.setChecked(fmt in self._config.formats)
            drow.addWidget(box)
            self.format_checks[fmt] = box
        drow.addStretch(1)
        root.addWidget(defaults)

        docs = QGroupBox("Documents")
        drow2 = QHBoxLayout(docs)
        self.chk_pdf = QCheckBox("PDF report")
        self.chk_pdf.setChecked(self._config.pdf)
        self.chk_md = QCheckBox("Markdown report")
        self.chk_md.setChecked(self._config.markdown)
        drow2.addWidget(self.chk_pdf)
        drow2.addWidget(self.chk_md)
        drow2.addStretch(1)
        root.addWidget(docs)

        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        self.btn_generate = QPushButton("Generate now")
        self.btn_generate.setToolTip(
            "Save, then render these reports for the currently loaded results.")
        self.btn_generate.clicked.connect(self._generate_now)
        buttons.addButton(self.btn_generate, QDialogButtonBox.ActionRole)
        buttons.accepted.connect(self._save)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

    # ── Plot list ─────────────────────────────────────────────────────────────

    def _refresh_plot_list(self, select: int = 0) -> None:
        self.plot_list.blockSignals(True)
        self.plot_list.clear()
        for spec in self._config.plots:
            self.plot_list.addItem(self._label(spec))
        self.plot_list.blockSignals(False)
        if self._config.plots:
            self.plot_list.setCurrentRow(min(select, len(self._config.plots) - 1))
        else:
            self._build_detail(None)

    @staticmethod
    def _label(spec: PlotSpec) -> str:
        from chipify.report_service import default_plot_name
        return f"{spec.type}  ·  {default_plot_name(spec)}"

    def _current(self) -> PlotSpec | None:
        row = self.plot_list.currentRow()
        if 0 <= row < len(self._config.plots):
            return self._config.plots[row]
        return None

    def _add_plot(self) -> None:
        self._config.plots.append(PlotSpec("scatter", options={}))
        self._refresh_plot_list(select=len(self._config.plots) - 1)

    def _remove_plot(self) -> None:
        row = self.plot_list.currentRow()
        if 0 <= row < len(self._config.plots):
            del self._config.plots[row]
            self._refresh_plot_list(select=max(0, row - 1))

    def _on_select(self, _row: int) -> None:
        self._build_detail(self._current())

    # ── Per-plot form, generated from PLOT_TYPES ──────────────────────────────

    def _build_detail(self, spec: PlotSpec | None) -> None:
        while self.detail_form.count():
            item = self.detail_form.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        self._fields.clear()
        if spec is None:
            self.detail_form.addRow(QLabel("Add a plot to configure it."))
            return

        type_combo = QComboBox()
        type_combo.addItems(sorted(PLOT_TYPES))
        type_combo.setCurrentText(spec.type)
        type_combo.currentTextChanged.connect(self._on_type_changed)
        self.detail_form.addRow("Type", type_combo)
        self._fields["type"] = type_combo

        name_edit = QLineEdit(spec.name)
        name_edit.setPlaceholderText("(derived from the settings below)")
        name_edit.textChanged.connect(lambda t: self._set_name(t))
        self.detail_form.addRow("File name", name_edit)
        self._fields["name"] = name_edit

        ptype = PLOT_TYPES[spec.type]
        for key in list(ptype.required) + list(ptype.optional):
            widget = self._make_field(spec, key)
            label = key.replace("_", " ").capitalize()
            if key in ptype.required:
                label += " *"
            self.detail_form.addRow(label, widget)
            self._fields[key] = widget
            # A combo shows its first item immediately, so an untouched field
            # would display a value the spec never recorded — and saving would
            # write a plot missing a key the user can plainly see filled in.
            self._commit_displayed(spec, key, widget)

        fmt_row = QWidget()
        fmt_layout = QHBoxLayout(fmt_row)
        fmt_layout.setContentsMargins(0, 0, 0, 0)
        self._fmt_overrides: dict[str, QCheckBox] = {}
        for fmt in _format_names():
            box = QCheckBox(fmt)
            box.setChecked(fmt in spec.formats)
            box.toggled.connect(lambda _c, f=fmt: self._toggle_format(f))
            fmt_layout.addWidget(box)
            self._fmt_overrides[fmt] = box
        fmt_layout.addStretch(1)
        self.detail_form.addRow("Formats", fmt_row)
        self.detail_form.addRow(QLabel(
            "<i>Leave every format unticked to use the defaults below.</i>"))

    @staticmethod
    def _displayed_value(widget: QWidget) -> Any:
        """What the widget currently shows, in the spec's own vocabulary."""
        if isinstance(widget, QCheckBox):
            return widget.isChecked()
        if isinstance(widget, QComboBox):
            return widget.currentText()
        if isinstance(widget, QLineEdit):
            return [s.strip() for s in widget.text().split(",") if s.strip()]
        return None

    def _commit_displayed(self, spec: PlotSpec, key: str, widget: QWidget) -> None:
        """Record the widget's shown value when the spec has none yet."""
        if key in spec.options:
            return
        value = self._displayed_value(widget)
        if value in (None, "", [], False):
            return
        spec.options[key] = value

    def _make_field(self, spec: PlotSpec, key: str) -> QWidget:
        kind = _FIELD_KIND.get(key, "text")
        value = spec.options.get(key)

        if kind == "bool":
            box = QCheckBox()
            box.setChecked(bool(value))
            box.toggled.connect(lambda v, k=key: self._set_option(k, bool(v)))
            return box

        if kind == "signals":
            edit = QLineEdit(", ".join(value or []))
            available = self._choices.signals(spec.type)
            edit.setPlaceholderText(
                ", ".join(available) if available
                else "all signals declared for this analysis")
            edit.textChanged.connect(lambda t, k=key: self._set_option(
                k, [s.strip() for s in t.split(",") if s.strip()] or None))
            return edit

        combo = QComboBox()
        combo.setEditable(kind in ("column", "measurement", "sweep"))
        items = {
            "column": self._choices.columns,
            "measurement": self._choices.measurements,
            "sweep": ["", *self._choices.sweeps],
            "runs": list(_tl.RUN_MODES),
            "fit": _FIT_CURVES,
            "bins": _BINS,
        }.get(kind, [])
        combo.addItems([str(i) for i in items])
        if value is not None:
            combo.setCurrentText(str(value))
        elif kind == "sweep":
            combo.setCurrentText("")
        combo.currentTextChanged.connect(
            lambda t, k=key: self._set_option(k, t or None))
        return combo

    # ── Edits ─────────────────────────────────────────────────────────────────

    def _set_option(self, key: str, value: Any) -> None:
        spec = self._current()
        if spec is None:
            return
        if value in (None, ""):
            spec.options.pop(key, None)
        else:
            spec.options[key] = value
        self._sync_label()

    def _set_name(self, text: str) -> None:
        spec = self._current()
        if spec is not None:
            spec.name = text.strip()
            self._sync_label()

    def _toggle_format(self, fmt: str) -> None:
        spec = self._current()
        if spec is None:
            return
        checked = self._fmt_overrides[fmt].isChecked()
        if checked and fmt not in spec.formats:
            spec.formats.append(fmt)
        elif not checked and fmt in spec.formats:
            spec.formats.remove(fmt)

    def _on_type_changed(self, new_type: str) -> None:
        spec = self._current()
        if spec is None or new_type == spec.type:
            return
        # Options are type-specific; keep only the ones the new type accepts.
        allowed = set(PLOT_TYPES[new_type].required) | set(PLOT_TYPES[new_type].optional)
        spec.type = new_type
        spec.options = {k: v for k, v in spec.options.items() if k in allowed}
        self._build_detail(spec)
        self._sync_label()

    def _sync_label(self) -> None:
        row = self.plot_list.currentRow()
        spec = self._current()
        if spec is not None and 0 <= row < self.plot_list.count():
            self.plot_list.item(row).setText(self._label(spec))

    # ── Persist ───────────────────────────────────────────────────────────────

    def _collect(self) -> ReportsConfig:
        self._config.formats = [f for f, b in self.format_checks.items() if b.isChecked()]
        self._config.pdf = self.chk_pdf.isChecked()
        self._config.markdown = self.chk_md.isChecked()
        return self._config

    def _write(self) -> bool:
        """Persist through the editor so file, form and raw view stay in step."""
        block = _ye.config_to_reports(self._collect())
        return bool(self._editor.set_document_key("reports", block))

    def _save(self) -> None:
        if self._write():
            self.accept()

    def _generate_now(self) -> None:
        if not self._write():
            return
        window = self._editor.window()
        if hasattr(window, "generate_reports"):
            self.accept()
            window.generate_reports()
