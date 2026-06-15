# Copyright (c) 2026 Santiago Hofwimmer
"""
throttle.py – QTimer-based redraw coalescing.

The Qt replacement for the legacy ``ThrottledRedraw`` (which was built on
``widget.after()``). Coalesces a burst of ``request()`` calls into at most one
callback per *interval* — leading edge fires immediately, trailing edge fires
once the burst settles — so live-plot / live-table refreshes stay smooth
during a fast simulation.
"""
from __future__ import annotations

from typing import Callable

from PySide6.QtCore import QObject, QTimer


class Throttle(QObject):
    """Rate-limit *callback* to one call per *interval_ms* (leading + trailing)."""

    def __init__(
        self,
        callback: Callable[[], None],
        interval_ms: int,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._callback = callback
        self._pending = False
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(max(0, interval_ms))
        self._timer.timeout.connect(self._on_timeout)

    def request(self) -> None:
        """Ask for a refresh; fires now if idle, otherwise coalesces."""
        if self._timer.isActive():
            self._pending = True
        else:
            self._callback()
            self._timer.start()

    def force_now(self) -> None:
        """Fire immediately (used at simulation end to flush the final state)."""
        self._timer.stop()
        self._pending = False
        self._callback()

    def cancel(self) -> None:
        """Drop any pending trailing-edge call and stop the cooldown."""
        self._timer.stop()
        self._pending = False

    def _on_timeout(self) -> None:
        if self._pending:
            self._pending = False
            self._callback()
            self._timer.start()
