# Copyright (c) 2026 Santiago Hofwimmer
"""
theme.py – Qt theming for the chipify desktop app.

Defines the night / dark / light palettes (the same three themes as the legacy
CustomTkinter GUI) and turns the active palette into a Qt style sheet (QSS).
The matplotlib palette is exposed via :func:`plot_theme` with the same stable
keys that :mod:`chipify.plot_manager` and the plot plugins already consume, so
the plotting layer stays shared and unchanged.

Unlike the legacy :mod:`chipify.gui.theme`, this module imports no GUI toolkit
at import time and has no global side effects — building the QSS is a pure
function of the theme name.
"""
from __future__ import annotations

# ── Palette definitions ─────────────────────────────────────────────────────
# Hex values mirror chipify.gui.theme.THEMES so the Qt app matches the look of
# the CustomTkinter GUI. ``text`` is added for Qt foreground; the matplotlib
# keys (mpl_bg / mpl_fg) feed plot_theme().
THEMES: dict[str, dict[str, str]] = {
    "night": {
        "bg": "#000000", "panel": "#1a1a1a", "card_bg": "#111111",
        "card_border": "#2e2e2e", "text": "#e6e6e6", "text_muted": "#9a9a9a",
        "hover": "#262626", "pressed": "#333333", "input_bg": "#161616",
        "mpl_bg": "#1a1a1a", "mpl_fg": "white",
    },
    "dark": {
        "bg": "#242424", "panel": "#2b2b2b", "card_bg": "#232323",
        "card_border": "#3d3d3d", "text": "#e6e6e6", "text_muted": "#9a9a9a",
        "hover": "#3a3a3a", "pressed": "#454545", "input_bg": "#1f1f1f",
        "mpl_bg": "#2b2b2b", "mpl_fg": "white",
    },
    "light": {
        "bg": "#ebebeb", "panel": "#dbdbdb", "card_bg": "#f2f2f2",
        "card_border": "#c9c9c9", "text": "#2b2b2b", "text_muted": "#6b6b6b",
        "hover": "#e3e3e3", "pressed": "#cfcfcf", "input_bg": "#ffffff",
        "mpl_bg": "white", "mpl_fg": "#2b2b2b",
    },
}

#: Theme-independent semantic colours (match chipify.gui.theme).
ACCENT: str = "#3484F0"
ACCENT_HOVER: str = "#2b6fd0"
DANGER: str = "#e74c3c"
DANGER_HOVER: str = "#c0392b"

DEFAULT_THEME: str = "night"


def available_themes() -> list[str]:
    """Theme names, in display order."""
    return ["night", "dark", "light"]


def palette(mode: str) -> dict[str, str]:
    """Return a copy of the palette for *mode* (falls back to the default)."""
    return dict(THEMES.get(mode, THEMES[DEFAULT_THEME]))


def load_theme_name() -> str:
    """Active theme from settings.json, validated against known themes."""
    try:
        from chipify import app_config
        name = str(app_config.load_config().get("theme", DEFAULT_THEME))
    except Exception:
        return DEFAULT_THEME
    return name if name in THEMES else DEFAULT_THEME


def plot_theme(mode: str) -> dict[str, str]:
    """Matplotlib palette for *mode* with the stable keys PlotManager expects.

    Mirrors :func:`chipify.gui.theme.plot_theme` so figures look identical to
    the CustomTkinter GUI.
    """
    p = palette(mode)
    is_light = mode == "light"
    return {
        "bg":          p["mpl_bg"],
        "fg":          p["mpl_fg"],
        "grid":        "#999999" if is_light else "gray",
        "spine":       p["mpl_fg"],
        "legend_bg":   "#dbdbdb" if is_light else "#2b2b2b",
        "legend_edge": "#888888" if is_light else "gray",
        "legend_text": p["mpl_fg"],
        "accent":      ACCENT,
    }


def build_palette(mode: str):
    """Build a QPalette for *mode* so the Fusion style renders native widgets
    (combo boxes, spin boxes, inputs, menus) in the theme's colours.

    Theming via the palette — rather than QSS on every complex widget — keeps
    those widgets' sub-controls (spin arrows, combo popups) native and working.
    """
    from PySide6.QtGui import QColor, QPalette

    p = palette(mode)
    bg = QColor(p["bg"])
    base = QColor(p["input_bg"])
    text = QColor(p["text"])
    panel = QColor(p["panel"])
    button = QColor(p["card_bg"])
    muted = QColor(p["text_muted"])
    accent = QColor(ACCENT)
    white = QColor("#ffffff")

    qp = QPalette()
    qp.setColor(QPalette.Window, bg)
    qp.setColor(QPalette.WindowText, text)
    qp.setColor(QPalette.Base, base)
    qp.setColor(QPalette.AlternateBase, panel)
    qp.setColor(QPalette.ToolTipBase, button)
    qp.setColor(QPalette.ToolTipText, text)
    qp.setColor(QPalette.Text, text)
    qp.setColor(QPalette.Button, button)
    qp.setColor(QPalette.ButtonText, text)
    qp.setColor(QPalette.BrightText, white)
    qp.setColor(QPalette.Highlight, accent)
    qp.setColor(QPalette.HighlightedText, white)
    qp.setColor(QPalette.PlaceholderText, muted)
    qp.setColor(QPalette.Link, accent)
    for role in (QPalette.Text, QPalette.WindowText, QPalette.ButtonText):
        qp.setColor(QPalette.Disabled, role, muted)
    return qp


def build_qss(mode: str, font_size: int = 13) -> str:
    """Build the application-wide Qt style sheet for *mode* at *font_size* (pt).

    Object-name hooks used by widgets across the app:
      * ``QFrame#LeftPanel`` / ``QFrame#Card`` – panelled containers
      * ``QPushButton#Accent`` – primary action (Run); ``#Danger`` – Stop
      * ``QLabel#Muted`` – secondary text; ``QLabel#Heading`` – section titles
      * ``QLabel#Section`` – small sidebar section captions
      * ``QLabel#Stat`` / ``QLabel#StatValue`` – run-summary rows
    """
    p = palette(mode)
    return f"""
    QWidget {{
        background-color: {p['bg']};
        color: {p['text']};
        font-size: {font_size}px;
        selection-background-color: {ACCENT};
        selection-color: #ffffff;
    }}
    QMainWindow, QDialog {{ background-color: {p['bg']}; }}

    QFrame#LeftPanel {{
        background-color: {p['panel']};
        border: none;
        border-right: 1px solid {p['card_border']};
    }}
    QFrame#Card {{
        background-color: {p['card_bg']};
        border: 1px solid {p['card_border']};
        border-radius: 6px;
    }}

    QLabel {{ background: transparent; }}
    QLabel#Heading {{ font-size: {font_size + 3}px; font-weight: 600; }}
    QLabel#Muted {{ color: {p['text_muted']}; }}
    QLabel#Section {{
        color: {p['text_muted']}; font-size: {font_size - 2}px;
        font-weight: 700; letter-spacing: 1px;
    }}
    QLabel#Stat {{ color: {p['text_muted']}; }}
    QLabel#StatValue {{ font-weight: 600; }}

    QPushButton {{
        background-color: {p['card_bg']};
        border: 1px solid {p['card_border']};
        border-radius: 6px;
        padding: 6px 12px;
    }}
    QPushButton:hover {{ background-color: {p['hover']}; }}
    QPushButton:pressed {{ background-color: {p['pressed']}; }}
    QPushButton:disabled {{ color: {p['text_muted']}; border-color: {p['card_border']}; }}

    QPushButton#Accent {{ background-color: {ACCENT}; border-color: {ACCENT}; color: #ffffff; }}
    QPushButton#Accent:hover {{ background-color: {ACCENT_HOVER}; border-color: {ACCENT_HOVER}; }}
    QPushButton#Danger {{ background-color: {DANGER}; border-color: {DANGER}; color: #ffffff; }}
    QPushButton#Danger:hover {{ background-color: {DANGER_HOVER}; border-color: {DANGER_HOVER}; }}

    /* Only plain text inputs are styled here. Combo boxes and spin boxes are
       intentionally left to the Fusion style + palette: border/background QSS
       on those complex widgets breaks their sub-controls (the spin up/down
       arrows stop rendering/working, dropdown popups misbehave) unless every
       sub-control is also styled with arrow images. */
    QLineEdit, QPlainTextEdit, QTextEdit {{
        background-color: {p['input_bg']};
        border: 1px solid {p['card_border']};
        border-radius: 5px;
        padding: 4px 6px;
    }}

    /* Flat underline-style tab bar (cleaner than boxed tabs under Fusion). */
    QTabWidget::pane {{
        border: none;
        border-top: 1px solid {p['card_border']};
        top: -1px;
    }}
    QTabBar {{ qproperty-drawBase: 0; }}
    QTabBar::tab {{
        background: transparent;
        color: {p['text_muted']};
        padding: 8px 18px;
        border: none;
        border-bottom: 2px solid transparent;
        margin: 0;
    }}
    QTabBar::tab:selected {{ color: {p['text']}; border-bottom: 2px solid {ACCENT}; }}
    QTabBar::tab:hover {{ color: {p['text']}; }}

    QTreeView, QTableView, QListView {{
        background-color: {p['card_bg']};
        alternate-background-color: {p['panel']};
        border: 1px solid {p['card_border']};
        border-radius: 6px;
        gridline-color: {p['card_border']};
    }}
    QTreeView::item:selected, QTableView::item:selected, QListView::item:selected {{
        background-color: {ACCENT}; color: #ffffff;
    }}
    QHeaderView::section {{
        background-color: {p['panel']};
        color: {p['text']};
        padding: 4px 6px;
        border: none;
        border-right: 1px solid {p['card_border']};
        border-bottom: 1px solid {p['card_border']};
    }}

    QScrollBar:vertical {{ background: {p['bg']}; width: 12px; margin: 0; }}
    QScrollBar:horizontal {{ background: {p['bg']}; height: 12px; margin: 0; }}
    QScrollBar::handle {{ background: {p['card_border']}; border-radius: 5px; min-height: 24px; min-width: 24px; }}
    QScrollBar::handle:hover {{ background: {p['text_muted']}; }}
    QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; width: 0; }}

    QProgressBar {{
        background-color: {p['input_bg']};
        border: 1px solid {p['card_border']};
        border-radius: 6px;
        text-align: center;
        height: 18px;
    }}
    QProgressBar::chunk {{ background-color: {ACCENT}; border-radius: 5px; }}

    QStatusBar {{ background-color: {p['panel']}; border-top: 1px solid {p['card_border']}; }}
    QStatusBar QLabel {{ color: {p['text_muted']}; }}

    QMenu {{ background-color: {p['card_bg']}; border: 1px solid {p['card_border']}; }}
    QMenu::item:selected {{ background-color: {ACCENT}; color: #ffffff; }}

    QToolTip {{
        background-color: {p['card_bg']};
        color: {p['text']};
        border: 1px solid {p['card_border']};
    }}
    """
