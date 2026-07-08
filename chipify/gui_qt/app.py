# Copyright (c) 2026 Santiago Hofwimmer
"""
app.py – QApplication bootstrap for the chipify Qt GUI.

``main()`` is the target of the ``chipify-qt`` console script (and, via
``chipify.cli.run_gui``, of the default ``chipify`` entry point). It selects the
matplotlib Qt backend, installs the active theme's style sheet, and shows the
main window.
"""
from __future__ import annotations

import logging
import os
import sys
from pathlib import Path


def _select_mpl_backend() -> None:
    """Force matplotlib onto the Qt backend before any pyplot import."""
    import matplotlib
    matplotlib.use("QtAgg")


def _set_windows_app_id() -> None:
    """Give the process an explicit AppUserModelID on Windows.

    Without this, Windows groups the app under—and shows the taskbar icon
    of—the host ``python.exe`` launcher rather than our own window icon.
    Must run before any window is created. No-op (and never fatal) elsewhere.
    """
    if sys.platform != "win32":
        return
    try:
        import ctypes
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(  # type: ignore[attr-defined]
            "Chipify.EDA.Dashboard")
    except Exception:  # pragma: no cover - best-effort cosmetic tweak
        pass


def _app_icon():
    """Build the application/window QIcon from the bundled package resources.

    The ``.ico`` carries 16–256 px renditions (crisp title-bar/taskbar sizes);
    the 256 px PNG is added as a high-res fallback for platforms that ignore
    ``.ico``. Returns an empty QIcon if the assets are missing.
    """
    from PySide6.QtGui import QIcon

    res = Path(__file__).resolve().parent / "resources"
    icon = QIcon()
    for name in ("chipify.ico", "chipify.png"):
        path = res / name
        if path.exists():
            icon.addFile(str(path))
    return icon


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


def _start_import_warmup(log: logging.Logger) -> None:
    """Pre-import heavy, lazily-loaded libraries on a background thread.

    ``scipy.stats`` (~0.8s, and it pulls in ``scipy.spatial``) is only needed the
    first time a distribution fit / QQ-plot is drawn, so it is imported lazily
    (see ``plot_manager`` / ``distribution_plots``) to keep launch fast. Warming
    it here — *after* the window is already on screen — means that first plot
    isn't laggy either. These are pure compute imports with no Qt interaction, so
    a plain daemon thread is safe; a concurrent lazy import on the main thread is
    serialised by the import system.
    """
    import threading

    def _warm() -> None:
        try:
            import scipy.stats  # noqa: F401
        except Exception:  # pragma: no cover - best-effort, never fatal
            log.debug("import warm-up skipped", exc_info=True)

    threading.Thread(target=_warm, name="chipify-import-warmup",
                     daemon=True).start()


def main() -> int:
    """Launch the Chipify Qt desktop GUI. Returns the Qt exit code."""
    from chipify import app_config

    app_config.setup_logging()
    log = logging.getLogger("chipify.gui_qt")
    _set_windows_app_id()
    if _prefer_xwayland():
        log.info("Wayland session detected; preferring XWayland (xcb) with a "
                 "native-Wayland fallback.")
    _select_mpl_backend()

    from PySide6.QtWidgets import QApplication

    from chipify.gui_qt import theme
    from chipify.gui_qt.main_window import MainWindow

    app = QApplication.instance() or QApplication(sys.argv)
    app.setApplicationName("Chipify")
    app.setApplicationDisplayName("Chipify EDA Dashboard")
    # App-wide default icon — inherited by the main window and every dialog /
    # secondary window (settings, multi-plot dashboard, …).
    app.setWindowIcon(_app_icon())

    # Use Qt's Fusion style rather than the platform/native style. Fusion draws
    # and manages combo-box popups itself instead of handing them to the
    # platform — this fixes the Wayland bug where a native xdg_popup dropdown
    # does not close on selection — and it makes the QSS theme render
    # identically across platforms.
    app.setStyle("Fusion")

    cfg = app_config.load_config()
    mode = theme.load_theme_name()
    font_size = int(cfg.get("font_size", 13))
    font = app.font()
    font.setPointSize(font_size)
    app.setFont(font)
    app.setPalette(theme.build_palette(mode))
    app.setStyleSheet(theme.build_qss(mode, font_size))
    log.info("Starting Chipify Qt GUI (theme=%s, PySide6).", mode)

    window = MainWindow()
    # Start maximized so the window always fits the screen regardless of
    # resolution; the title bar and window controls stay available, and the
    # user can un-maximize to the clamped restored size set in MainWindow.
    window.showMaximized()
    # Window is up — warm the lazily-imported heavy libs in the background so the
    # first distribution plot doesn't pay the deferred import cost interactively.
    _start_import_warmup(log)
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
