# Copyright (c) 2026 Santiago Hofwimmer
"""
app.py – QApplication bootstrap for the chipify Qt GUI.

``main()`` is the target of the temporary ``chipify-qt`` console script (and,
once the rebuild is complete, of the ``chipify`` entry point). It selects the
matplotlib Qt backend, installs the active theme's style sheet, and shows the
main window.
"""
from __future__ import annotations

import logging
import os
import sys


def _select_mpl_backend() -> None:
    """Force matplotlib onto the Qt backend before any pyplot import."""
    import matplotlib
    matplotlib.use("QtAgg")


def _prefer_xwayland() -> bool:
    """On a Wayland session, prefer XWayland (xcb) with a Wayland fallback.

    Qt's Wayland backend has compositor-dependent popup bugs — combo-box
    dropdowns that don't dismiss on selection, and strict ``xdg_surface``
    maximized-buffer protocol errors. Rendering through XWayland avoids them.

    Sets ``QT_QPA_PLATFORM="xcb;wayland"`` — Qt tries xcb first and falls back
    to native Wayland if the xcb plugin can't initialise (e.g. ``libxcb-cursor0``
    is not installed), so the app never hard-aborts. Respects an explicit
    ``QT_QPA_PLATFORM`` and an opt-out ``CHIPIFY_QT_WAYLAND=1`` (force Wayland).
    Only acts when an X server (``DISPLAY``) is available. Returns True if set.
    """
    if sys.platform != "linux":
        return False
    if os.environ.get("QT_QPA_PLATFORM") or os.environ.get("CHIPIFY_QT_WAYLAND") == "1":
        return False
    on_wayland = bool(os.environ.get("WAYLAND_DISPLAY")) or \
        os.environ.get("XDG_SESSION_TYPE", "").lower() == "wayland"
    if on_wayland and os.environ.get("DISPLAY"):
        os.environ["QT_QPA_PLATFORM"] = "xcb;wayland"
        return True
    return False


def main() -> int:
    """Launch the Chipify Qt desktop GUI. Returns the Qt exit code."""
    from chipify import app_config

    app_config.setup_logging()
    log = logging.getLogger("chipify.gui_qt")
    if _prefer_xwayland():
        log.info("Wayland session detected; preferring XWayland (xcb) with a "
                 "native-Wayland fallback. If dropdowns still misbehave, install "
                 "libxcb-cursor0 so the xcb plugin can load. "
                 "Set CHIPIFY_QT_WAYLAND=1 to force native Wayland.")
    _select_mpl_backend()

    from PySide6.QtWidgets import QApplication

    from chipify.gui_qt import theme
    from chipify.gui_qt.main_window import MainWindow

    app = QApplication.instance() or QApplication(sys.argv)
    app.setApplicationName("Chipify")
    app.setApplicationDisplayName("Chipify EDA Dashboard")

    # Use Qt's Fusion style rather than the platform/native style. Fusion draws
    # and manages combo-box popups itself instead of handing them to the
    # platform — this fixes the Wayland bug where a native xdg_popup dropdown
    # does not close on selection — and it makes the QSS theme render
    # identically across platforms.
    app.setStyle("Fusion")

    mode = theme.load_theme_name()
    app.setStyleSheet(theme.build_qss(mode))
    log.info("Starting Chipify Qt GUI (theme=%s, PySide6).", mode)

    window = MainWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
