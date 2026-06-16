# Copyright (c) 2026 Santiago Hofwimmer
"""
helpers.py – Small Qt widget helpers shared across tabs.
"""
from __future__ import annotations

from typing import Callable

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QComboBox, QSizePolicy, QWidget


def deferred(fn: Callable) -> Callable:
    """Wrap *fn* so it runs on the next event-loop tick instead of inline.

    Connect this to a ``QComboBox`` selection signal when the handler does
    non-trivial work (a redraw, a data load): running heavy work synchronously
    inside the selection handler blocks the event loop while the popup is
    closing, which on Wayland leaves the dropdown surface visibly stuck open.
    Deferring lets the popup finish closing first.
    """
    def _slot(*args, **kwargs):
        QTimer.singleShot(0, lambda: fn(*args, **kwargs))
    return _slot


def compact_combo(combo: QComboBox, length: int = 10) -> QComboBox:
    """Keep a combo from widening to its longest item.

    Long entries (history-run labels, measurement names) would otherwise make
    the combo's size hint huge; with several combos in a row the control panel's
    minimum width can exceed the window — which, on a maximized Wayland surface,
    is a fatal ``xdg_surface`` protocol error (the committed buffer must not be
    larger than the configured maximized size). The dropdown popup still shows
    each item's full text.
    """
    combo.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
    combo.setMinimumContentsLength(length)
    return combo


def elide_horizontally(widget: QWidget) -> QWidget:
    """Let *widget* shrink/clip horizontally instead of forcing layout width."""
    policy = widget.sizePolicy()
    policy.setHorizontalPolicy(QSizePolicy.Ignored)
    widget.setSizePolicy(policy)
    return widget
