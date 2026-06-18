# Copyright (c) 2026 Santiago Hofwimmer
"""
chipify.gui_qt – PySide6 (Qt) desktop GUI.

This package is the Qt rebuild of the CustomTkinter GUI in ``chipify.gui``.
It reuses the framework-agnostic core unchanged (simulator, schema, analyses,
plot_manager, exporters, reports, config) and the shared state/services layer
(``chipify.uikit.state`` and the agnostic ``chipify.uikit.services`` modules).

Launch with the ``chipify-qt`` console script (see ``chipify.gui_qt.app:main``).
"""
from __future__ import annotations
