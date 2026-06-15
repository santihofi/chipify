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
import sys


def _select_mpl_backend() -> None:
    """Force matplotlib onto the Qt backend before any pyplot import."""
    import matplotlib
    matplotlib.use("QtAgg")


def main() -> int:
    """Launch the Chipify Qt desktop GUI. Returns the Qt exit code."""
    from chipify import app_config

    app_config.setup_logging()
    log = logging.getLogger("chipify.gui_qt")
    _select_mpl_backend()

    from PySide6.QtWidgets import QApplication

    from chipify.gui_qt import theme
    from chipify.gui_qt.main_window import MainWindow

    app = QApplication.instance() or QApplication(sys.argv)
    app.setApplicationName("Chipify")
    app.setApplicationDisplayName("Chipify EDA Dashboard")

    mode = theme.load_theme_name()
    app.setStyleSheet(theme.build_qss(mode))
    log.info("Starting Chipify Qt GUI (theme=%s, PySide6).", mode)

    window = MainWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
