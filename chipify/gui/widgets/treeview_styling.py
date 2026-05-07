"""
treeview_styling.py – Apply the Chipify dark theme to a ttk.Treeview widget.

Call ``apply_dark_style(tree)`` after the treeview is created to style it
consistently across all tabs.
"""
from __future__ import annotations

from tkinter import ttk

from chipify.gui.theme import PANEL_COLOR


def apply_dark_style(tree: ttk.Treeview) -> None:
    """Configure dark-theme styles and tag colours on *tree*."""
    style = ttk.Style()
    style.theme_use("default")
    style.configure(
        "Treeview",
        background=PANEL_COLOR,
        foreground="white",
        rowheight=25,
        fieldbackground=PANEL_COLOR,
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
