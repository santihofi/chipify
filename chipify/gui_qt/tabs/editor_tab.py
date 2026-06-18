# Copyright (c) 2026 Santiago Hofwimmer
"""
editor_tab.py – Datasheet (YAML) editor: form view + raw view.

Qt port of the legacy CustomTkinter "Datasheet Editor" tab. The form↔dict
translation, the new-file template, and value formatting are reused unchanged
from the framework-agnostic :mod:`chipify.uikit.services.yaml_editor_service`;
the form's ``QLineEdit``\\ s are wrapped in a tiny ``.get()`` adapter so
``sync_form_to_yaml`` (written for Tk ``StringVar``\\ s) works as-is. The custom
``ChipifyDumper`` (inline lists, quoted strings) is reused from
:mod:`chipify.uikit.widgets.yaml_dumper`.

Save preserves the file's comments/formatting when the form did not change the
data (it re-saves the original text); otherwise it dumps the edited dict.
"""
from __future__ import annotations

import logging

import yaml
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QComboBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QStackedWidget,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from chipify import settings
from chipify.uikit.services import yaml_editor_service as _ye
from chipify.uikit.widgets.yaml_dumper import ChipifyDumper, QuotedString, register
from chipify.gui_qt.widgets.helpers import autoclose_combo, deferred

log = logging.getLogger("chipify.gui_qt.tabs.editor")

_SKIP_KEYS = ("values", "measure", "transient_signals", "dc_signals", "ac_signals")
_ANALYSIS_ROWS = (
    ("transient_signals", "Transient", "e.g.  v(out), v(in), i(vdd)"),
    ("dc_signals", "DC Sweep", "e.g.  i(vdd), v(out)"),
    ("ac_signals", "AC / Bode", "e.g.  v(out), v(in)"),
)


class _Var:
    """Adapter giving a QLineEdit a Tk-``StringVar``-style ``.get()``.

    Lets ``yaml_editor_service.sync_form_to_yaml`` consume Qt widgets unchanged.
    """

    def __init__(self, widget: QLineEdit) -> None:
        self._w = widget

    def get(self) -> str:
        return self._w.text()


def _clear_layout(layout) -> None:
    while layout.count():
        item = layout.takeAt(0)
        w = item.widget()
        if w is not None:
            w.setParent(None)
            w.deleteLater()
        elif item.layout() is not None:
            _clear_layout(item.layout())


class DatasheetEditorTab(QWidget):
    """Edit the selected datasheet's YAML via a form or a raw text editor."""

    def __init__(self, window, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._window = window
        register()  # idempotent: ChipifyDumper representers

        self.current_yaml_path: str | None = None
        self.current_yaml_data: dict = {}
        self.raw_text: str = ""
        self.param_key: str = "params"
        self.test_key: str = "tests"
        self.param_vars: list[dict] = []
        self.test_vars: list[dict] = []

        self._build_ui()

    # ── Layout ────────────────────────────────────────────────────────────────

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(10, 10, 10, 10)
        root.setSpacing(8)

        top = QHBoxLayout()
        top.addWidget(QLabel("Datasheet"))
        self.title_label = QLabel("—")
        self.title_label.setObjectName("Muted")
        top.addWidget(self.title_label)
        top.addSpacing(20)
        self.mode_combo = QComboBox()
        self.mode_combo.addItems(["Form View", "Raw YAML"])
        autoclose_combo(self.mode_combo)
        self.mode_combo.currentIndexChanged.connect(deferred(self._on_mode_change))
        top.addWidget(self.mode_combo)
        top.addStretch(1)
        self.btn_new = QPushButton("New…")
        self.btn_new.clicked.connect(self._action_new)
        top.addWidget(self.btn_new)
        self.btn_save = QPushButton("Save Datasheet")
        self.btn_save.setObjectName("Accent")
        self.btn_save.clicked.connect(self._save)
        top.addWidget(self.btn_save)
        root.addLayout(top)

        # Body: datasheet (form/raw stack) on the left, equations on the right.
        # In Form view this reads as three columns: parameters · testbenches ·
        # equations. (Equations live in settings.json, not the datasheet, so the
        # panel stays visible in Raw view too.)
        body = QHBoxLayout()
        body.setSpacing(10)
        self.stack = QStackedWidget()
        self.stack.addWidget(self._build_form_page())   # index 0 = Form
        self.stack.addWidget(self._build_raw_page())     # index 1 = Raw
        body.addWidget(self.stack, stretch=2)

        from chipify.gui_qt.tabs.equations_tab import EquationsTab
        self.equations_panel = EquationsTab(self._window.reapply_equations)
        body.addWidget(self.equations_panel, stretch=1)
        root.addLayout(body, stretch=1)

    def _build_form_page(self) -> QWidget:
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        host = QWidget()
        cols = QHBoxLayout(host)
        cols.setSpacing(10)

        # Left: parameters
        left = QVBoxLayout()
        phdr = QHBoxLayout()
        lbl_p = QLabel("SWEEP PARAMETERS")
        lbl_p.setObjectName("Heading")
        phdr.addWidget(lbl_p)
        phdr.addStretch(1)
        btn_add_p = QPushButton("+ Add")
        btn_add_p.clicked.connect(self._action_add_param)
        phdr.addWidget(btn_add_p)
        left.addLayout(phdr)
        self._param_box = QVBoxLayout()
        self._param_box.addStretch(1)
        left.addLayout(self._param_box, stretch=1)
        cols.addLayout(left, stretch=1)

        # Right: testbenches
        right = QVBoxLayout()
        thdr = QHBoxLayout()
        lbl_t = QLabel("TESTBENCHES")
        lbl_t.setObjectName("Heading")
        thdr.addWidget(lbl_t)
        thdr.addStretch(1)
        btn_add_t = QPushButton("+ Add Testbench")
        btn_add_t.clicked.connect(self._action_add_test)
        thdr.addWidget(btn_add_t)
        right.addLayout(thdr)
        self._tests_box = QVBoxLayout()
        self._tests_box.addStretch(1)
        right.addLayout(self._tests_box, stretch=1)
        cols.addLayout(right, stretch=1)

        scroll.setWidget(host)
        return scroll

    def _build_raw_page(self) -> QWidget:
        self.raw_editor = QPlainTextEdit()
        font = QFont("monospace")
        font.setStyleHint(QFont.Monospace)
        font.setPointSize(11)
        self.raw_editor.setFont(font)
        return self.raw_editor

    # ── Loading ───────────────────────────────────────────────────────────────

    def load_datasheet(self) -> None:
        """Load the window's currently selected datasheet into both views."""
        path = self._window.current_yaml_path
        if not path:
            self.current_yaml_path = None
            self.current_yaml_data = {}
            self.raw_text = ""
            self.title_label.setText("—")
            self.raw_editor.setPlainText("")
            self._build_form()
            return
        try:
            with open(path, "r", encoding="utf-8") as fh:
                raw = fh.read()
            self.current_yaml_data = yaml.safe_load(raw) or {}
        except Exception as exc:  # noqa: BLE001
            QMessageBox.critical(self, "Load Error", f"Error loading datasheet:\n{exc}")
            return
        self.current_yaml_path = path
        self.raw_text = raw
        self.param_key, _ = _ye.get_params_dict(self.current_yaml_data)
        self.test_key, _ = _ye.get_tests_dict(self.current_yaml_data)
        import os
        self.title_label.setText(os.path.basename(path))
        self.raw_editor.setPlainText(raw)
        self._build_form()

    # ── Form build ────────────────────────────────────────────────────────────

    def _build_form(self) -> None:
        _clear_layout(self._param_box)
        _clear_layout(self._tests_box)
        self.param_vars = []
        self.test_vars = []
        self.param_key, params = _ye.get_params_dict(self.current_yaml_data)
        self.test_key, tests = _ye.get_tests_dict(self.current_yaml_data)

        self._param_box.addWidget(self._build_param_card(params))
        self._param_box.addStretch(1)

        if tests:
            for t_idx, (tb_name, tb_data) in enumerate(tests.items()):
                self._tests_box.addWidget(
                    self._build_test_card(t_idx, tb_name, tb_data or {})
                )
        else:
            empty = QLabel("No testbenches yet — click  + Add Testbench")
            empty.setObjectName("Muted")
            self._tests_box.addWidget(empty)
        self._tests_box.addStretch(1)

    def _build_param_card(self, params: dict) -> QFrame:
        card = QFrame()
        card.setObjectName("Card")
        grid = QGridLayout(card)
        grid.addWidget(QLabel("Name"), 0, 0)
        grid.addWidget(QLabel("Values  (list or range DSL)"), 0, 1)
        r = 1
        for name, val in (params or {}).items():
            if isinstance(val, list):
                val_str = ", ".join(_ye.gui_repr_param(x) for x in val)
            else:
                val_str = _ye.gui_repr_param(val)
            key_e = QLineEdit(str(name))
            val_e = QLineEdit(val_str)
            val_e.setPlaceholderText("1.5, 2.0  or  range(10)")
            delbtn = self._del_button(lambda _=False, i=r - 1: self._action_del_param(i))
            grid.addWidget(key_e, r, 0)
            grid.addWidget(val_e, r, 1)
            grid.addWidget(delbtn, r, 2)
            self.param_vars.append({"key": _Var(key_e), "val": _Var(val_e)})
            r += 1
        if r == 1:
            hint = QLabel("No parameters yet — click  + Add")
            hint.setObjectName("Muted")
            grid.addWidget(hint, 1, 0, 1, 3)
        grid.setColumnStretch(1, 1)
        return card

    def _build_test_card(self, t_idx: int, tb_name: str, tb_data: dict) -> QFrame:
        card = QFrame()
        card.setObjectName("Card")
        v = QVBoxLayout(card)

        hdr = QHBoxLayout()
        name_e = QLineEdit(str(tb_name))
        name_e.setPlaceholderText("testbench name (tb/*.sch)")
        hdr.addWidget(name_e, stretch=1)
        del_t = QPushButton("✕ Delete")
        del_t.clicked.connect(lambda _=False, i=t_idx: self._action_del_test(i))
        hdr.addWidget(del_t)
        v.addLayout(hdr)

        grid = QGridLayout()
        for col, txt in enumerate(("Measurement", "Min", "Typ", "Max", "Unit")):
            lbl = QLabel(txt)
            lbl.setObjectName("Muted")
            grid.addWidget(lbl, 0, col)
        test_val_vars: list[dict] = []
        row_i = 1
        for v_name, v_data in tb_data.items():
            if v_name in _SKIP_KEYS:
                continue
            if not isinstance(v_data, dict):
                v_data = {}
            name_v = QLineEdit(str(v_name))
            min_v = QLineEdit(_ye.fmt_bound(v_data.get("vmin", v_data.get("min", ""))))
            typ_v = QLineEdit(_ye.fmt_bound(v_data.get("vtyp", v_data.get("typ", ""))))
            max_v = QLineEdit(_ye.fmt_bound(v_data.get("vmax", v_data.get("max", ""))))
            unit_v = QLineEdit(str(v_data.get("unit", v_data.get("units", "")) or ""))
            unit_v.setPlaceholderText("V, Hz…")
            for w in (min_v, typ_v, max_v):
                w.setFixedWidth(80)
            unit_v.setFixedWidth(60)
            delv = self._del_button(
                lambda _=False, t=t_idx, n=v_name: self._action_del_value(t, n)
            )
            grid.addWidget(name_v, row_i, 0)
            grid.addWidget(min_v, row_i, 1)
            grid.addWidget(typ_v, row_i, 2)
            grid.addWidget(max_v, row_i, 3)
            grid.addWidget(unit_v, row_i, 4)
            grid.addWidget(delv, row_i, 5)
            test_val_vars.append({
                "name": _Var(name_v), "vmin": _Var(min_v),
                "vmax": _Var(max_v), "vtyp": _Var(typ_v),
                "unit": _Var(unit_v),
                "orig_name": str(v_name),
            })
            row_i += 1
        if row_i == 1:
            none_lbl = QLabel("No measurements yet")
            none_lbl.setObjectName("Muted")
            grid.addWidget(none_lbl, 1, 0, 1, 5)
        grid.setColumnStretch(6, 1)
        v.addLayout(grid)

        add_v = QPushButton("+ Add Measurement")
        add_v.clicked.connect(lambda _=False, i=t_idx: self._action_add_value(i))
        v.addWidget(add_v)

        cap = QLabel("CAPTURED SIGNALS")
        cap.setObjectName("Muted")
        v.addWidget(cap)
        analysis_vars: dict = {}
        for yaml_key, label, placeholder in _ANALYSIS_ROWS:
            existing = tb_data.get(yaml_key, [])
            initial = ", ".join(str(s) for s in existing) if isinstance(existing, list) else str(existing)
            row = QHBoxLayout()
            lab = QLabel(label)
            lab.setObjectName("Muted")
            lab.setFixedWidth(70)
            row.addWidget(lab)
            edit = QLineEdit(initial)
            edit.setPlaceholderText(placeholder)
            row.addWidget(edit, stretch=1)
            v.addLayout(row)
            analysis_vars[yaml_key] = _Var(edit)

        self.test_vars.append({
            "tb_name": _Var(name_e),
            "values": test_val_vars,
            "tran_signals": analysis_vars["transient_signals"],
            "analysis_signals": analysis_vars,
        })
        return card

    def _del_button(self, slot) -> QToolButton:
        btn = QToolButton()
        btn.setText("✕")
        btn.clicked.connect(slot)
        return btn

    # ── Form ↔ state ──────────────────────────────────────────────────────────

    def _sync_to_state(self) -> None:
        if not isinstance(self.current_yaml_data, dict):
            self.current_yaml_data = {}
        self.current_yaml_data = _ye.sync_form_to_yaml(
            self.current_yaml_data, self.param_key, self.test_key,
            self.param_vars, self.test_vars, QuotedString,
        )

    def _action_add_param(self) -> None:
        self._sync_to_state()
        self.current_yaml_data.setdefault(self.param_key, {})["new_param"] = [1, 2]
        self._build_form()

    def _action_del_param(self, idx: int) -> None:
        self._sync_to_state()
        keys = list(self.current_yaml_data.get(self.param_key, {}).keys())
        if idx < len(keys):
            del self.current_yaml_data[self.param_key][keys[idx]]
        self._build_form()

    def _action_add_test(self) -> None:
        self._sync_to_state()
        self.current_yaml_data.setdefault(self.test_key, {})["new_testbench"] = {}
        self._build_form()

    def _action_del_test(self, idx: int) -> None:
        self._sync_to_state()
        keys = list(self.current_yaml_data.get(self.test_key, {}).keys())
        if idx < len(keys):
            del self.current_yaml_data[self.test_key][keys[idx]]
        self._build_form()

    def _action_add_value(self, test_idx: int) -> None:
        self._sync_to_state()
        keys = list(self.current_yaml_data.get(self.test_key, {}).keys())
        if test_idx < len(keys):
            tb = self.current_yaml_data[self.test_key][keys[test_idx]]
            name, n = "new_measurement", 1
            while name in tb:
                name = f"new_measurement_{n}"
                n += 1
            tb[name] = {}
        self._build_form()

    def _action_del_value(self, test_idx: int, val_name: str) -> None:
        self._sync_to_state()
        keys = list(self.current_yaml_data.get(self.test_key, {}).keys())
        if test_idx < len(keys):
            tb = self.current_yaml_data[self.test_key][keys[test_idx]]
            tb.pop(val_name, None)
        self._build_form()

    # ── Mode switch ───────────────────────────────────────────────────────────

    def _on_mode_change(self, *_a) -> None:
        if self.mode_combo.currentText() == "Form View":
            try:
                self.current_yaml_data = yaml.safe_load(self.raw_editor.toPlainText()) or {}
            except Exception as exc:  # noqa: BLE001
                QMessageBox.critical(self, "YAML Error", f"Syntax error:\n{exc}")
                self.mode_combo.blockSignals(True)
                self.mode_combo.setCurrentText("Raw YAML")
                self.mode_combo.blockSignals(False)
                return
            self._build_form()
            self.stack.setCurrentIndex(0)
        else:
            self._sync_to_state()
            if not self._raw_matches_state():
                self.raw_editor.setPlainText(self._dump())
            self.stack.setCurrentIndex(1)

    def _raw_matches_state(self) -> bool:
        try:
            text = self.raw_editor.toPlainText()
            return bool(text.strip()) and yaml.safe_load(text) == self.current_yaml_data
        except Exception:  # noqa: BLE001
            return False

    def _dump(self) -> str:
        return yaml.dump(self.current_yaml_data, Dumper=ChipifyDumper,
                         default_flow_style=False, sort_keys=False)

    # ── New / Save ────────────────────────────────────────────────────────────

    def _action_new(self) -> None:
        name, ok = QInputDialog.getText(self, "New Datasheet", "Name for the new datasheet:")
        if not ok or not name.strip():
            return
        try:
            path = _ye.create_datasheet(settings.IN_DIR, name)
        except (ValueError, FileExistsError, OSError) as exc:
            QMessageBox.critical(self, "New Datasheet", str(exc))
            return
        import os
        self._window.set_active_datasheet(os.path.basename(path))
        self._window.set_status(f"Created {os.path.basename(path)}", "#2ecc71")

    def _save(self) -> None:
        if not self.current_yaml_path:
            QMessageBox.warning(self, "Save", "No datasheet selected.")
            return
        try:
            if self.mode_combo.currentText() == "Form View":
                self._sync_to_state()
                text = self.raw_editor.toPlainText() if self._raw_matches_state() else self._dump()
                if not self._raw_matches_state():
                    self.raw_editor.setPlainText(text)
            else:
                text = self.raw_editor.toPlainText()
                yaml.safe_load(text)  # validate
            with open(self.current_yaml_path, "w", encoding="utf-8") as fh:
                fh.write(text)
        except Exception as exc:  # noqa: BLE001
            QMessageBox.critical(self, "Save Error", f"Could not save datasheet:\n{exc}")
            return
        self.raw_text = text
        self._window.set_status("Datasheet saved.", "#2ecc71")
