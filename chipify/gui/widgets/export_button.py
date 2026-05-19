"""
export_button.py – Shared "💾 Export" button widget for plots.

Drops into any CTk frame and gives the user a menu of every registered
:class:`chipify.plugin_loader.ExporterPlugin` (PNG, SVG, plus anything
the user has dropped in ``~/.chipify/plugins/``). The caller supplies
a callback that returns the matplotlib Figure to save.

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
    Create a "💾 Export" button on *parent* and place it via either ``pack``
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
        Used as the default filename (minus extension) in the save dialog.
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
        text="💾 Export",
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

    def _save_with(exporter_cls: type) -> None:
        try:
            exporter = exporter_cls()
        except Exception as exc:
            log.exception("Failed to instantiate exporter %s", exporter_cls)
            messagebox.showerror("Export Error", f"Could not load exporter:\n{exc}")
            return

        ext = (getattr(exporter, "extension", "") or "").lstrip(".")
        if not ext:
            messagebox.showerror(
                "Export Error",
                f"Exporter '{getattr(exporter, 'name', exporter_cls.__name__)}' "
                "declared no file extension.",
            )
            return

        default_dir = _exports_dir()
        default_name = f"{_resolve_name()}.{ext}"

        out_path = filedialog.asksaveasfilename(
            title=f"Save as {exporter.name}",
            initialdir=default_dir,
            initialfile=default_name,
            defaultextension=f".{ext}",
            filetypes=[(exporter.name, f"*.{ext}"), ("All files", "*.*")],
        )
        if not out_path:
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

    def _show_menu() -> None:
        exporters = list(get_exporter_plugins())
        if not exporters:
            messagebox.showwarning(
                "Export",
                "No exporters available. Reinstall chipify or add a plugin "
                "to ~/.chipify/plugins/.",
            )
            return

        def _make_cmd(c: type) -> Callable[[], None]:
            return lambda: _save_with(c)

        menu = tk.Menu(parent, tearoff=0)
        for cls in exporters:
            label = getattr(cls, "name", cls.__name__)
            menu.add_command(label=label, command=_make_cmd(cls))

        x = btn.winfo_rootx()
        y = btn.winfo_rooty() + btn.winfo_height()
        try:
            menu.tk_popup(x, y)
        finally:
            menu.grab_release()

    btn.configure(command=_show_menu)

    if pack_kwargs is not None:
        btn.pack(**pack_kwargs)
    elif grid_kwargs is not None:
        btn.grid(**grid_kwargs)

    return btn
