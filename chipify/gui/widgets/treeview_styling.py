"""
treeview_styling.py – Apply the Chipify theme to a ttk.Treeview widget.

Call ``apply_treeview_style(tree, mode)`` after the treeview is created.
``apply_dark_style`` is kept as a backward-compatible alias.
"""
from __future__ import annotations

from tkinter import ttk

import chipify.gui.theme as _theme


def apply_treeview_style(tree: ttk.Treeview, mode: str = "night") -> None:
    """Configure theme-appropriate styles and tag colours on *tree*."""
    style = ttk.Style()
    style.theme_use("default")

    if mode == "light":
        style.configure(
            "Treeview",
            rowheight=25,
            borderwidth=0,
        )
        style.map("Treeview", background=[("selected", "#3484F0")])
        style.configure("Treeview.Heading", relief="flat")
        style.map("Treeview.Heading", background=[("active", "#3484F0")])
        tree.tag_configure("pass", background="#c8f0c8")
        tree.tag_configure("fail", background="#f0c8c8")
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
        style.map("Treeview", background=[("selected", "#1f538d")])
        style.configure(
            "Treeview.Heading",
            background="#565b5e",
            foreground="white",
            relief="flat",
        )
        style.map("Treeview.Heading", background=[("active", "#3484F0")])
        tree.tag_configure("pass", background="#1a4d1a")
        tree.tag_configure("fail", background="#4d1a1a")
        tree.tag_configure("warn", background="#e67e22", foreground="black")


def apply_dark_style(tree: ttk.Treeview) -> None:
    """Backward-compatible alias — applies night/dark style."""
    apply_treeview_style(tree, "night")
