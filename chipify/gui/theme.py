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
    "night": {"ctk_mode": "dark",  "bg": "#000000", "panel": "#1a1a1a", "mpl_bg": "#1a1a1a", "mpl_fg": "white",
              "card_bg": "#111111", "card_border": "#2e2e2e", "text_muted": "#9a9a9a"},
    "dark":  {"ctk_mode": "dark",  "bg": "#242424", "panel": "#2b2b2b", "mpl_bg": "#2b2b2b", "mpl_fg": "white",
              "card_bg": "#232323", "card_border": "#3d3d3d", "text_muted": "#9a9a9a"},
    "light": {"ctk_mode": "light", "bg": "#ebebeb", "panel": "#dbdbdb", "mpl_bg": "white",   "mpl_fg": "#2b2b2b",
              "card_bg": "#f2f2f2", "card_border": "#c9c9c9", "text_muted": "#6b6b6b"},
}

# Theme-independent semantic colours.
ACCENT: str = "#3484F0"
DANGER: str = "#e74c3c"


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
CARD_BG: str = _t["card_bg"]
CARD_BORDER: str = _t["card_border"]
TEXT_MUTED: str = _t["text_muted"]
CURRENT_MODE: str = _initial

# Legacy aliases
background_color = BACKGROUND_COLOR
panel_color = PANEL_COLOR


def apply_theme(mode: str) -> None:
    """Update module globals and CTk appearance for *mode* (night|dark|light)."""
    global BACKGROUND_COLOR, PANEL_COLOR, MPL_BG_COLOR, MPL_FG_COLOR, CURRENT_MODE
    global CARD_BG, CARD_BORDER, TEXT_MUTED
    global background_color, panel_color
    t = THEMES.get(mode, THEMES["night"])
    ctk.set_appearance_mode(t["ctk_mode"])
    BACKGROUND_COLOR = t["bg"]
    PANEL_COLOR = t["panel"]
    MPL_BG_COLOR = t["mpl_bg"]
    MPL_FG_COLOR = t["mpl_fg"]
    CARD_BG = t["card_bg"]
    CARD_BORDER = t["card_border"]
    TEXT_MUTED = t["text_muted"]
    CURRENT_MODE = mode
    background_color = BACKGROUND_COLOR
    panel_color = PANEL_COLOR


def plot_theme() -> dict:
    """
    Return the active matplotlib palette as a dict.

    Stable keys (suitable for use in PlotManager and plot plugins):
        bg          – axes/figure facecolor
        fg          – primary text + tick + label colour
        grid        – grid line colour
        spine       – axis spine colour
        legend_bg   – legend facecolor
        legend_edge – legend frame colour
        legend_text – legend text colour
        accent      – primary highlight colour (e.g. selected items)
    """
    is_light = CURRENT_MODE == "light"
    return {
        "bg":          MPL_BG_COLOR,
        "fg":          MPL_FG_COLOR,
        "grid":        "#999999" if is_light else "gray",
        "spine":       MPL_FG_COLOR,
        "legend_bg":   "#dbdbdb" if is_light else "#2b2b2b",
        "legend_edge": "#888888" if is_light else "gray",
        "legend_text": MPL_FG_COLOR,
        "accent":      "#3484F0",
    }
