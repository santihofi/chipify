# Copyright (c) 2026 Santiago Hofwimmer
"""
run_annotation_dialog.py – View/edit a history run's notes and tags (Qt).

Edits the ``notes``/``tags`` fields of a run's meta sidecar in place via
:func:`chipify.run_meta.update_meta` (a minimal sidecar is created for runs
that predate metadata). Qt port of the CustomTkinter ``RunAnnotationDialog``.
"""
from __future__ import annotations

from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QVBoxLayout,
    QWidget,
)

from chipify import run_meta


class RunAnnotationDialog(QDialog):
    """Modal editor for a run's notes + tags."""

    def __init__(self, parent: QWidget, selection: str, csv_path: str) -> None:
        super().__init__(parent)
        self.setWindowTitle("Run Annotation")
        self.setMinimumWidth(440)
        self._csv_path = csv_path
        meta = run_meta.read_meta(csv_path)

        layout = QVBoxLayout(self)

        title = QLabel(selection)
        title.setObjectName("Heading")
        layout.addWidget(title)

        info_bits = []
        if meta.get("yaml"):
            info_bits.append(f"Datasheet: {meta['yaml']}")
        if meta.get("timestamp"):
            info_bits.append(f"Simulated: {meta['timestamp']}")
        if meta.get("global_yield") is not None:
            info_bits.append(f"Yield: {meta['global_yield']:.1f}%")
        if meta.get("total_runs") is not None:
            info_bits.append(f"Samples: {meta['total_runs']}")
        info = QLabel("\n".join(info_bits) if info_bits else "No metadata recorded.")
        info.setObjectName("Muted")
        layout.addWidget(info)

        layout.addWidget(QLabel("Notes:"))
        self._notes = QPlainTextEdit(str(meta.get("notes", "") or ""))
        layout.addWidget(self._notes, stretch=1)

        layout.addWidget(QLabel("Tags (comma-separated):"))
        self._tags = QLineEdit(", ".join(str(t) for t in (meta.get("tags") or [])))
        layout.addWidget(self._tags)

        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self._save)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _save(self) -> None:
        notes = self._notes.toPlainText().strip()
        tags = [t.strip() for t in self._tags.text().split(",") if t.strip()]
        run_meta.update_meta(self._csv_path, notes=notes, tags=tags)
        self.accept()
