# Copyright (c) 2026 Santiago Hofwimmer
"""
main_thread.py – Marshal callbacks onto the GUI thread.

:class:`PluginContext` (reused unchanged) expects a ``tk_after(ms, fn)``
callable to schedule work on the main thread — historically ``widget.after``.
``QTimer.singleShot`` is the Qt equivalent but only works when called *from*
the main thread, whereas ``PluginContext.run_async`` calls back from a worker
thread. :class:`MainThreadInvoker` bridges that: a queued signal hops the call
onto the GUI thread first, then schedules the timer there.
"""
from __future__ import annotations

from PySide6.QtCore import QObject, QTimer, Signal


class MainThreadInvoker(QObject):
    """Provides a thread-safe ``after(ms, fn)`` that runs *fn* on the GUI thread.

    Construct it on the main (GUI) thread. Because the invoker has main-thread
    affinity, emitting ``_scheduled`` from any other thread is delivered via a
    queued connection, so ``_run`` (and the subsequent timer) execute on the
    GUI thread.
    """

    _scheduled = Signal(int, object)

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._scheduled.connect(self._run)

    def after(self, ms: int, fn) -> None:
        """``widget.after``-compatible scheduler, safe from any thread."""
        self._scheduled.emit(int(ms), fn)

    def _run(self, ms: int, fn) -> None:
        QTimer.singleShot(ms, fn)
