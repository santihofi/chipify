"""
theme.py – Application-wide colour constants and CTk appearance bootstrap.

Import this module before any CTk widget is instantiated so that the
appearance mode and colour theme are applied consistently.
"""
from __future__ import annotations

import customtkinter as ctk

ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("blue")

BACKGROUND_COLOR: str = "#000000"
PANEL_COLOR: str = "#1a1a1a"

# Legacy aliases used by the existing gui_tk.py code (removed once the shim is
# in place and all callers have been migrated).
background_color = BACKGROUND_COLOR
panel_color = PANEL_COLOR
