# Copyright (c) 2026 Santiago Hofwimmer
"""
run_annotation_dialog.py – View/edit the notes and tags of a history run.

The ``notes``/``tags`` fields have existed in the run meta schema (run_meta.py)
since v1 but had no UI. This modal edits them in place via
``run_meta.update_meta``; a minimal sidecar is created for runs that predate
metadata (without a ``yaml`` field, so datasheet filtering is unaffected).
"""
from __future__ import annotations

import customtkinter as ctk

from chipify import run_meta


class RunAnnotationDialog(ctk.CTkToplevel):
    """Modal dialog showing a run's key metadata with editable notes/tags."""

    def __init__(self, parent: ctk.CTk, selection: str, csv_path: str) -> None:
        super().__init__(parent)
        self.title("Run Annotation")
        self.geometry("460x420")
        self.resizable(False, False)
        # grab_set needs a small delay so the window is fully mapped first
        self.after(50, self.grab_set)

        self._csv_path = csv_path
        meta = run_meta.read_meta(csv_path)

        ctk.CTkLabel(
            self, text=selection,
            font=ctk.CTkFont(size=15, weight="bold")
        ).pack(pady=(18, 2))

        info_bits = []
        if meta.get("yaml"):
            info_bits.append(f"Datasheet: {meta['yaml']}")
        if meta.get("timestamp"):
            info_bits.append(f"Simulated: {meta['timestamp']}")
        if meta.get("global_yield") is not None:
            info_bits.append(f"Yield: {meta['global_yield']:.1f}%")
        if meta.get("total_runs") is not None:
            info_bits.append(f"Samples: {meta['total_runs']}")
        ctk.CTkLabel(
            self,
            text="\n".join(info_bits) if info_bits else "No metadata recorded for this run.",
            text_color="gray", font=ctk.CTkFont(size=11), justify="left",
        ).pack(pady=(0, 10))

        body = ctk.CTkFrame(self, fg_color="transparent")
        body.pack(fill="both", expand=True, padx=24)

        ctk.CTkLabel(body, text="Notes:", anchor="w").pack(anchor="w")
        self._notes_box = ctk.CTkTextbox(body, height=140)
        self._notes_box.pack(fill="both", expand=True, pady=(4, 10))
        self._notes_box.insert("1.0", str(meta.get("notes", "") or ""))

        ctk.CTkLabel(body, text="Tags (comma-separated):", anchor="w").pack(anchor="w")
        self._tags_var = ctk.StringVar(
            value=", ".join(str(t) for t in (meta.get("tags") or [])))
        ctk.CTkEntry(body, textvariable=self._tags_var).pack(fill="x", pady=(4, 0))

        btn_row = ctk.CTkFrame(self, fg_color="transparent")
        btn_row.pack(fill="x", padx=24, pady=(14, 16))
        ctk.CTkButton(
            btn_row, text="Cancel", command=self.destroy,
            fg_color="transparent", border_width=1,
            text_color=("gray10", "#DCE4EE")
        ).pack(side="left")
        ctk.CTkButton(
            btn_row, text="Save", command=self._save,
            fg_color="#2ecc71", hover_color="#27ae60"
        ).pack(side="right")

    def _save(self) -> None:
        notes = self._notes_box.get("1.0", "end").strip()
        tags = [t.strip() for t in self._tags_var.get().split(",") if t.strip()]
        run_meta.update_meta(self._csv_path, notes=notes, tags=tags)
        self.destroy()
