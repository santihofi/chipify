"""
throttled_redraw.py – Debounced redraw scheduler for Matplotlib-heavy views.

Guarantees at most one redraw per ``interval_ms``, with a trailing-edge
call so the final request always fires.

Usage::

    throttle = ThrottledRedraw(widget, some_redraw_fn, interval_ms=1500)
    throttle.request()    # call as often as you like
    throttle.force_now()  # immediate unthrottled fire (e.g. on sim end)
"""
from __future__ import annotations

import logging
import time

log = logging.getLogger("chipify.throttle")


class ThrottledRedraw:
    """Leading + trailing edge throttle backed by ``widget.after()``."""

    def __init__(self, widget, redraw_fn, interval_ms: int = 1500):
        self._widget = widget
        self._redraw = redraw_fn
        self._interval_ms = interval_ms
        self._last_fire: float = 0.0
        self._pending_id = None

    def request(self) -> None:
        """Request a redraw. May be coalesced with nearby requests."""
        now = time.monotonic()
        elapsed_ms = (now - self._last_fire) * 1000

        if elapsed_ms >= self._interval_ms:
            self.cancel_pending()
            self._fire()
        elif self._pending_id is None:
            remaining = int(self._interval_ms - elapsed_ms)
            self._pending_id = self._widget.after(remaining, self._fire)

    def force_now(self) -> None:
        """Immediate unthrottled redraw. Use on simulation end."""
        self.cancel_pending()
        self._fire()

    def update_interval(self, ms: int) -> None:
        """Change the throttle interval (clamped to 500–5000 ms)."""
        self._interval_ms = max(500, min(5000, ms))

    def _fire(self) -> None:
        self._last_fire = time.monotonic()
        self._pending_id = None
        try:
            self._redraw()
        except Exception as exc:
            log.warning("Throttled redraw error: %s", exc)

    def cancel_pending(self) -> None:
        """Cancel any scheduled trailing-edge redraw (safe from abort/cleanup)."""
        if self._pending_id is not None:
            self._widget.after_cancel(self._pending_id)
            self._pending_id = None
