# Copyright (c) 2026 Santiago Hofwimmer
"""
treeview_styling.py – Apply the Chipify theme to a ttk.Treeview widget.

Call ``apply_treeview_style(tree, mode)`` after the treeview is created.
``apply_dark_style`` is kept as a backward-compatible alias.
"""
from __future__ import annotations

from tkinter import ttk

import chipify.gui.theme as _theme


def apply_treeview_style(tree: ttk.Treeview, mode: str = "night") -> None:
    """Configure theme-appropriate styles and tag colours on *tree*.

    `style.configure` is sticky: properties stay set across calls, so the
    light branch must explicitly set background / fieldbackground (otherwise
    a previous dark-mode call would leave the tree looking dark).
    """
    style = ttk.Style()
    style.theme_use("default")

    if mode == "light":
        panel = _theme.PANEL_COLOR or "#dbdbdb"
        style.configure(
            "Treeview",
            background=panel,
            foreground="black",
            fieldbackground=panel,
            rowheight=25,
            borderwidth=0,
        )
        style.map("Treeview", background=[("selected", "#3484F0")],
                              foreground=[("selected", "white")])
        style.configure(
            "Treeview.Heading",
            background="#cfcfcf",
            foreground="black",
            relief="flat",
        )
        style.map("Treeview.Heading", background=[("active", "#3484F0")])
        tree.tag_configure("pass", background="#c8f0c8", foreground="black")
        tree.tag_configure("fail", background="#f0c8c8", foreground="black")
        tree.tag_configure("warn", background="#f0e4aa", foreground="black")
    else:
        panel = _theme.PANEL_COLOR or "#1a1a1a"
        style.configure(
            "Treeview",
            background=panel,
            foreground="white",
            rowheight=25,
            fieldbackground=panel,
            borderwidth=0,
        )
        style.map("Treeview", background=[("selected", "#1f538d")],
                              foreground=[("selected", "white")])
        style.configure(
            "Treeview.Heading",
            background="#565b5e",
            foreground="white",
            relief="flat",
        )
        style.map("Treeview.Heading", background=[("active", "#3484F0")])
        tree.tag_configure("pass", background="#1a4d1a", foreground="white")
        tree.tag_configure("fail", background="#4d1a1a", foreground="white")
        tree.tag_configure("warn", background="#e67e22", foreground="black")


def apply_dark_style(tree: ttk.Treeview) -> None:
    """Backward-compatible alias — applies night/dark style."""
    apply_treeview_style(tree, "night")
