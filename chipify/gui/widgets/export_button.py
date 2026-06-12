# Copyright (c) 2026 Santiago Hofwimmer
"""
export_button.py – Shared "Export" button widget for plots.

Drops into any CTk frame and gives the user a CustomTkinter-themed dialog
that lets them pick a format (any registered
:class:`chipify.plugin_loader.ExporterPlugin`: PNG, SVG, plus anything
they've dropped in ``~/.chipify/plugins/``), filename, and output folder.

Usage
-----
::

    from chipify.gui.widgets.export_button import attach_export_button

    attach_export_button(
        parent_frame,
        get_fig=lambda: self.fig,
        suggested_name=lambda: self.plot_param_var.get(),
        pack_kwargs={"side": "left", "padx": 8},
    )
"""

from __future__ import annotations

import logging
import os
import re
import tkinter as tk
from tkinter import filedialog, messagebox
from typing import TYPE_CHECKING, Any, Callable

import customtkinter as ctk

from chipify import settings
from chipify.plugin_loader import get_exporter_plugins

if TYPE_CHECKING:
    from matplotlib.figure import Figure
    from chipify.plugin_loader import ExporterPlugin

log = logging.getLogger("chipify.gui.export")

_INVALID_FILENAME_CHARS = re.compile(r'[\\/:*?"<>|]+')


def _sanitize(name: str) -> str:
    """Trim and replace OS-illegal filename characters."""
    cleaned = _INVALID_FILENAME_CHARS.sub("_", (name or "").strip())
    cleaned = cleaned.strip("._ ")
    return cleaned or "plot"


def _exports_dir() -> str:
    path = os.path.join(settings.OUT_DIR, "exports")
    os.makedirs(path, exist_ok=True)
    return path


def _panel_color() -> str:
    try:
        from chipify.gui import theme as _t
        return _t.PANEL_COLOR
    except Exception:
        return "#1a1a1a"


# ── CTk export dialog ────────────────────────────────────────────────────────


class ExportDialog(ctk.CTkToplevel):  # type: ignore[misc]
    """Modal dialog for picking format / filename / folder.

    Built entirely from CustomTkinter widgets so it matches the rest of
    the app's appearance. The only non-CTk surface is the native
    *directory*-picker invoked from the Browse… button — Tk ships no
    folder picker in CTk form, but the dialog itself stays themed.
    """

    def __init__(
        self,
        parent: tk.Misc,
        *,
        exporters: list[type["ExporterPlugin"]],
        suggested_name: str,
        initial_dir: str,
        on_save: Callable[[type["ExporterPlugin"], str], None],
    ) -> None:
        super().__init__(parent)
        self.title("Export Plot")
        self.geometry("440x260")
        self.resizable(False, False)

        try:
            self.configure(fg_color=_panel_color())
        except Exception:
            pass

        self._exporters = exporters
        self._on_save = on_save
        self._folder = initial_dir

        # ── Layout ───────────────────────────────────────────────────────
        body = ctk.CTkFrame(self, fg_color="transparent")
        body.pack(fill="both", expand=True, padx=18, pady=(16, 6))
        body.grid_columnconfigure(1, weight=1)

        ctk.CTkLabel(body, text="Filename:", anchor="w").grid(
            row=0, column=0, sticky="w", pady=(0, 6))
        self._name_var = ctk.StringVar(value=suggested_name)
        self._name_entry = ctk.CTkEntry(body, textvariable=self._name_var)
        self._name_entry.grid(row=0, column=1, sticky="ew", padx=(10, 0), pady=(0, 6))

        ctk.CTkLabel(body, text="Format:", anchor="w").grid(
            row=1, column=0, sticky="w", pady=(0, 6))
        format_names = [getattr(c, "name", c.__name__) for c in exporters]
        self._format_var = ctk.StringVar(value=format_names[0])
        self._format_menu = ctk.CTkOptionMenu(
            body, values=format_names, variable=self._format_var,
            command=self._on_format_change, dynamic_resizing=False,
        )
        self._format_menu.grid(row=1, column=1, sticky="ew", padx=(10, 0), pady=(0, 6))

        ctk.CTkLabel(body, text="Folder:", anchor="w").grid(
            row=2, column=0, sticky="w", pady=(0, 6))
        self._folder_label = ctk.CTkLabel(
            body, text=self._display_folder(self._folder),
            anchor="w", text_color=("gray20", "#aaaaaa"),
        )
        self._folder_label.grid(row=2, column=1, sticky="ew", padx=(10, 0), pady=(0, 6))

        ctk.CTkButton(
            body, text="Browse…",
            command=self._pick_folder, width=110,
            fg_color="transparent", border_width=1,
            text_color=("gray10", "#DCE4EE"),
        ).grid(row=3, column=1, sticky="w", padx=(10, 0))

        # ── Buttons row ──────────────────────────────────────────────────
        btn_row = ctk.CTkFrame(self, fg_color="transparent")
        btn_row.pack(side="bottom", fill="x", padx=18, pady=(0, 16))

        ctk.CTkButton(
            btn_row, text="Cancel", width=100,
            command=self._cancel,
            fg_color="transparent", border_width=1,
            text_color=("gray10", "#DCE4EE"),
        ).pack(side="right", padx=(8, 0))

        ctk.CTkButton(
            btn_row, text="Save", width=100,
            command=self._save,
            fg_color="#3484F0", hover_color="#1a6fc4",
        ).pack(side="right")

        self.bind("<Return>", lambda _e: self._save())
        self.bind("<Escape>", lambda _e: self._cancel())
        self.after(50, self._post_open_focus)

    # ── Helpers ──────────────────────────────────────────────────────────

    def _post_open_focus(self) -> None:
        try:
            self.grab_set()
        except Exception:
            pass
        try:
            self._name_entry.focus_set()
            self._name_entry.select_range(0, "end")
        except Exception:
            pass

    def _display_folder(self, path: str) -> str:
        if len(path) <= 50:
            return path
        return "…" + path[-49:]

    def _selected_exporter(self) -> type["ExporterPlugin"] | None:
        name = self._format_var.get()
        for cls in self._exporters:
            if getattr(cls, "name", cls.__name__) == name:
                return cls
        return None

    def _on_format_change(self, _selection: str) -> None:
        # If the user hadn't typed anything custom, no need to do anything;
        # filename is independent of the format. Extension is added on save.
        pass

    def _pick_folder(self) -> None:
        chosen = filedialog.askdirectory(
            parent=self,
            title="Choose export folder",
            initialdir=self._folder,
            mustexist=True,
        )
        if chosen:
            self._folder = chosen
            self._folder_label.configure(text=self._display_folder(chosen))

    def _cancel(self) -> None:
        try:
            self.grab_release()
        except Exception:
            pass
        self.destroy()

    def _save(self) -> None:
        cls = self._selected_exporter()
        if cls is None:
            messagebox.showerror("Export", "No exporter selected.", parent=self)
            return

        ext = (getattr(cls, "extension", "") or "").lstrip(".")
        if not ext:
            messagebox.showerror(
                "Export",
                f"Exporter '{getattr(cls, 'name', cls.__name__)}' "
                "declared no file extension.",
                parent=self,
            )
            return

        raw_name = self._name_var.get()
        base = _sanitize(raw_name)
        # Strip a user-typed extension if it matches the chosen format
        if base.lower().endswith(f".{ext}".lower()):
            base = base[: -(len(ext) + 1)]
        filename = f"{base}.{ext}"

        try:
            os.makedirs(self._folder, exist_ok=True)
        except OSError as exc:
            messagebox.showerror("Export", f"Cannot create folder:\n{exc}", parent=self)
            return

        out_path = os.path.join(self._folder, filename)
        if os.path.exists(out_path):
            if not messagebox.askyesno(
                "Overwrite?",
                f"{filename} already exists in this folder.\nOverwrite?",
                parent=self,
            ):
                return

        try:
            self.grab_release()
        except Exception:
            pass
        self.destroy()
        self._on_save(cls, out_path)


# ── Public API ───────────────────────────────────────────────────────────────


def attach_export_button(
    parent: tk.Misc,
    *,
    get_fig: Callable[[], "Figure"],
    suggested_name: Callable[[], str] | str = "plot",
    get_theme: Callable[[], dict[str, Any] | None] | None = None,
    on_status: Callable[[str, str], None] | None = None,
    pack_kwargs: dict[str, Any] | None = None,
    grid_kwargs: dict[str, Any] | None = None,
    **btn_kwargs: Any,
) -> ctk.CTkButton:
    """
    Create an "Export" button on *parent* and place it via either ``pack``
    or ``grid`` (caller chooses one).

    Parameters
    ----------
    parent:
        The CTk/Tk frame that hosts the button.
    get_fig:
        Zero-arg callable returning the live ``matplotlib.figure.Figure``
        to save. Called fresh each time the user picks a format, so the
        very latest plot is what gets exported.
    suggested_name:
        Either a literal string or a zero-arg callable returning a string.
        Used as the default filename (minus extension) in the dialog.
    get_theme:
        Optional zero-arg callable returning a palette dict, forwarded to
        the exporter's ``theme=`` kwarg.
    on_status:
        Optional callback ``(message, color)`` for surfacing progress in a
        host label (e.g. ``main_window.lbl_status``). When omitted, only
        messagebox notifications fire.
    pack_kwargs / grid_kwargs:
        Exactly one of these may be supplied; passed to ``btn.pack(...)``
        or ``btn.grid(...)`` respectively. If neither is given, the button
        is returned unplaced for the caller to position.
    btn_kwargs:
        Forwarded to :class:`ctk.CTkButton` (width, fg_color, …).
    """
    if pack_kwargs is not None and grid_kwargs is not None:
        raise ValueError("attach_export_button: pass pack_kwargs OR grid_kwargs, not both")

    defaults: dict[str, Any] = dict(
        text="Export",
        width=100,
        fg_color="transparent",
        border_width=1,
        text_color=("gray10", "#DCE4EE"),
    )
    defaults.update(btn_kwargs)

    btn = ctk.CTkButton(parent, **defaults)

    def _resolve_name() -> str:
        raw = suggested_name() if callable(suggested_name) else suggested_name
        return _sanitize(str(raw))

    def _resolve_theme() -> dict[str, Any] | None:
        if get_theme is None:
            return None
        try:
            return get_theme()
        except Exception:
            return None

    def _do_export(exporter_cls: type, out_path: str) -> None:
        try:
            exporter = exporter_cls()
        except Exception as exc:
            log.exception("Failed to instantiate exporter %s", exporter_cls)
            messagebox.showerror("Export Error", f"Could not load exporter:\n{exc}")
            return

        if on_status:
            on_status(f"Status: Saving {exporter.name}…", "yellow")

        try:
            fig = get_fig()
            written = exporter.export(fig, out_path, theme=_resolve_theme())
        except Exception as exc:
            log.exception("Exporter %s failed", exporter.name)
            if on_status:
                on_status(f"Status: {exporter.name} export failed", "red")
            messagebox.showerror("Export Error", f"{exporter.name} export failed:\n{exc}")
            return

        if on_status:
            on_status(f"Status: Saved {os.path.basename(written)}", "#2ecc71")
        log.info("Exported figure via %s → %s", exporter.name, written)

    def _open_dialog() -> None:
        exporters = list(get_exporter_plugins())
        if not exporters:
            messagebox.showwarning(
                "Export",
                "No exporters available. Reinstall chipify or add a plugin "
                "to ~/.chipify/plugins/.",
            )
            return

        ExportDialog(
            parent,
            exporters=exporters,
            suggested_name=_resolve_name(),
            initial_dir=_exports_dir(),
            on_save=_do_export,
        )

    btn.configure(command=_open_dialog)

    if pack_kwargs is not None:
        btn.pack(**pack_kwargs)
    elif grid_kwargs is not None:
        btn.grid(**grid_kwargs)

    return btn
