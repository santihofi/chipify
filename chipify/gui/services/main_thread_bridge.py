"""
main_thread_bridge.py – Thread-safe DataFrame transfer from background
threads to the Tkinter main thread via queue.Queue + widget.after().

The background thread calls ``enqueue_chunk(df)`` (thread-safe).
The main thread polls the queue and calls ``AppState.append_results()``.
"""
from __future__ import annotations

import logging
import queue

log = logging.getLogger("chipify.bridge")


class MainThreadBridge:
    """Queue-based dispatcher: background thread → Tkinter main thread."""

    def __init__(self, root_widget, state, poll_interval_ms: int = 100):
        self._root = root_widget
        self._state = state
        self._queue: queue.Queue = queue.Queue()
        self._poll_ms = poll_interval_ms
        self._polling = False
        self._after_id = None

    # ── Called from ANY thread (thread-safe) ──────────────────────────────

    def enqueue_chunk(self, chunk_df) -> None:
        """Put a partial DataFrame onto the queue. Thread-safe."""
        self._queue.put(chunk_df)

    # ── Called from main thread only ──────────────────────────────────────

    def start_polling(self) -> None:
        """Begin polling the queue on the Tkinter main thread."""
        self._polling = True
        self._poll()

    def stop_polling(self) -> None:
        """Stop polling and drain any remaining queued items."""
        self._polling = False
        if self._after_id is not None:
            self._root.after_cancel(self._after_id)
            self._after_id = None
        self._drain()

    def _poll(self) -> None:
        """Process up to N queued chunks per tick, then reschedule."""
        batch_limit = 5
        for _ in range(batch_limit):
            try:
                chunk = self._queue.get_nowait()
                self._state.append_results(chunk)
            except queue.Empty:
                break
        if self._polling:
            self._after_id = self._root.after(self._poll_ms, self._poll)

    def _drain(self) -> None:
        """Process all remaining items in the queue."""
        while not self._queue.empty():
            try:
                chunk = self._queue.get_nowait()
                self._state.append_results(chunk)
            except queue.Empty:
                break
