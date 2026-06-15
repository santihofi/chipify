# Copyright (c) 2026 Santiago Hofwimmer
"""
mpl_canvas.py – Embeddable matplotlib canvas for Qt.

Wraps a :class:`~matplotlib.figure.Figure` in a ``FigureCanvasQTAgg`` plus the
Qt navigation toolbar. Using a bare ``Figure`` (not ``pyplot``) keeps each tab's
figure independent of pyplot's global state. The ``PlotManager.draw_*`` methods
receive ``self.figure`` and ``self.canvas`` and call ``canvas.draw()`` as before.
"""
from __future__ import annotations

from matplotlib.backends.backend_qtagg import (
    FigureCanvasQTAgg,
    NavigationToolbar2QT,
)
from matplotlib.figure import Figure
from PySide6.QtWidgets import QVBoxLayout, QWidget


class MplCanvas(QWidget):
    """A matplotlib figure + Qt canvas + (optional) navigation toolbar."""

    def __init__(
        self,
        parent: QWidget | None = None,
        *,
        figsize: tuple[float, float] = (6.0, 4.0),
        toolbar: bool = True,
    ) -> None:
        super().__init__(parent)
        self.figure = Figure(figsize=figsize, layout="tight")
        self.canvas = FigureCanvasQTAgg(self.figure)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        if toolbar:
            self.toolbar = NavigationToolbar2QT(self.canvas, self)
            layout.addWidget(self.toolbar)
        layout.addWidget(self.canvas, stretch=1)

    def add_subplot(self):
        """Reset the figure to a single axes and return it."""
        self.figure.clf()
        return self.figure.add_subplot(111)

    def draw(self) -> None:
        self.canvas.draw_idle()
