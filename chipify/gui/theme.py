"""
theme.py – Application-wide colour constants and CTk appearance bootstrap.

Import this module before any CTk widget is instantiated so that the
appearance mode and colour theme are applied consistently.
"""
from __future__ import annotations

import customtkinter as ctk

# ── Theme definitions ─────────────────────────────────────────────────────────
# "bg" / "panel" of None means: let CTk use its own default for the current mode.

THEMES: dict[str, dict] = {
    "night": {"ctk_mode": "dark",  "bg": "#000000", "panel": "#1a1a1a"},
    "dark":  {"ctk_mode": "dark",  "bg": None,      "panel": None},
    "light": {"ctk_mode": "light", "bg": None,      "panel": None},
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

BACKGROUND_COLOR: str | None = _t["bg"]
PANEL_COLOR: str | None = _t["panel"] if _t["panel"] is not None else "#1a1a1a"

# Legacy aliases
background_color = BACKGROUND_COLOR
panel_color = PANEL_COLOR


def apply_theme(mode: str) -> None:
    """Update module globals and CTk appearance for *mode* (night|dark|light)."""
    global BACKGROUND_COLOR, PANEL_COLOR, background_color, panel_color
    t = THEMES.get(mode, THEMES["night"])
    ctk.set_appearance_mode(t["ctk_mode"])
    BACKGROUND_COLOR = t["bg"]
    PANEL_COLOR = t["panel"] if t["panel"] is not None else "#1a1a1a"
    background_color = BACKGROUND_COLOR
    panel_color = PANEL_COLOR
