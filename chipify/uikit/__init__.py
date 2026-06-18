# Copyright (c) 2026 Santiago Hofwimmer
"""
chipify.uikit – framework-agnostic application/GUI-support modules.

Toolkit-neutral building blocks shared by the Qt GUI (``chipify.gui_qt``) and
usable headlessly: the :class:`~chipify.uikit.state.AppState` pub-sub bus and
the ``services`` layer (equation evaluation, measurement statistics, transient
loading, scatter-hover, netlist export, the plugin facade, and the YAML
datasheet-editor helpers). None of these import a GUI toolkit.

Result/data-loading utilities used by the core live in :mod:`chipify.data_loader`.
"""
