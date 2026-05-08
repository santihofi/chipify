"""
theme.py – Application-wide colour constants and CTk appearance bootstrap.

Import this module before any CTk widget is instantiated so that the
appearance mode and colour theme are applied consistently.

Every theme defines explicit hex colours for ``bg`` and ``panel`` so that the
values are always usable both as CTk widget ``fg_color`` AND as matplotlib
``facecolor`` (which does not understand CTk's ``("light", "dark")`` tuples).
"""
from __future__ import annotations

import customtkinter as ctk

# ── Theme definitions ─────────────────────────────────────────────────────────
# Hex codes are chosen to track CTk's built-in light/dark frame defaults
# (gray92 ≈ #ebebeb, gray86 ≈ #dbdbdb, gray17 ≈ #2b2b2b, gray14 ≈ #242424).

THEMES: dict[str, dict] = {
    "night": {"ctk_mode": "dark",  "bg": "#000000", "panel": "#1a1a1a", "mpl_bg": "#1a1a1a", "mpl_fg": "white"},
    "dark":  {"ctk_mode": "dark",  "bg": "#242424", "panel": "#2b2b2b", "mpl_bg": "#2b2b2b", "mpl_fg": "white"},
    "light": {"ctk_mode": "light", "bg": "#ebebeb", "panel": "#dbdbdb", "mpl_bg": "white",   "mpl_fg": "#2b2b2b"},
}


def _load_initial() -> str:
    try:
        from chipify import app_config
        return app_config.load_config().get("theme", "night")
    except Exception:
        return "night"


_initial = _load_initial()
_t = THEMES.get(_initial, THEMES["night"])

ctk.set_appearance_mode(_t["ctk_mode"])
ctk.set_default_color_theme("blue")

BACKGROUND_COLOR: str = _t["bg"]
PANEL_COLOR: str = _t["panel"]
MPL_BG_COLOR: str = _t["mpl_bg"]
MPL_FG_COLOR: str = _t["mpl_fg"]
CURRENT_MODE: str = _initial

# Legacy aliases
background_color = BACKGROUND_COLOR
panel_color = PANEL_COLOR


def apply_theme(mode: str) -> None:
    """Update module globals and CTk appearance for *mode* (night|dark|light)."""
    global BACKGROUND_COLOR, PANEL_COLOR, MPL_BG_COLOR, MPL_FG_COLOR, CURRENT_MODE
    global background_color, panel_color
    t = THEMES.get(mode, THEMES["night"])
    ctk.set_appearance_mode(t["ctk_mode"])
    BACKGROUND_COLOR = t["bg"]
    PANEL_COLOR = t["panel"]
    MPL_BG_COLOR = t["mpl_bg"]
    MPL_FG_COLOR = t["mpl_fg"]
    CURRENT_MODE = mode
    background_color = BACKGROUND_COLOR
    panel_color = PANEL_COLOR
